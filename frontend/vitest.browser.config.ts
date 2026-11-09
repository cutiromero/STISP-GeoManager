import react from "@vitejs/plugin-react";
import { playwright } from "@vitest/browser-playwright";
import { existsSync } from "node:fs";
import { defineConfig } from "vitest/config";

const windowsChromePath =
  "C:/Program Files/Google/Chrome/Application/chrome.exe";
const localLaunchOptions =
  process.platform === "win32" && existsSync(windowsChromePath)
    ? { executablePath: windowsChromePath }
    : undefined;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@ant-design/pro-components": "@ant-design/pro-components/es",
    },
  },
  optimizeDeps: {
    include: [
      "mapbox-gl",
      "antd",
      "@ant-design/icons",
      "@ant-design/pro-components",
      "antd/locale/en_US",
      "dayjs",
      "dayjs/locale/en",
      "dayjs/locale/zh-cn",
      "react-dom/client",
    ],
  },
  test: {
    include: ["src/**/*.browser.{test,spec}.{ts,tsx}"],
    passWithNoTests: true,
    setupFiles: ["./src/test/browserSetup.ts"],
    testTimeout: 30000,
    server: {
      deps: {
        inline: [/@ant-design\/pro-components/],
      },
    },
    deps: {
      optimizer: {
        web: {
          include: ["@ant-design/pro-components"],
        },
      },
    },
    browser: {
      enabled: true,
      provider: playwright({ launchOptions: localLaunchOptions }),
      headless: true,
      screenshotDirectory: "test-results/browser-screenshots",
      instances: [
        {
          browser: "chromium",
          viewport: { width: 1600, height: 900 },
        },
      ],
    },
  },
});
