from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import DataResource
from apps.catalog.permissions import user_can_access
from apps.catalog.serializers import serialize_resource
from apps.core.api import api_login_required
from apps.core.permissions import feature_denied_response, has_feature_perm
from apps.core.runtime_config import RuntimeConfigError, runtime_upload_max_mb
from apps.core.storage import gene_data_path, table_data_path


class NonGeoAnalysisError(ValueError):
    pass


ANALYSIS_SAMPLE_LIMIT = 10_000
DEFAULT_QUERY_LIMIT = 80
MAX_QUERY_LIMIT = 500
MAX_DIRECT_FILE_ANALYSIS_MB = 64
SUPPORTED_TABLE_SUFFIXES = {".csv", ".tsv", ".xls", ".xlsx"}
SUPPORTED_GENE_SUFFIXES = {
    ".fa",
    ".fasta",
    ".fq",
    ".fastq",
    ".vcf",
    ".gff",
    ".gff3",
    ".gb",
    ".gbk",
}


@require_GET
@api_login_required
def resource_nongeo_analysis(request, pk: int):
    resource, error = _authorized_resource(request, pk)
    if error:
        return error
    try:
        dataframe, total_count, descriptions = _resource_dataframe(
            resource,
            limit=ANALYSIS_SAMPLE_LIMIT,
            offset=0,
        )
        payload = _analytics_payload(
            resource,
            dataframe,
            total_count=total_count,
            descriptions=descriptions,
        )
    except NonGeoAnalysisError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse(payload)


@require_POST
@api_login_required
def resource_nongeo_query(request, pk: int):
    resource, error = _authorized_resource(request, pk)
    if error:
        return error
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"detail": "请求体不是有效 JSON"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "请求体必须是 JSON 对象"}, status=400)
    try:
        limit = _bounded_integer(payload.get("limit", DEFAULT_QUERY_LIMIT), 1, MAX_QUERY_LIMIT, "limit")
        offset = _bounded_integer(payload.get("offset", 0), 0, 10_000_000, "offset")
        sort_field = str(payload.get("sortField") or "").strip() or None
        sort_direction = str(payload.get("sortDirection") or "asc").strip().lower()
        if sort_direction not in {"asc", "desc"}:
            raise NonGeoAnalysisError("sortDirection 仅支持 asc 或 desc")
        dataframe, total_count, descriptions = _resource_dataframe(
            resource,
            limit=limit,
            offset=offset,
            sort_field=sort_field,
            sort_direction=sort_direction,
        )
    except NonGeoAnalysisError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse(
        _table_payload(
            resource,
            dataframe,
            total_count=total_count,
            limit=limit,
            offset=offset,
            descriptions=descriptions,
        )
    )


def _authorized_resource(request, pk: int):
    if not has_feature_perm(request.user, "core.query_data"):
        return None, feature_denied_response(request.user)
    resource = DataResource.objects.filter(pk=pk, status=DataResource.Status.ACTIVE).first()
    if resource is None:
        return None, JsonResponse({"detail": "数据资源不存在"}, status=404)
    if resource.data_type not in {DataResource.DataType.TABLE, DataResource.DataType.GENE}:
        return None, JsonResponse({"detail": "该资源不是可分析的非地理表格或基因数据"}, status=400)
    if not user_can_access(resource, request.user):
        return None, JsonResponse({"detail": "无权访问该数据资源"}, status=403)
    return resource, None


def _resource_dataframe(
    resource: DataResource,
    *,
    limit: int,
    offset: int,
    sort_field: str | None = None,
    sort_direction: str = "asc",
) -> tuple[pd.DataFrame, int, dict[str, str]]:
    if resource.data_type == DataResource.DataType.TABLE and resource.file_format.upper() == "SQLITE":
        return _sqlite_dataframe(
            resource,
            limit=limit,
            offset=offset,
            sort_field=sort_field,
            sort_direction=sort_direction,
        )
    path = _resource_file_path(resource)
    dataframe = _read_resource_file(resource, path)
    descriptions: dict[str, str] = {}
    total_count = int(len(dataframe))
    if sort_field:
        if sort_field not in dataframe.columns:
            raise NonGeoAnalysisError(f"排序字段不存在：{sort_field}")
        dataframe = dataframe.sort_values(
            by=sort_field,
            ascending=sort_direction == "asc",
            na_position="last",
            kind="stable",
        )
    return dataframe.iloc[offset : offset + limit].copy(), total_count, descriptions


