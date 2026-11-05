"""Persist only bounded, credential-redacted model output, never prompts."""

import re

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def response_artifact(text):
    text = re.sub(
        r"""(?i)((?:api[_-]?key|access[_-]?token|password|secret|密码|密钥)["\s]*[:=：]\s*)(["'])(.*?)(\2)""",
        r"\1\2[已脱敏]\4",
        text,
        flags=re.S,
    )
    text = re.sub(
        r'(?i)((?:api[_-]?key|access[_-]?token|password|secret|密码|密钥)["\s]*[:=：]\s*["\']?)([^\s"\',;}]+)',
        r"\1[已脱敏]",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',;}]+", "Bearer [已脱敏]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[已脱敏]", text)
    encoded = text.encode("utf-8")
    truncated = len(encoded) > MAX_RESPONSE_BYTES
    if truncated:
        marker = "\n（响应超过审计体积上限，已截断）"
        text = (
            encoded[: MAX_RESPONSE_BYTES - len(marker.encode("utf-8"))].decode(
                "utf-8", errors="ignore"
            )
            + marker
        )
    return {"content": text, "truncated": truncated, "sizeBytes": len(encoded)}
