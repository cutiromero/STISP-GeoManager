from xml.sax.saxutils import escape
from zipfile import ZipFile

from apps.content.science_document import load_science_manifest, read_science_document


def test_frozen_document_contains_eight_articles_and_actual_links():
    manifest = load_science_manifest()
    assert len(manifest["articles"]) == 8
    assert sum(len(item["images"]) for item in manifest["articles"]) == 8
    assert sum(len(item["links"]) for item in manifest["articles"]) == 7
    assert manifest["articles"][7]["links"] == []
    assert (
        manifest["articles"][6]["links"][0]["url"]
        == "https://global-surface-water.appspot.com/"
    )


def test_extracts_fields_images_and_captions_in_document_order(tmp_path):
    doc = tmp_path / "science.docx"
    paragraphs = ["<w:p><w:r><w:t>栏目介绍</w:t></w:r></w:p>"]
    relationships = []
    for number in range(1, 9):
        for text in (f"{number:02d} / 分类{number}", f"标题{number}", "摘要", "正文"):
            paragraphs.append(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
        paragraphs.extend(
            [
                f'<w:p><w:r><a:blip r:embed="image{number}" /></w:r></w:p>',
                f"<w:p><w:r><w:t>图 {number}｜原图注</w:t></w:r></w:p>",
                f'<w:p><w:r><w:instrText> HYPERLINK "https://example.org/{number}" \\h </w:instrText></w:r><w:r><w:t>延伸阅读：资料{number}</w:t></w:r></w:p>',
            ]
        )
        relationships.append(
            f'<Relationship Id="image{number}" Target="media/image{number}.png" />'
        )
    with ZipFile(doc, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'
            + "".join(paragraphs)
            + "</w:body></w:document>",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            "<Relationships>" + "".join(reversed(relationships)) + "</Relationships>",
        )
        for number in range(1, 9):
            archive.writestr(
                f"word/media/image{number}.png", f"image-{number}".encode()
            )
    manifest, assets = read_science_document(doc)
    assert manifest["introduction"] == ["栏目介绍"]
    for number, article in enumerate(manifest["articles"], 1):
        assert article["title"] == f"标题{number}"
        assert article["paragraphs"] == ["正文"]
        assert article["links"] == [
            {"title": f"资料{number}", "url": f"https://example.org/{number}"}
        ]
        assert article["images"][0]["caption"] == f"图 {number}｜原图注"
        assert assets[f"science-{number:02d}.png"] == f"image-{number}".encode()
