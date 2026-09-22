from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


class AccountEmailError(ValueError):
    pass


def normalize_account_email(value: object) -> str:
    return str(value or "").strip().casefold()


def validate_account_email(value: object, *, exclude_user_id: int | None = None) -> str:
    email = normalize_account_email(value)
    if not email:
        raise AccountEmailError("请输入邮箱")
    try:
        validate_email(email)
    except ValidationError as exc:
        raise AccountEmailError("请输入有效邮箱") from exc

    User = get_user_model()
    existing = User.objects.filter(email__iexact=email)
    if exclude_user_id is not None:
        existing = existing.exclude(pk=exclude_user_id)
    if existing.exists():
        raise AccountEmailError("邮箱已被使用")
    return email
