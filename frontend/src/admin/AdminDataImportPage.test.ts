import { describe, expect, it } from "vitest";
import { normalizeImportValues } from "./importValues";

describe("normalizeImportValues", () => {
  it("keeps the selected business domain type in the import payload", () => {
    expect(
      normalizeImportValues({
        name: " 胡杨群落样方数据 ",
        domainType: "community",
        categoryCode: "thematic_community",
        importMode: "geographic",
        longitudeColumn: "Longitude",
        latitudeColumn: "Latitude",
        accessGroupIds: [],
      }),
    ).toEqual({
      name: "胡杨群落样方数据",
      domainType: "community",
      categoryCode: "thematic_community",
      importMode: "geographic",
      longitudeColumn: "Longitude",
      latitudeColumn: "Latitude",
      accessGroupIds: [],
    });
  });

  it("accepts the vector business domain type", () => {
    expect(
      normalizeImportValues({
        name: " 新疆边界 ",
        domainType: "vector",
        categoryCode: "base_geo_admin",
        importMode: "geographic",
        longitudeColumn: "",
        latitudeColumn: "",
        accessGroupIds: [],
      }),
    ).toMatchObject({
      name: "新疆边界",
      domainType: "vector",
      categoryCode: "base_geo_admin",
      importMode: "geographic",
    });
  });
});
