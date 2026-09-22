import { readFileSync, readdirSync, statSync } from "node:fs";
import { relative, resolve } from "node:path";

const [expectedArg, actualArg] = process.argv.slice(2);
if (!expectedArg || !actualArg) {
  throw new Error("请提供两个待比较目录");
}

const expectedRoot = resolve(process.cwd(), expectedArg);
const actualRoot = resolve(process.cwd(), actualArg);
const expectedFiles = filesUnder(expectedRoot);
const actualFiles = filesUnder(actualRoot);
const differences = [];

for (const path of new Set([...expectedFiles, ...actualFiles])) {
  if (!expectedFiles.has(path)) {
    differences.push(`生成目录多出文件：${path}`);
    continue;
  }
  if (!actualFiles.has(path)) {
    differences.push(`生成目录缺少文件：${path}`);
    continue;
  }
  const expected = readFileSync(resolve(expectedRoot, path));
  const actual = readFileSync(resolve(actualRoot, path));
  if (!expected.equals(actual)) {
    differences.push(`生成内容漂移：${path}`);
  }
}

if (differences.length > 0) {
  console.error(differences.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`OpenAPI 生成文件一致（${expectedFiles.size} 个文件）。`);
}

function filesUnder(root) {
  const files = new Set();
  visit(root);
  return files;

  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const absolute = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        visit(absolute);
      } else if (entry.isFile() || statSync(absolute).isFile()) {
        files.add(relative(root, absolute).replaceAll("\\", "/"));
      }
    }
  }
}
