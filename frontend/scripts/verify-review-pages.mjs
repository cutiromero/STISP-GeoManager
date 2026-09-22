import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
});
await context.addCookies([
  {
    name: "sessionid",
    value: sessions.admin.cookie,
    url: "http://127.0.0.1:5173",
  },
]);
const page = await context.newPage();
const report = { mapboxResponses: {}, errors: [], pages: [] };
page.on("response", (response) => {
  if (new URL(response.url()).hostname === "api.mapbox.com")
    report.mapboxResponses[response.status()] =
      (report.mapboxResponses[response.status()] ?? 0) + 1;
});
page.on("pageerror", (e) => report.errors.push(e.message));
try {
  for (const [route, name] of [
    ["/resources/data/inventory", "inventory"],
    ["/projects/manage", "project-management"],
    ["/map", "mapbox-loaded"],
  ]) {
    await page.goto(`http://127.0.0.1:5173${route}`);
    await page.getByRole("button", { name: "用户信息" }).waitFor();
    await page.waitForTimeout(name === "mapbox-loaded" ? 10000 : 1200);
    await page.screenshot({
      path: `../output/20260918-review-fixes/${name}.png`,
      fullPage: true,
    });
    report.pages.push({
      route,
      text: (await page.locator("body").innerText()).slice(0, 450),
    });
  }
} finally {
  await browser.close();
  await writeFile(
    "../output/20260918-review-fixes/live-pages-report.json",
    JSON.stringify(report, null, 2),
  );
}
console.log(JSON.stringify(report, null, 2));
