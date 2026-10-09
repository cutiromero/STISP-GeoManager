"""Capability registry used by the agent worker.

The worker still accepts only structured, explicitly registered actions.  The
few actions with side effects (submitting an existing compute algorithm and
requesting result ingestion) are guarded by the administrator policy and the
same project permissions as their HTTP counterparts.  Model arguments never
become SQL, code, shell commands, or filesystem paths.
"""

from contextlib import closing
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import hashlib
import math
import ipaddress
import platform
import re
import sqlite3
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

import pandas as pd
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import DataResource
from apps.catalog.permissions import filter_accessible
from apps.core.storage import table_data_path, vector_geopackage_path
from .policy import require_access, fresh_user, CAPABILITIES

ROW_LIMIT = 10000
MAX_RESULT_BYTES = 24000
MAX_WEB_BYTES = 512 * 1024
MAX_WEB_RESULTS = 8
WEB_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str
    description: str
    arguments: tuple[str, ...]


TOOLS = {
    t.name: t
    for t in (
        ToolSpec(
            "search_resources",
            "read_data",
            "查找当前项目数据，query 可为空；最多20项",
            ("query",),
        ),
        ToolSpec(
            "describe_resource",
            "read_data",
            "查看资源说明、字段、记录范围；resourceId",
            ("resourceId",),
        ),
        ToolSpec(
            "read_rows",
            "read_data",
            "读取最多30条样本；resourceId, fields字段数组, filters筛选数组",
            ("resourceId", "fields", "filters"),
        ),
        ToolSpec(
            "summarize_data",
            "analyze_data",
            "确定性统计计数、空值、最小、最大、均值、标准差；resourceId, fields, filters",
            ("resourceId", "fields", "filters"),
        ),
        ToolSpec(
            "aggregate_data",
            "analyze_data",
            "按groupBy字段分组统计field数值；metric为count/sum/mean/min/max；resourceId,groupBy,field,metric,filters",
            ("resourceId", "groupBy", "field", "metric", "filters"),
        ),
        ToolSpec(
            "compare_summaries",
            "analyze_data",
            "引用本轮已有summarize_data证据比较，evidenceIds数组，保留单位与口径限制",
            ("evidenceIds",),
        ),
        ToolSpec(
            "read_document",
            "read_data",
            "读取数据目录中的纯文本资源，resourceId须来自search_resources或用户选定数据；offset字符位置。知识库documentId不能用于此工具，知识文献使用search_knowledge检索",
            ("resourceId", "offset"),
        ),
        ToolSpec(
            "get_system_info",
            "system_info",
            "查看平台运行参数、计算运行时和主机资源摘要（需管理员开启）",
            ("sections",),
        ),
        ToolSpec(
            "list_compute_algorithms",
            "read_data",
            "按query目标关键词查找已发布算法，空格分词（如面积 周长）；返回具体版本完整manifest，先核对输入/参数/输出再执行。query可省略以列出目录",
            ("query",),
        ),
        ToolSpec(
            "execute_operator",
            "execute_operator",
            "提交已发布计算算法；versionId、inputs、parameters、name；默认计算后让用户选择入库，仅明确要求自动入库设置autoImport=true。缺少已确认波段/字段时生成计算卡片而不提交。返回taskId才代表实际提交",
            (
                "versionId",
                "inputs",
                "parameters",
                "name",
                "idempotencyKey",
                "autoImport",
            ),
        ),
        ToolSpec(
            "get_compute_task",
            "read_data",
            "查询计算任务真实状态及outputs和入库结果；taskId是UUID",
            ("taskId",),
        ),
        ToolSpec(
            "list_compute_tasks",
            "read_data",
            "查找本人当前项目最近计算任务，可用query筛选名称",
            ("query",),
        ),
        ToolSpec(
            "import_compute_result",
            "write_data",
            "按taskId自动查找真实输出并入库，也可传整数outputId（两者互斥）；尚在计算时登记完成后自动入库。可选outputKeys、name。只有ready才表示已入库",
            ("taskId", "outputId", "outputKeys", "name"),
        ),
        ToolSpec(
            "search_knowledge",
            "read_data",
            "联合检索已审核知识规则与当前可见文档原文（语义+关键词），返回citation引用、来源和适用条件；query",
            ("query",),
        ),
        ToolSpec(
            "read_knowledge_document",
            "read_data",
            "按search_knowledge返回的documentId读取知识文献原文；offset从0开始，limit为1至8000字符；返回nextOffset供继续阅读。documentId属于知识库，不是数据resourceId",
            ("documentId", "offset", "limit"),
        ),
        ToolSpec(
            "check_knowledge_constraints",
            "analyze_data",
            "按知识规则检查结构化facts，返回conflict/pass/needs_context；可选entryIds，缺条件时不能断言通过",
            ("facts", "entryIds"),
        ),
        ToolSpec(
            "search_web",
            "internet",
            "联网检索公开网页；query或url，返回受限摘要和引用链接",
            ("query", "url", "maxResults"),
        ),
    )
}


