import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const out = path.resolve("../output/upgrade-browser");
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const results = [];
for (const route of ["/", "/resources/catalog", "/knowledge", "/news"]) {
  await page.goto(`http://127.0.0.1:5173${route}`);
  await page.waitForTimeout(1800);
  await page.screenshot({
    path: path.join(out, (route.replaceAll("/", "_") || "root") + ".png"),
    fullPage: true,
  });
  results.push({
    route,
    url: page.url(),
    text: (await page.locator("body").innerText()).slice(0, 1800),
  });
}
await page.getByRole("button", { name: "阅读全文 →" }).first().click();
await page.waitForTimeout(500);
await page.screenshot({
  path: path.join(out, "news-detail.png"),
  fullPage: true,
});
const report = {
  results,
  errors,
  brokenImages: await page
    .locator("img")
    .evaluateAll((images) =>
      images
        .filter((im) => !im.complete || !im.naturalWidth)
        .map((im) => im.src),
    ),
};
await writeFile(path.join(out, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
await browser.close();
if (errors.length || report.brokenImages.length) process.exitCode = 1;
