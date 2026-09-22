import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";

const sessions = JSON.parse(
  await readFile("../.runtime/review-browser-sessions.json", "utf8"),
);
const out = "../output/20260918-upload-projects";
const browser = await chromium.launch({ headless: true });
const report = {
  users: [],
  requests: [],
  errors: [],
  temporaryResourceRemoved: false,
};
let created;
let adminPage;
let destination;
let currentPage;
try {
  for (const key of ["researcher", "admin"]) {
    const context = await browser.newContext({
      viewport: { width: 1680, height: 1050 },
    });
    await context.addCookies([
      {
        name: "sessionid",
        value: sessions[key].cookie,
        url: "http://127.0.0.1:5173",
      },
    ]);
    const page = await context.newPage();
    currentPage = page;
    page.on("pageerror", (e) => report.errors.push(e.message));
    await page.goto("http://127.0.0.1:5173/resources/data/import");
    const field = page.getByRole("combobox", {
      name: "所属项目标签",
      exact: true,
    });
    await field.waitFor();
    const projects = await page.evaluate(
      async () => (await (await fetch("/api/projects/")).json()).items,
    );
    await page.waitForTimeout(700);
    await field.click();
    const options = page.locator(
      ".ant-select-dropdown:visible .ant-select-item-option-content",
    );
    await options.first().waitFor();
    await page.waitForTimeout(200);
    if ((await options.count()) === 0) {
      await field.press("ArrowDown");
      await options.first().waitFor();
    }
    const labels = await options.allTextContents();
    assert.deepEqual(
      labels,
      projects.map((p) => p.name + (p.isActive ? "" : "（停用）")),
    );
    report.users.push({ user: key, selectableProjectTags: labels });
    await page.screenshot({
      path: `${out}/${key}-upload-options.png`,
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    if (key !== "admin") {
      await context.close();
      continue;
    }
    adminPage = page;
    destination = projects.find((p) => p.id !== 1);
    assert.ok(destination);
    page.on("request", (request) => {
      if (
        /\/api\/catalog\/import\/(preview|validate|commit)\//.test(
          request.url(),
        )
      ) {
        report.requests.push({
          path: new URL(request.url()).pathname,
          projectTagId: request.headers()["x-project-id"],
        });
      }
    });
    await field.click();
    await options.filter({ hasText: destination.name }).click();
    await page
      .locator("input[type=file]")
      .first()
      .setInputFiles({
        name: `codex_upload_acceptance_${Date.now()}.csv`,
        mimeType: "text/csv",
        buffer: Buffer.from("sample,value\nA,1\nB,2\n"),
      });
    await page.getByRole("button", { name: /数据校验并继续/ }).waitFor();
    assert.equal(await field.isDisabled(), true);
    await page.getByRole("button", { name: /数据校验并继续/ }).click();
    await page.getByRole("button", { name: /提交导入/ }).waitFor();
    const committed = page.waitForResponse((response) =>
      response.url().endsWith("/api/catalog/import/commit/"),
    );
    await page.getByRole("button", { name: /提交导入/ }).click();
    const response = await committed;
    const result = await response.json();
    assert.equal(response.status(), 201, JSON.stringify(result));
    created = { id: result.resourceId, name: result.resourceName };
    assert.ok(created.name.startsWith("codex_upload_acceptance_"));
    assert.ok(report.requests.length >= 3);
    assert.ok(
      report.requests.every((r) => r.projectTagId === String(destination.id)),
    );
    const visibility = await page.evaluate(
      async ({ id, project }) => {
        const results = [];
        for (const tag of ["1", String(project)]) {
          const response = await fetch("/api/admin/data/resources/", {
            headers: { "X-Project-Id": tag },
          });
          const data = await response.json();
          results.push({
            tag,
            found: data.items.some((r) => r.id === id),
            projectTagId: data.items.find((r) => r.id === id)?.projectTagId,
          });
        }
        return results;
      },
      { id: created.id, project: destination.id },
    );
    assert.equal(visibility[0].found, false);
    assert.equal(visibility[1].projectTagId, destination.id);
    report.visibility = visibility;
    await page.screenshot({
      path: `${out}/admin-upload-completed.png`,
      fullPage: true,
    });
    await page.evaluate(
      ({ id, project }) =>
        sessionStorage.setItem(`project:${id}`, String(project)),
      { id: sessions.admin.id, project: destination.id },
    );
    await page.goto("http://127.0.0.1:5173/resources/data/inventory");
    await page.getByRole("combobox", { name: "存量数据所属项目" }).waitFor();
    await page
      .getByRole("button", { name: created.name, exact: true })
      .waitFor();
    assert.ok(
      await page
        .getByRole("columnheader", { name: "所属项目标签", exact: true })
        .count(),
    );
    await page.screenshot({
      path: `${out}/inventory-selected-project.png`,
      fullPage: true,
    });
  }
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = String(error);
  if (currentPage && !currentPage.isClosed())
    await currentPage.screenshot({
      path: `${out}/failure.png`,
      fullPage: true,
    });
  throw error;
} finally {
  if (created && adminPage) {
    const cleanup = await adminPage.evaluate(
      async ({ created, tag }) => {
        const csrf = document.cookie
          .split("; ")
          .find((c) => c.startsWith("csrftoken="))
          ?.slice("csrftoken=".length);
        const response = await fetch(
          `/api/admin/data/resources/${created.id}/`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": decodeURIComponent(csrf ?? ""),
              "X-Project-Id": String(tag),
            },
            body: JSON.stringify({
              action: "delete",
              confirmationName: created.name,
            }),
          },
        );
        return { status: response.status, body: await response.json() };
      },
      { created, tag: destination.id },
    );
    report.temporaryResourceRemoved = cleanup.status === 200;
    if (cleanup.status !== 200) report.cleanupError = cleanup;
  }
  await writeFile(
    `${out}/live-browser-report.json`,
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
