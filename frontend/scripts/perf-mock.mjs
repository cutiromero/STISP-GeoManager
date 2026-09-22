import { spawn } from "node:child_process";
import { mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = parseArgs(process.argv.slice(2));
const frontendRoot = path.resolve(
  args.frontendRoot || path.resolve(__dirname, ".."),
);
const toolRoot = path.resolve(args.toolRoot || path.resolve(__dirname, ".."));
const distRoot = path.join(frontendRoot, "dist");
const resultRoot = path.join(frontendRoot, "perf-results");
const transparentPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lp2xWQAAAABJRU5ErkJggg==",
  "base64",
);
let shuttingDown = false;

const label = args.label || "run";
const previewPort = await findAvailablePort(Number(args.previewPort || 4173));
const prismPort = await findAvailablePort(Number(args.prismPort || 4010));

const scenarios = [
  { name: "login", path: "/login", authenticated: false },
  { name: "map", path: "/map", authenticated: true },
  { name: "admin-dashboard", path: "/admin/dashboard", authenticated: true },
];

const children = [];

async function main() {
  await mkdir(resultRoot, { recursive: true });

  startProcess(toolBin("prism"), [
    "mock",
    "../mock/prism/openapi.prism.json",
    "--host",
    "127.0.0.1",
    "--port",
    String(prismPort),
  ]);
  startProcess(toolBin("vite"), [
    "preview",
    "--host",
    "127.0.0.1",
    "--port",
    String(previewPort),
    "--strictPort",
  ]);

  await Promise.all([
    waitForHttp(`http://127.0.0.1:${prismPort}/api/bootstrap/`),
    waitForHttp(`http://127.0.0.1:${previewPort}/`),
  ]);

  const browser = await chromium.launch({ headless: true });
  try {
    const pages = [];
    for (const scenario of scenarios) {
      pages.push(await measureScenario(browser, scenario));
    }
    const result = {
      label,
      generatedAt: new Date().toISOString(),
      environment: {
        previewUrl: `http://127.0.0.1:${previewPort}`,
        apiUrl: `http://127.0.0.1:${prismPort}`,
        browser: "chromium",
      },
      pages,
      bundles: await readBundleSizes(),
    };
    const outFile = path.join(resultRoot, `${label}.json`);
    await writeFile(outFile, `${JSON.stringify(result, null, 2)}\n`);
    console.log(`Wrote ${path.relative(frontendRoot, outFile)}`);
    printSummary(result);
  } finally {
    await browser.close();
  }
}

async function measureScenario(browser, scenario) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
  });
  if (scenario.authenticated) {
    await context.addCookies([
      {
        name: "sessionid",
        value: "mock-session",
        domain: "127.0.0.1",
        path: "/",
      },
      {
        name: "csrftoken",
        value: "mock-csrf",
        domain: "127.0.0.1",
        path: "/",
      },
    ]);
  }
  await context.route("**/*", async (route) => {
    const url = route.request().url();
    if (!scenario.authenticated && url.includes("/api/auth/me/")) {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "请先登录" }),
      });
      return;
    }
    if (isExternalMapAsset(url)) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: transparentPng,
      });
      return;
    }
    if (url.startsWith(`http://127.0.0.1:${previewPort}/api/`)) {
      await route.continue({
        url: url.replace(
          `http://127.0.0.1:${previewPort}`,
          `http://127.0.0.1:${prismPort}`,
        ),
      });
      return;
    }
    await route.continue();
  });

  const page = await context.newPage();
  await page.addInitScript(() => {
    window.__perfMetrics = {
      cls: 0,
      longTasks: [],
      fcp: null,
      lcp: null,
    };
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.name === "first-contentful-paint") {
            window.__perfMetrics.fcp = entry.startTime;
          }
        }
      }).observe({ type: "paint", buffered: true });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__perfMetrics.lcp = entry.startTime;
        }
      }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) {
            window.__perfMetrics.cls += entry.value;
          }
        }
      }).observe({ type: "layout-shift", buffered: true });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__perfMetrics.longTasks.push({
            startTime: entry.startTime,
            duration: entry.duration,
          });
        }
      }).observe({ type: "longtask", buffered: true });
    } catch {
      // Older browsers may not expose every observer type.
    }
  });

  const startedAt = Date.now();
  await page.goto(`http://127.0.0.1:${previewPort}${scenario.path}`, {
    waitUntil: "networkidle",
    timeout: 60000,
  });
  await page.waitForTimeout(1200);
  const metrics = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const resources = performance.getEntriesByType("resource");
    const jsTransfer = resources
      .filter((item) => item.initiatorType === "script")
      .reduce((total, item) => total + item.transferSize, 0);
    const cssTransfer = resources
      .filter(
        (item) => item.initiatorType === "link" || item.name.endsWith(".css"),
      )
      .reduce((total, item) => total + item.transferSize, 0);
    const imageTransfer = resources
      .filter(
        (item) =>
          item.initiatorType === "img" ||
          /\.(png|jpe?g|webp|avif|svg)(\?|$)/i.test(item.name),
      )
      .reduce((total, item) => total + item.transferSize, 0);
    const longTasks = window.__perfMetrics.longTasks;
    const memory = performance.memory
      ? {
          usedJSHeapSize: performance.memory.usedJSHeapSize,
          totalJSHeapSize: performance.memory.totalJSHeapSize,
          jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
        }
      : null;
    return {
      loadMs: nav?.loadEventEnd ?? 0,
      domContentLoadedMs: nav?.domContentLoadedEventEnd ?? 0,
      fcpMs: window.__perfMetrics.fcp,
      lcpMs: window.__perfMetrics.lcp,
      cls: window.__perfMetrics.cls,
      longTaskCount: longTasks.length,
      longTaskTotalMs: longTasks.reduce(
        (total, item) => total + item.duration,
        0,
      ),
      transferBytes: {
        js: jsTransfer,
        css: cssTransfer,
        image: imageTransfer,
      },
      memory,
      resourceCount: resources.length,
    };
  });
  await context.close();
  return {
    name: scenario.name,
    path: scenario.path,
    wallTimeMs: Date.now() - startedAt,
    ...metrics,
  };
}

