import assert from "node:assert/strict";
import test from "node:test";
import { checkCardSource } from "./check-card-images.mjs";

test("卡片原图引用和原图回退必须报错", () => {
  for (const value of [
    "item.coverUrl",
    'item["coverUrl"]',
    "item.previewUrl",
    "item.thumbnailUrl ?? item.coverUrl",
    "resultThumbnailUrl(item) ?? resultPreviewUrl(item)",
  ]) {
    const errors = checkCardSource(
      "Example.tsx",
      `<CardCover thumbnailUrl={${value}} alt="" />`,
    );
    assert.ok(
      errors.some((error) => error.includes("请改用 CardCover")),
      value,
    );
  }
});

test("原生卡片和自定义卡片不能绕开共用封面", () => {
  for (const text of [
    "<Card cover={<img src={item.coverUrl} />} />",
    '<article className="news-card"><Image src={item.url} /></article>',
  ]) {
    assert.ok(checkCardSource("Example.tsx", text).length);
  }
  assert.ok(checkCardSource("ExampleCard.tsx", "<img src={value} />").length);
});

test("缩略图卡片与原图详情可以共存", () => {
  assert.deepEqual(
    checkCardSource(
      "Example.tsx",
      '<><Card cover={<CardCover thumbnailUrl={item.thumbnailUrl} alt="" />} /><Image src={item.coverUrl} /></>',
    ),
    [],
  );
});

test("卡片背景及原始静态素材不能绕过缩略图", () => {
  assert.ok(
    checkCardSource(
      "Example.tsx",
      "<Card style={{backgroundImage: `url(${item.coverUrl})`}} />",
    ).length,
  );
  assert.ok(
    checkCardSource(
      "Example.tsx",
      'import photo from "../assets/photo.jpg"; const cover = <CardCover thumbnailUrl={photo} alt="" />',
    ).length,
  );
  assert.deepEqual(
    checkCardSource(
      "Example.tsx",
      'import photo from "@card-assets/photo.jpg.webp"; const cover = <CardCover thumbnailUrl={photo} alt="" />',
    ),
    [],
  );
});
