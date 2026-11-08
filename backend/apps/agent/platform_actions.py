"""Project-bound navigation, reconstructed from authoritative tool evidence."""

from django.core.exceptions import PermissionDenied
from apps.catalog.models import WorkspaceScene
from apps.catalog.share_access import check_snapshot
from apps.compute.packages import ComputeError
from apps.core.permissions import has_feature_perm
from .resource_discovery import resolve_discoverable_resource

PAGES = {
    "map": ("打开地理工作台", "/map"),
    "resources": ("打开数据资源", "/resources/catalog"),
    "compute": ("打开计算中心", "/compute"),
    "knowledge": ("打开知识库", "/resources/knowledge-base"),
}


def platform_actions(run, user, policy):
    result = []
    seen = set()
    for evidence in run.evidence:
        value = evidence.get("result", {})
        if evidence.get("tool") == "prepare_map_workspace" and policy.get(
            "mapDisplayEnabled", True
        ):
            identity = value.get("workspaceId")
            if type(identity) is not int or identity in seen:
                continue
            if not has_feature_perm(user, "catalog.view_workspacescene"):
                continue
            scene = WorkspaceScene.objects.filter(
                pk=identity,
                owner=user,
                project_tag_id=run.project_tag_id,
                status="active",
            ).first()
            if not scene or scene.snapshot.get("agentSource", {}).get("runId") != str(
                run.id
            ):
                continue
            references = scene.snapshot.get("agentSource", {}).get("resources", [])
            if (
                not isinstance(references, list)
                or not references
                or any(
                    not isinstance(item, dict)
                    or type(item.get("id")) is not int
                    or item["id"] <= 0
                    for item in references
                )
            ):
                continue
            try:
                check_snapshot(scene.snapshot, user, run.project_tag_id)
                for item in references:
                    resolve_discoverable_resource(
                        user, policy, item["id"], run.resource_ids
                    )
            except (PermissionDenied, ComputeError):
                continue
            seen.add(identity)
            result.append(
                {
                    "kind": "workspace",
                    "sceneId": scene.id,
                    "projectId": run.project_tag_id,
                    "title": scene.name,
                    "resourceIds": [item["id"] for item in references],
                }
            )
        elif evidence.get("tool") == "get_platform_link":
            page = value.get("page")
            if page in PAGES and page not in seen:
                seen.add(page)
                result.append(
                    {
                        "kind": "page",
                        "page": page,
                        "projectId": run.project_tag_id,
                        "title": PAGES[page][0],
                        "resourceIds": [],
                    }
                )
    return result[-10:]