async function readBundleSizes() {
  const manifestPath = path.join(distRoot, ".vite", "manifest.json");
  let manifest = {};
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch {
    return readDistFiles();
  }
  const files = new Set();
  for (const item of Object.values(manifest)) {
    if (item.file) files.add(item.file);
    for (const css of item.css ?? []) files.add(css);
    for (const asset of item.assets ?? []) files.add(asset);
  }
  const results = [];
  for (const file of files) {
    const fullPath = path.join(distRoot, file);
    try {
      const fileStat = await stat(fullPath);
      results.push({ file, bytes: fileStat.size });
    } catch {
      // Ignore manifest entries that do not exist.
    }
  }
  return results.sort((a, b) => b.bytes - a.bytes);
}

async function readDistFiles() {
  const results = [];
  async function visit(dir) {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await visit(fullPath);
        continue;
      }
      const fileStat = await stat(fullPath);
      results.push({
        file: path.relative(distRoot, fullPath),
        bytes: fileStat.size,
      });
    }
  }
  await visit(distRoot);
  return results.sort((a, b) => b.bytes - a.bytes);
}

function startProcess(command, args) {
  const child = spawn(command, args, {
    cwd: frontendRoot,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, FORCE_COLOR: "0" },
  });
  children.push(child);
  child.stdout.on("data", (chunk) =>
    process.stdout.write(`[${command}] ${chunk}`),
  );
  child.stderr.on("data", (chunk) =>
    process.stderr.write(`[${command}] ${chunk}`),
  );
  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }
    if (code && !process.exitCode) {
      process.exitCode = code;
    }
    if (signal && !process.exitCode) {
      process.exitCode = 1;
    }
  });
  return child;
}

function toolBin(name) {
  return path.join(toolRoot, "node_modules", ".bin", name);
}

async function waitForHttp(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // Server not ready yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function isExternalMapAsset(url) {
  return (
    url.includes("tile.openstreetmap.org") ||
    url.includes("tiles.openfreemap.org") ||
    url.includes("api.mapbox.com") ||
    url.includes("events.mapbox.com")
  );
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      parsed[key] =
        argv[index + 1] && !argv[index + 1].startsWith("--")
          ? argv[++index]
          : "true";
    }
  }
  return parsed;
}

function printSummary(result) {
  for (const page of result.pages) {
    console.log(
      [
        page.name,
        `load=${Math.round(page.loadMs)}ms`,
        `fcp=${Math.round(page.fcpMs ?? 0)}ms`,
        `lcp=${Math.round(page.lcpMs ?? 0)}ms`,
        `cls=${page.cls.toFixed(4)}`,
        `heap=${formatBytes(page.memory?.usedJSHeapSize ?? 0)}`,
      ].join(" "),
    );
  }
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

async function findAvailablePort(startPort) {
  for (let port = startPort; port < startPort + 20; port += 1) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }
  throw new Error(`No available port from ${startPort} to ${startPort + 19}`);
}

async function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, "127.0.0.1");
  });
}

async function shutdown() {
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill("SIGTERM");
    }
  }
}

process.on("SIGINT", async () => {
  await shutdown();
  process.exit(130);
});
process.on("SIGTERM", async () => {
  await shutdown();
  process.exit(143);
});
process.on("exit", () => {
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
});

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(shutdown);
