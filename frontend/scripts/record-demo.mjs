#!/usr/bin/env node

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(scriptDir, "..");
const projectRoot = path.resolve(frontendRoot, "..");
const demoDir = path.join(projectRoot, "demo");
const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactBaseName = `huyang-system-demo-${timestamp}`;
const webmDir = path.join(demoDir, "raw-video");
const mp4Path = path.join(demoDir, `${artifactBaseName}.mp4`);
const tracePath = path.join(demoDir, `${artifactBaseName}-trace.zip`);
const screenshotPath = path.join(demoDir, `${artifactBaseName}-failure.png`);
const logPath = path.join(demoDir, `${artifactBaseName}.log`);
const eventsPath = path.join(demoDir, `${artifactBaseName}-events.json`);

const baseUrl = process.env.DEMO_BASE_URL ?? "http://127.0.0.1:5173";
const username = process.env.DEMO_USERNAME ?? "admin";
const password = process.env.DEMO_PASSWORD ?? "admin";
const headless = process.env.DEMO_HEADLESS !== "false";
const startServers =
  process.env.DEMO_START_SERVERS === undefined
    ? baseUrl === "http://127.0.0.1:5173"
    : process.env.DEMO_START_SERVERS !== "0";
const useStatefulAuth = process.env.DEMO_STATEFUL_AUTH !== "0";
const showDemoCursor = process.env.DEMO_SHOW_CURSOR !== "0";
const viewport = { width: 1920, height: 1080 };
const slowMoMs = Number(process.env.DEMO_SLOW_MO_MS ?? 80);
const stepPauseMs = Number(process.env.DEMO_STEP_PAUSE_MS ?? 1200);

const events = [];
const childProcesses = [];

async function main() {
  await fs.mkdir(demoDir, { recursive: true });
  await fs.mkdir(webmDir, { recursive: true });

  logStep("准备演示录制目录", { demoDir });

  if (startServers && !(await canReach(baseUrl))) {
    await startDemoServers();
  } else {
    logStep("复用已有前端服务", { baseUrl });
  }

  const browser = await chromium.launch({
    headless,
    slowMo: slowMoMs,
  });
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    locale: "zh-CN",
    recordVideo: {
      dir: webmDir,
      size: viewport,
    },
  });
  await context.tracing.start({
    screenshots: true,
    snapshots: true,
    sources: true,
  });

  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      logStep(`浏览器 ${message.type()}`, { text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    logStep("页面运行时错误", { message: error.message });
  });

  if (useStatefulAuth) {
    await installStatefulAuthMock(page);
  }
  if (showDemoCursor) {
    await installDemoCursor(page);
  }
  await disableWorkspaceTour(page);

  try {
    await runDemoScenario(page);
    await context.tracing.stop({ path: tracePath });
    await context.close();
    await browser.close();
    const webmPath = await locateRecordedWebm();
    await convertVideoToMp4(webmPath, mp4Path);
    logStep("演示视频录制完成", { mp4Path, tracePath });
  } catch (error) {
    await handleRecordingFailure(error, page, context, browser);
    throw error;
  } finally {
    await writeEventLog();
    await stopChildProcesses();
  }
}

