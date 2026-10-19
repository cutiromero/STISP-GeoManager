from __future__ import annotations

PLATFORM_CHINESE_NAME = "时空智能服务平台"
PLATFORM_ENGLISH_NAME = "Spatiotemporal Intelligence Service Platform"
PLATFORM_ABBREVIATION = "STISP"
PLATFORM_EDITION = "STISP Spatiotemporal Services Edition"

LEGACY_PLATFORM_NAMES = frozenset(
    {
        "干旱区胡杨林生态智慧监测平台",
        "全球胡杨林生态系统保护数据共享平台",
        "中亚胡杨林生态系统保护数据共享平台",
        "中亚胡杨林生态保护数据共享平台",
        "中亚胡杨林生态数据共享平台",
        "中亚胡杨生态系统保护数据共享平台",
        "中亚胡杨生态数据门户",
    }
)


def canonicalize_platform_name(value: object) -> str:
    """Upgrade known legacy brand names while preserving custom deployment names."""
    name = str(value or "").strip()
    return PLATFORM_CHINESE_NAME if name in LEGACY_PLATFORM_NAMES else name
