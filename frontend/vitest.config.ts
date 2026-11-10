import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@card-assets": fileURLToPath(
        new URL("./.cache/card-assets", import.meta.url),
      ),
      "@ant-design/pro-components": "@ant-design/pro-components/es",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["src/**/*.browser.{test,spec}.{ts,tsx}"],
    testTimeout: 20000,
  },
});
