import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const resultRoot = path.join(frontendRoot, "perf-results");

const [beforeLabel, afterLabel] = process.argv
  .slice(2)
  .filter((arg) => arg !== "--");
if (!beforeLabel || !afterLabel) {
  console.error("Usage: pnpm run perf:compare -- before after");
  process.exit(1);
}

const before = await readResult(beforeLabel);
const after = await readResult(afterLabel);
const markdown = renderComparison(before, after);
const outFile = path.join(resultRoot, `${beforeLabel}-vs-${afterLabel}.md`);
await writeFile(outFile, markdown);
console.log(markdown);
console.log(`Wrote ${path.relative(frontendRoot, outFile)}`);

async function readResult(label) {
  const file = path.join(resultRoot, `${label}.json`);
  return JSON.parse(await readFile(file, "utf8"));
}

function renderComparison(before, after) {
  const lines = [
    `# Frontend Performance: ${before.label} vs ${after.label}`,
    "",
    `Generated: ${new Date().toISOString()}`,
    "",
    "| Page | Metric | Before | After | Change |",
    "| --- | ---: | ---: | ---: | ---: |",
  ];

  for (const beforePage of before.pages) {
    const afterPage = after.pages.find((item) => item.name === beforePage.name);
    if (!afterPage) continue;
    addMetric(
      lines,
      beforePage.name,
      "Load",
      beforePage.loadMs,
      afterPage.loadMs,
      "ms",
    );
    addMetric(
      lines,
      beforePage.name,
      "FCP",
      beforePage.fcpMs,
      afterPage.fcpMs,
      "ms",
    );
    addMetric(
      lines,
      beforePage.name,
      "LCP",
      beforePage.lcpMs,
      afterPage.lcpMs,
      "ms",
    );
    addMetric(
      lines,
      beforePage.name,
      "CLS",
      beforePage.cls,
      afterPage.cls,
      "score",
    );
    addMetric(
      lines,
      beforePage.name,
      "Long task total",
      beforePage.longTaskTotalMs,
      afterPage.longTaskTotalMs,
      "ms",
    );
    addMetric(
      lines,
      beforePage.name,
      "JS heap",
      beforePage.memory?.usedJSHeapSize ?? 0,
      afterPage.memory?.usedJSHeapSize ?? 0,
      "bytes",
    );
  }

  lines.push("", "## Largest Bundles", "");
  lines.push("| File | Before | After | Change |");
  lines.push("| --- | ---: | ---: | ---: |");
  const files = new Set([
    ...before.bundles.slice(0, 20).map((item) => item.file),
    ...after.bundles.slice(0, 20).map((item) => item.file),
  ]);
  for (const file of files) {
    const beforeSize =
      before.bundles.find((item) => item.file === file)?.bytes ?? 0;
    const afterSize =
      after.bundles.find((item) => item.file === file)?.bytes ?? 0;
    lines.push(
      `| ${file} | ${formatBytes(beforeSize)} | ${formatBytes(afterSize)} | ${formatDelta(beforeSize, afterSize)} |`,
    );
  }
  lines.push("");
  return lines.join("\n");
}

function addMetric(lines, page, label, before, after, unit) {
  const beforeValue = before ?? 0;
  const afterValue = after ?? 0;
  lines.push(
    `| ${page} | ${label} | ${formatValue(beforeValue, unit)} | ${formatValue(afterValue, unit)} | ${formatDelta(beforeValue, afterValue)} |`,
  );
}

function formatValue(value, unit) {
  if (unit === "bytes") return formatBytes(value);
  if (unit === "score") return Number(value).toFixed(4);
  return `${Math.round(Number(value))} ${unit}`;
}

function formatDelta(before, after) {
  if (!before && !after) return "0%";
  if (!before) return "+100%";
  const delta = ((after - before) / before) * 100;
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(1)}%`;
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
