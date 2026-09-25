"""Self-service capability disclosure and research-role applications."""

import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.audit.service import log_operation
from apps.core.api import api_login_required
from apps.core.initialization import (
    DEFAULT_USER_GROUP_NAME,
    GUEST_GROUP_NAME,
    RESEARCH_USER_GROUP_NAME,
    ensure_research_user_group,
    is_guest_user,
    is_superadmin_user,
)
from apps.core.localization import localized
from apps.core.models import RoleApplication, UserProfile
from apps.core.permissions import (
    FEATURE_PERMISSIONS,
    effective_feature_permissions,
    disabled_feature_permissions,
)
from apps.core.role_applications import serialize_role_application


def permission_items(names):
    return [
        dict(id=p.perm_name, label=p.localized_name, group=p.localized_group)
        for p in FEATURE_PERMISSIONS
        if p.perm_name in names
    ]


def research_eligible(user):
    groups = set(user.groups.values_list("name", flat=True))
    return bool(
        user.is_active
        and not user.is_superuser
        and not is_superadmin_user(user)
        and not is_guest_user(user)
        and GUEST_GROUP_NAME not in groups
        and DEFAULT_USER_GROUP_NAME in groups
        and RESEARCH_USER_GROUP_NAME not in groups
    )


def account_access(user):
    from apps.agent.policy import allowed, policy

    effective = effective_feature_permissions(user)
    p = policy()
    chat, agent = allowed(user, "chat", p), allowed(user, "agent", p)
    visible = set(effective)
    if not chat:
        visible.discard("core.use_local_model")
    if not agent:
        visible.discard("core.use_data_agent")
    eligible = research_eligible(user)
    extra = set()
    if eligible:
        research = ensure_research_user_group()
        extra = {
            f"{x.content_type.app_label}.{x.codename}"
            for x in research.permissions.select_related("content_type")
        }
        extra -= effective | disabled_feature_permissions(user)
    application = RoleApplication.objects.filter(user=user).first()
    actions = []
    if chat or agent:
        if p.get("allowAttachments"):
            actions.append(localized("上传对话附件", "Upload conversation attachments"))
        if p.get("internetEnabled"):
            actions.append(localized("联网检索", "Search the web"))
    if agent:
        actions += [
            localized("读取有权访问的数据", "Read authorized data"),
            localized("分析数据并生成报告", "Analyze data and produce reports"),
        ]
        if p.get("operatorEnabled"):
            actions.append(
                localized(
                    "经确认执行已开放的数据操作",
                    "Run enabled data operations after confirmation",
                )
            )
    items = permission_items(visible)
    if is_superadmin_user(user) or user.is_superuser:
        items += [
            dict(
                id=key,
                label=localized(zh, en),
                group=localized("平台管理", "Platform administration"),
            )
            for key, zh, en in [
                ("projects.manage", "管理项目及成员", "Manage projects and members"),
                (
                    "agent.manage",
                    "配置智能体模型、权限和额度",
                    "Configure agent models, access and budgets",
                ),
                (
                    "research.review",
                    "审核科研用户申请",
                    "Review research-user applications",
                ),
            ]
        ]
    if "core.manage_auth" in visible:
        items.append(
            dict(
                id="content.manage",
                label=localized(
                    "编辑和发布科普、团队动态",
                    "Edit and publish knowledge and team news",
                ),
                group=localized("内容管理", "Content management"),
            )
        )
    return dict(
        permissions=items,
        agentActions=actions,
        researchEligible=eligible,
        researchAdditionalPermissions=permission_items(extra),
        application=serialize_role_application(application, include_user=False)
        if application
        else None,
    )


@require_GET
@api_login_required
def access_view(request):
    return JsonResponse(account_access(request.user))


@require_POST
@api_login_required
def apply_research(request):
    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeError):
        body = None
    limits = {"displayName": 150, "department": 200, "reason": 2000}
    if not isinstance(body, dict) or any(
        not isinstance(body.get(k), str) or not body[k].strip() or len(body[k]) > n
        for k, n in limits.items()
    ):
        return JsonResponse(
            {
                "detail": localized(
                    "请填写姓名、单位和申请说明，并检查文本长度",
                    "Enter your name, affiliation and reason within the length limits",
                )
            },
            status=400,
        )
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if not research_eligible(user):
            return JsonResponse(
                {
                    "detail": localized(
                        "当前账号不符合申请条件",
                        "This account is not eligible to apply",
                    )
                },
                status=403,
            )
        application = RoleApplication.objects.filter(user=user).first()
        if application and application.status == RoleApplication.Status.PENDING:
            return JsonResponse(
                {
                    "detail": localized(
                        "已申请，请等待超级管理员审核",
                        "Application already submitted; awaiting super administrator review",
                    )
                },
                status=409,
            )
        user.first_name = body["displayName"].strip()
        user.save(update_fields=["first_name"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.department = body["department"].strip()
        profile.save(update_fields=["department", "updated_at"])
        RoleApplication.objects.update_or_create(
            user=user,
            defaults=dict(
                reason=body["reason"].strip(),
                status=RoleApplication.Status.PENDING,
                reviewer=None,
                review_note="",
                reviewed_at=None,
                created_at=timezone.now(),
            ),
        )
        log_operation(
            user, "认证授权", "申请科研用户", "success", "科研用户申请已提交", request
        )
    return JsonResponse(account_access(user))
