import { describe, expect, it } from "vitest";
import { ownerAccessScopeId, selectableAccessScopeIds } from "./accessScopes";

describe("selectableAccessScopeIds", () => {
  it("removes persisted role ids that are absent from the selectable options", () => {
    expect(
      selectableAccessScopeIds(
        [ownerAccessScopeId, 3, 2],
        [{ id: 2, name: "科研用户", isGuest: false, isSuperadmin: false }],
      ),
    ).toEqual([ownerAccessScopeId, 2]);
  });
});