def _sqlite_dataframe(
    resource: DataResource,
    *,
    limit: int,
    offset: int,
    sort_field: str | None,
    sort_direction: str,
) -> tuple[pd.DataFrame, int, dict[str, str]]:
    path = table_data_path("data.sqlite")
    if not path.is_file():
        raise NonGeoAnalysisError("非地理表格数据库不存在")
    table_name = resource.storage_path.strip()
    if not table_name:
        raise NonGeoAnalysisError("数据资源缺少后台表格标识")
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if not exists:
            raise NonGeoAnalysisError("数据资源对应的后台表格不存在")
        quoted_table = _quote_sqlite_identifier(table_name)
        column_rows = connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
        columns = [str(row[1]) for row in column_rows]
        if not columns:
            raise NonGeoAnalysisError("后台表格没有可分析字段")
        if sort_field and sort_field not in columns:
            raise NonGeoAnalysisError(f"排序字段不存在：{sort_field}")
        total_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
        )
        order_sql = ""
        if sort_field:
            direction = "DESC" if sort_direction == "desc" else "ASC"
            order_sql = f" ORDER BY {_quote_sqlite_identifier(sort_field)} {direction}"
        dataframe = pd.read_sql_query(
            f"SELECT * FROM {quoted_table}{order_sql} LIMIT ? OFFSET ?",
            connection,
            params=(limit, offset),
        )
        descriptions: dict[str, str] = {}
        metadata_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'data_columns'"
        ).fetchone()
        if metadata_table:
            descriptions = {
                str(column): str(description or "")
                for column, description in connection.execute(
                    "SELECT column_name, description FROM data_columns WHERE table_name = ?",
                    (table_name,),
                ).fetchall()
            }
    return dataframe, total_count, descriptions


