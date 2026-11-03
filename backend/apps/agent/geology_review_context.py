"""Model-only map evidence projection; execution and approval retain full geometry."""

from __future__ import annotations

import hashlib
import json
import math

from shapely.errors import GEOSException
from shapely.geometry import shape

from apps.compute.packages import ComputeError


def _geometry_summary(value, source):
    raw = (
        value
        if isinstance(value, str)
        else json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    try:
        geometry = json.loads(raw)
        geom = shape(geometry)
        bounds = list(geom.bounds)
        if (
            geom.is_empty
            or len(bounds) != 4
            or not all(math.isfinite(number) for number in bounds)
        ):
            raise ValueError("invalid geometry bounds")
    except (ValueError, TypeError, KeyError, AttributeError, GEOSException) as exc:
        raise ComputeError("模型分析资料缺少可核对的几何范围") from exc
    return {
        "type": geometry["type"],
        "bounds": bounds,
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "source": source,
        "coordinatesStoredInOriginal": True,
    }


def model_results(results):
    """Keep every actual table row and value except the coordinate transport."""
    projected = []
    for result in results:
        rows = []
        changed = False
        for index, row in enumerate(result.get("rows", [])):
            if "geometry_json" not in row:
                rows.append(row)
                continue
            changed = True
            rows.append(
                {
                    **{
                        key: value
                        for key, value in row.items()
                        if key != "geometry_json"
                    },
                    "geometrySummary": _geometry_summary(
                        row["geometry_json"],
                        {
                            "outputId": result["outputId"],
                            "outputChecksum": result["checksum"],
                            "rowIndex": index,
                            "column": "geometry_json",
                        },
                    ),
                }
            )
        if not changed:
            projected.append(result)
            continue
        value = {**result, "rows": rows}
        if "columns" in result:
            value["columns"] = [
                "geometrySummary" if name == "geometry_json" else name
                for name in result["columns"]
            ]
        projected.append(value)
    return projected


def model_review(review):
    if not isinstance(review, dict):
        return review
    suggestions = []
    for suggestion in review.get("suggestions", []):
        if "preview" not in suggestion:
            suggestions.append(suggestion)
            continue
        suggestions.append(
            {
                **{key: value for key, value in suggestion.items() if key != "preview"},
                "previewSummary": _geometry_summary(
                    suggestion["preview"],
                    {
                        "proposalHash": review["proposalHash"],
                        "suggestionId": suggestion["id"],
                        "field": "preview",
                    },
                ),
            }
        )
    return {**review, "suggestions": suggestions}