def resources(user, p, selected=()):
    qs = filter_accessible(DataResource.objects.all(), user).filter(
        data_type__in=p["dataTypes"]
    )
    return qs.filter(pk__in=selected) if selected else qs


def resolve_resource(user, p, resource_id, selected=()):
    if type(resource_id) is not int or resource_id < 1:
        raise ValidationError("resourceId 必须是有效资源 ID")
    r = resources(user, p, selected).filter(pk=resource_id).first()
    if not r:
        raise PermissionDenied("资源不存在、已失效或无权访问")
    return r


def brief(r):
    return {
        "id": r.id,
        "name": r.name,
        "dataType": r.data_type,
        "description": r.description[:800],
    }


def check_evidence(run, user, p):
    # Reauthorize ALL accumulated evidence before revealing history or reusing it.
    knowledge_refs, document_refs = set(), set()
    for ev in run.evidence:
        # System, algorithm, compute and web evidence intentionally have no
        # DataResource.  Their permissions are rechecked by the capability
        # gate on the next action instead of pretending they are resources.
        if ev.get("resourceId") is not None:
            resolve_resource(user, p, ev["resourceId"], run.resource_ids)
        if ev.get("tool") == "search_web" and not _policy_switch(
            p, "internetEnabled", "allowInternet"
        ):
            raise PermissionDenied("联网检索权限已关闭")
        if ev.get("tool") == "get_system_info" and not _policy_switch(
            p, "systemInfoEnabled", "allowSystemInfo"
        ):
            raise PermissionDenied("系统参数访问权限已关闭")
        if ev.get("tool") in {
            "execute_operator",
            "import_compute_result",
        } and not p.get("operatorEnabled", False):
            raise PermissionDenied("智能体算子权限已关闭")
        if (
            ev["tool"] in {"read_document", "read_knowledge_document"}
            and not p["allowDocuments"]
        ):
            raise PermissionDenied("文档读取权限已关闭")
        if ev["tool"] == "compare_summaries" and not p["allowCompare"]:
            raise PermissionDenied("跨资源比较权限已关闭")
        result = ev.get("result", {})
        if ev.get("tool") in {
            "execute_operator",
            "get_compute_task",
            "import_compute_result",
            "list_compute_tasks",
        }:
            from .compute_tools import authorized_task

            entries = (
                result.get("items", [])
                if ev["tool"] == "list_compute_tasks"
                else [result]
            )
            for item in entries:
                if isinstance(item, dict) and item.get("taskId"):
                    authorized_task(user, item["taskId"], p)
        if ev.get("tool") in {"search_knowledge", "check_knowledge_constraints"}:
            entries = (
                result.get("items", [])
                if ev["tool"] == "search_knowledge"
                else result.get("findings", [])
            )
            for item in entries:
                knowledge_refs.add(
                    (item.get("id", item.get("entryId")), item.get("revision"))
                )
        if ev.get("tool") in {"search_knowledge", "read_knowledge_document"}:
            document_refs.update(
                (item.get("documentId"), item.get("documentSha256"))
                for item in result.get("documents", [])
            )
    if knowledge_refs:
        from apps.knowledge.services import visible_entries

        visible = set(
            visible_entries(user)
            .filter(pk__in=[identity for identity, _ in knowledge_refs])
            .values_list("id", "revision")
        )
        if not knowledge_refs <= visible:
            raise PermissionDenied("知识依据已更新或访问权限已变化，请重新检索")
    if document_refs:
        from .knowledge_tools import check_document_evidence

        check_document_evidence(user, document_refs)


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def frame(resource):
    """Bound memory; never decode vector geometries or execute data file macros."""
    if resource.data_type == "vector" or (
        resource.data_type == "table" and resource.file_format.upper() == "SQLITE"
    ):
        path = (
            vector_geopackage_path()
            if resource.data_type == "vector"
            else table_data_path("data.sqlite")
        )
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            started = time.monotonic()
            db.set_progress_handler(lambda: int(time.monotonic() - started > 5), 1000)
            table = resource.storage_path
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                raise ValidationError("数据表不可用")
            columns = [c[1] for c in db.execute(f"PRAGMA table_info({_q(table)})")]
            if resource.data_type == "vector":
                geometry = {
                    c[0]
                    for c in db.execute(
                        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?",
                        (table,),
                    )
                }
                columns = [c for c in columns if c not in geometry]
            if len(columns) > 100:
                raise ValidationError("字段超过100个，请先在数据模块整理所需字段")
            data = pd.read_sql_query(
                f"SELECT {','.join(_q(c) for c in columns)} FROM {_q(table)} LIMIT ?",
                db,
                params=(ROW_LIMIT + 1,),
            )
            descriptions = {}
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='data_columns'"
            ).fetchone():
                descriptions = dict(
                    db.execute(
                        "SELECT column_name,description FROM data_columns WHERE table_name=?",
                        (table,),
                    )
                )
    elif resource.data_type in {"table", "gene"}:
        from apps.catalog.nongeo import _resource_file_path, _read_resource_file

        path = _resource_file_path(resource)
        descriptions = {}
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValidationError("文件超过10MB，请先导入平台表格库后分析")
        if path.suffix.lower() in {".csv", ".tsv"}:
            data = pd.read_csv(
                path,
                sep="\t" if path.suffix.lower() == ".tsv" else ",",
                nrows=ROW_LIMIT + 1,
            )
        elif path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            from itertools import islice

            workbook = load_workbook(
                path, read_only=True, data_only=True, keep_links=False
            )
            try:
                rows = workbook.active.iter_rows(values_only=True)
                headers = next(rows, ())
                if len(headers) > 100:
                    raise ValidationError("字段过多，请先导入平台表格库")
                data = pd.DataFrame(
                    islice(rows, ROW_LIMIT + 1), columns=[str(c) for c in headers]
                )
            finally:
                workbook.close()
        elif path.stat().st_size <= 2 * 1024 * 1024:
            data = _read_resource_file(resource, path)
        else:
            raise ValidationError("该格式的直接解析上限为2MB，请先导入表格库")
    else:
        raise ValidationError("此类型仅支持元数据，不支持行统计")
    if len(data.columns) > 100 or data.memory_usage(deep=True).sum() > 32 * 1024 * 1024:
        raise ValidationError("数据过宽或内容过大，请缩小源数据")
    truncated = len(data) > ROW_LIMIT
    data = data.iloc[:ROW_LIMIT].copy()
    for column in data.columns:
        if data[column].map(lambda x: isinstance(x, bytes)).any():
            data = data.drop(columns=column)
    return data, {
        "scope": "prefix_sample" if truncated else "full",
        "truncated": truncated,
        "scannedRows": len(data),
        "rowLimit": ROW_LIMIT,
        "fieldDescriptions": descriptions,
        "limitation": "仅前10000条，不代表总体"
        if truncated
        else "完整读取；单位以字段说明为准",
    }


