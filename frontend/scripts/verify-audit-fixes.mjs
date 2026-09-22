import { chromium } from "playwright";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import assert from "node:assert/strict";

const origin = "http://127.0.0.1:5173";
const out = "../output/20260918-platform-audit";
await mkdir(out, { recursive: true });
const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const browser = await chromium.launch({ headless: true });
const report = { titles: [], errors: [] };
const context = await browser.newContext({
  viewport: { width: 1680, height: 1050 },
});
await context.addCookies([
  { name: "sessionid", value: sessions.admin.cookie, url: origin },
]);
await context.addInitScript(
  ({ id }) => {
    sessionStorage.setItem(`project:${id}`, "2");
  },
  { id: sessions.admin.id },
);
const page = await context.newPage();
page.on("pageerror", (e) => report.errors.push(e.message));
try {
  for (const path of ["/admin/profile", "/resources/data/inventory", "/map"]) {
    await page.goto(origin + path);
    await page
      .getByRole("combobox", { name: "当前项目标签", exact: true })
      .waitFor();
    await page.waitForTimeout(1200);
    const title = await page.title();
    assert.equal(title, "时空智能服务平台");
    report.titles.push({ path, title });
  }
  await page
    .getByRole("button", { name: "打开空间查询工作台", exact: true })
    .click();
  const target = page.getByRole("combobox", { name: "选择已加载的矢量资源" });
  await target.click();
  await page
    .getByText("请先将可查询的矢量数据加载到图层树", { exact: true })
    .waitFor();
  assert.equal(
    await page
      .locator(".ant-select-dropdown:visible .ant-select-item-option")
      .count(),
    0,
  );
  report.emptyLayerList = true;
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "快速加载", exact: true })
    .first()
    .click();
  await page.waitForTimeout(1500);
  await target.click();
  const option = page.locator(
    ".ant-select-dropdown:visible .ant-select-item-option-content",
  );
  await option.first().waitFor();
  assert.equal(await option.count(), 1);
  await option.click();
  report.loadedLayerOptions = 1;
  await page.screenshot({ path: `${out}/spatial-loaded.png` });
  await writeFile(
    `${out}/map-loaded-dom.txt`,
    await page.locator("body").innerText(),
  );
  await page.getByRole("tab", { name: /工程/ }).click();
  await page.getByRole("button", { name: "编辑123", exact: true }).click();
  const modal = page.locator(".workspace-scene-edit-modal");
  await modal.waitFor();
  report.noticeColors = await modal
    .locator(".project-scope-notice")
    .evaluate((el) => ({
      background: getComputedStyle(el).backgroundColor,
      title: getComputedStyle(el.querySelector(".ant-alert-title")).color,
      description: getComputedStyle(el.querySelector(".ant-alert-description"))
        .color,
    }));
  assert.equal(report.noticeColors.description, "rgb(48, 76, 96)");
  report.footerColor = await modal
    .locator(".workspace-scene-fixed-access")
    .evaluate((el) => getComputedStyle(el).color);
  assert.equal(report.footerColor, "rgb(226, 237, 245)");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/edit-project-readable.png` });
  await modal.getByRole("button", { name: /取\s*消/ }).click();
  let resumeResponse;
  const responseGate = new Promise((resolve) => {
    resumeResponse = resolve;
  });
  let observedQuery;
  const queryStarted = new Promise((resolve) => {
    observedQuery = resolve;
  });
  await page.route("**/api/catalog/resources/*/query/", async (route) => {
    const response = await route.fetch();
    observedQuery();
    await responseGate;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "当前视图", exact: true }).click();
  await page.getByRole("button", { name: /执行查询/ }).click();
  await queryStarted;
  await page.getByRole("tab", { name: /图层/ }).click();
  await page
    .getByRole("button", { name: "移除why_test_种质", exact: true })
    .first()
    .click();
  resumeResponse();
  await page.waitForTimeout(600);
  await target.click();
  await page
    .getByText("请先将可查询的矢量数据加载到图层树", { exact: true })
    .waitFor();
  assert.equal(
    await page
      .locator(".ant-select-dropdown:visible .ant-select-item-option")
      .count(),
    0,
  );
  assert.ok(await page.getByRole("button", { name: /执行查询/ }).isDisabled());
  report.removingLastLayerClearsQueryTarget = true;
  report.delayedResultCannotRestoreRemovedTarget = true;
  await page.keyboard.press("Escape");
  await page.screenshot({ path: `${out}/spatial-after-remove.png` });
  console.log(
    "Page titles, loaded-only query options and project notice colors verified.",
  );
} finally {
  await writeFile(`${out}/ui-report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
