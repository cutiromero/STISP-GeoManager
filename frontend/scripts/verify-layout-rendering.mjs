import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
const out = path.resolve("../output/upgrade-layout");
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
await page.goto("http://127.0.0.1:5173/map");
const results = await page.evaluate(async () => {
  const transformed = await (
    await fetch("/src/components/MapCanvas.tsx")
  ).text();
  const modulePath = transformed.match(/from "([^"]*\/mapbox-gl\.js[^"]*)"/)[1];
  const mapbox = await import(modulePath);
  const { defaultCompositionLayout } =
    await import("/src/map-composition/layout.ts");
  const { renderCompositionPng, compositionIssues } =
    await import("/src/map-composition/render.ts");
  const container = document.createElement("div");
  container.style.cssText = "width:800px;height:600px";
  document.body.append(container);
  const map = new mapbox.default.Map({
    container,
    style: {
      version: 8,
      sources: {
        areas: {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: {},
                geometry: {
                  type: "Polygon",
                  coordinates: [
                    [
                      [81, 36],
                      [84, 36],
                      [84, 38],
                      [81, 38],
                      [81, 36],
                    ],
                  ],
                },
              },
              {
                type: "Feature",
                properties: {},
                geometry: {
                  type: "Polygon",
                  coordinates: [
                    [
                      [85, 39],
                      [88, 39],
                      [88, 42],
                      [85, 42],
                      [85, 39],
                    ],
                  ],
                },
              },
            ],
          },
        },
      },
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": "#edf4f8" },
        },
        {
          id: "areas",
          type: "fill",
          source: "areas",
          paint: { "fill-color": "#419876", "fill-opacity": 0.8 },
        },
        {
          id: "outline",
          type: "line",
          source: "areas",
          paint: { "line-color": "#23546a", "line-width": 2 },
        },
      ],
    },
    center: [85, 39],
    zoom: 4,
    attributionControl: false,
  });
  await new Promise((resolve) => map.on("load", resolve));
  const output = [];
  for (const variant of ["standard", "dragged", "a3"]) {
    const layout = defaultCompositionLayout(
      "布局验收样图 · 合成测试数据",
      [80, 35, 90, 44],
      "数据来源：本地合成图层，仅用于软件验收",
    );
    layout.overview.bounds = [78, 33, 92, 46];
    layout.page.dpi = variant === "a3" ? 150 : 300;
    layout.legend.enabled = false;
    if (variant === "dragged") {
      layout.northArrow.xMm = 185;
      layout.northArrow.yMm = 35;
      layout.title.xMm = 20;
      layout.title.widthMm = 210;
      layout.extraTexts = [
        {
          ...layout.note,
          id: "text-example",
          text: "独立文字要素",
          xMm: 30,
          yMm: 40,
          widthMm: 50,
          heightMm: 10,
        },
      ];
      layout.editor.order = [
        "mapFrame",
        "overview",
        "title",
        "text-example",
        "scaleBar",
        "northArrow",
      ];
    }
    if (variant === "a3") {
      layout.page = {
        ...layout.page,
        preset: "A3",
        widthMm: 420,
        heightMm: 297,
      };
      layout.mapFrame.widthMm = 285;
      layout.legend.xMm = 310;
      layout.overview.xMm = 310;
      layout.northArrow.xMm = 335;
    }
    const blob = await renderCompositionPng(map, layout, [], undefined);
    const data = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
    output.push({ variant, data, issues: compositionIssues(layout, []) });
  }
  map.remove();
  container.remove();
  return output;
});
for (const item of results) {
  await writeFile(
    path.join(out, item.variant + ".png"),
    Buffer.from(item.data.split(",")[1], "base64"),
  );
  console.log(item.variant, JSON.stringify(item.issues));
}
await browser.close();