def _resource_file_path(resource: DataResource) -> Path:
    relative = PurePosixPath(resource.storage_path.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise NonGeoAnalysisError("数据资源存储路径无效")
    root = gene_data_path().parent.resolve()
    path = root.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise NonGeoAnalysisError("数据资源存储路径越出非地理数据目录") from exc
    if not path.is_file():
        raise NonGeoAnalysisError("数据资源文件不存在")
    try:
        configured_mb = runtime_upload_max_mb()
    except RuntimeConfigError as exc:
        raise NonGeoAnalysisError(str(exc)) from exc
    safe_limit_mb = min(configured_mb, MAX_DIRECT_FILE_ANALYSIS_MB)
    if path.stat().st_size > safe_limit_mb * 1024 * 1024:
        raise NonGeoAnalysisError(
            f"源文件超过 {safe_limit_mb} MB 在线分析安全限制，请先导入平台表格库"
        )
    return path


def _read_resource_file(resource: DataResource, path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if resource.data_type == DataResource.DataType.TABLE:
        if suffix not in SUPPORTED_TABLE_SUFFIXES:
            raise NonGeoAnalysisError("该表格文件格式暂不支持在线分析")
        if suffix in {".csv", ".tsv"}:
            separator = "\t" if suffix == ".tsv" else ","
            last_error: Exception | None = None
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    return pd.read_csv(path, sep=separator, encoding=encoding)
                except UnicodeDecodeError as exc:
                    last_error = exc
            raise NonGeoAnalysisError(f"表格文件编码无法识别：{last_error}")
        try:
            return pd.read_excel(path)
        except Exception as exc:
            raise NonGeoAnalysisError(f"读取表格文件失败：{exc}") from exc
    if suffix not in SUPPORTED_GENE_SUFFIXES:
        raise NonGeoAnalysisError("该基因文件格式暂不支持在线分析")
    if suffix in {".fa", ".fasta"}:
        return pd.DataFrame(_read_fasta(path))
    if suffix in {".fq", ".fastq"}:
        return pd.DataFrame(_read_fastq(path))
    if suffix == ".vcf":
        return _read_vcf(path)
    if suffix in {".gff", ".gff3"}:
        return _read_gff(path)
    return pd.DataFrame(_read_genbank(path))


def _read_fasta(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    identifier = ""
    description = ""
    sequence_parts: list[str] = []

    def append_record() -> None:
        if not identifier:
            return
        sequence = "".join(sequence_parts).upper()
        canonical = sum(sequence.count(base) for base in "ACGT")
        gc_count = sequence.count("G") + sequence.count("C")
        records.append(
            {
                "sequenceId": identifier,
                "description": description,
                "length": len(sequence),
                "gcContent": round(gc_count / canonical, 6) if canonical else None,
                "sequencePreview": sequence[:80],
            }
        )

    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            text = line.strip()
            if text.startswith(">"):
                append_record()
                header = text[1:].strip()
                identifier, _, description = header.partition(" ")
                sequence_parts = []
            elif text:
                sequence_parts.append(text)
    append_record()
    if not records:
        raise NonGeoAnalysisError("FASTA 文件没有有效序列记录")
    return records


def _read_fastq(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        while True:
            header = source.readline()
            if not header:
                break
            sequence = source.readline().strip().upper()
            separator = source.readline()
            quality = source.readline().rstrip("\r\n")
            if not header.startswith("@") or not separator.startswith("+") or len(sequence) != len(quality):
                raise NonGeoAnalysisError("FASTQ 文件结构无效或记录不完整")
            identifier, _, description = header[1:].strip().partition(" ")
            canonical = sum(sequence.count(base) for base in "ACGT")
            gc_count = sequence.count("G") + sequence.count("C")
            mean_quality = (
                sum(max(0, ord(character) - 33) for character in quality) / len(quality)
                if quality
                else 0
            )
            records.append(
                {
                    "sequenceId": identifier,
                    "description": description,
                    "length": len(sequence),
                    "gcContent": round(gc_count / canonical, 6) if canonical else None,
                    "meanQuality": round(mean_quality, 3),
                    "sequencePreview": sequence[:80],
                }
            )
    if not records:
        raise NonGeoAnalysisError("FASTQ 文件没有有效序列记录")
    return records


def _read_vcf(path: Path) -> pd.DataFrame:
    header: list[str] | None = None
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if line.startswith("##"):
                continue
            if line.startswith("#"):
                header = line.lstrip("#").rstrip("\r\n").split("\t")
                continue
            if line.strip():
                rows.append(line.rstrip("\r\n").split("\t"))
    if not header:
        raise NonGeoAnalysisError("VCF 文件缺少字段头")
    return pd.DataFrame(rows, columns=header[: max((len(row) for row in rows), default=len(header))])


def _read_gff(path: Path) -> pd.DataFrame:
    columns = ["seqid", "source", "type", "start", "end", "score", "strand", "phase", "attributes"]
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if not line.startswith("#") and line.strip():
                values = line.rstrip("\r\n").split("\t")
                if len(values) == len(columns):
                    rows.append(values)
    if not rows:
        raise NonGeoAnalysisError("GFF 文件没有有效注释记录")
    return pd.DataFrame(rows, columns=columns)


def _read_genbank(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for line in source:
            if line.startswith("LOCUS"):
                if current:
                    records.append(current)
                tokens = line.split()
                current = {
                    "locus": tokens[1] if len(tokens) > 1 else "",
                    "length": _safe_int(tokens[2]) if len(tokens) > 2 else None,
                    "definition": "",
                    "accession": "",
                }
            elif current is not None and line.startswith("DEFINITION"):
                current["definition"] = line[12:].strip()
            elif current is not None and line.startswith("ACCESSION"):
                current["accession"] = line[12:].strip().split()[0] if line[12:].strip() else ""
            elif line.startswith("//") and current:
                records.append(current)
                current = None
    if current:
        records.append(current)
    if not records:
        raise NonGeoAnalysisError("GenBank 文件没有有效记录")
    return records


def _analytics_payload(
    resource: DataResource,
    dataframe: pd.DataFrame,
    *,
    total_count: int,
    descriptions: dict[str, str],
) -> dict[str, Any]:
    profiles = _field_profiles(dataframe, total_count=total_count, descriptions=descriptions)
    categorical = _categorical_distributions(dataframe, profiles)
    numeric = _numeric_distributions(dataframe, profiles)
    correlation = _correlation(dataframe, profiles)
    analyzed_count = int(len(dataframe))
    completeness = (
        sum(float(profile["completeness"]) for profile in profiles) / len(profiles)
        if profiles
        else 0
    )
    numeric_count = sum(profile["role"] == "measure" for profile in profiles)
    category_count = sum(profile["role"] == "category" for profile in profiles)
    text_count = sum(profile["role"] in {"text", "identifier"} for profile in profiles)
    suggested_view = _suggested_view(profiles)
    preview = _table_payload(
        resource,
        dataframe.head(DEFAULT_QUERY_LIMIT),
        total_count=total_count,
        limit=DEFAULT_QUERY_LIMIT,
        offset=0,
        descriptions=descriptions,
    )
    insights = [
        f"资源包含 {total_count} 条记录和 {len(profiles)} 个字段。",
        f"当前统计基于 {analyzed_count} 条真实记录，字段平均完整率为 {completeness:.1%}。",
    ]
    if analyzed_count < total_count:
        insights.append(
            f"为保障在线分析稳定性，分布与相关性基于前 {analyzed_count} 条记录抽样；明细总数仍为真实全量计数。"
        )
    elif numeric_count:
        insights.append(f"检测到 {numeric_count} 个数值指标，可用于分布和相关性分析。")
    return {
        "resource": serialize_resource(resource),
        "summary": {
            "rowCount": total_count,
            "analyzedRowCount": analyzed_count,
            "sampled": analyzed_count < total_count,
            "fieldCount": len(profiles),
            "numericFieldCount": numeric_count,
            "textFieldCount": text_count,
            "categoricalFieldCount": category_count,
            "completeness": round(completeness, 6),
            "updatedAt": resource.updated_at.isoformat(),
            "suggestedView": suggested_view,
        },
        "fields": profiles,
        "categoricalDistributions": categorical,
        "numericDistributions": numeric,
        "correlation": correlation,
        "tablePreview": preview,
        "insights": insights,
    }


def _field_profiles(
    dataframe: pd.DataFrame,
    *,
    total_count: int,
    descriptions: dict[str, str],
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    analyzed_count = len(dataframe)
    for column_value in dataframe.columns:
        column = str(column_value)
        series = dataframe[column_value]
        missing = series.isna() | series.astype(str).str.strip().eq("")
        populated = series[~missing]
        numeric = pd.to_numeric(populated, errors="coerce")
        numeric_ratio = float(numeric.notna().mean()) if len(populated) else 0
        is_numeric = bool(len(populated) and numeric_ratio >= 0.9)
        unique_count = int(populated.nunique(dropna=True))
        role = _field_role(column, unique_count, len(populated), is_numeric)
        non_null_count = int((~missing).sum())
        estimated_non_null = (
            round(non_null_count / analyzed_count * total_count)
            if analyzed_count and analyzed_count < total_count
            else non_null_count
        )
        profile: dict[str, Any] = {
            "name": column,
            "type": _field_type(series, numeric, is_numeric),
            "label": column,
            "description": descriptions.get(column, ""),
            "unit": "",
            "role": role,
            "nullable": bool(missing.any()),
            "nonNullCount": estimated_non_null,
            "nullCount": max(0, total_count - estimated_non_null),
            "completeness": round(non_null_count / analyzed_count, 6) if analyzed_count else 0,
            "uniqueCount": unique_count,
            "sampleValues": [_json_scalar(value) for value in populated.head(3).tolist()],
        }
        if is_numeric and numeric.notna().any():
            values = numeric.dropna().astype(float)
            profile.update(
                {
                    "min": _finite_float(values.min()),
                    "max": _finite_float(values.max()),
                    "mean": _finite_float(values.mean()),
                }
            )
        profiles.append(profile)
    return profiles


def _field_role(name: str, unique_count: int, populated_count: int, is_numeric: bool) -> str:
    normalized = name.strip().lower()
    if any(token in normalized for token in ("longitude", "latitude", "lon", "lat", "经度", "纬度")):
        return "coordinate"
    if any(token in normalized for token in ("date", "time", "日期", "时间")):
        return "date"
    if normalized in {"id", "fid", "objectid"} or any(
        token in normalized for token in ("编号", "编码", "accession", "sequenceid")
    ):
        return "identifier"
    if is_numeric:
        return "measure"
    category_threshold = max(12, min(50, int(math.sqrt(max(populated_count, 1)) * 3)))
    if 0 < unique_count <= category_threshold:
        return "category"
    return "text"


def _field_type(series: pd.Series, numeric: pd.Series, is_numeric: bool) -> str:
    if is_numeric:
        values = numeric.dropna().astype(float)
        if len(values) and bool((values % 1 == 0).all()):
            return "integer"
        return "float"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    return "string"


def _categorical_distributions(dataframe: pd.DataFrame, profiles: list[dict[str, Any]]):
    result = []
    for profile in profiles:
        if profile["role"] != "category":
            continue
        series = dataframe[profile["name"]]
        populated = series[~(series.isna() | series.astype(str).str.strip().eq(""))]
        total = int(len(populated))
        counts = populated.value_counts(dropna=True).head(12)
        result.append(
            {
                "field": profile["name"],
                "label": profile["label"],
                "total": total,
                "items": [
                    {
                        "value": _json_scalar(value),
                        "count": int(count),
                        "ratio": round(int(count) / total, 6) if total else 0,
                    }
                    for value, count in counts.items()
                ],
            }
        )
    return result


def _numeric_distributions(dataframe: pd.DataFrame, profiles: list[dict[str, Any]]):
    result = []
    for profile in profiles:
        if profile["role"] != "measure":
            continue
        values = pd.to_numeric(dataframe[profile["name"]], errors="coerce").dropna().astype(float)
        if values.empty:
            continue
        minimum = float(values.min())
        maximum = float(values.max())
        bins = _histogram_bins(values, minimum, maximum)
        result.append(
            {
                "field": profile["name"],
                "label": profile["label"],
                "min": _finite_float(minimum),
                "max": _finite_float(maximum),
                "mean": _finite_float(values.mean()),
                "median": _finite_float(values.median()),
                "q1": _finite_float(values.quantile(0.25)),
                "q3": _finite_float(values.quantile(0.75)),
                "bins": bins,
            }
        )
    return result


def _histogram_bins(values: pd.Series, minimum: float, maximum: float):
    if minimum == maximum:
        return [
            {
                "label": _number_label(minimum),
                "min": _finite_float(minimum),
                "max": _finite_float(maximum),
                "count": int(len(values)),
                "ratio": 1,
            }
        ]
    width = (maximum - minimum) / 5
    result = []
    for index in range(5):
        lower = minimum + width * index
        upper = maximum if index == 4 else minimum + width * (index + 1)
        mask = (values >= lower) & (values <= upper if index == 4 else values < upper)
        count = int(mask.sum())
        result.append(
            {
                "label": f"{_number_label(lower)}-{_number_label(upper)}",
                "min": _finite_float(lower),
                "max": _finite_float(upper),
                "count": count,
                "ratio": round(count / len(values), 6),
            }
        )
    return result


def _correlation(dataframe: pd.DataFrame, profiles: list[dict[str, Any]]):
    fields = [profile["name"] for profile in profiles if profile["role"] == "measure"][:6]
    if len(fields) < 2:
        return None
    numeric = pd.DataFrame(
        {field: pd.to_numeric(dataframe[field], errors="coerce") for field in fields}
    )
    matrix = numeric.corr(min_periods=2)
    return {
        "fields": fields,
        "values": [
            [_finite_float(matrix.loc[row, column], fallback=0) for column in fields]
            for row in fields
        ],
    }


def _table_payload(
    resource: DataResource,
    dataframe: pd.DataFrame,
    *,
    total_count: int,
    limit: int,
    offset: int,
    descriptions: dict[str, str],
) -> dict[str, Any]:
    fields = []
    for column_value in dataframe.columns:
        column = str(column_value)
        series = dataframe[column_value]
        missing = series.isna() | series.astype(str).str.strip().eq("")
        populated = series[~missing]
        numeric = pd.to_numeric(populated, errors="coerce")
        is_numeric = bool(len(populated) and float(numeric.notna().mean()) >= 0.9)
        fields.append(
            {
                "name": column,
                "type": _field_type(series, numeric, is_numeric),
                "nullable": bool(missing.any()),
                "sampleValues": [_json_scalar(value) for value in populated.head(3).tolist()],
                "description": descriptions.get(column, ""),
            }
        )
    rows = [
        {str(column): _json_scalar(value) for column, value in row.items()}
        for row in dataframe.to_dict(orient="records")
    ]
    return {
        "resourceId": resource.id,
        "resourceName": resource.name,
        "totalCount": total_count,
        "returnedCount": len(rows),
        "limit": limit,
        "offset": offset,
        "fields": fields,
        "rows": rows,
    }


def _suggested_view(profiles: list[dict[str, Any]]) -> str:
    names = " ".join(profile["name"].lower() for profile in profiles)
    if any(token in names for token in ("species", "物种", "生活型")):
        return "species"
    if any(token in names for token in ("community", "群落")):
        return "community"
    if any(token in names for token in ("trait", "性状", "指标")):
        return "traits"
    if any(token in names for token in ("soil", "climate", "环境", "土壤")):
        return "environment"
    return "generic"


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _bounded_integer(value: Any, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool):
        raise NonGeoAnalysisError(f"{field} 必须是整数")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise NonGeoAnalysisError(f"{field} 必须是整数") from exc
    if result < minimum or result > maximum:
        raise NonGeoAnalysisError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
    return result


def _json_scalar(value: Any):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _finite_float(value: Any, fallback: float | None = None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(number, 6) if math.isfinite(number) else fallback


def _number_label(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _safe_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
