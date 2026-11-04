import type {
  ComputeAlgorithmList,
  ComputeCandidateList,
  ComputeOutput,
  ComputeTask,
  ComputeTaskList,
} from "./generated/types.gen";
import { ResponseFormatError } from "./responseDiagnostics";

export function responseObject(value: unknown, path: string) {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new ResponseFormatError(`${path}: expected object`);
  return value as Record<string, unknown>;
}

export function responseArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value))
    throw new ResponseFormatError(`${path}: expected array`);
  return value;
}

export function responseField(
  value: Record<string, unknown>,
  key: string,
  type: "string" | "number" | "boolean",
  path: string,
) {
  if (
    typeof value[key] !== type ||
    (type === "number" && !Number.isFinite(value[key]))
  )
    throw new ResponseFormatError(`${path}.${key}: expected ${type}`);
}

export function responseValues(
  value: unknown,
  type: "string" | "number",
  path: string,
) {
  responseArray(value, path).forEach((entry, index) => {
    if (typeof entry !== type || (type === "number" && !Number.isFinite(entry)))
      throw new ResponseFormatError(`${path}[${index}]: expected ${type}`);
  });
}

function version(value: unknown, path: string) {
  const item = responseObject(value, path);
  responseField(item, "id", "number", path);
  for (const key of ["version", "status", "createdAt"])
    responseField(item, key, "string", path);
  const manifest = responseObject(item.manifest, `${path}.manifest`);
  for (const key of ["identifier", "name"])
    responseField(manifest, key, "string", `${path}.manifest`);
  for (const key of ["inputs", "parameters", "outputs"]) {
    responseArray(manifest[key], `${path}.manifest.${key}`).forEach(
      (spec, index) => {
        const specPath = `${path}.manifest.${key}[${index}]`;
        const entry = responseObject(spec, specPath);
        for (const name of [
          "key",
          "label",
          key === "parameters" ? "type" : "kind",
        ])
          responseField(entry, name, "string", specPath);
        if (entry.choices !== undefined)
          responseValues(entry.choices, "string", `${specPath}.choices`);
        if (entry.geometryTypes !== undefined)
          responseValues(
            entry.geometryTypes,
            "string",
            `${specPath}.geometryTypes`,
          );
        if (entry.when !== undefined)
          responseObject(entry.when, `${specPath}.when`);
      },
    );
  }
  if (manifest.agent !== undefined) {
    const agent = responseObject(manifest.agent, `${path}.manifest.agent`);
    responseField(agent, "enabled", "boolean", `${path}.manifest.agent`);
  }
}

export function assertAlgorithmList(
  value: unknown,
): asserts value is ComputeAlgorithmList {
  const data = responseObject(value, "algorithms");
  responseField(data, "total", "number", "algorithms");
  responseArray(data.items, "algorithms.items").forEach((entry, index) => {
    const path = `algorithms.items[${index}]`;
    const item = responseObject(entry, path);
    responseField(item, "id", "number", path);
    responseField(item, "enabled", "boolean", path);
    for (const key of ["name", "identifier"])
      responseField(item, key, "string", path);
    responseArray(item.versions, `${path}.versions`).forEach((entry, index) =>
      version(entry, `${path}.versions[${index}]`),
    );
  });
}

export function assertCandidateList(
  value: unknown,
): asserts value is ComputeCandidateList {
  const data = responseObject(value, "candidates");
  responseField(data, "total", "number", "candidates");
  responseArray(data.items, "candidates.items").forEach((entry, index) => {
    const path = `candidates.items[${index}]`;
    const item = responseObject(entry, path);
    responseField(item, "id", "number", path);
    for (const key of ["name", "kind"])
      responseField(item, key, "string", path);
    for (const key of ["fields", "geometryTypes"])
      responseValues(item[key], "string", `${path}.${key}`);
  });
}

export function assertComputeOutput(
  value: unknown,
  path = "output",
): asserts value is ComputeOutput {
  const output = responseObject(value, path);
  responseField(output, "id", "number", path);
  for (const key of [
    "key",
    "label",
    "kind",
    "fileName",
    "importStatus",
    "importError",
    "downloadUrl",
    "previewUrl",
  ])
    responseField(output, key, "string", path);
  responseObject(output.metadata, `${path}.metadata`);
  responseField(output, "expired", "boolean", path);
}

export function assertComputeTask(
  value: unknown,
  path = "task",
): asserts value is ComputeTask {
  const task = responseObject(value, path);
  for (const key of ["id", "name", "status", "stage", "error"])
    responseField(task, key, "string", path);
  responseField(task, "progress", "number", path);
  responseObject(task.parameters, `${path}.parameters`);
  responseArray(task.inputs, `${path}.inputs`).forEach((entry, index) =>
    responseObject(entry, `${path}.inputs[${index}]`),
  );
  responseArray(task.outputs, `${path}.outputs`).forEach((entry, index) =>
    assertComputeOutput(entry, `${path}.outputs[${index}]`),
  );
  version(task.version, `${path}.version`);
}

export function assertComputeTaskList(
  value: unknown,
): asserts value is ComputeTaskList {
  const data = responseObject(value, "tasks");
  responseField(data, "total", "number", "tasks");
  responseArray(data.items, "tasks.items").forEach((entry, index) =>
    assertComputeTask(entry, `tasks.items[${index}]`),
  );
}
