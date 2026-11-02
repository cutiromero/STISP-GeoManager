import { describe, expect, it } from "vitest";
import { constrainMapPanelLayout } from "./useMapPanelLayout";

describe("map panel layout bounds", () => {
  it("preserves central map space when only one panel can shrink", () => {
    const value = constrainMapPanelLayout(
      { left: 560, right: 240, leftCollapsed: false, rightCollapsed: false },
      1000,
    );
    expect(value.left + value.right).toBeLessThanOrEqual(700);
    expect(value.right).toBe(240);
  });
  it("keeps stored expanded widths while minimized and clamps invalid widths", () => {
    expect(
      constrainMapPanelLayout(
        { left: -1, right: 900, leftCollapsed: true, rightCollapsed: false },
        1200,
      ),
    ).toMatchObject({ left: 240, right: 560 });
  });
});
