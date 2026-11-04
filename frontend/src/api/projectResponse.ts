import type { ProjectTagList } from "./generated/types.gen";
import { ResponseFormatError } from "./responseDiagnostics";

export function assertProjectList(
  value: unknown,
): asserts value is ProjectTagList {
  const fail = (path: string): never => {
    throw new ResponseFormatError(
      path,
      "项目列表返回内容异常，当前页面已保留，请重试",
    );
  };
  if (!value || typeof value !== "object" || Array.isArray(value))
    fail("projects");
  const data = value as Record<string, unknown>;
  for (const key of ["items", "assignableItems"]) {
    if (key === "assignableItems" && data[key] === undefined) continue;
    const items = data[key];
    if (!Array.isArray(items)) fail(`projects.${key}`);
    for (const item of items as unknown[]) {
      if (!item || typeof item !== "object" || Array.isArray(item))
        fail(`projects.${key}[]`);
      const project = item as Record<string, unknown>;
      if (typeof project.id !== "number" || !Number.isFinite(project.id))
        fail(`projects.${key}[].id`);
      if (typeof project.name !== "string") fail(`projects.${key}[].name`);
      for (const field of ["isActive", "isDefault"])
        if (typeof project[field] !== "boolean")
          fail(`projects.${key}[].${field}`);
    }
  }
  for (const key of ["canManage", "canAssign"])
    if (typeof data[key] !== "boolean") fail(`projects.${key}`);
  if (
    data.defaultProjectId != null &&
    (typeof data.defaultProjectId !== "number" ||
      !Number.isFinite(data.defaultProjectId))
  )
    fail("projects.defaultProjectId");
}
