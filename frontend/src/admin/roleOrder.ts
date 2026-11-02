import type { Group } from "../types";

const builtinOrder = [
  "超级管理员",
  "平台管理员",
  "数据管理员",
  "科研用户",
  "普通用户",
  "游客",
];

function builtinRank(name: string): number {
  const index = builtinOrder.indexOf(name);
  return index === -1 ? builtinOrder.length : index;
}

/** Display order only: the server remains responsible for authorization. */
export function sortRolesByPermissions(groups: readonly Group[]): Group[] {
  return [...groups].sort((left, right) => {
    if ((left.name === "超级管理员") !== (right.name === "超级管理员")) {
      return left.name === "超级管理员" ? -1 : 1;
    }
    return (
      new Set(right.permissions).size - new Set(left.permissions).size ||
      builtinRank(left.name) - builtinRank(right.name) ||
      left.name.localeCompare(right.name, "zh-CN") ||
      left.id - right.id
    );
  });
}
