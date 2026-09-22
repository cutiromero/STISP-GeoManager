import { chromium } from "playwright";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const out = "../output/20260918-review-fixes";
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const errors = [];
const report = [];
try {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
  });
  await context.addCookies([
    {
      name: "sessionid",
      value: sessions.admin.cookie,
      url: "http://127.0.0.1:5173",
    },
  ]);
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:5173/knowledge");
  await page.getByRole("button", { name: "阅读全文 →" }).first().waitFor();
  const initial = await page
    .getByRole("button", { name: "阅读全文 →" })
    .count();
  for (const project of ["2", "3", "all"]) {
    await page.evaluate(
      ({ id, project }) => sessionStorage.setItem(`project:${id}`, project),
      { id: sessions.admin.id, project },
    );
    await page.reload();
    await page.getByRole("button", { name: "阅读全文 →" }).first().waitFor();
    assert.equal(
      await page.getByRole("button", { name: "阅读全文 →" }).count(),
      initial,
    );
    await page.getByRole("button", { name: "阅读全文 →" }).first().click();
    await page.getByRole("button", { name: "编辑内容" }).waitFor();
    await page.screenshot({
      path: `${out}/knowledge-project-${project}.png`,
      fullPage: true,
    });
    report.push({
      check: "knowledge",
      selectedProject: project,
      count: initial,
      detail: true,
    });
    await page.goto("http://127.0.0.1:5173/knowledge");
  }
  await page.evaluate(
    (id) => sessionStorage.setItem(`project:${id}`, "1"),
    sessions.admin.id,
  );
  await page.goto("http://127.0.0.1:5173/resources/catalog");
  await page.getByText("why_test_种质", { exact: true }).waitFor();
  assert.ok((await page.locator("body").innerText()).includes("地理数据"));
  assert.ok((await page.locator("body").innerText()).includes("非地理数据"));
  await page.screenshot({ path: `${out}/data-catalog.png`, fullPage: true });
  report.push({
    check: "catalog",
    classification: "spatial/non_spatial",
    existingData: true,
  });
  await context.close();

  const research = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
  });
  await research.addCookies([
    {
      name: "sessionid",
      value: sessions.researcher.cookie,
      url: "http://127.0.0.1:5173",
    },
  ]);
  const workbench = await research.newPage();
  workbench.on("pageerror", (error) => errors.push(error.message));
  await workbench.goto("http://127.0.0.1:5173/map");
  await workbench.getByRole("button", { name: "用户信息" }).waitFor();
  const me = await workbench.evaluate(
    async () => (await (await fetch("/api/auth/me/")).json()).user.username,
  );
  assert.equal(me, "刘洋");
  const bootstrapDefault = await workbench.evaluate(
    async () =>
      (await (await fetch("/api/bootstrap/")).json()).map.defaultBasemap,
  );
  assert.equal(bootstrapDefault, "satellite");
  await workbench.screenshot({
    path: `${out}/mapbox-default.png`,
    fullPage: true,
  });
  report.push({ check: "defaultBasemap", value: bootstrapDefault });
  await workbench.getByRole("button", { name: "用户信息" }).click();
  await workbench.getByRole("button", { name: /安全退出/ }).click();
  await workbench.waitForURL("**/login");
  await workbench
    .getByRole("button", { name: /登录/ })
    .first()
    .waitFor();
  assert.equal(
    await workbench.evaluate(async () => (await fetch("/api/auth/me/")).status),
    401,
  );
  await workbench.screenshot({
    path: `${out}/liuyang-logout.png`,
    fullPage: true,
  });
  report.push({
    check: "logout",
    user: "刘洋",
    path: "/login",
    serverSession: "unauthenticated",
  });
  await research.close();
  assert.deepEqual(errors, []);
} finally {
  await writeFile(
    `${out}/live-browser-report.json`,
    JSON.stringify({ report, errors }, null, 2),
  );
  await browser.close();
}
console.log(JSON.stringify({ report, errors }, null, 2));
