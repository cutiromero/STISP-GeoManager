from __future__ import annotations

import ipaddress
from typing import Any

CLIENT_IP_HEADERS = (
    "HTTP_CF_CONNECTING_IP",
    "HTTP_TRUE_CLIENT_IP",
    "HTTP_X_REAL_IP",
)


def log_operation(
    user: Any,
    module: str,
    action: str,
    status: str,
    message: str = "",
    request: Any = None,
    *,
    event_code: str = "",
    target_type: str = "",
    target_id: int | None = None,
    target_code: str = "",
    target_name: str = "",
) -> None:
    from apps.audit.models import OperationLog

    OperationLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        module=module,
        action=action,
        event_code=event_code,
        status=status,
        target_type=target_type,
        target_id=target_id,
        target_code=target_code,
        target_name=target_name,
        message=message,
        ip_address=_client_ip(request),
    )


def _client_ip(request: Any) -> str | None:
    if request is None:
        return None

    candidates: list[str] = []
    for header in CLIENT_IP_HEADERS:
        candidates.extend(_ip_header_values(request.META.get(header)))
    candidates.extend(_ip_header_values(request.META.get("HTTP_X_FORWARDED_FOR")))
    candidates.extend(_forwarded_header_values(request.META.get("HTTP_FORWARDED")))
    candidates.extend(_ip_header_values(request.META.get("REMOTE_ADDR")))

    public_ip = _first_public_ip(candidates)
    if public_ip is not None:
        return public_ip
    return candidates[0] if candidates else None


def _ip_header_values(value: str | None) -> list[str]:
    if not value:
        return []
    addresses: list[str] = []
    for raw_item in value.split(","):
        address = _normalize_ip(raw_item)
        if address is not None:
            addresses.append(address)
    return addresses


def _forwarded_header_values(value: str | None) -> list[str]:
    if not value:
        return []
    addresses: list[str] = []
    for forwarded_item in value.split(","):
        for part in forwarded_item.split(";"):
            key, separator, raw_value = part.partition("=")
            if separator and key.strip().lower() == "for":
                address = _normalize_ip(raw_value)
                if address is not None:
                    addresses.append(address)
                break
    return addresses


def _normalize_ip(value: str) -> str | None:
    text = value.strip().strip('"').strip("'")
    if not text or text.lower() == "unknown":
        return None
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    elif text.count(":") == 1 and "." in text:
        text = text.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _first_public_ip(addresses: list[str]) -> str | None:
    for address in addresses:
        if ipaddress.ip_address(address).is_global:
            return address
    return None
