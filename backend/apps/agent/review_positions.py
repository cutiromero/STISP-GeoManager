"""Bounded display positions for the full frozen automatic disposition scope."""

import math
from shapely.geometry import shape
from shapely.errors import GEOSException

POINT_LIMIT = 2000
GRID_SIZE = 16


def automatic_positions(plan):
    ids = set(plan.get("retainedReview", {}).get("automaticSuggestionIds", []))
    suggestions = plan.get("modificationReview", {}).get("suggestions", [])
    points = []
    for item in suggestions:
        if item["id"] not in ids:
            continue
        try:
            geometry = shape(item.get("preview") or {})
            if geometry.is_empty:
                continue
            point = geometry.representative_point()
            if not (
                math.isfinite(point.x)
                and math.isfinite(point.y)
                and -180 <= point.x <= 180
                and -85.051129 <= point.y <= 85.051129
            ):
                continue
            points.append(
                {
                    "id": item["id"],
                    "coordinates": [round(point.x, 6), round(point.y, 6)],
                    "count": 1,
                }
            )
        except (ValueError, TypeError, KeyError, AttributeError, GEOSException):
            continue
    located = len(points)
    if len(points) > POINT_LIMIT:
        west = min(p["coordinates"][0] for p in points)
        south = min(p["coordinates"][1] for p in points)
        width = max(p["coordinates"][0] for p in points) - west
        height = max(p["coordinates"][1] for p in points) - south
        cells = {}
        for point in points:
            x, y = point["coordinates"]
            key = (
                min(GRID_SIZE - 1, int((x - west) / width * GRID_SIZE)) if width else 0,
                min(GRID_SIZE - 1, int((y - south) / height * GRID_SIZE))
                if height
                else 0,
            )
            cell = cells.setdefault(
                key,
                {
                    "id": f"automatic-cell-{key[0]}-{key[1]}",
                    "sum": [0.0, 0.0],
                    "count": 0,
                },
            )
            cell["sum"][0] += x
            cell["sum"][1] += y
            cell["count"] += 1
        points = [
            {
                "id": item["id"],
                "coordinates": [value / item["count"] for value in item["sum"]],
                "count": item["count"],
            }
            for _, item in sorted(cells.items())
        ]
    return {"total": len(ids), "locatedCount": located, "points": points}
