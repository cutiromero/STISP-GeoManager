import { readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");
const rootDir = resolve(frontendDir, "..");
const specPath = resolve(rootDir, "mock/prism/openapi.prism.json");
const examplesDir = resolve(rootDir, "mock/prism/examples");

const spec = JSON.parse(await readFile(specPath, "utf8"));
const exampleFiles = (await readdir(examplesDir))
  .filter((file) => file.endsWith(".json"))
  .sort();
const examples = {};

for (const file of exampleFiles) {
  const fileExamples = JSON.parse(
    await readFile(resolve(examplesDir, file), "utf8"),
  );
  for (const operationKey of Object.keys(fileExamples)) {
    if (examples[operationKey]) {
      throw new Error(`Duplicate mock example target: ${operationKey}`);
    }
  }
  Object.assign(examples, fileExamples);
}

for (const [operationKey, responses] of Object.entries(examples)) {
  const [methodToken, path] = operationKey.split(" ");
  const method = methodToken?.toLowerCase();
  const operation = spec.paths?.[path]?.[method];
  if (!operation) {
    throw new Error(`Mock example target not found: ${operationKey}`);
  }

  for (const [status, example] of Object.entries(responses)) {
    const response = operation.responses?.[status];
    if (!response) {
      throw new Error(
        `Mock response status not found: ${operationKey} ${status}`,
      );
    }

    const content = response.content;
    if (!content) {
      throw new Error(
        `Mock response has no content: ${operationKey} ${status}`,
      );
    }

    const contentType = content["application/json"]
      ? "application/json"
      : Object.keys(content)[0];
    if (!contentType) {
      throw new Error(
        `Mock response has no media type: ${operationKey} ${status}`,
      );
    }

    content[contentType].example = example;
  }
}

await writeFile(specPath, `${JSON.stringify(spec, null, 2)}\n`, "utf8");
console.log(
  `Injected ${Object.keys(examples).length} Prism mock operation examples from ${exampleFiles.length} files into ${specPath}`,
);
