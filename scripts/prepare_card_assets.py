"""构建前用后端共用编码器准备静态卡片图片，不修改原文件。"""

import hashlib
from pathlib import Path
import sys

CONFIGURATION = "静态卡片图片配置"
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "frontend/src/assets"
OUTPUT = ROOT / "frontend/.cache/card-assets"
PORTRAIT_EDGE = 320
CARD_EDGE = 640
ABOUT_IMAGES = (
    "about/knowledge-populus-forest.png",
    "about/poplar-water-golden.jpeg",
    "about/xjafs-monitoring-tower.png",
)

sys.path.insert(0, str(ROOT / "backend"))
from apps.catalog.thumbnails import encode_thumbnail


def main():
    sources = [ASSETS / name for name in ABOUT_IMAGES]
    sources.extend(
        path
        for path in sorted((ASSETS / "team").glob("*"))
        if path.suffix.lower() in {".png", ".jpeg", ".jpg"} and "logo" not in path.name
    )
    encoder = (ROOT / "backend/apps/catalog/thumbnails.py").read_bytes()
    for source in sources:
        target = OUTPUT / (str(source.relative_to(ASSETS)) + ".webp")
        edge = PORTRAIT_EDGE if source.parent.name == "team" else CARD_EDGE
        digest = hashlib.sha256(
            source.read_bytes() + encoder + str(edge).encode()
        ).hexdigest()
        stamp = target.with_suffix(".stamp")
        if target.is_file() and stamp.is_file() and stamp.read_text() == digest:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode_thumbnail(source, edge=edge))
        stamp.write_text(digest)
    print(f"静态卡片缩略图已准备：{len(sources)} 张，输出 {OUTPUT}")


if __name__ == "__main__":
    main()
