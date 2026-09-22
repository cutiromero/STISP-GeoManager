import { readFile } from "node:fs/promises";
import { join } from "node:path";

const canonicalName = "时空智能服务平台";
const legacyNames = [
  "全球胡杨林生态系统保护数据共享平台",
  "中亚胡杨林生态系统保护数据共享平台",
  "中亚胡杨林生态保护数据共享平台",
  "中亚胡杨林生态数据共享平台",
  "中亚胡杨生态系统保护数据共享平台",
  "中亚胡杨生态数据门户",
];

const requiredFiles = [
  ["index.html", `<title>${canonicalName}</title>`],
  ["../config/app.example.toml", `name = "${canonicalName}"`],
  ["../config/app.docker.toml", `name = "${canonicalName}"`],
  ["src/config/platformBrand.ts", `chineseName: "${canonicalName}"`],
  [
    "../backend/apps/core/platform_brand.py",
    `PLATFORM_CHINESE_NAME = "${canonicalName}"`,
  ],
];

const activeFiles = [
  "index.html",
  "../config/app.example.toml",
  "../config/app.docker.toml",
  "src/App.tsx",
  "src/admin/AdminDataImportPage.tsx",
  "src/admin/AdminSystemSettingsPage.tsx",
  "src/components/WorkspaceHeader.tsx",
  "../backend/apps/core/views.py",
  "../backend/apps/core/admin_api.py",
  "../backend/apps/core/backup_service.py",
  "../backend/apps/core/runtime_config.py",
];

const failures = [];
for (const [relativePath, expectedText] of requiredFiles) {
  const content = await readFile(join(process.cwd(), relativePath), "utf8");
  if (!content.includes(expectedText)) {
    failures.push(`${relativePath} 缺少统一品牌文本：${expectedText}`);
  }
}

for (const relativePath of activeFiles) {
  const content = await readFile(join(process.cwd(), relativePath), "utf8");
  for (const legacyName of legacyNames) {
    if (content.includes(legacyName)) {
      failures.push(`${relativePath} 重新引入旧平台名称：${legacyName}`);
    }
  }
  if (relativePath.startsWith("src/") && content.includes("document.title =")) {
    failures.push(
      `${relativePath} 直接修改 document.title；请统一调用 applyPlatformDocumentTitle`,
    );
  }
}

if (failures.length > 0) {
  throw new Error(`平台品牌一致性检查失败：\n- ${failures.join("\n- ")}`);
}

console.log(`平台品牌一致性检查通过：${canonicalName}`);