def filtered(data, args):
    filters = args.get("filters", [])
    if not isinstance(filters, list) or len(filters) > 8:
        raise ValidationError("最多8个结构化筛选条件")
    for f in filters:
        if (
            not isinstance(f, dict)
            or set(f) != {"field", "op", "value"}
            or f["field"] not in data.columns
        ):
            raise ValidationError("筛选字段不存在或格式无效")
        s = data[f["field"]]
        v = f["value"]
        if isinstance(v, (dict, list)) or (isinstance(v, str) and len(v) > 500):
            raise ValidationError("筛选值无效")
        if f["op"] == "eq":
            mask = s == v
        elif f["op"] == "ne":
            mask = s != v
        elif f["op"] in {"gt", "gte", "lt", "lte"}:
            if type(v) not in (int, float):
                raise ValidationError("范围筛选需要数值")
            numeric = pd.to_numeric(s, errors="coerce")
            mask = {
                "gt": numeric.gt,
                "gte": numeric.ge,
                "lt": numeric.lt,
                "lte": numeric.le,
            }[f["op"]](v)
        elif f["op"] == "contains":
            mask = s.astype(str).str.contains(str(v), regex=False, na=False)
        else:
            raise ValidationError("不支持的筛选运算")
        data = data[mask]
    return data


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if hasattr(value, "item"):
        return clean(value.item())
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value[:1000] if isinstance(value, str) else value
    return str(value)[:1000]


def _policy_switch(policy_value, *names):
    """Read an additive policy switch while old deployments are upgrading."""
    return any(bool(policy_value.get(name, False)) for name in names)


def _check_special_capability(spec, policy_value):
    if spec.capability == "system_info" and not _policy_switch(
        policy_value, "systemInfoEnabled", "allowSystemInfo"
    ):
        raise PermissionDenied("系统参数访问尚未由管理员开启")
    if spec.capability in {"execute_operator", "write_data"} and not policy_value.get(
        "operatorEnabled", False
    ):
        # Keep disabled capabilities indistinguishable from an unregistered
        # tool to the model.  This also preserves the worker's protocol-error
        # retry path while preventing any side effect.
        raise ValidationError("未开放该工具或能力")
    if spec.capability == "internet" and not _policy_switch(
        policy_value, "internetEnabled", "allowInternet"
    ):
        raise PermissionDenied("联网检索尚未由管理员开启")