async function runDemoScenario(page) {
  // 统一登录页：展示平台定位、服务状态和身份认证入口。
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.getByText("用户登录").waitFor();
  await page.waitForLoadState("networkidle").catch(() => {});
  await pause("展示统一登录页");

  // 用户登录：输入账号密码并进入登录后的三维地球工作台。
  await page.getByPlaceholder("请输入账号").fill(username);
  await page.getByPlaceholder("请输入密码").fill(password);
  await page.getByRole("button", { name: /登录并进入三维地球/ }).click();
  await page.waitForURL(/\/map/, { timeout: 30_000 });
  await page.getByText("数据资源").first().waitFor();
  await pause("登录后进入地理数据工作台");

  // 全局检索：按业务关键词筛选数据、工程和专题入口。
  await page.getByPlaceholder("搜索数据、工程、专题").fill("塔里木");
  await page.keyboard.press("Enter");
  await pause("使用全局搜索筛选塔里木相关数据");

  // 数据目录：选择样地监测点资源，展示字段、空间范围和数据来源。
  const resourceList = page.getByRole("list", { name: "数据资源" });
  await resourceList.waitFor();
  const surveyResource = resourceList
    .locator("li")
    .filter({ hasText: "塔里木河胡杨样地监测点" });
  await surveyResource.waitFor();
  await surveyResource.locator("button").first().click();
  await page.getByText("字段与元信息").waitFor();
  await page.getByText("sample_id").waitFor();
  await pause("查看数据资源字段与元信息");

  // 查询加载：执行属性/空间条件为空的默认查询，并把结果加载为临时矢量图层。
  await page.getByRole("button", { name: "查询并加载" }).click();
  await page
    .getByText(/查询命中 \d+ 条/)
    .first()
    .waitFor();
  await pause("查询样地数据并加载到地图");

  // 图层管理：切换到图层面板，展示已加载图层、显隐控制和图层操作入口。
  await page.getByRole("tab", { name: /图层/ }).click();
  await page
    .getByRole("tree", { name: /已加载图层/ })
    .getByText("塔里木河胡杨样地监测点")
    .waitFor();
  await pause("展示图层管理面板");

  // 底部结果面板：查看已加载图层的查询结果摘要和元数据。
  const bottomPanel = page.getByLabel("底部数据与绘制面板");
  await bottomPanel.getByRole("tab", { name: /结果/ }).click();
  await pause("展示结果和元数据面板");

  // 空间查询工具：展示绘制范围、导入范围和后续空间查询入口。
  await bottomPanel.getByRole("tab", { name: /空间查询/ }).click();
  await bottomPanel.getByText("范围工具").waitFor();
  await pause("展示空间查询工具");

  // 非地理数据：切换到表格/基因数据工作台，展示非空间数据分析页面。
  await page.getByRole("button", { name: /非地理数据/ }).click();
  await page.waitForURL(/\/nongeo/);
  await page.getByText("分析视图").first().waitFor();
  await pause("展示非地理数据分析工作台");

  // 数据管理：进入数据中心，展示数据概览与管理式页面框架。
  await page.getByRole("button", { name: /数据管理/ }).click();
  await page.waitForURL(/\/resources/);
  await page.getByText("数据概览").first().waitFor();
  await pause("展示数据管理概览");

  // 后台管理：进入后台运行概览，展示权限控制后的管理入口。
  await page.getByRole("button", { name: /后台管理/ }).click();
  await page.waitForURL(/\/admin/);
  await page.getByText("运行概览").first().waitFor();
  await page.getByText("用户信息").first().waitFor();
  await pause("展示后台运行概览");

  // 操作日志：查看后台日志页面，演示审计与追踪能力。
  await page
    .getByRole("menuitem", { name: /日志管理/ })
    .first()
    .click();
  await page.waitForURL(/\/admin\/logs/);
  await page.getByText("日志列表").waitFor();
  await pause("展示操作日志列表");

  // 用户入口：打开当前用户信息，展示个人资料、后台入口和退出能力。
  await page.getByRole("button", { name: "用户信息" }).click();
  await page.getByText("系统管理员").first().waitFor();
  await pause("展示用户信息入口");
}

async function installStatefulAuthMock(page) {
  const authExamples = JSON.parse(
    await fs.readFile(
      path.join(projectRoot, "mock/prism/examples/00-public-auth.json"),
      "utf8",
    ),
  );
  const loginUser = authExamples["POST /api/auth/login/"]["200"].user;
  let authenticated = false;

  await page.route("**/api/auth/csrf/", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie": "csrftoken=demo-csrf; Path=/; SameSite=Lax",
      },
      body: JSON.stringify({ detail: "csrf cookie set" }),
    });
  });

  await page.route("**/api/auth/me/", async (route) => {
    if (!authenticated) {
      await route.fulfill({
        status: 401,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ detail: "请先登录" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ authenticated: true, user: loginUser }),
    });
  });

  await page.route("**/api/auth/login/", async (route) => {
    authenticated = true;
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie": "sessionid=demo-session; Path=/; SameSite=Lax",
      },
      body: JSON.stringify({ user: loginUser }),
    });
  });

  await page.route("**/api/auth/logout/", async (route) => {
    authenticated = false;
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie":
          "sessionid=; Path=/; Max-Age=0; SameSite=Lax, csrftoken=; Path=/; Max-Age=0; SameSite=Lax",
      },
      body: JSON.stringify({ detail: "已退出登录" }),
    });
  });
}

