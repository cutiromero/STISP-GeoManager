import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@ant-design/pro-components": "@ant-design/pro-components/es",
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          configure(proxy) {
            proxy.on("error", (_error, _request, response) => {
              writeBackendUnavailable(response);
            });
          },
        },
        "/static": {
          target: apiProxyTarget,
          changeOrigin: true,
          configure(proxy) {
            proxy.on("error", (_error, _request, response) => {
              writeBackendUnavailable(response);
            });
          },
        },
      },
    },
    build: {
      manifest: true,
      // 减少内存占用：不计算 gzip 大小
      reportCompressedSize: false,
      modulePreload: {
        resolveDependencies(_filename, deps, context) {
          if (context.hostType !== "html") {
            return deps;
          }
          return deps.filter(
            (dep) =>
              !/assets\/js\/admin-/i.test(dep) &&
              !/assets\/js\/vendor-mapbox-/i.test(dep),
          );
        },
      },
      // 代码分割策略
      rollupOptions: {
        output: {
          // 控制 chunk 文件命名
          chunkFileNames: "assets/js/[name]-[hash].js",
          entryFileNames: "assets/js/[name]-[hash].js",
          assetFileNames: (assetInfo) => {
            const info = assetInfo.name || "";
            if (info.endsWith(".css")) {
              return "assets/css/[name]-[hash][extname]";
            }
            return "assets/[name]-[hash][extname]";
          },
        },
      },
      // 启用 CSS 代码分割
      cssCodeSplit: true,
      // 调整 chunk 大小警告阈值（mapbox-gl 本身就很大）
      chunkSizeWarningLimit: 2000,
    },
    // 优化依赖预构建
    optimizeDeps: {
      // 预构建这些大型依赖，避免开发时重复编译
      include: [
        "mapbox-gl",
        "antd",
        "@ant-design/icons",
        "@ant-design/pro-components",
        "react-router",
        "react-router-dom",
      ],
    },
  };
});

function writeBackendUnavailable(response: unknown) {
  if (!isWritableResponse(response)) {
    return;
  }
  if (!response.headersSent) {
    response.writeHead(503, {
      "Content-Type": "application/json; charset=utf-8",
    });
  }
  response.end(JSON.stringify({ detail: "后端服务尚未就绪，请稍后重试" }));
}

function isWritableResponse(response: unknown): response is {
  headersSent: boolean;
  writeHead: (statusCode: number, headers: Record<string, string>) => void;
  end: (body: string) => void;
} {
  return (
    typeof response === "object" &&
    response !== null &&
    "headersSent" in response &&
    "writeHead" in response &&
    "end" in response &&
    typeof response.writeHead === "function" &&
    typeof response.end === "function"
  );
}
