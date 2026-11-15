/** Run unchanged browser tests in an ASCII source mirror when required by Vitest. */
import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { execFileSync } from "node:child_process";

// ==================== CONFIGURATION ====================
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2).filter((value) => value !== "--");
const exclusions = new Set([
  "node_modules",
  ".runtime",
  ".cache",
  "dist",
  "test-results",
]);
const stamp = `${Date.now()}-${process.pid}`;
const output = join(frontend, "test-results", "browser-runs", stamp);
const externalFixtures = [
  "backend/apps/knowledge/seed_entries.json",
  "backend/apps/knowledge/seed_entries_20261009.json",
  "backend/apps/knowledge/seed_entries_20261010.json",
];
// =======================================================

async function hashes(root) {
  const result = {};
  async function walk(folder) {
    for (const entry of (await readdir(folder, { withFileTypes: true })).sort(
      (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0),
    )) {
      if (
        exclusions.has(entry.name) ||
        entry.name.startsWith(".env") ||
        entry.name === ".npmrc"
      )
        continue;
      const path = join(folder, entry.name);
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile())
        result[relative(root, path)] = createHash("sha256")
          .update(await readFile(path))
          .digest("hex");
    }
  }
  await walk(root);
  return result;
}

let mirror;
let mirrorRoot;
let code = 1;
let child;
const forward = (signal) => child?.kill(signal);
try {
  execFileSync(
    "python",
    [join(frontend, "../scripts/prepare_card_assets.py")],
    { stdio: "inherit" },
  );
  const dependencies = await realpath(join(frontend, "node_modules"));
  const before = await hashes(frontend);
  let cwd = frontend,
    config = "vitest.browser.config.ts";
  if (
    Array.from(frontend).some((character) => character.codePointAt(0) > 127)
  ) {
    // Vitest browser mocks mismatch percent-encoded non-ASCII module URLs.
    mirrorRoot = await mkdtemp(join(tmpdir(), "stisp-browser-"));
    mirror = join(mirrorRoot, "frontend");
    await cp(frontend, mirror, {
      recursive: true,
      filter: (path) => {
        const parts = relative(frontend, path).split(/[\\/]/);
        return !parts.some(
          (part) =>
            exclusions.has(part) ||
            part.startsWith(".env") ||
            part === ".npmrc",
        );
      },
    });
    await symlink(dependencies, join(mirror, "node_modules"), "dir");
    await cp(
      join(frontend, ".cache/card-assets"),
      join(mirror, ".cache/card-assets"),
      { recursive: true },
    );
    for (const fixture of externalFixtures) {
      const source = join(frontend, "..", fixture);
      const target = join(mirrorRoot, fixture);
      await mkdir(dirname(target), { recursive: true });
      await cp(source, target);
      if (!Buffer.from(await readFile(source)).equals(await readFile(target)))
        throw new Error(`Browser fixture mirror differs: ${fixture}`);
    }
    cwd = mirror;
    config = "vitest.browser.mirror.config.mjs";
    await writeFile(
      join(mirror, config),
      `import {mergeConfig,defineConfig} from 'vitest/config';\nimport base from './vitest.browser.config.ts';\nexport default mergeConfig(base,defineConfig({cacheDir:'.test-cache',server:{fs:{allow:${JSON.stringify([mirror, dependencies, join(mirrorRoot, "backend/apps/knowledge")])}}}}));\n`,
    );
    const copied = await hashes(mirror);
    for (const [name, digest] of Object.entries(before)) {
      if (copied[name] !== digest)
        throw new Error(`Browser source mirror differs: ${name}`);
    }
    console.log(
      "Browser tests use an identical ASCII source mirror; existing dependencies are reused.",
    );
  }
  const command = [
    join(dependencies, "vitest", "vitest.mjs"),
    "--config",
    config,
    "run",
    "--browser.headless",
    ...args,
  ];
  child = spawn(process.execPath, command, { cwd, stdio: "inherit" });
  process.on("SIGINT", forward);
  process.on("SIGTERM", forward);
  code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (status, signal) =>
      resolve(status ?? (signal ? 130 : 1)),
    );
  });
  const after = await hashes(frontend);
  if (JSON.stringify(before) !== JSON.stringify(after))
    throw new Error(
      "Source changed while browser tests ran; rerun verification.",
    );
  await mkdir(output, { recursive: true });
  if (mirror) {
    await cp(join(mirror, "test-results"), join(output, "artifacts"), {
      recursive: true,
    }).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  }
  await writeFile(
    join(output, "receipt.json"),
    JSON.stringify(
      {
        source: frontend,
        identicalSourceMirror: Boolean(mirror),
        args,
        exitCode: code,
        sourceHashes: before,
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(error.message);
  code = 1;
} finally {
  process.removeListener("SIGINT", forward);
  process.removeListener("SIGTERM", forward);
  if (mirrorRoot) await rm(mirrorRoot, { recursive: true, force: true });
}
process.exitCode = code;
