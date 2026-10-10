import { describe, expect, it } from "vitest";
import {
  fallbackTaxonomyTree,
  findTaxonomyNode,
  taxonomyLeafOptions,
  taxonomySelectOptions,
} from "./taxonomy";
describe("coordinate based data taxonomy", () => {
  it("exposes original data and computation results while keeping upload choices limited", () => {
    expect(fallbackTaxonomyTree.map((n) => n.code)).toEqual([
      "spatial",
      "non_spatial",
      "compute_results",
    ]);
    expect(taxonomyLeafOptions(null)).toEqual([
      { value: "spatial", label: "地理数据" },
      { value: "non_spatial", label: "非地理数据" },
    ]);
    expect(taxonomySelectOptions(null)).toEqual([
      expect.objectContaining({ value: "spatial", disabled: false }),
      expect.objectContaining({ value: "non_spatial", disabled: false }),
      expect.objectContaining({ value: "compute_results", disabled: true }),
    ]);
    expect(
      findTaxonomyNode(fallbackTaxonomyTree, "compute_results"),
    ).toMatchObject({ name: "计算结果", selectable: false, children: [] });
  });
  it("removes retired topic categories", () => {
    expect(findTaxonomyNode(fallbackTaxonomyTree, "habitat_soil")).toBeNull();
    expect(findTaxonomyNode(fallbackTaxonomyTree, "spatial")?.children).toEqual(
      [],
    );
  });
});
