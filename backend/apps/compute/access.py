from apps.core.permissions import has_feature_perm
from apps.core.initialization import is_guest_user
from apps.projects.context import current_scope
from apps.projects.access import can_access_project
from .packages import ComputeError


PERMISSIONS = (
    "submit_task",
    "view_own_task",
    "cancel_own_task",
    "manage_algorithms",
    "publish_algorithm",
    "download_algorithm",
    "manage_tasks",
)


def permission(user, name):
    return bool(
        user.is_authenticated
        and user.is_active
        and not is_guest_user(user)
        and has_feature_perm(user, name if "." in name else "compute." + name)
    )


def require_actor(user, project_id, *perms):
    if not user.is_authenticated or not user.is_active:
        raise ComputeError("请先登录；账号可能已停用", 401)
    if not can_access_project(user, project_id):
        raise ComputeError("项目访问权限已撤回", 403)
    for name in perms:
        if not permission(user, name):
            raise ComputeError("没有执行该操作的权限：" + name, 403)


def project_id():
    scope = current_scope.get()
    return scope.selected if scope and scope.selected else 1


def task_access(task, user):
    require_actor(user, task.project_tag_id)
    if task.project_tag_id != project_id():
        raise ComputeError("请切换到任务所属项目", 404)
    if task.owner_id == user.id:
        if not permission(user, "view_own_task") and not permission(
            user, "manage_tasks"
        ):
            raise ComputeError("没有查看计算记录的权限", 403)
    elif not permission(user, "manage_tasks"):
        raise ComputeError("对象不存在或无权访问", 404)
