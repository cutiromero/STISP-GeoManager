import { describe, expect, it } from "vitest";
import {
  fallbackTaxonomyTree,
  findTaxonomyNode,
  taxonomyLeafOptions,
  taxonomySelectOptions,
} from "./taxonomy";
describe("coordinate based data taxonomy", () => {
  it("exposes two selectable categories", () => {
    expect(fallbackTaxonomyTree.map((n) => n.code)).toEqual([
      "spatial",
      "non_spatial",
    ]);
    expect(taxonomyLeafOptions(null)).toEqual([
      { value: "spatial", label: "地理数据" },
      { value: "non_spatial", label: "非地理数据" },
    ]);
    expect(taxonomySelectOptions(null).every((n) => !n.disabled)).toBe(true);
  });
  it("removes retired topic categories", () => {
    expect(findTaxonomyNode(fallbackTaxonomyTree, "habitat_soil")).toBeNull();
    expect(findTaxonomyNode(fallbackTaxonomyTree, "spatial")?.children).toEqual(
      [],
    );
  });
});