def _system_info(user, policy_value):
    """Return a bounded, secret-free view of the current platform runtime."""
    import os
    from apps.agent.config import registry
    from apps.compute.services import runtime_state
    from apps.core.runtime_config import (
        runtime_max_raster_side_pixels,
        runtime_query_result_limit,
        runtime_system_name,
        runtime_upload_max_mb,
    )

    from apps.core.admin_api import (
        _cpu_snapshot,
        _disk_snapshot,
        _gpu_snapshot,
        _memory_snapshot,
    )

    sections = {
        "platform",
        "resources",
        "limits",
        "models",
        "compute",
    }
    requested = policy_value.get("_systemInfoSections")
    # The actual request is supplied by execute; this fallback keeps this
    # helper safe when called by tests or a future adapter.
    if isinstance(requested, list):
        selected = sections.intersection(str(v) for v in requested)
    else:
        selected = sections
    result = {"generatedAt": timezone.localtime().isoformat()}
    if "platform" in selected:
        result["platform"] = {
            "name": runtime_system_name(),
            "python": platform.python_version(),
            "os": platform.platform(),
            "machine": platform.machine(),
            "cpuCount": os.cpu_count() or 1,
        }
    if "resources" in selected:
        result["resources"] = {
            "cpu": _cpu_snapshot(),
            "memory": _memory_snapshot(),
            "disk": _disk_snapshot(),
        }
        gpu = _gpu_snapshot()
        if gpu is not None:
            result["resources"]["gpu"] = gpu
    if "limits" in selected:
        result["limits"] = {
            "uploadMaxMb": runtime_upload_max_mb(),
            "queryResultLimit": runtime_query_result_limit(),
            "maxRasterSidePixels": runtime_max_raster_side_pixels(),
        }
    if "models" in selected:
        result["models"] = [
            {
                "alias": model.alias,
                "name": model.name,
                "modelId": model.model_id,
                "contextWindowTokens": model.context_window_tokens,
                "agent": model.agent,
                "supportsThinking": model.qwen,
            }
            for model in registry().values()
        ]
    if "compute" in selected:
        state = runtime_state(user)
        # runtime_state includes only permission booleans and configured limits;
        # no credentials or process command lines are returned.
        result["compute"] = {
            "available": state["available"],
            "workerOnline": state["workerOnline"],
            "detail": state["detail"],
            "limits": state["limits"],
        }
    return clean(result)


def _algorithm_list(user, search=""):
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
    from apps.compute.access import project_id, permission

    project = project_id()
    query = (
        allowed_algorithms()
        .filter(enabled=True, versions__status="published")
        .prefetch_related("versions")
        .distinct()
        .order_by("name", "id")
    )
    terms = re.split(r"[\s,，、;；/]+", search.strip()) if search.strip() else []
    if terms:
        matches = Q()
        for term in terms:
            matches |= (
                Q(name__icontains=term)
                | Q(description__icontains=term)
                | Q(identifier__icontains=term)
            )
        query = query.filter(matches)
    found = list(query[:51])
    manage = permission(user, "manage_algorithms")
    items = []
    for algorithm in found[:50]:
        versions = []
        for version in algorithm.versions.all():
            if version.status != "published":
                continue
            manifest = version.manifest or {}
            versions.append(
                {
                    "id": version.id,
                    "version": version.version,
                    "status": version.status,
                    "manifest": manifest,
                    "description": manifest.get("description", ""),
                    "inputs": [
                        {
                            key: item.get(key)
                            for key in (
                                "key",
                                "label",
                                "kind",
                                "required",
                                "minBands",
                                "geometryTypes",
                            )
                            if key in item
                        }
                        for item in manifest.get("inputs", [])[:32]
                    ],
                    "parameters": [
                        {
                            key: item.get(key)
                            for key in (
                                "key",
                                "label",
                                "type",
                                "required",
                                "default",
                                "choices",
                                "min",
                                "max",
                            )
                            if key in item
                        }
                        for item in manifest.get("parameters", [])[:64]
                    ],
                    "agentEnabled": agent_algorithm_allowed(version),
                }
            )
        items.append(
            {
                "id": algorithm.id,
                "projectTagId": algorithm.project_tag_id,
                "identifier": algorithm.identifier,
                "name": algorithm.name,
                "description": algorithm.description[:800],
                "category": algorithm.category,
                "author": algorithm.author,
                "canManage": manage and algorithm.project_tag_id == project,
                "versions": versions,
            }
        )
    return {
        "items": items,
        "projectTagId": project,
        "query": search,
        "truncated": len(found) > 50,
    }


