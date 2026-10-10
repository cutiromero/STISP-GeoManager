"""Conversation-bound algorithm plans, backed by real platform resources."""

import hashlib
import json
import re
from functools import lru_cache

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.compute.data import candidate
from apps.compute.models import AlgorithmVersion
from apps.compute.packages import ComputeError
from apps.compute.serializers import version_data
from apps.compute.services import allowed_algorithms, agent_algorithm_allowed
from .compute_intent_text import (
    algorithm_match,
    explicit_parameters,
    followup_question,
    import_requested,
    computation_requested,
)
from .models import AgentRun
from .tools import execute, evidence_items, resources, resolve_resource
from .selections import algorithm_ids, knowledge_selection, require_algorithm

OPEN = {"collecting", "ready", "blocked"}


def record_tool(run, name, arguments):
    result, pairs = execute(run, name, arguments)
    additions = evidence_items(run, name, pairs)
    run.evidence += additions
    AgentRun.objects.filter(pk=run.id).update(evidence=run.evidence)
    return result, [item["id"] for item in additions]


def _version(version_id, run=None):
    if run is not None:
        require_algorithm(run, version_id)
    version = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            pk=version_id,
            status="published",
            algorithm__enabled=True,
            algorithm__in=allowed_algorithms(),
        )
        .first()
    )
    if not version or not agent_algorithm_allowed(version):
        raise PermissionDenied("算法已停用或不允许智能体调用")
    return version


def _history(run):
    return run.conversation.runs.filter(id__lt=run.id, owner_id=run.owner_id).order_by(
        "-id"
    )


def previous_plan(run):
    for previous in _history(run)[:30]:
        if previous.compute_intent and previous.compute_intent.get("status") in OPEN:
            selected = algorithm_ids(run)
            if (
                selected is not None
                and previous.compute_intent["versionId"] not in selected
            ):
                continue
            if run.resource_ids and not set(
                previous.compute_intent["inputs"].values()
            ) <= set(run.resource_ids):
                continue
            return previous
    return None


def _selected(run):
    if run.resource_ids:
        return list(run.resource_ids)
    if run.data_selection_mode == "manual":
        return []
    if not re.search(
        r"这个|这张|这幅|这份|该影像|该数据|同一|继续|对啊|就是|它", run.prompt
    ):
        return []
    for previous in _history(run)[:30]:
        if previous.resource_ids:
            return list(previous.resource_ids)
        described = {
            ev["resourceId"]
            for ev in previous.evidence
            if ev.get("tool") == "describe_resource"
            and type(ev.get("resourceId")) is int
        }
        if len(described) == 1:
            return list(described)
    return []


def match_version(run):
    if not computation_requested(run.prompt):
        return None
    found = []
    selected = algorithm_ids(run)
    if selected is not None and len(selected) == 1:
        chosen = _version(selected[0], run)
        if not algorithm_match(run.prompt, chosen.algorithm) and any(
            a.id != chosen.algorithm_id and algorithm_match(run.prompt, a)
            for a in allowed_algorithms().filter(enabled=True)
        ):
            raise ValidationError("问题中的算法与手选算法不一致，请调整算法选择或问题")
        return chosen
    for algorithm in (
        allowed_algorithms().filter(enabled=True).prefetch_related("versions")
    ):
        if not algorithm_match(run.prompt, algorithm):
            continue
        versions = [
            v
            for v in algorithm.versions.all()
            if v.status == "published"
            and agent_algorithm_allowed(v)
            and (selected is None or v.id in selected)
        ]
        found.extend(versions if selected is not None else versions[:1])
    if len(found) > 1 and selected is not None:
        named_versions = [
            v
            for v in found
            if re.search(rf"(?<![\d.]){re.escape(v.version)}(?![\d.])", run.prompt)
        ]
        if len(named_versions) == 1:
            return named_versions[0]
    return found[0] if len(found) == 1 else None


