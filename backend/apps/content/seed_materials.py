import io
import posixpath
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def compact_image(content, size=1800):
    with Image.open(io.BytesIO(content)) as original:
        im = ImageOps.exif_transpose(original).convert("RGB")
        im.thumbnail((size, size))
        output = io.BytesIO()
        im.save(output, "JPEG", quality=88, optimize=True)
        return output.getvalue()


def slide_illustration(folder, lecture, page):
    files = sorted(Path(folder).glob(f"*第{lecture}讲*.pptx"))
    if len(files) != 1:
        raise ValueError(f"未找到唯一的第 {lecture} 讲素材文件")
    with ZipFile(files[0]) as archive:
        rels = ET.fromstring(archive.read(f"ppt/slides/_rels/slide{page}.xml.rels"))
        pictures = []
        notes = ""
        for rel in rels:
            target = posixpath.normpath(
                posixpath.join("ppt/slides", rel.attrib["Target"])
            ).lstrip("/")
            if rel.attrib.get("TargetMode") == "External":
                continue
            if rel.attrib["Type"].endswith("/image"):
                data = archive.read(target)
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        if im.width >= 250 and im.height >= 150:
                            pictures.append((im.width * im.height, data))
                except OSError:
                    continue
            if rel.attrib["Type"].endswith("/notesSlide"):
                note = ET.fromstring(archive.read(target))
                notes = " ".join(t.text or "" for t in note.findall(".//a:t", NS))
        if not pictures:
            raise ValueError(f"{files[0].name} P{page} 没有可提取的插图")
        source = f"沈占锋《{files[0].stem}》P{page}。配图摘取自用户提供的课件，正文按知识主题重新整理。"
        if "来源" in notes:
            source += (
                " 原页备注："
                + notes[notes.index("来源") :]
                .split("讲授提示")[0]
                .split("建议用时")[0]
                .strip()[:1800]
            )
        return compact_image(max(pictures, key=lambda item: item[0])[1]), source
