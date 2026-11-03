import { expect, it } from "vitest";
import type { ComputeCandidate } from "../api/generated/types.gen";
import { demoInputsReady } from "./DemoWorkflowForm";
import {
  isLogicReasoningProject,
  multiElementInputIssues,
  multiElementPrompt,
  multiElementRoles,
  multiElementSegments,
  multiElementType,
} from "./multiElementScenario";

const input = (
  kind: string,
  geometries: string[] = [],
  fields: string[] = [],
): ComputeCandidate =>
  ({
    id: 1,
    name: "可读数据名称",
    kind: kind as ComputeCandidate["kind"],
    fields,
    geometryTypes: geometries,
    bands: 0,
    crs: "EPSG:32646",
    status: "ready",
    reasons: [],
  }) as ComputeCandidate;

it("多要素场景的九角色不会把线、面、矿物栅格和规则表互串", () => {
  expect(multiElementRoles).toHaveLength(9);
  expect(
    multiElementInputIssues("faults", input("vector", ["Polygon"])),
  ).not.toEqual([]);
  expect(
    multiElementInputIssues("coverage", input("vector", ["MultiPolygon"])),
  ).toEqual([]);
  expect(
    multiElementInputIssues(
      "lithology",
      input("vector", ["Polygon"], ["feature_id", "name", "geo_sym"]),
    ),
  ).toEqual([]);
  expect(multiElementInputIssues("hematite", input("table"))).not.toEqual([]);
  expect(multiElementInputIssues("rules", input("table"))).not.toEqual([]);
  expect(demoInputsReady(multiElementType, { lithology: 1 })).toBe(false);
});

it("三个简短入口明确分段并保留批准和版本要求", () => {
  expect(multiElementSegments.map((item) => item.value)).toEqual([
    "all",
    "lithology",
    "structure",
    "alteration",
  ]);
  expect(multiElementPrompt("structure")).toContain("segment=structure");
  expect(multiElementPrompt("alteration")).toContain("上游成果版本");
  expect(multiElementPrompt("lithology")).toContain("逐项建议经我批准");
});

it("treats only the backend's geology project codes as the logic-reasoning project", () => {
  expect(isLogicReasoningProject("02")).toBe(true);
  expect(isLogicReasoningProject("demo-geology-reasoning")).toBe(true);
  expect(isLogicReasoningProject("default")).toBe(false);
  expect(isLogicReasoningProject("demo-arid-ecology")).toBe(false);
  expect(isLogicReasoningProject(undefined)).toBe(false);
});
