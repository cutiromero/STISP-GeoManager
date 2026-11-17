"""Project-bound navigation, reconstructed from authoritative tool evidence."""

from django.core.exceptions import PermissionDenied
from apps.catalog.models import WorkspaceScene
from apps.catalog.share_access import check_snapshot
from apps.compute.packages import ComputeError
from apps.core.permissions import has_feature_perm
from .resource_discovery import resolve_discoverable_resource

PAGES = {
    "business_flows": ("打开业务流", "/business-flows"),
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
        if (
            evidence.get("tool")
            in {
                "prepare_map_workspace",
                "get_map_workspace",
                "update_map_workspace",
                "export_map_workspace",
                "get_export_task",
            }
            and policy.get("mapDisplayEnabled", True)
            and value.get("workspaceId") not in seen
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
            if not scene or (
                evidence.get("tool") == "prepare_map_workspace"
                and scene.snapshot.get("agentSource", {}).get("runId") != str(run.id)
            ):
                continue
            try:
                from .workspace_tools import context

                _, _, bound = context(run, user, policy, scene.pk)
                references = [{"id": resource.pk} for resource in bound]
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
        if evidence.get("tool") in {
            "export_map_workspace",
            "get_export_task",
        } and isinstance(value.get("jobId"), str):
            identity = value["jobId"]
            if identity not in seen:
                from .export_tools import read_export

                try:
                    exported, bound = read_export(run, user, policy, identity)
                except (PermissionDenied, ComputeError):
                    continue
                if exported["artifactAvailable"]:
                    seen.add(identity)
                    result.append(
                        {
                            "kind": "export",
                            "jobId": identity,
                            "projectId": run.project_tag_id,
                            "title": "下载导出文件",
                            "resourceIds": [resource.pk for resource in bound],
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
