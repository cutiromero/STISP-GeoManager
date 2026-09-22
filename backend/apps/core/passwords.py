from __future__ import annotations

import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*"


def generate_password(length: int = 8) -> str:
    """生成符合平台长度限制的随机密码。"""
    if length < 6:
        length = 6
    if length > 16:
        length = 16
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(length))


def password_validation_errors(password: str, *, user=None) -> list[str]:
    errors: list[str] = []
    if len(password) < 6:
        errors.append("密码长度至少 6 位")
    if len(password) > 16:
        errors.append("密码长度不能超过 16 位")
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        errors.extend(str(message) for message in exc.messages)
    return list(dict.fromkeys(errors))
