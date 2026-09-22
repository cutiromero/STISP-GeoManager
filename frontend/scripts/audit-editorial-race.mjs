import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";
import assert from "node:assert/strict";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
let releaseOld;
const oldGate = new Promise((resolve) => {
  releaseOld = resolve;
});
let observedOld;
const oldStarted = new Promise((resolve) => {
  observedOld = resolve;
});
try {
  await page.route("**/api/content/articles/?*", async (route) => {
    const category = new URL(route.request().url()).searchParams.get(
      "category",
    );
    if (!category) return route.continue();
    if (category === "遥感基础") {
      observedOld();
      await oldGate;
    }
    await route.fulfill({
      json: {
        items: [
          {
            id: 990001,
            projectTagId: 1,
            kind: "knowledge",
            title: `${category}测试文章`,
            summary: "仅浏览器内模拟响应",
            category,
            body: "",
            status: "published",
            source: "",
            links: [],
            eventDate: "",
            publishedAt: "",
            coverUrl: "",
            assets: [],
            pinned: false,
            revision: 1,
          },
        ],
        total: 1,
        canEdit: false,
      },
    });
  });
  await page.goto("http://127.0.0.1:5173/knowledge");
  await page.getByRole("heading", { name: "理解时空，探索智能" }).waitFor();
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: "遥感基础", exact: true }).click();
  await oldStarted;
  await page
    .getByRole("button", { name: "GIS 与地图制图", exact: true })
    .click();
  await page.getByText("GIS 与地图制图测试文章", { exact: true }).waitFor();
  releaseOld();
  await page.getByText("遥感基础测试文章", { exact: true }).waitFor();
  assert.ok(
    (
      await page
        .getByRole("button", { name: "GIS 与地图制图", exact: true })
        .getAttribute("class")
    ).includes("ant-btn-primary"),
  );
  await writeFile(
    "../output/20260918-platform-audit/editorial-race-probe.json",
    JSON.stringify(
      {
        reproduced: true,
        selectedCategory: "GIS 与地图制图",
        displayedArticleCategory: "遥感基础",
        method:
          "delayed synthetic GET responses in isolated anonymous browser; no server data changes",
      },
      null,
      2,
    ),
  );
  console.log(
    "Reproduced: stale category response overwrites newer selection.",
  );
} finally {
  releaseOld();
  await browser.close();
}
