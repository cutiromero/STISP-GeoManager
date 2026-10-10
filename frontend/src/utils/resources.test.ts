import { describe, expect, it } from "vitest";
import type { ResourceListItem } from "../types";
import {
  isComputeResult,
  isGeographicResource,
  isNonGeographicResource,
  resourceSourceLabel,
} from "./resources";

function resource(dataType: ResourceListItem["dataType"]): ResourceListItem {
  const spatialClass =
    dataType === "vector" || dataType === "raster" ? "spatial" : "non_spatial";
  return {
    id: 1,
    name: "测试资源",
    code: `test-${dataType}`,
    dataType,
    spatialClass,
    domainType: "other",
    category: null,
    source: "",
    provider: "",
    dataDate: null,
    spatialExtent: "",
    coordinateSystem: "",
    fileFormat: "",
    description: "",
    qualityNote: "",
    sizeBytes: 0,
    itemCount: 0,
    status: "active",
    isQueryable: false,
    isRenderable: false,
    updatedAt: "2026-07-14T00:00:00+08:00",
  };
}

describe("resource workspace classification", () => {
  it.each(["vector", "raster"] as const)(
    "classifies %s as geographic",
    (dataType) => {
      const item = resource(dataType);
      expect(isGeographicResource(item)).toBe(true);
      expect(isNonGeographicResource(item)).toBe(false);
    },
  );

  it.each(["table", "gene", "document", "image"] as const)(
    "classifies %s as non-geographic",
    (dataType) => {
      const item = resource(dataType);
      expect(isGeographicResource(item)).toBe(false);
      expect(isNonGeographicResource(item)).toBe(true);
    },
  );

  it("recognizes computation results without changing their map capability", () => {
    const item = {
      ...resource("raster"),
      category: {
        id: 3,
        type: "data_category",
        code: "compute_results",
        name: "计算结果",
        parentId: null,
        selectable: false,
      },
      source: "compute-output:internal-storage-key",
    };
    expect(isComputeResult(item)).toBe(true);
    expect(isGeographicResource(item)).toBe(true);
    expect(resourceSourceLabel(item, "平台算法计算")).toBe("平台算法计算");
  });

  it("keeps original data sources and does not infer result classification from text", () => {
    const item = { ...resource("table"), source: "compute-output:user-text" };
    expect(isComputeResult(item)).toBe(false);
    expect(resourceSourceLabel(item, "平台算法计算")).toBe(item.source);
  });
});
