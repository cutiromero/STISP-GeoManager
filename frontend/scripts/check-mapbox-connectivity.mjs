import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const requests = [];
page.on("requestfailed", (request) => {
  const url = new URL(request.url());
  requests.push({
    event: "failed",
    host: url.hostname,
    path: url.pathname,
    reason: request.failure()?.errorText,
  });
});
page.on("response", (response) => {
  const url = new URL(response.url());
  if (url.hostname !== "127.0.0.1")
    requests.push({
      event: "response",
      host: url.hostname,
      path: url.pathname,
      status: response.status(),
    });
});
await page.goto("http://127.0.0.1:5173/map");
await page.waitForTimeout(15000);
await writeFile(
  "../output/20260918-review-fixes/mapbox-connectivity.json",
  JSON.stringify(requests, null, 2),
);
console.log(JSON.stringify(requests.slice(0, 15), null, 2));
await browser.close();
