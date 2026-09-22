import { describe, expect, it } from "vitest";
import {
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
} from "./symbolization";
import {
  parseRasterSymbolizationJson,
  parseVectorSymbolizationJson,
} from "./symbolizationImport";
import type { RasterBandMetadata, ResourceField } from "./types";

describe("parseVectorSymbolizationJson", () => {
  it("imports a complete copied scheme and preserves its renderer", () => {
    const source = cloneDefaultVectorSymbolization();
    source.opacity = 64;
    source.renderer = {
      type: "uniqueValue",
      field: "species",
      updatedByUser: true,
      classes: [
        {
          id: "poplar",
          label: "胡杨",
          values: ["胡杨"],
          color: "#2f7d62",
          iconImage: "gm-populus",
          size: 1,
          count: 8,
          visible: true,
        },
      ],
      defaultClass: {
        id: "other",
        label: "其他",
        values: [],
        color: "#8a8f98",
        iconImage: "gm-tree",
        size: 1,
        count: 0,
        visible: true,
      },
    };

    const imported = parseVectorSymbolizationJson(JSON.stringify(source), [
      field("species"),
    ]);

    expect(imported).toEqual(source);
    expect(imported).not.toBe(source);
    expect(imported.circle).not.toBe(source.circle);
    expect(imported.renderer).not.toBe(source.renderer);
  });

  it("rejects a scheme that references a field absent from the target layer", () => {
    const source = cloneDefaultVectorSymbolization();
    source.renderer = {
      type: "graduated",
      field: "elevation",
      method: "equalInterval",
      classCount: 1,
      precision: 1,
      colorRamp: "green",
      classes: [
        {
          id: "range-1",
          label: "0–100",
          min: 0,
          max: 100,
          color: "#2f7d62",
          iconImage: "gm-marker",
          size: 1,
          count: 4,
          visible: true,
        },
      ],
      defaultClass: {
        id: "no-data",
        label: "无数值",
        min: null,
        max: null,
        color: "#8a8f98",
        iconImage: "gm-marker",
        size: 1,
        count: 0,
        visible: true,
      },
    };

    expect(() =>
      parseVectorSymbolizationJson(JSON.stringify(source), [field("name")]),
    ).toThrow("目标图层缺少方案引用的字段：elevation");
  });

  it("rejects raster JSON and invalid vector scalar types", () => {
    expect(() =>
      parseVectorSymbolizationJson(
        JSON.stringify(cloneDefaultRasterSymbolization()),
      ),
    ).toThrow("该 JSON 不是完整的矢量符号化方案");

    const source = cloneDefaultVectorSymbolization() as unknown as Record<
      string,
      unknown
    >;
    source.opacity = "90";
    expect(() => parseVectorSymbolizationJson(JSON.stringify(source))).toThrow(
      "opacity 必须是有限数值",
    );
  });
});

describe("parseRasterSymbolizationJson", () => {
  it("imports a complete copied scheme for compatible target bands", () => {
    const source = cloneDefaultRasterSymbolization();
    source.opacity = 72;
    source.mode = "rgb";
    source.bands = [3, 2, 1];
    source.alphaBand = 4;

    const imported = parseRasterSymbolizationJson(
      JSON.stringify(source),
      rasterBands("Byte", 4),
    );

    expect(imported).toEqual(source);
    expect(imported).not.toBe(source);
    expect(imported.stretch).not.toBe(source.stretch);
  });

  it("rejects unavailable bands and incomplete RGB definitions", () => {
    const source = cloneDefaultRasterSymbolization();
    source.mode = "rgb";
    source.bands = [1, 2, 4];

    expect(() =>
      parseRasterSymbolizationJson(
        JSON.stringify(source),
        rasterBands("Byte", 3),
      ),
    ).toThrow("目标栅格缺少方案引用的波段：4");

    source.bands = [1, 2];
    expect(() => parseRasterSymbolizationJson(JSON.stringify(source))).toThrow(
      "RGB 方案必须且只能配置 3 个输出波段",
    );
  });

  it("rejects a unique-value scheme for a floating-point band", () => {
    const source = cloneDefaultRasterSymbolization();
    source.mode = "unique";
    source.uniqueValues = [{ value: 1, color: "#2f7d62", label: "胡杨" }];

    expect(() =>
      parseRasterSymbolizationJson(
        JSON.stringify(source),
        rasterBands("Float32", 1),
      ),
    ).toThrow("唯一值方案只能应用到整型波段");
  });
});

function field(name: string): ResourceField {
  return {
    name,
    type: "String",
    nullable: false,
    sampleValues: [],
    description: "",
  };
}

function rasterBands(type: string, count: number): RasterBandMetadata[] {
  return Array.from({ length: count }, (_, index) => ({
    band: index + 1,
    type,
    description: `Band ${index + 1}`,
    colorInterpretation: "Undefined",
    min: 0,
    max: 255,
    isInteger: type !== "Float32",
  }));
}