async function installDemoCursor(page) {
  await page.addInitScript(() => {
    const cursorState = {
      ready: false,
      x: 120,
      y: 120,
      pointer: null,
      ring: null,
      style: null,
    };

    function ensureCursor() {
      if (cursorState.ready || !document.body) {
        return;
      }
      cursorState.ready = true;

      const style = document.createElement("style");
      style.setAttribute("data-demo-cursor", "true");
      style.textContent = `
        .demo-cursor-pointer,
        .demo-cursor-ring {
          position: fixed;
          left: 0;
          top: 0;
          z-index: 2147483647;
          pointer-events: none;
          will-change: transform, opacity;
        }

        .demo-cursor-pointer {
          width: 19px;
          height: 25px;
          transform: translate3d(var(--demo-cursor-x), var(--demo-cursor-y), 0);
          transition: transform 90ms linear;
          filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.38));
        }

        .demo-cursor-pointer::before {
          content: "";
          position: absolute;
          inset: 0;
          background: #ffffff;
          clip-path: polygon(0 0, 0 21px, 6px 16px, 9px 25px, 14px 23px, 11px 15px, 19px 15px);
        }

        .demo-cursor-pointer::after {
          content: "";
          position: absolute;
          left: 1px;
          top: 1px;
          width: 17px;
          height: 23px;
          background: #111111;
          clip-path: polygon(0 0, 0 19px, 5px 14px, 8px 22px, 12px 21px, 9px 13px, 17px 13px);
          opacity: 0.98;
        }

        .demo-cursor-pointer.demo-cursor-pressed {
          transition-duration: 45ms;
          transform: translate3d(var(--demo-cursor-x), var(--demo-cursor-y), 0) scale(0.9);
        }

        .demo-cursor-ring {
          width: 12px;
          height: 12px;
          margin-left: -6px;
          margin-top: -6px;
          border: 2px solid rgba(21, 214, 186, 0.9);
          border-radius: 999px;
          opacity: 0;
          transform: translate3d(var(--demo-cursor-click-x), var(--demo-cursor-click-y), 0) scale(0.2);
        }

        .demo-cursor-ring.demo-cursor-pulse {
          animation: demo-cursor-pulse 520ms ease-out;
        }

        @keyframes demo-cursor-pulse {
          0% {
            opacity: 0.95;
            transform: translate3d(var(--demo-cursor-click-x), var(--demo-cursor-click-y), 0) scale(0.35);
          }
          100% {
            opacity: 0;
            transform: translate3d(var(--demo-cursor-click-x), var(--demo-cursor-click-y), 0) scale(2.7);
          }
        }
      `;
      document.head.appendChild(style);

      const pointer = document.createElement("div");
      pointer.className = "demo-cursor-pointer";
      pointer.setAttribute("aria-hidden", "true");
      const ring = document.createElement("div");
      ring.className = "demo-cursor-ring";
      ring.setAttribute("aria-hidden", "true");
      document.body.append(pointer, ring);

      cursorState.pointer = pointer;
      cursorState.ring = ring;
      cursorState.style = style;
      moveCursor(cursorState.x, cursorState.y);
    }

    function moveCursor(x, y) {
      cursorState.x = x;
      cursorState.y = y;
      document.documentElement.style.setProperty(
        "--demo-cursor-x",
        `${Math.round(x)}px`,
      );
      document.documentElement.style.setProperty(
        "--demo-cursor-y",
        `${Math.round(y)}px`,
      );
    }

    function pulseCursor(x, y) {
      ensureCursor();
      if (!cursorState.ring || !cursorState.pointer) {
        return;
      }
      document.documentElement.style.setProperty(
        "--demo-cursor-click-x",
        `${Math.round(x)}px`,
      );
      document.documentElement.style.setProperty(
        "--demo-cursor-click-y",
        `${Math.round(y)}px`,
      );
      cursorState.pointer.classList.add("demo-cursor-pressed");
      cursorState.ring.classList.remove("demo-cursor-pulse");
      void cursorState.ring.offsetWidth;
      cursorState.ring.classList.add("demo-cursor-pulse");
      window.setTimeout(() => {
        cursorState.pointer?.classList.remove("demo-cursor-pressed");
      }, 130);
    }

    window.addEventListener(
      "mousemove",
      (event) => {
        ensureCursor();
        moveCursor(event.clientX, event.clientY);
      },
      { capture: true, passive: true },
    );
    window.addEventListener(
      "mousedown",
      (event) => {
        pulseCursor(event.clientX, event.clientY);
      },
      { capture: true, passive: true },
    );
    window.addEventListener("DOMContentLoaded", ensureCursor);
    ensureCursor();
  });
}

async function disableWorkspaceTour(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "huyang-system.workspace-tour.v1.1.admin",
      "completed",
    );
  });
}

