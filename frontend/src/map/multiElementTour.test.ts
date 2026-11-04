import { expect, it } from "vitest";
import type {
  AgentModificationSuggestion,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { beforeReviewMap, reviewWorkflow } from "./geologyReview.testFixtures";
import {
  actualTourChanges,
  featureCollection,
  prospectChanges,
  prospectSignature,
  tourAlgorithm,
  tourLabels,
} from "./multiElementTour";

const feature = beforeReviewMap.features[0]!;
function fixture() {
  const workflow = reviewWorkflow();
  const actions = ["set_code", "exclude", "downweight", "keep"];
  const suggestions = actions.map(
    (action, index): AgentModificationSuggestion => ({
      ...workflow.modificationReview!.suggestions[0]!,
      id: `suggestion-${index}`,
      featureId: `object-${index}`,
      kind: "multi_element",
      action,
      ruleId: `rule-${index}`,
      element:
        index === 1 ? "structure" : index === 2 ? "alteration" : "lithology",
    }),
  );
  workflow.modificationReview = {
    proposalHash: "frozen",
    suggestions,
    approvedSuggestionIds: suggestions.slice(0, 3).map((item) => item.id),
  };
  workflow.plan.stages = [
    {
      name: "apply",
      status: "completed",
      identifier: "real-algorithm",
      taskId: "actual-task",
      approvedEdits: suggestions.map((item) => ({
        feature_id: item.featureId,
        rule_id: item.ruleId,
        action: item.action,
        target_code: item.action === "set_code" ? "T₃b" : "",
        weight: item.action === "downweight" ? 0.5 : 1,
      })),
      results: [
        {
          key: "changes",
          taskId: "actual-task",
          outputId: 286,
          checksum: "a".repeat(64),
          scope: "all",
          rowCount: suggestions.length,
          rows: suggestions.map((item) => ({
            feature_id: item.featureId,
            rule_id: item.ruleId,
            action: item.action,
            target_code: item.action === "set_code" ? "T₃b" : "",
            weight: item.action === "downweight" ? "0.5" : "1.0",
            actual_changed: item.action !== "keep" ? "True" : "False",
            old_code: "Q",
            new_code: "T₃b",
          })),
        },
      ],
    },
  ];
  workflow.plan.algorithms = {
    "real-algorithm": { name: "实际修改算法", manifest: { version: "1.0.1" } },
  };
  const differences = featureCollection(
    suggestions.map((item) => ({
      ...feature,
      properties: {
        feature_id: item.featureId,
        rule_id: item.ruleId,
        suggested_action: item.action,
        target_code: item.action === "set_code" ? "T₃b" : "",
      },
    })),
  );
  return { workflow, differences };
}

it("导览仅显示实际执行、已批准并与冻结操作一致的变化，排除保留及重复记录", () => {
  const { workflow, differences } = fixture();
  differences.features.push(differences.features[0]!);
  expect(
    actualTourChanges(workflow, differences).map((item) => item.action),
  ).toEqual(["set_code", "exclude", "downweight"]);
  workflow.modificationReview!.approvedSuggestionIds = ["suggestion-0"];
  expect(actualTourChanges(workflow, differences)).toHaveLength(1);
  workflow.plan.stages = [];
  expect(actualTourChanges(workflow, differences)).toHaveLength(0);
});

it("从完整实际变更表匹配几何，保留任务、文件和行定位，不把空间疑点当成已执行结果", () => {
  const { workflow, differences } = fixture();
  expect(differences.features[0]!.properties.actual_changed).toBeUndefined();
  const changes = actualTourChanges(workflow, differences);
  expect(changes).toHaveLength(3);
  expect(changes[0]!.feature.geometry).toBe(differences.features[0]!.geometry);
  expect(changes[0]!.feature.properties).toMatchObject({
    action: "set_code",
    old_code: "Q",
    new_code: "T₃b",
    actual_changed: "True",
  });
  expect(changes[0]!.resultRef).toEqual({
    taskId: "actual-task",
    outputId: 286,
    checksum: "a".repeat(64),
    rowIndex: 1,
  });
  const stages = workflow.plan.stages as Array<Record<string, unknown>>;
  stages[0]!.results = [];
  differences.features[0]!.properties.actual_changed = true;
  expect(actualTourChanges(workflow, differences)).toHaveLength(0);
});

it("拒绝未完成、抽样、截断、异任务、重复结果和与获批参数不同的处置", () => {
  for (const patch of [
    { scope: "representative_sample" },
    { rowCount: 99 },
    { taskId: "unrelated-task" },
    { checksum: "missing" },
  ]) {
    const { workflow, differences } = fixture();
    const stage = (workflow.plan.stages as Array<Record<string, unknown>>)[0]!;
    const results = stage.results as Array<Record<string, unknown>>;
    Object.assign(results[0]!, patch);
    expect(actualTourChanges(workflow, differences)).toHaveLength(0);
  }
  const { workflow, differences } = fixture();
  const stage = (workflow.plan.stages as Array<Record<string, unknown>>)[0]!;
  const result = (stage.results as Array<Record<string, unknown>>)[0]!;
  const rows = result.rows as Array<Record<string, unknown>>;
  rows.push({ ...rows[0] });
  result.rowCount = rows.length;
  expect(actualTourChanges(workflow, differences)).toHaveLength(2);
  rows.pop();
  result.rowCount = rows.length;
  rows[2]!.weight = "0.25";
  rows[0]!.new_code = "different";
  expect(
    actualTourChanges(workflow, differences).map((item) => item.action),
  ).toEqual(["exclude"]);
  stage.status = "running";
  expect(actualTourChanges(workflow, differences)).toHaveLength(0);
});

it("代号和权重由实际输入输出读取，不猜测矿物原权重", () => {
  const { workflow, differences } = fixture();
  const changes = actualTourChanges(workflow, differences);
  expect(tourLabels(changes[0]!).before).toBe("Q");
  expect(tourLabels(changes[0]!).after).toBe("T₃b");
  const mineral = changes[2]!;
  expect(tourLabels(mineral).before).toBe("证据权重 原记录未提供");
  expect(tourLabels(mineral, undefined, undefined, true).before).toBe(
    "证据权重 读取中…",
  );
  expect(
    tourLabels(
      mineral,
      { ...feature, properties: { weight: 0.8 } },
      { ...feature, properties: { weight: 0.3 } },
    ),
  ).toMatchObject({ before: "证据权重 0.8", after: "证据权重 0.3" });
  expect(tourAlgorithm(workflow)).toEqual({
    name: "实际修改算法",
    version: "1.0.1",
    taskId: "actual-task",
  });
});

it("核查区匹配真实几何和等级，不因编号、环起点或环方向改变而误报", () => {
  const one = structuredClone(feature);
  one.properties = { grade: "B", zone_id: "B001", area_km2: 2 };
  one.geometry = {
    type: "Polygon",
    coordinates: [
      [
        [1, 1],
        [2, 1],
        [2, 2],
        [1, 1],
      ],
    ],
  };
  const same = structuredClone(one);
  same.properties.zone_id = "B002";
  same.geometry = {
    type: "Polygon",
    coordinates: [
      [
        [2, 2],
        [2, 1],
        [1, 1],
        [2, 2],
      ],
    ],
  };
  expect(prospectSignature(one)).toBe(prospectSignature(same));
  const changed = structuredClone(one);
  changed.properties.area_km2 = 0.65;
  changed.geometry = {
    type: "Polygon",
    coordinates: [
      [
        [3, 1],
        [4, 1],
        [4, 2],
        [3, 1],
      ],
    ],
  };
  const result = prospectChanges(
    featureCollection([one, changed]),
    featureCollection([same]),
  );
  expect(result.before.features).toEqual([changed]);
  expect(result.after.features).toEqual([]);
  expect(result.grades).toEqual([
    {
      grade: "B",
      before: { count: 2, area: 2.65 },
      after: { count: 1, area: 2 },
    },
  ]);
  same.properties.grade = "A";
  expect(prospectSignature(one)).not.toBe(prospectSignature(same));
});

it("统计保留同形重复对象的数量，缺少真实面积时不给出估算值", () => {
  const zone = { ...feature, properties: { grade: "A" } };
  const before: GeoJsonFeatureCollection = featureCollection([zone, zone]);
  const result = prospectChanges(before, featureCollection([zone]));
  expect(result.before.features).toHaveLength(1);
  expect(result.grades[0]!.before.area).toBeNull();
});
