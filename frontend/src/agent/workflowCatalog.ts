import type {
  ComputeAlgorithm,
  ComputeVersion,
} from "../api/generated/types.gen";
import { getActiveProject } from "../projects/session";

export async function allWorkflowPages<T extends { id: number }>(
  load: (
    params: Record<string, string | number | undefined>,
  ) => Promise<{ items: T[]; total: number }>,
  projectId: string,
  signal: AbortSignal,
) {
  const assertCurrent = () => {
    if (signal.aborted || getActiveProject() !== projectId)
      throw new DOMException(
        "项目已切换，已停止读取旧项目资料。",
        "AbortError",
      );
  };
  const items: T[] = [];
  let total = 1;
  for (let page = 1; items.length < total; page++) {
    assertCurrent();
    const result = await load({ page, pageSize: 100 });
    assertCurrent();
    const seen = new Set(items.map((item) => item.id));
    const fresh = result.items.filter((item) => !seen.has(item.id));
    if (!fresh.length && items.length < result.total)
      throw new Error("资料列表分页不完整，请重新打开 MH-workflow 后再试。");
    items.push(...fresh);
    total = result.total;
  }
  return items;
}

export function workflowGeologyVersions(
  algorithms: ComputeAlgorithm[],
  identifiers: string[],
) {
  const versions = new Map<string, ComputeVersion>();
  const available = algorithms
    .filter(
      (algorithm) =>
        algorithm.enabled && identifiers.includes(algorithm.identifier),
    )
    .flatMap((algorithm) =>
      algorithm.versions
        .filter(
          (version) =>
            version.status === "published" &&
            version.manifest.agent?.enabled !== false,
        )
        .map((version) => ({ identifier: algorithm.identifier, version })),
    )
    .sort(
      (a, b) =>
        (Date.parse(b.version.createdAt) || 0) -
          (Date.parse(a.version.createdAt) || 0) || b.version.id - a.version.id,
    );
  for (const item of available)
    if (!versions.has(item.identifier))
      versions.set(item.identifier, item.version);
  return identifiers.flatMap((identifier) =>
    versions.has(identifier) ? [versions.get(identifier)!] : [],
  );
}
