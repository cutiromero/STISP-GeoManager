export const ownerAccessScopeId = "__owner__";

export type AccessScopeId = number | typeof ownerAccessScopeId;

export function withFixedAccessScopes(
  values: AccessScopeId[] = [],
): AccessScopeId[] {
  const optionalValues = values.filter((value) => value !== ownerAccessScopeId);
  return [ownerAccessScopeId, ...optionalValues];
}

export function realAccessGroupIds(values: AccessScopeId[] = []): number[] {
  return values.filter((value): value is number => typeof value === "number");
}

export function selectableAccessScopeIds(
  values: AccessScopeId[] = [],
  groups: ReadonlyArray<{ id: number }> = [],
): AccessScopeId[] {
  const selectableGroupIds = new Set(groups.map((group) => group.id));
  return withFixedAccessScopes(
    values.filter(
      (value) =>
        value === ownerAccessScopeId ||
        (typeof value === "number" && selectableGroupIds.has(value)),
    ),
  );
}
