import { describe, expect, it } from "vitest";
import type { ResourceListItem } from "../types";
import { isGeographicResource, isNonGeographicResource } from "./resources";

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
});
