"""Plain public labels; retain source identities in the internal provenance."""

import re


def display_text(value: str) -> str:
    replacements = {
        "人工精修 · 师弟手动修改的岩性图": "精修岩性图",
        "师弟手动修改的岩性图": "精修岩性图",
        "师弟人工精修": "人工编辑",
        "师弟解译成果": "地质解译成果",
        "师弟基于预测结果": "基于预测结果",
        "师弟提供的": "",
        "师弟原面积CSV": "原面积CSV",
        "师弟原图": "原图",
        "师弟": "资料提供者",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"[ \t]*[·•][ \t]*", " ", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()
