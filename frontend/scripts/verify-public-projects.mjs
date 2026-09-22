import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";

const origin = "http://127.0.0.1:5173";
const out = "../output/20260918-public-project";
const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const browser = await chromium.launch({ headless: true });
const report = { users: [], errors: [] };
let page;
async function dropdownOptions(field) {
  await field.click();
  const options = page.locator(
    ".ant-select-dropdown:visible .ant-select-item-option-content",
  );
  await options.first().waitFor();
  await page.waitForTimeout(200);
  if (!(await options.count())) {
    await field.press("ArrowDown");
    await options.first().waitFor();
  }
  return options;
}
try {
  for (const key of ["admin", "researcher", "anonymous"]) {
    const context = await browser.newContext({
      viewport: { width: 1680, height: 1050 },
    });
    if (key !== "anonymous") {
      await context.addCookies([
        { name: "sessionid", value: sessions[key].cookie, url: origin },
      ]);
      await context.addInitScript(
        ({ id }) => {
          if (!sessionStorage.getItem("public-project-check")) {
            sessionStorage.setItem(`project:${id}`, "all");
            sessionStorage.setItem("public-project-check", "1");
          }
        },
        { id: sessions[key].id },
      );
    }
    page = await context.newPage();
    page.on("pageerror", (error) => report.errors.push(error.message));
    await page.goto(`${origin}/news`);
    await page
      .getByRole("heading", { name: "团队新闻动态", exact: true })
      .waitFor();
    const projects = await (
      await context.request.get(`${origin}/api/projects/`)
    ).json();
    assert.equal(projects.items[0].name, "公开");
    const publicNews = await (
      await context.request.get(`${origin}/api/content/articles/?kind=news`)
    ).json();
    assert.ok(publicNews.items.length > 0);
    const news = publicNews.items[0];
    await page.getByText(news.title, { exact: true }).first().waitFor();
    const selector = page.getByRole("combobox", {
      name: "当前项目标签",
      exact: true,
    });
    await selector.waitFor();
    await page.waitForTimeout(700);
    const options = await dropdownOptions(selector);
    const labels = await options.allTextContents();
    assert.deepEqual(
      labels,
      projects.items.map((p) => p.name + (p.isActive ? "" : "（停用）")),
    );
    assert.ok(!labels.includes("全部可访问"));
    await page.keyboard.press("Escape");
    if (key !== "anonymous") {
      assert.equal(
        await page.evaluate(
          (id) => sessionStorage.getItem(`project:${id}`),
          sessions[key].id,
        ),
        "1",
      );
    }
    const privateProject = projects.items.find((p) => p.id !== 1 && p.isActive);
    if (privateProject) {
      const options = await dropdownOptions(selector);
      await options.filter({ hasText: privateProject.name }).click();
      await page.getByRole("button", { name: "切换项目", exact: true }).click();
      await page.waitForFunction(
        ({ id, project }) =>
          sessionStorage.getItem(`project:${id}`) === String(project),
        { id: sessions[key].id, project: privateProject.id },
      );
      await page.getByText(news.title, { exact: true }).first().waitFor();
    }
    await page.goto(`${origin}/news/${news.id}`);
    await page
      .getByRole("heading", { name: news.title, exact: true })
      .waitFor();
    const images = page.locator('img[src*="/api/content/assets/"]');
    assert.ok(await images.count());
    await images.first().waitFor();
    await page.waitForFunction(() =>
      [...document.querySelectorAll('img[src*="/api/content/assets/"]')].every(
        (img) => img.complete && img.naturalWidth > 0,
      ),
    );
    for (const tag of ["1", "2", "3", "99999", "all"]) {
      const response = await context.request.get(
        `${origin}/api/content/articles/?kind=news`,
        { headers: { "X-Project-Id": tag } },
      );
      assert.equal(response.status(), 200);
      assert.deepEqual(
        (await response.json()).items.map((a) => a.id),
        publicNews.items.map((a) => a.id),
      );
    }
    const aggregate = await context.request.get(
      `${origin}/api/catalog/resources/`,
      { headers: { "X-Project-Id": "all" } },
    );
    assert.equal(aggregate.status(), 400);
    await page.screenshot({ path: `${out}/${key}-news.png`, fullPage: true });
    if (key === "admin") {
      await page.goto(`${origin}/projects/manage`);
      await page.waitForURL("**/admin/projects");
      await page
        .getByRole("heading", { name: "项目标签管理", exact: true })
        .waitFor();
      await page.getByRole("link", { name: /项目管理/ }).waitFor();
      assert.equal(
        await page
          .locator("header")
          .getByRole("button", { name: /项目管理/ })
          .count(),
        0,
      );
      await page.getByRole("button", { name: "后台管理", exact: true }).hover();
      await page
        .getByRole("menuitem", { name: "项目管理", exact: true })
        .waitFor();
      await page
        .getByRole("menuitem", { name: "项目管理", exact: true })
        .click();
      await page.getByText("分配用户标签", { exact: true }).waitFor();
      await page.screenshot({
        path: `${out}/admin-project-management.png`,
        fullPage: true,
      });
    } else if (key === "researcher") {
      await page.goto(`${origin}/admin/projects`);
      await page.waitForURL("**/admin/profile");
      assert.equal(
        await page.getByRole("link", { name: /项目管理/ }).count(),
        0,
      );
    }
    if (key !== "anonymous") {
      await page.goto(`${origin}/resources/data/inventory`);
      const inventory = page.getByRole("combobox", {
        name: "存量数据所属项目",
        exact: true,
      });
      await inventory.waitFor();
      await page.waitForTimeout(700);
      const options = await dropdownOptions(inventory);
      assert.deepEqual(await options.allTextContents(), labels);
      await page.keyboard.press("Escape");
      await page.screenshot({
        path: `${out}/${key}-inventory.png`,
        fullPage: true,
      });
    }
    report.users.push({
      user: key,
      selectableProjects: labels,
      legacyAllRestored: key !== "anonymous",
      newsId: news.id,
      newsImagesLoaded: true,
      aggregateStatus: aggregate.status(),
    });
    await context.close();
  }
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = String(error);
  if (page && !page.isClosed())
    await page.screenshot({ path: `${out}/live-failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(
    `${out}/live-browser-report.json`,
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