async function startDemoServers() {
  logStep("启动 Prism mock 服务和 Vite 演示服务");
  const prismLog = path.join(demoDir, `${artifactBaseName}-prism.log`);
  const viteLog = path.join(demoDir, `${artifactBaseName}-vite.log`);
  const prismProcess = spawnLogged("pnpm", ["run", "mock:api"], prismLog);
  childProcesses.push(prismProcess);
  await waitForUrl(
    "http://127.0.0.1:4010/api/health/",
    "Prism mock API",
    prismProcess,
  );
  const viteProcess = spawnLogged(
    "pnpm",
    ["run", "dev:mock", "--", "--port", "5173"],
    viteLog,
  );
  childProcesses.push(viteProcess);
  await waitForUrl(baseUrl, "Vite frontend", viteProcess);
}

function spawnLogged(command, args, outputPath) {
  const child = spawn(command, args, {
    cwd: frontendRoot,
    detached: process.platform !== "win32",
    stdio: ["ignore", "pipe", "pipe"],
    env: process.env,
  });
  const stream = createWriteStream(outputPath, { flags: "a" });
  child.stdout.pipe(stream);
  child.stderr.pipe(stream);
  child.on("exit", (code, signal) => {
    logStep("子进程退出", { command, args, code, signal, outputPath });
  });
  return child;
}

async function waitForUrl(url, label, processToWatch) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (await canReach(url)) {
      logStep(`${label} 已就绪`, { url });
      return;
    }
    if (processToWatch.exitCode !== null || processToWatch.signalCode) {
      throw new Error(
        `${label} 启动进程已退出，请查看 demo 目录下的服务日志：${url}`,
      );
    }
    await sleep(750);
  }
  throw new Error(`${label} 未在 60 秒内启动：${url}`);
}

async function canReach(url) {
  try {
    const response = await fetch(url, { method: "GET" });
    return response.status < 500;
  } catch {
    return false;
  }
}

async function locateRecordedWebm() {
  const files = await fs.readdir(webmDir);
  const webmFiles = files
    .filter((file) => file.endsWith(".webm"))
    .map((file) => path.join(webmDir, file));
  if (webmFiles.length === 0) {
    throw new Error("Playwright 未生成 WebM 原始视频");
  }
  const stats = await Promise.all(
    webmFiles.map(async (file) => ({ file, stat: await fs.stat(file) })),
  );
  stats.sort((left, right) => right.stat.mtimeMs - left.stat.mtimeMs);
  return stats[0].file;
}

async function convertVideoToMp4(webmPath, outputPath) {
  const encoders = await selectFfmpegEncoders();
  logStep("转换视频为 1920x1080 30fps MP4", {
    webmPath,
    outputPath,
    encoders: encoders.map((encoder) => encoder.name),
  });

  const failures = [];
  for (const encoder of encoders) {
    try {
      logStep("尝试 FFmpeg 视频编码器", {
        encoder: encoder.name,
        hardware: encoder.hardware,
      });
      await runCommand("ffmpeg", [
        "-y",
        "-i",
        webmPath,
        "-vf",
        "scale=1920:1080:flags=lanczos",
        "-r",
        "30",
        "-pix_fmt",
        "yuv420p",
        ...encoder.args,
        "-movflags",
        "+faststart",
        outputPath,
      ]);
      logStep("FFmpeg 视频编码器可用", {
        encoder: encoder.name,
        hardware: encoder.hardware,
      });
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push(`${encoder.name}: ${message}`);
      logStep("FFmpeg 视频编码器失败，尝试下一个", {
        encoder: encoder.name,
        hardware: encoder.hardware,
        message,
      });
    }
  }

  throw new Error(`MP4 转换失败，已尝试编码器：\n${failures.join("\n\n")}`);
}

async function selectFfmpegEncoders() {
  const availableEncoders = await getAvailableFfmpegEncoders();
  const priority =
    process.platform === "darwin"
      ? ["h264_videotoolbox", "h264_nvenc", "h264_qsv"]
      : ["h264_nvenc", "h264_qsv", "h264_videotoolbox"];
  const candidates = priority
    .filter((name) => availableEncoders.has(name))
    .map((name) => ffmpegEncoderConfig(name));
  candidates.push(ffmpegEncoderConfig("libx264"));
  return candidates;
}

async function getAvailableFfmpegEncoders() {
  try {
    const { stdout } = await runCommandCapture("ffmpeg", [
      "-hide_banner",
      "-encoders",
    ]);
    return new Set(
      stdout
        .split("\n")
        .map((line) => line.match(/^\s*[A-Z.]{6}\s+(\S+)/)?.[1])
        .filter(Boolean),
    );
  } catch (error) {
    logStep("FFmpeg 编码器枚举失败，将直接尝试 CPU 编码", {
      message: error instanceof Error ? error.message : String(error),
    });
    return new Set();
  }
}