def _signature(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@lru_cache(maxsize=256)
def _candidate(resource_id, project_id, updated_at):
    from apps.catalog.models import DataResource

    resource = DataResource.objects.get(pk=resource_id, project_tag_id=project_id)
    return candidate(resource)


def _save(run, intent):
    run.compute_intent = intent
    AgentRun.objects.filter(pk=run.id).update(
        compute_intent=intent, updated_at=timezone.now()
    )


def _refresh(run, user, p, *, validate_snapshot=False):
    intent = dict(run.compute_intent)
    version = _version(intent["versionId"], run)
    if version.checksum != intent["algorithmChecksum"]:
        raise ValidationError("算法版本内容已变化，请重新发起计算")
    manifest = version.manifest
    metadata, snapshots = {}, {}
    inputs = intent["inputs"]
    if set(inputs) - {spec["key"] for spec in manifest["inputs"]}:
        raise ValidationError("包含算法未声明的输入")
    for key, resource_id in inputs.items():
        resource = resolve_resource(user, p, resource_id, run.resource_ids)
        if (
            validate_snapshot
            and intent.get("inputSnapshots", {}).get(key)
            != resource.updated_at.isoformat()
        ):
            raise ValidationError("输入数据已变化，请重新核对后发起计算")
        metadata[key] = candidate(resource)
        snapshots[key] = resource.updated_at.isoformat()
    missing_inputs = [
        spec["key"]
        for spec in manifest["inputs"]
        if spec["required"] and spec["key"] not in inputs
    ]
    params = dict(intent["parameters"])
    if set(params) - {spec["key"] for spec in manifest["parameters"]}:
        raise ValidationError("包含算法未声明的参数")
    missing_params = []
    for spec in manifest["parameters"]:
        when = spec.get("when")
        if when and params.get(when["key"]) != when["equals"]:
            params.pop(spec["key"], None)
            continue
        key = spec["key"]
        if (
            key not in params
            and spec["type"] not in {"band", "field"}
            and "default" in spec
        ):
            params[key] = spec["default"]
        if key not in params and spec["required"]:
            missing_params.append(key)
        if key in params and spec["type"] in {"band", "field"}:
            value = params[key]
            source = metadata.get(spec["input"])
            if source and (
                spec["type"] == "band"
                and (type(value) is not int or not 1 <= value <= source["bands"])
                or spec["type"] == "field"
                and (not isinstance(value, str) or value not in source["fields"])
            ):
                raise ValidationError(spec["label"] + "不属于当前输入数据")
    intent.update(
        parameters=params,
        inputSnapshots=snapshots,
        missingInputs=missing_inputs,
        missingParameters=missing_params,
        status="collecting" if missing_inputs or missing_params else "ready",
    )
    intent["message"] = (
        "请选择输入数据和参数，选好后即可计算"
        if intent["status"] == "collecting"
        else "参数已就绪，可以开始计算"
    )
    intent["planRevision"] = _signature(
        {
            key: intent[key]
            for key in (
                "versionId",
                "algorithmChecksum",
                "inputs",
                "inputSnapshots",
                "parameters",
                "autoImport",
            )
        }
    )
    _save(run, intent)
    return version


def _prepare(run, user, p, version, inherited=None):
    manifest = version.manifest
    selected = _selected(run)
    inputs = {}
    if inherited and inherited.compute_intent["versionId"] == version.id:
        inputs = dict(inherited.compute_intent["inputs"])
    if selected:
        selected_resources = [
            resolve_resource(user, p, resource_id, run.resource_ids)
            for resource_id in selected
        ]
        for spec in manifest["inputs"]:
            matches = [r for r in selected_resources if r.data_type == spec["kind"]]
            if len(matches) == 1:
                inputs[spec["key"]] = matches[0].id
    if not inputs:
        for spec in manifest["inputs"]:
            matches = [
                r
                for r in resources(user, p, run.resource_ids)
                .filter(data_type=spec["kind"])
                .order_by("id")[:100]
                if r.name and r.name.casefold() in run.prompt.casefold()
            ]
            if len(matches) == 1:
                inputs[spec["key"]] = matches[0].id
    params = {}
    if (
        inherited
        and inherited.compute_intent["versionId"] == version.id
        and inputs == inherited.compute_intent["inputs"]
    ):
        params = dict(inherited.compute_intent["parameters"])
    explicit, conflicts = explicit_parameters(run.prompt, manifest)
    params.update(explicit)
    for key in conflicts:
        params.pop(key, None)
    warnings = ["同一参数出现了不同选择，请在卡片中核对"] if conflicts else []
    if any(spec["type"] == "band" for spec in manifest["parameters"]):
        warnings.append(
            "波段号按当前影像的实际顺序选择；未知辐射定标会影响指数的科学解释。"
        )
    auto_import = bool(
        inherited
        and inherited.compute_intent["versionId"] == version.id
        and inherited.compute_intent["autoImport"]
    )
    if re.search(r"自动.{0,4}入库", run.prompt):
        auto_import = not bool(
            re.search(r"(?:不|不要|无需).{0,3}自动.{0,4}入库", run.prompt)
        )
    _save(
        run,
        {
            "versionId": version.id,
            "algorithmChecksum": version.checksum,
            "status": "collecting",
            "message": "正在核对算法与数据",
            "inputs": inputs,
            "parameters": params,
            "missingInputs": [],
            "missingParameters": [],
            "warnings": warnings,
            "knowledgeEvidenceIds": [],
            "taskId": None,
            "autoImport": auto_import,
            "planRevision": "",
        },
    )
    _refresh(run, user, p)
    if inherited:
        old = {
            **inherited.compute_intent,
            "status": "superseded",
            "message": "已由本轮参数选择替代",
        }
        _save(inherited, old)
    _, evidence_ids = record_tool(
        run, "list_compute_algorithms", {"query": version.algorithm.identifier}
    )
    knowledge_ids = []
    if knowledge_selection(run)["mode"] != "none":
        try:
            _, knowledge_ids = record_tool(
                run, "search_knowledge", {"query": version.algorithm.name}
            )
        except (ValidationError, ComputeError):
            knowledge_ids = []
    _save(run, {**run.compute_intent, "knowledgeEvidenceIds": knowledge_ids})
    return evidence_ids


def serialize(run, user, p):
    intent = run.compute_intent
    if not intent:
        return None
    version = _version(intent["versionId"], run)
    for resource_id in intent["inputs"].values():
        resolve_resource(user, p, resource_id, run.resource_ids)
    candidates = []
    kinds = {spec["kind"] for spec in version.manifest["inputs"]}
    eligible = resources(user, p, run.resource_ids).filter(data_type__in=kinds)
    chosen = set(intent["inputs"].values())
    visible_candidates = [
        *eligible.filter(pk__in=chosen).order_by("id"),
        *eligible.exclude(pk__in=chosen).order_by("name", "id")[:10],
    ]
    for resource in visible_candidates:
        try:
            candidates.append(
                _candidate(
                    resource.id,
                    resource.project_tag_id,
                    resource.updated_at.isoformat(),
                )
            )
        except ComputeError:
            continue
    return {
        **{
            key: intent[key]
            for key in (
                "status",
                "message",
                "inputs",
                "parameters",
                "missingInputs",
                "missingParameters",
                "warnings",
                "knowledgeEvidenceIds",
                "taskId",
                "autoImport",
                "planRevision",
            )
        },
        "algorithm": version_data(version),
        "inputCandidates": candidates,
    }


def submit_plan(run, user, p):
    if run.compute_intent.get("taskId"):
        from .compute_tools import authorized_task

        authorized_task(user, run.compute_intent["taskId"], p)
        return report(run, user, p)
    _refresh(run, user, p, validate_snapshot=True)
    intent = run.compute_intent
    if intent["status"] != "ready":
        raise ValidationError("请先选择缺少的输入数据和参数")
    version = _version(intent["versionId"], run)
    names = [
        resolve_resource(user, p, resource_id, run.resource_ids).name
        for resource_id in intent["inputs"].values()
    ]
    name = ("、".join(names) + " · " + version.algorithm.name)[:160]
    result, _ = record_tool(
        run,
        "execute_operator",
        {
            "versionId": version.id,
            "inputs": intent["inputs"],
            "parameters": intent["parameters"],
            "name": name,
            "autoImport": intent["autoImport"],
        },
    )
    _save(
        run,
        {
            **intent,
            "status": "submitted",
            "message": "计算已提交，进度会自动更新",
            "taskId": result["taskId"],
        },
    )
    return report(run, user, p)


def prepare_from_tool(run, user, p, version, inputs):
    """Model discovery may propose a plan, but cannot confirm user band choices."""
    interactive = [
        spec
        for spec in version.manifest["parameters"]
        if spec["type"] in {"band", "field"}
    ]
    if not interactive:
        return None
    intent = run.compute_intent
    if (
        intent
        and intent.get("versionId") == version.id
        and intent.get("status") == "ready"
    ):
        return None
    _prepare(run, user, p, version)
    intent = {**run.compute_intent, "inputs": inputs}
    _save(run, intent)
    _refresh(run, user, p)
    if run.compute_intent["status"] == "ready":
        return None
    return {
        "needsInput": True,
        "message": run.compute_intent["message"],
        "detail": "使用计算卡片选择真实输入和参数；这不是已提交的计算任务。",
    }


def update(run, user, p, value):
    if run.cancel_requested or run.conversation.archived:
        raise ComputeError("本轮已停止或会话已归档", 409)
    intent = run.compute_intent
    if not intent:
        raise ValidationError("本轮没有待处理的计算计划")
    if intent["status"] in {"superseded", "cancelled"}:
        raise ComputeError("计算计划已被替代或取消，请使用最新卡片", 409)
    if value.get("planRevision") != intent["planRevision"]:
        raise ComputeError("参数选择已更新，请刷新卡片", 409)
    action = value.get("action")
    if action not in {"update", "submit", "cancel"}:
        raise ValidationError("请选择更新、运行或取消操作")
    if action == "cancel":
        if intent.get("taskId"):
            raise ComputeError("计算已提交，请通过任务卡停止计算", 409)
        _save(run, {**intent, "status": "cancelled", "message": "计算计划已取消"})
        return
    if intent.get("taskId"):
        if action == "submit" and all(
            value.get(key, intent[key]) == intent[key]
            for key in ("inputs", "parameters", "autoImport")
        ):
            submit_plan(run, user, p)
            return
        raise ComputeError("计算已提交，不能修改本次输入参数", 409)
    with transaction.atomic():
        AgentRun.objects.filter(pk=run.id).update(updated_at=timezone.now())
        run.refresh_from_db()
        if run.compute_intent["planRevision"] != value["planRevision"]:
            raise ComputeError("参数选择已更新，请刷新卡片", 409)
        newer = run.conversation.runs.filter(id__gt=run.id).exclude(compute_intent={})
        if newer.exists():
            raise ComputeError("已有更新的计算计划，请使用最新卡片", 409)
        intent = dict(run.compute_intent)
        if action == "submit":
            requested_inputs = value.get("inputs", intent["inputs"])
            for key, resource_id in intent["inputs"].items():
                if requested_inputs.get(key) == resource_id:
                    resource = resolve_resource(user, p, resource_id, run.resource_ids)
                    if (
                        intent.get("inputSnapshots", {}).get(key)
                        != resource.updated_at.isoformat()
                    ):
                        raise ValidationError("输入数据已变化，请重新核对后发起计算")
        for key in ("inputs", "parameters"):
            if key in value:
                if not isinstance(value[key], dict) or len(value[key]) > 100:
                    raise ValidationError("输入数据与参数必须为对象")
                intent[key] = value[key]
        if "autoImport" in value:
            if type(value["autoImport"]) is not bool:
                raise ValidationError("自动入库选项无效")
            intent["autoImport"] = value["autoImport"]
        _save(run, intent)
        _refresh(run, user, p)
        if action == "submit":
            answer = submit_plan(run, user, p)
            run.answer = answer
            AgentRun.objects.filter(pk=run.id).update(answer=answer)


def process(run, user, p):
    """Fast deterministic path; return None for ordinary conversational work."""
    if run.conversation.mode != "agent":
        return None
    version = match_version(run)
    prior = previous_plan(run)
    if not version and prior:
        previous_version = _version(prior.compute_intent["versionId"], run)
        explicit, _ = explicit_parameters(run.prompt, previous_version.manifest)
        if explicit:
            version = previous_version
    if version:
        # This deterministic reply uses real calls and parameter plans, rather
        # than model history. Keep its provenance independent of older answers.
        run.knowledge_selection = {
            **(run.knowledge_selection or {}),
            "_contextRunIds": [],
        }
        AgentRun.objects.filter(pk=run.id).update(
            knowledge_selection=run.knowledge_selection
        )
        if not p.get("operatorEnabled", False):
            raise PermissionDenied("智能体算子调用尚未开启")
        try:
            _prepare(run, user, p, version, prior)
        except (ValidationError, ComputeError) as exc:
            if not run.compute_intent:
                raise
            _save(
                run,
                {**run.compute_intent, "status": "blocked", "message": str(exc)[:300]},
            )
        if run.compute_intent["status"] == "ready":
            try:
                return submit_plan(run, user, p)
            except (ValidationError, ComputeError) as exc:
                _save(
                    run,
                    {
                        **run.compute_intent,
                        "status": "blocked",
                        "message": str(exc)[:300],
                    },
                )
        return (
            run.compute_intent["message"]
            + "。请在下方计算卡片中选择；进度和结果会在这里持续更新。"
        )
    if computation_requested(run.prompt) and len(algorithm_ids(run) or []) > 1:
        return "本轮选择了多个算法版本，请在算法按钮中保留一个，或在问题中明确要运行的算法名称和版本。"
    if followup_question(run.prompt):
        run.knowledge_selection = {
            **(run.knowledge_selection or {}),
            "_contextRunIds": [],
        }
        AgentRun.objects.filter(pk=run.id).update(
            knowledge_selection=run.knowledge_selection
        )
        task_ids = conversation_tasks(run)
        if not task_ids:
            if algorithm_ids(run) is not None or run.resource_ids:
                return "当前算法和数据选择范围内没有本会话的已提交计算；请调整选择或从对应任务卡查看结果。"
            return (
                "本会话还没有实际提交的计算。请在计算卡片中选择输入数据和波段后运行。"
            )
        if len(task_ids) > 1:
            return "本会话有多项计算，请在对应任务卡片中查看进度、打开结果或入库。"
        task_id = task_ids[0]
        if import_requested(run.prompt):
            record_tool(run, "import_compute_result", {"taskId": task_id})
        else:
            record_tool(run, "get_compute_task", {"taskId": task_id})
        return report(run, user, p)
    return None


def conversation_tasks(run):
    from .selections import scoped_task_ids

    ids = set()
    for item in run.conversation.runs.filter(owner_id=run.owner_id, id__lte=run.id):
        ids.update(
            str(identity)
            for identity in item.compute_followups.values_list("task_id", flat=True)
        )
        for evidence in item.evidence:
            if evidence.get("tool") in {
                "execute_operator",
                "get_compute_task",
                "import_compute_result",
            }:
                result = evidence.get("result", {})
                if isinstance(result, dict) and isinstance(result.get("taskId"), str):
                    ids.add(result["taskId"])
    return sorted(scoped_task_ids(run, ids))


def report(run, user, p):
    from .compute_tools import run_tasks

    cards = run_tasks(run, user, p)["items"]
    if not cards:
        return "本轮尚无实际提交的计算；请完成计算卡片中的数据和参数选择。"
    lines = []
    for card in cards:
        task = card["task"]
        if task["status"] == "succeeded":
            lines.append(
                f"**{task['name']}**计算完成。结果可通过下方卡片在地理工作台查看。"
            )
            ready = [
                output
                for output in task["outputs"]
                if output["importStatus"] == "ready" and output["resourceId"]
            ]
            if ready:
                for output in ready:
                    if output.get("resourceName") and output.get("resourceLocation"):
                        lines.append(
                            f"已保存至「{output['resourceLocation']}」，名称为「{output['resourceName']}」。"
                        )
            elif card["trackingStatus"] == "waiting_import":
                lines.append("正在入库，完成后卡片会显示数据目录中的位置。")
            elif card["trackingStatus"] == "blocked":
                lines.append("自动入库已暂停，结果保留；请查看任务卡说明。")
            else:
                lines.append("结果已保留；可先查看，再选择是否入库。")
        elif task["status"] in {"failed", "cancelled"}:
            lines.append(
                f"**{task['name']}**"
                + (
                    "计算失败：" + task["error"]
                    if task["status"] == "failed"
                    else "已停止计算。"
                )
            )
        else:
            lines.append(
                f"**{task['name']}**已提交，当前{task['stage']}（{task['progress']}%）。平台会自动跟踪，完成后在卡片中显示结果。"
            )
    return "\n\n".join(lines)
