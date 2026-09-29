"""Read the supplied science column in OOXML order, including field hyperlinks."""

import hashlib
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
MANIFEST_PATH = Path(__file__).with_name("science_column_20260929.json")


def _text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", NS)).strip()


def _links(paragraph: ET.Element, relationships: dict) -> list[dict[str, str]]:
    links = []
    for link in paragraph.findall(".//w:hyperlink", NS):
        relation = relationships.get(link.get(f"{{{NS['r']}}}id"), {})
        if relation.get("TargetMode") == "External":
            links.append({"title": _text(link), "url": relation["Target"]})
    instruction = "".join(
        node.text or "" for node in paragraph.findall(".//w:instrText", NS)
    )
    instruction += " ".join(
        node.get(f"{{{NS['w']}}}instr", "")
        for node in paragraph.findall(".//w:fldSimple", NS)
    )
    for target in re.findall(r'\bHYPERLINK\s+"([^"]+)"', instruction):
        links.append({"title": _text(paragraph), "url": target})
    for link in links:
        parsed = urlparse(link["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("延伸阅读必须为 HTTP(S) 链接")
        link["title"] = link["title"].removeprefix("延伸阅读：")
    return links


def read_science_document(source: Path) -> tuple[dict, dict[str, bytes]]:
    """Extract eight articles and their exact embedded images; no database access."""
    articles: list[dict] = []
    introduction = []
    assets = {}
    current = None
    with ZipFile(source) as archive:
        relationships = {
            item.attrib["Id"]: item.attrib
            for item in ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        }
        body = ET.fromstring(archive.read("word/document.xml"))
        for paragraph in body.findall(".//w:body/w:p", NS):
            text = _text(paragraph)
            heading = re.fullmatch(r"(\d{2})\s*/\s*(.+)", text)
            if heading:
                number = int(heading[1])
                current = {
                    "seedKey": f"science-20260929-{number:02d}",
                    "number": number,
                    "category": heading[2],
                    "title": "",
                    "summary": "",
                    "paragraphs": [],
                    "links": [],
                    "images": [],
                }
                articles.append(current)
                continue
            if current is None:
                if text:
                    introduction.append(text)
                continue
            for image in paragraph.findall(".//a:blip", NS):
                relation = relationships[image.attrib[f"{{{NS['r']}}}embed"]]
                target = posixpath.normpath(posixpath.join("word", relation["Target"]))
                if not target.startswith("word/media/"):
                    raise ValueError("科普插图必须是文档内嵌媒体")
                content = archive.read(target)
                name = f"science-{current['number']:02d}{Path(target).suffix}"
                assets[name] = content
                current["images"].append(
                    {
                        "name": name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "caption": "",
                    }
                )
            links = _links(paragraph, relationships)
            if links:
                current["links"].extend(links)
            elif re.match(r"^图\s*\d+[｜|]", text):
                if not current["images"]:
                    raise ValueError("图注之前没有插图")
                current["images"][-1]["caption"] = text
            elif text and not current["title"]:
                current["title"] = text
            elif text and not current["summary"]:
                current["summary"] = text
            elif text:
                current["paragraphs"].append(text)
    if [article["number"] for article in articles] != list(range(1, 9)):
        raise ValueError("文档必须按顺序包含 01–08 八篇科普")
    for article in articles:
        if len(article["images"]) != 1 or not article["images"][0]["caption"]:
            raise ValueError("每篇科普须包含一幅插图和图注")
        if not article["title"] or not article["summary"] or not article["paragraphs"]:
            raise ValueError("科普标题、摘要或正文缺失")
    return {
        "sourceName": source.name,
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "introduction": introduction,
        "articles": articles,
    }, assets


def load_science_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def extract_science_document(source: Path, destination: Path) -> dict:
    """Write release-only media plus its manifest to an explicit directory."""
    manifest, assets = read_science_document(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in assets.items():
        target = destination / name
        if target.exists() and target.read_bytes() != content:
            raise ValueError(f"目标插图已存在且内容不同：{name}")
        target.write_bytes(content)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