function ffmpegEncoderConfig(name) {
  switch (name) {
    case "h264_videotoolbox":
      return {
        name,
        hardware: "apple-videotoolbox",
        args: ["-c:v", "h264_videotoolbox", "-b:v", "12M", "-allow_sw", "0"],
      };
    case "h264_nvenc":
      return {
        name,
        hardware: "nvidia-nvenc",
        args: ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0"],
      };
    case "h264_qsv":
      return {
        name,
        hardware: "intel-quick-sync",
        args: [
          "-c:v",
          "h264_qsv",
          "-preset",
          "medium",
          "-global_quality",
          "19",
        ],
      };
    default:
      return {
        name: "libx264",
        hardware: "cpu",
        args: ["-c:v", "libx264", "-preset", "medium", "-crf", "18"],
      };
  }
}

async function runCommand(command, args) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: projectRoot });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      reject(
        new Error(
          `${command} 执行失败。请安装 ffmpeg 后重试。原始错误：${error.message}`,
        ),
      );
    });
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} 退出码 ${code}\n${stderr}`));
    });
  });
}

async function runCommandCapture(command, args) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: projectRoot });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      reject(
        new Error(
          `${command} 执行失败。请安装 ffmpeg 后重试。原始错误：${error.message}`,
        ),
      );
    });
    child.on("exit", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(new Error(`${command} 退出码 ${code}\n${stderr}`));
    });
  });
}

async function handleRecordingFailure(error, page, context, browser) {
  const message = error instanceof Error ? error.message : String(error);
  logStep("演示录制失败", { message, screenshotPath, tracePath });
  try {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  } catch (screenshotError) {
    logStep("失败截图保存失败", {
      message:
        screenshotError instanceof Error
          ? screenshotError.message
          : String(screenshotError),
    });
  }
  try {
    await context.tracing.stop({ path: tracePath });
  } catch (traceError) {
    logStep("trace 保存失败", {
      message:
        traceError instanceof Error ? traceError.message : String(traceError),
    });
  }
  try {
    await context.close();
  } catch {}
  try {
    await browser.close();
  } catch {}
  await writeEventLog();
}

async function pause(label) {
  logStep(label);
  await sleep(stepPauseMs);
}

function logStep(message, data = {}) {
  events.push({ at: new Date().toISOString(), message, ...data });
  console.log(`[demo] ${message}`);
}

async function writeEventLog() {
  const text = events
    .map((event) => `${event.at} ${event.message} ${JSON.stringify(event)}`)
    .join("\n");
  await fs.writeFile(logPath, `${text}\n`, "utf8");
  await fs.writeFile(eventsPath, JSON.stringify(events, null, 2), "utf8");
}

async function stopChildProcesses() {
  await Promise.all(childProcesses.map((child) => stopChildProcess(child)));
}

async function stopChildProcess(child) {
  if (child.exitCode !== null || child.signalCode) {
    return;
  }
  signalChildProcess(child, "SIGTERM");
  const stopped = await waitForChildExit(child, 3_000);
  if (!stopped) {
    signalChildProcess(child, "SIGKILL");
    await waitForChildExit(child, 1_000);
  }
}

function signalChildProcess(child, signal) {
  try {
    if (process.platform !== "win32" && child.pid) {
      process.kill(-child.pid, signal);
      return;
    }
    child.kill(signal);
  } catch (error) {
    logStep("子进程终止信号发送失败", {
      pid: child.pid,
      signal,
      message: error instanceof Error ? error.message : String(error),
    });
  }
}

function waitForChildExit(child, timeoutMs) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode) {
      resolve(true);
      return;
    }
    const timer = setTimeout(() => {
      child.off("exit", onExit);
      resolve(false);
    }, timeoutMs);
    function onExit() {
      clearTimeout(timer);
      resolve(true);
    }
    child.once("exit", onExit);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

process.on("SIGINT", () => {
  void stopChildProcesses().finally(() => process.exit(130));
});

process.on("SIGTERM", () => {
  void stopChildProcesses().finally(() => process.exit(143));
});

main().catch(async (error) => {
  const message =
    error instanceof Error ? error.stack || error.message : String(error);
  console.error(`[demo] 录制失败：${message}`);
  await writeEventLog().catch(() => {});
  process.exitCode = 1;
});