def _validate_web_host(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("网页地址必须为 http 或 https")
    if parsed.username or parsed.password or parsed.port:
        raise ValidationError("网页地址不得包含账号、密码或非标准端口")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ValidationError("网页地址不允许访问本机服务")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValidationError("网页地址无法解析") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValidationError("网页地址解析到受限网络，已拒绝访问")
    return parsed


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_web_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _WebText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(" ".join(data.split()))


def _web_fetch(url, max_results):
    _validate_web_host(url)
    opener = build_opener(_SafeRedirect)
    request = Request(
        url,
        headers={
            "User-Agent": "GeoManager-Agent/1.0 (+public research retrieval)",
            "Accept": "text/html,text/plain,application/json;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=WEB_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type().lower()
            if content_type not in {
                "text/html",
                "text/plain",
                "application/json",
                "text/xml",
            }:
                raise ValidationError("网页内容类型不受支持，仅能读取文本或HTML")
            payload = response.read(MAX_WEB_BYTES + 1)
            if len(payload) > MAX_WEB_BYTES:
                raise ValidationError("网页内容超过读取上限")
            charset = response.headers.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
    except HTTPError as exc:
        raise ValidationError(f"网页返回HTTP {exc.code}") from exc
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise ValidationError("网页暂时无法访问") from exc
    if content_type == "application/json":
        try:
            parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False)[:12000]
        except json.JSONDecodeError:
            text = text[:12000]
        return {"url": url, "title": "JSON", "snippets": [text], "links": []}
    parser = _WebText()
    parser.feed(text)
    clean_text = " ".join(parser.parts)
    title = parser.parts[0][:240] if parser.parts else url
    snippets = [
        clean_text[i : i + 500]
        for i in range(0, min(len(clean_text), max_results * 500), 500)
    ]
    links = []
    for link in parser.links:
        absolute = urljoin(url, link)
        try:
            _validate_web_host(absolute)
        except ValidationError:
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) >= max_results:
            break
    return {"url": url, "title": title, "snippets": snippets, "links": links}


def _web_search(query, max_results):
    endpoint = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    result = _web_fetch(endpoint, max_results)
    # Search result snippets are already text; preserve the endpoint citation
    # and return bounded chunks, avoiding any raw HTML in model context.
    snippets = result.get("snippets", [])
    links = result.get("links", [])
    return {
        "query": query,
        "source": endpoint,
        "items": [
            {
                "title": f"公开网页结果 {index + 1}",
                "url": link,
                "snippet": snippets[index] if index < len(snippets) else "",
            }
            for index, link in enumerate(links[:max_results])
        ],
    }


def _operator_submit(run, user, p, args):
    from apps.compute.services import submit as submit_compute
    from apps.compute.access import project_id
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
    from apps.compute.models import AlgorithmVersion
    from .compute_tools import track, compact_task

    run.refresh_from_db(fields=["compute_intent", "cancel_requested"])
    if run.cancel_requested:
        raise PermissionDenied("本轮已停止，不能提交计算")

    version_id = args.get("versionId")
    if type(version_id) is not int or version_id < 1:
        raise ValidationError("versionId 必须为有效算法版本 ID")
    version = AlgorithmVersion.objects.filter(
        pk=version_id, status="published", algorithm__in=allowed_algorithms()
    ).first()
    if not version or not agent_algorithm_allowed(version):
        raise PermissionDenied("算法未发布或未允许智能体调用")
    inputs, parameters = args.get("inputs", {}), args.get("parameters", {})
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        raise ValidationError("inputs 与 parameters 必须为对象")
    name = args.get("name") or "智能体计算任务"
    auto_import = args.get("autoImport", False)
    if type(auto_import) is not bool:
        raise ValidationError("autoImport 必须为布尔值")
    if auto_import:
        from apps.compute.access import require_actor

        require_actor(user, project_id(), "catalog.add_dataresource")
    for resource_id in inputs.values():
        resolve_resource(user, p, resource_id, run.resource_ids)
    from .compute_intents import prepare_from_tool

    if run.compute_intent.get("status") in {"superseded", "cancelled"}:
        raise ValidationError("本轮计算计划已被替代或取消")
    if run.compute_intent.get("taskId"):
        if run.compute_intent.get("versionId") != version.id:
            raise ValidationError("本轮计算已经提交，请从新的请求发起其他算法")
        pending = None
    else:
        pending = prepare_from_tool(run, user, p, version, inputs)
    if pending is not None:
        return pending, [(None, pending)]
    if run.compute_intent and run.compute_intent.get("versionId") == version.id:
        if (
            inputs != run.compute_intent["inputs"]
            or parameters != run.compute_intent["parameters"]
            or auto_import != run.compute_intent["autoImport"]
        ):
            raise ValidationError("请使用用户在计算卡片或当前消息中明确选择的参数")
    elif auto_import and not re.search(r"(?<!不)(?<!不要)自动.{0,4}入库", run.prompt):
        raise ValidationError("自动入库需要用户明确选择，默认先查看计算结果")
    if run.compute_intent.get("taskId"):
        from .compute_tools import authorized_task

        task = authorized_task(user, run.compute_intent["taskId"], p)
        result = {**compact_task(task), "autoImport": auto_import}
        return result, [(None, result)]
    # Model retries cannot create a second calculation with an invented key.
    digest = hashlib.sha256(
        json.dumps([version_id, inputs, parameters], sort_keys=True).encode()
    ).hexdigest()[:32]
    key = f"agent-{run.id}-{digest}"
    from apps.compute.models import ComputeTask

    if (
        run.compute_followups.count() >= p["maxOperatorSteps"]
        and not ComputeTask.objects.filter(owner=user, idempotency_key=key).exists()
    ):
        raise ValidationError("已达到本轮算子步骤上限")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 160:
        raise ValidationError("任务名称无效")
    if not isinstance(key, str) or not 1 <= len(key) <= 80:
        raise ValidationError("幂等键无效")
    with transaction.atomic():
        task = submit_compute(
            user,
            {
                "name": name.strip(),
                "versionId": version_id,
                "inputs": inputs,
                "parameters": parameters,
                "idempotencyKey": key,
                "trial": False,
            },
        )
        track(run, task, auto_import=auto_import)
    # The compute service performs full validation and rechecks project/data
    # authorization.  Pair input resources with the evidence for audit/history.
    pairs = []
    for resource_id in inputs.values():
        if type(resource_id) is int:
            resource = resources(user, p).filter(pk=resource_id).first()
            if resource:
                pairs.append(
                    (resource, {"taskId": str(task.id), "status": task.status})
                )
    result = {
        **compact_task(task),
        "autoImport": auto_import,
        "projectTagId": project_id(),
    }
    if run.compute_intent and run.compute_intent.get("versionId") == version.id:
        from .compute_intents import _save

        _save(
            run,
            {
                **run.compute_intent,
                "status": "submitted",
                "taskId": str(task.id),
                "message": "计算已提交，进度会自动更新",
            },
        )
    return result, [(resource, result) for resource, _ in pairs] or [(None, result)]


def execute(run, name, args):
    spec = TOOLS.get(name)
    if not spec or not CAPABILITIES.get(spec.capability):
        raise ValidationError("未开放该工具或能力")
    if not isinstance(args, dict) or set(args) - set(spec.arguments):
        raise ValidationError("工具参数无效")
    user = fresh_user(run.owner_id)
    p = require_access(user, "agent", run.model)
    check_evidence(run, user, p)
    _check_special_capability(spec, p)
    if name == "search_web" and not getattr(run, "internet_enabled", False):
        raise PermissionDenied("本轮未开启联网检索")
    if name == "get_system_info":
        sections = args.get("sections")
        if sections is not None and (
            not isinstance(sections, list)
            or len(sections) > 5
            or any(not isinstance(value, str) for value in sections)
        ):
            raise ValidationError("sections 必须为最多5项文字数组")
        # Avoid putting a request-specific selector into persisted policy.
        selected = (
            sections
            if sections is not None
            else ["platform", "resources", "limits", "models", "compute"]
        )
        allowed_sections = {"platform", "resources", "limits", "models", "compute"}
        if any(value not in allowed_sections for value in selected):
            raise ValidationError("不支持的系统信息分区")
        scoped_policy = {**p, "_systemInfoSections": selected}
        result = _system_info(user, scoped_policy)
        return result, [(None, result)]
    if name == "list_compute_algorithms":
        query = args.get("query", "")
        if not isinstance(query, str) or len(query) > 200:
            raise ValidationError("query 必须为不超过200字的算法关键词")
        result = clean(_algorithm_list(user, query.strip()))
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES * 2:
            raise ValidationError("算法清单过大，请用query目标关键词缩小范围")
        return result, [(None, result)]
    if name == "execute_operator":
        return _operator_submit(run, user, p, args)
    if name == "import_compute_result":
        from .compute_tools import import_result

        return import_result(run, user, p, args)
    if name in {"get_compute_task", "list_compute_tasks"}:
        from .compute_tools import query_task, list_tasks

        return (query_task if name == "get_compute_task" else list_tasks)(
            run, user, p, args
        )
    if name == "search_knowledge":
        from .knowledge_tools import search_knowledge

        query = args.get("query", "")
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300:
            raise ValidationError("query 必须为1至300字")
        return search_knowledge(run, user, query.strip())
    if name == "read_knowledge_document":
        from .knowledge_tools import read_knowledge_document

        if not p["allowDocuments"]:
            raise PermissionDenied("文档正文读取未开启")
        return read_knowledge_document(run, user, args)
    if name == "check_knowledge_constraints":
        from apps.knowledge.services import check_constraints

        facts, ids = args.get("facts"), args.get("entryIds")
        if not isinstance(facts, dict) or len(json.dumps(facts)) > 24000:
            raise ValidationError("facts 必须为有界结构化对象")
        if ids is not None and (
            not isinstance(ids, list)
            or len(ids) > 30
            or any(type(i) is not int for i in ids)
        ):
            raise ValidationError("entryIds 必须为知识ID数组")
        result = check_constraints(user, facts, entry_ids=ids)
        return result, [(None, result)]
    if name == "search_web":
        query, url = args.get("query"), args.get("url")
        if (query is None) == (url is None):
            raise ValidationError("联网检索需要 query 或 url 其中一项")
        max_results = args.get("maxResults", 5)
        if type(max_results) is not int or not 1 <= max_results <= MAX_WEB_RESULTS:
            raise ValidationError("maxResults 必须为1至8的整数")
        if query is not None:
            if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
                raise ValidationError("搜索词长度必须为2至300个字符")
            result = _web_search(query.strip(), max_results)
        else:
            if not isinstance(url, str) or len(url) > 2000:
                raise ValidationError("网页地址无效")
            result = _web_fetch(url, max_results)
        result = clean(result)
        return result, [(None, result)]
    if name == "search_resources":
        query = args.get("query", "")
        if not isinstance(query, str) or len(query) > 200:
            raise ValidationError("搜索词过长或无效")
        normalized_query = query.strip().lower()
        table_query = any(
            marker in normalized_query
            for marker in (
                "table",
                "csv",
                "tsv",
                "xls",
                "xlsx",
                "excel",
                "表格",
                "数据表",
            )
        )
        text_query = Q(name__icontains=query) | Q(description__icontains=query)
        if table_query:
            text_query |= Q(data_type=DataResource.DataType.TABLE)
        found = list(
            resources(user, p, run.resource_ids).filter(text_query).order_by("id")[:21]
        )
        return {
            "items": [brief(r) for r in found[:20]],
            "truncated": len(found) > 20,
        }, [(r, {"metadata": brief(r)}) for r in found[:20]]
    if name == "compare_summaries":
        if not p["allowCompare"]:
            raise PermissionDenied("跨资源比较已关闭")
        ids = args.get("evidenceIds")
        if (
            not isinstance(ids, list)
            or not 2 <= len(ids) <= 3
            or any(type(i) is not int for i in ids)
        ):
            raise ValidationError("比较需要2至3个统计证据序号")
        selected = [
            ev
            for ev in run.evidence
            if ev["id"] in ids and ev["tool"] == "summarize_data"
        ]
        if len(selected) != len(set(ids)):
            raise ValidationError("仅能比较本轮已经完成的统计证据")
        result = {
            "summaries": selected,
            "limitation": "必须核对字段单位、筛选与样本口径；差异不代表因果关系",
        }
        return result, [
            (
                resolve_resource(user, p, ev["resourceId"], run.resource_ids),
                {"evidenceIds": ids, "limitation": result["limitation"]},
            )
            for ev in selected
        ]
    resource = resolve_resource(user, p, args.get("resourceId"), run.resource_ids)
    touched = {
        ev["resourceId"]
        for ev in run.evidence
        if ev["tool"] != "search_resources" and ev.get("resourceId") is not None
    }
    if resource.id not in touched and len(touched) >= p["maxResources"]:
        raise ValidationError("本次读取资源数已达上限，请缩小问题")
    if not p["allowCompare"] and touched and resource.id not in touched:
        raise PermissionDenied("跨资源读取已关闭")
    result = {
        "resource": brief(resource),
        "sourceUpdatedAt": resource.updated_at.isoformat(),
    }
    if name == "read_document":
        if not p["allowDocuments"]:
            raise PermissionDenied("文档正文读取未开启")
        if resource.data_type != "document":
            raise ValidationError("请选择文档资源")
        from apps.catalog.nongeo import _resource_file_path

        path = _resource_file_path(resource)
        if path.suffix.lower() not in {".txt", ".md", ".csv"}:
            raise ValidationError("当前仅支持纯文本正文，PDF或扫描件尚不可读取")
        if path.stat().st_size > 256 * 1024:
            raise ValidationError("文档超过256KB正文读取上限")
        offset = args.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 262144:
            raise ValidationError("正文位置无效")
        text = path.read_text(encoding="utf-8-sig")
        result.update(
            {
                "text": text[offset : offset + 6000],
                "offset": offset,
                "totalCharacters": len(text),
                "truncated": offset + 6000 < len(text),
            }
        )
    elif resource.data_type not in {"table", "vector", "gene"}:
        if name != "describe_resource":
            raise ValidationError("此类型只支持元数据读取")
        result.update(
            {
                "format": resource.file_format,
                "extent": resource.spatial_extent,
                "crs": resource.coordinate_system,
                "itemCount": resource.item_count,
                "contentRead": False,
            }
        )
        if resource.data_type == "raster":
            # Reuse the catalog's compact, persisted GDAL profile. This exposes
            # dimensions and band metadata without opening pixels or running a
            # raster operation in the agent worker.
            from apps.raster.services.profile import get_raster_profile

            profile = get_raster_profile(resource)
            if profile:
                metadata = profile.get("raster", {}).get("metadata", {})
                result["rasterMetadata"] = {
                    "size": metadata.get("size", []),
                    "driver": metadata.get("driver", ""),
                    "coordinateSystem": metadata.get("coordinateSystem", ""),
                    "bands": [
                        {
                            key: band.get(key)
                            for key in ("band", "type", "min", "max", "isInteger")
                        }
                        for band in metadata.get("bands", [])[:32]
                    ],
                }
    else:
        data, info = frame(resource)
        data = filtered(data, args)
        result.update(info)
        result.update({"filters": args.get("filters", []), "matchedRows": len(data)})
        fields = args.get("fields", list(data.columns)[:12])
        if (
            not isinstance(fields, list)
            or len(fields) > 12
            or any(not isinstance(f, str) or f not in data.columns for f in fields)
        ):
            raise ValidationError("字段不存在或超过12个")
        if name == "describe_resource":
            result["fields"] = [
                {
                    "name": str(c),
                    "type": str(data[c].dtype),
                    "description": info["fieldDescriptions"].get(c, ""),
                }
                for c in data.columns
            ]
        elif name == "read_rows":
            result["rows"] = data[fields].head(30).to_dict(orient="records")
            result["sampleRows"] = min(30, len(data))
        elif name == "summarize_data":
            stats = []
            for f in fields:
                s = data[f]
                numeric = pd.to_numeric(s, errors="coerce")
                entry = {
                    "field": f,
                    "count": len(s),
                    "validCount": int(s.notna().sum()),
                    "missingCount": int(s.isna().sum()),
                    "numericCount": int(numeric.notna().sum()),
                }
                if numeric.notna().any():
                    entry.update(
                        {
                            "sum": numeric.sum(),
                            "mean": numeric.mean(),
                            "min": numeric.min(),
                            "max": numeric.max(),
                            "stdSample": numeric.std(),
                        }
                    )
                entry["frequencies"] = [
                    {"value": str(k), "count": int(v)}
                    for k, v in s.value_counts(dropna=False).head(10).items()
                ]
                stats.append(entry)
            result["statistics"] = stats
        elif name == "aggregate_data":
            group, field, metric = (
                args.get("groupBy"),
                args.get("field"),
                args.get("metric", "count"),
            )
            if (
                not isinstance(group, str)
                or group not in data.columns
                or metric not in {"count", "sum", "mean", "min", "max"}
            ):
                raise ValidationError("分组字段或统计方法无效")
            if metric == "count":
                values = data.groupby(group, dropna=False, sort=True).size()
            else:
                if not isinstance(field, str) or field not in data.columns:
                    raise ValidationError("统计字段无效")
                values = (
                    pd.to_numeric(data[field], errors="coerce")
                    .groupby(data[group], dropna=False, sort=True)
                    .agg(metric)
                )
            result.update(
                {
                    "groupBy": group,
                    "field": field,
                    "metric": metric,
                    "groupsTruncated": len(values) > 50,
                    "groups": [
                        {"group": k, "value": v} for k, v in values.head(50).items()
                    ],
                }
            )
    result = clean(result)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
        raise ValidationError("工具结果过大，请减少字段或缩小筛选范围")
    return result, [(resource, result)]


def evidence_items(run, name, pairs):
    return [
        {
            "id": len(run.evidence) + i + 1,
            "resourceId": r.id if r is not None else None,
            "name": r.name if r is not None else name,
            "tool": name,
            "result": result,
            "recordedAt": timezone.now().isoformat(),
        }
        for i, (r, result) in enumerate(pairs)
    ]
