import { describe, expect, it } from "vitest";
import type { ComputeCandidate } from "../api/generated/types.gen";
import {
  geologyInputIssues,
  geologyRequiredFields,
  geologyWorkflowIssues,
} from "./geologyWorkflowInputs";

const candidate = (role: string, id = 1): ComputeCandidate => ({
  id,
  name: role,
  kind: role === "rules" ? "table" : "vector",
  projectTagId: 3,
  fields: geologyRequiredFields[role]!,
  bands: 0,
  crs: "EPSG:32646",
  geometryTypes: role === "rules" ? [] : ["Polygon"],
  sizeBytes: 100,
});

describe("geology workflow role validation", () => {
  it("separates map, coverage and rules by actual schema", () => {
    for (const role of ["initial_map", "coverage", "rules"]) {
      expect(geologyInputIssues(role, candidate(role))).toEqual([]);
      for (const other of ["initial_map", "coverage", "rules"].filter(
        (item) => item !== role,
      ))
        expect(
          geologyInputIssues(role, candidate(other)).length,
        ).toBeGreaterThan(0);
    }
  });

  it("rejects missing fields, lines, unknown geometry and missing resources", () => {
    expect(
      geologyInputIssues("initial_map", {
        ...candidate("initial_map"),
        fields: ["class"],
      }).join(" "),
    ).toContain("feature_id");
    expect(
      geologyInputIssues("coverage", {
        ...candidate("coverage"),
        geometryTypes: ["LineString"],
      }).join(" "),
    ).toContain("Polygon");
    expect(
      geologyInputIssues("coverage", {
        ...candidate("coverage"),
        geometryTypes: [],
      }).length,
    ).toBeGreaterThan(0);
    expect(geologyInputIssues("rules", undefined).join(" ")).toContain(
      "不可访问",
    );
  });

  it("preserves custom file names and checks duplicate role IDs", () => {
    const choices = [
      candidate("initial_map", 1),
      candidate("coverage", 2),
      { ...candidate("rules", 3), name: "新区域规则" },
    ];
    expect(
      geologyWorkflowIssues({ initial_map: 1, coverage: 2, rules: 3 }, choices),
    ).toEqual([]);
    expect(
      geologyWorkflowIssues(
        { initial_map: 1, coverage: 1, rules: 3 },
        choices,
      ).join(" "),
    ).toContain("同一资料");
    expect(
      geologyWorkflowIssues({ initial_map: 99 }, choices).join(" "),
    ).toContain("不可访问");
  });
});
