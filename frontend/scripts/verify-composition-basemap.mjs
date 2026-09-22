import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";

const origin = "http://127.0.0.1:5173";
const out = "../output/20260918-composition-basemap";
const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1800, height: 1100 },
  deviceScaleFactor: 1,
});
await context.addCookies([
  { name: "sessionid", value: sessions.admin.cookie, url: origin },
]);
await context.addInitScript(
  (id) => sessionStorage.setItem(`project:${id}`, "2"),
  sessions.admin.id,
);
const page = await context.newPage();
const report = { tiles: [], errors: [] };
let phase = "preview";
page.on("response", (response) => {
  const url = new URL(response.url());
  if (url.pathname.includes("/map/thumbnail-tiles/"))
    report.tiles.push({
      phase,
      path: url.pathname,
      purpose: url.searchParams.get("purpose"),
      status: response.status(),
      cache: response.headers()["cache-control"],
    });
});
page.on("pageerror", (error) =>
  report.errors.push(
    error.message.replace(/access_token=[^\s&]+/g, "access_token=[redacted]"),
  ),
);
try {
  await page.goto(`${origin}/news`);
  await page.getByRole("heading", { name: "团队新闻动态" }).waitFor();
  const original = await (
    await context.request.get(`${origin}/api/catalog/map-compositions/2/`, {
      headers: { "X-Project-Id": "2" },
    })
  ).json();
  assert.ok(original.layout);
  report.composition = {
    id: original.id,
    title: original.name,
    bounds: original.layout.mapFrame?.bounds,
  };
  await page.evaluate(async () => {
    const transformed = await (
      await fetch("/src/components/MapCanvas.tsx")
    ).text();
    const modulePath = transformed.match(
      /from "([^"]*\/mapbox-gl\.js[^"]*)"/,
    )[1];
    const { default: mapbox } = await import(modulePath);
    const MapClass = mapbox.Map;
    mapbox.Map = class extends MapClass {
      constructor(options) {
        super(options);
        if (options.interactive !== false)
          window.__verifyCompositionSourceMap = this;
      }
    };
    history.pushState({}, "", "/map?compositionId=2");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  const preview = page.getByAltText("专题图预览", { exact: true });
  await preview.waitFor({ timeout: 60000 });
  await page.waitForFunction(
    () => {
      const image = document.querySelector(".composition-editable-paper > img");
      return image?.complete && image.naturalWidth > 0;
    },
    undefined,
    { timeout: 60000 },
  );
  const previewData = await preview.evaluate((image) => {
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas.toDataURL("image/png");
  });
  await writeFile(
    `${out}/preview.png`,
    Buffer.from(previewData.split(",")[1], "base64"),
  );
  await page.screenshot({ path: `${out}/editor-preview.png`, fullPage: true });
  phase = "export";
  const exported = await page.evaluate(async (original) => {
    const map = window.__verifyCompositionSourceMap;
    const { normalizeCompositionLayout } =
      await import("/src/map-composition/layout.ts");
    const { renderCompositionPng } =
      await import("/src/map-composition/render.ts");
    const config = await (await fetch("/api/bootstrap/")).json();
    const layout = normalizeCompositionLayout(
      original.layout,
      original.name,
      [40, 20, 100, 60],
      "用户导入",
    );
    layout.page.dpi = 300;
    window.__verifyCompositionLayout = layout;
    const blob = await renderCompositionPng(
      map,
      layout,
      [],
      config.map.mapboxAccessToken,
    );
    const bitmap = await createImageBitmap(blob);
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    const reader = new FileReader();
    const data = await new Promise((resolve) => {
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
    return { ...size, data };
  }, original);
  assert.equal(exported.width, 3508);
  assert.equal(exported.height, 2480);
  await writeFile(
    `${out}/export-300dpi.png`,
    Buffer.from(exported.data.split(",")[1], "base64"),
  );
  report.output = { width: exported.width, height: exported.height, dpi: 300 };
  const actualTiles = report.tiles.filter((tile) => tile.purpose === "export");
  assert.ok(actualTiles.length > 0);
  assert.ok(actualTiles.every((tile) => tile.status === 200));
  assert.ok(actualTiles.every((tile) => !tile.cache?.includes("max-age=60")));
  phase = "fault-injection";
  await page.route("**/api/map/thumbnail-tiles/**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify({ detail: "模拟上游不可用，仅用于验证" }),
    }),
  );
  const failed = await page.evaluate(async () => {
    const { renderBoundsImage } =
      await import("/src/map-composition/mapImage.ts");
    const config = await (await fetch("/api/bootstrap/")).json();
    try {
      const result = await renderBoundsImage(
        window.__verifyCompositionSourceMap,
        [40, 20, 100, 60],
        1000,
        700,
        config.map.mapboxAccessToken,
      );
      result.close();
      return "unexpected success";
    } catch (error) {
      return error.message;
    }
  });
  assert.match(failed, /出图底图加载失败/);
  assert.ok(
    report.tiles.some(
      (tile) => tile.phase === "fault-injection" && tile.status === 503,
    ),
  );
  report.faultInjection = { rejected: true, error: failed };
  const after = await (
    await context.request.get(`${origin}/api/catalog/map-compositions/2/`, {
      headers: { "X-Project-Id": "2" },
    })
  ).json();
  assert.equal(after.updatedAt, original.updatedAt);
  assert.deepEqual(after.layout, original.layout);
  report.existingDraftUnchanged = true;
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = String(error).replace(
    /access_token=[^\s&]+/g,
    "access_token=[redacted]",
  );
  await page.screenshot({ path: `${out}/failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(
    `${out}/live-render-report.json`,
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
console.log(
  JSON.stringify(
    {
      ...report,
      tiles: {
        count: report.tiles.length,
        statuses: [...new Set(report.tiles.map((t) => t.status))],
      },
    },
    null,
    2,
  ),
);
