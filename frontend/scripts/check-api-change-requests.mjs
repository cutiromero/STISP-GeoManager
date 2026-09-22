import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");
const rootDir = resolve(frontendDir, "..");
const changeDocPath = resolve(rootDir, "docs/api-change-requests.md");

const validStatuses = new Set([
  "Proposed",
  "ContractReady",
  "Implementing",
  "BackendReady",
  "Verified",
  "Blocked",
  "Superseded",
]);

const requiredFields = [
  "Status",
  "Owner",
  "Endpoints",
  "Change type",
  "OpenAPI change",
  "Mock examples",
  "Frontend reason",
  "Backend implementation notes",
  "Verification",
  "Result",
];

const doc = await readFile(changeDocPath, "utf8");
const errors = [];

if (!doc.includes("## API Change Status Matrix")) {
  errors.push("Missing API Change Status Matrix section.");
}

const matrixIds = new Set();
for (const line of doc.split("\n")) {
  const match = line.match(/^\|\s*(API-\d{8}-\d{3})\s*\|\s*([^|]+?)\s*\|/);
  if (!match) {
    continue;
  }
  const [, id, statusText] = match;
  const status = statusText.trim();
  matrixIds.add(id);
  if (!validStatuses.has(status)) {
    errors.push(`Invalid status "${status}" in matrix row ${id}.`);
  }
}

const entries = [...doc.matchAll(/^## (API-\d{8}-\d{3}) - .+$/gm)];
const entryIds = new Set();

for (const entry of entries) {
  const id = entry[1];
  if (entryIds.has(id)) {
    errors.push(`Duplicate API change entry ${id}.`);
  }
  entryIds.add(id);

  const start = entry.index ?? 0;
  const nextHeading = doc.slice(start + 1).search(/\n## API-\d{8}-\d{3} - /);
  const section =
    nextHeading === -1
      ? doc.slice(start)
      : doc.slice(start, start + 1 + nextHeading);

  for (const field of requiredFields) {
    if (!section.includes(`- ${field}:`)) {
      errors.push(`Entry ${id} is missing field "${field}".`);
    }
  }

  const statusMatch = section.match(/^- Status:\s*(.+)$/m);
  if (statusMatch && !validStatuses.has(statusMatch[1].trim())) {
    errors.push(`Entry ${id} has invalid status "${statusMatch[1].trim()}".`);
  }
}

for (const id of matrixIds) {
  if (!entryIds.has(id)) {
    errors.push(`Matrix row ${id} has no matching detail entry.`);
  }
}

for (const id of entryIds) {
  if (!matrixIds.has(id)) {
    errors.push(`Detail entry ${id} is missing from the status matrix.`);
  }
}

const changedApiFiles = gitChangedFiles([
  "docs/openapi.yaml",
  "mock/prism/examples",
]);
const changedChangeDoc = gitChangedFiles(["docs/api-change-requests.md"]);

if (changedApiFiles.length > 0 && changedChangeDoc.length === 0) {
  errors.push(
    [
      "OpenAPI or mock examples changed without updating docs/api-change-requests.md.",
      "Changed files:",
      ...changedApiFiles.map((file) => `- ${file}`),
    ].join("\n"),
  );
}

if (errors.length > 0) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(
  `API change requests are valid (${entryIds.size} tracked change request${entryIds.size === 1 ? "" : "s"}).`,
);

function gitChangedFiles(paths) {
  const output = execFileSync(
    "git",
    ["diff", "--name-only", "HEAD", "--", ...paths],
    {
      cwd: rootDir,
      encoding: "utf8",
    },
  );
  return output
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}
