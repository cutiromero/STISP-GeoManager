import type {
  AgentModificationSuggestion,
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { record, reviewBounds } from "./geologyReviewData";

type Feature = GeoJsonFeatureCollection["features"][number];
export type TourChange = {
  key: string;
  feature: Feature;
  suggestion: AgentModificationSuggestion;
  action: string;
  resultRef: {
    taskId: string;
    outputId: number;
    checksum: string;
    rowIndex: number;
  };
};
export const featureCollection = (
  features: Feature[],
): GeoJsonFeatureCollection => ({
  type: "FeatureCollection",
  features,
});

export function actualTourChanges(
  workflow: AgentWorkflow,
  differences: GeoJsonFeatureCollection,
): TourChange[] {
  const review = workflow.modificationReview;
  const approved = new Set(review?.approvedSuggestionIds ?? []);
  const apply = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  )
    .map(record)
    .find((stage) => stage.name === "apply");
  const edits = Array.isArray(apply?.approvedEdits)
    ? apply.approvedEdits.map(record)
    : [];
  // The three spatial change outputs preserve issue geometry. Execution facts
  // come from the complete persisted CSV result, not those suggested actions.
  const result = (Array.isArray(apply?.results) ? apply.results : [])
    .map(record)
    .find((item) => item.key === "changes" && item.taskId === apply?.taskId);
  const rows = Array.isArray(result?.rows) ? result.rows.map(record) : [];
  if (
    apply?.status !== "completed" ||
    !apply.taskId ||
    result?.scope !== "all" ||
    result.rowCount !== rows.length ||
    !Number.isSafeInteger(result.outputId) ||
    Number(result.outputId) <= 0 ||
    !/^[a-f0-9]{64}$/.test(String(result.checksum))
  )
    return [];
  const sameId = (a: unknown, b: unknown) =>
    a !== undefined && a !== null && String(a) === String(b);
  const changed = (value: unknown) =>
    value === true ||
    value === 1 ||
    (typeof value === "string" && /^(?:true|1(?:\.0+)?)$/i.test(value.trim()));
  const seen = new Set<string>();
  return differences.features.flatMap((feature) => {
    const p = feature.properties;
    const matches = rows.flatMap((row, index) =>
      sameId(row.feature_id, p.feature_id) &&
      sameId(row.rule_id, p.rule_id) &&
      row.action === (p.suggested_action ?? p.action) &&
      changed(row.actual_changed) &&
      (!p.issue_id || sameId(row.issue_id, p.issue_id))
        ? [{ row, index }]
        : [],
    );
    if (matches.length !== 1) return [];
    const { row, index } = matches[0]!;
    const suggestion = review?.suggestions.find(
      (item) =>
        approved.has(item.id) &&
        sameId(item.featureId, row.feature_id) &&
        sameId(item.ruleId, row.rule_id) &&
        item.action === row.action,
    );
    if (
      !suggestion ||
      !edits.some(
        (edit) =>
          sameId(edit.feature_id, row.feature_id) &&
          sameId(edit.rule_id, row.rule_id) &&
          edit.action === row.action &&
          String(edit.target_code ?? "") === String(row.target_code ?? "") &&
          Number.isFinite(Number(edit.weight)) &&
          Number(edit.weight) === Number(row.weight) &&
          (!edit.snapshot_hash || edit.snapshot_hash === row.snapshot_hash) &&
          (!["set_code", "reclassify", "merge"].includes(String(row.action)) ||
            (Boolean(edit.target_code) && row.new_code === edit.target_code)),
      ) ||
      seen.has(suggestion.id)
    )
      return [];
    seen.add(suggestion.id);
    return [
      {
        key: suggestion.id,
        feature: { ...feature, properties: { ...p, ...row } },
        suggestion,
        action: String(row.action),
        resultRef: {
          taskId: String(result.taskId),
          outputId: Number(result.outputId),
          checksum: String(result.checksum),
          rowIndex: index + 1,
        },
      },
    ];
  });
}

export function tourAlgorithm(workflow: AgentWorkflow) {
  const stage = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  )
    .map(record)
    .find((value) => value.name === "apply");
  const algorithm = record(
    record(workflow.plan.algorithms)[String(stage?.identifier)],
  );
  return {
    name: String(algorithm.name ?? stage?.identifier ?? "本次修改算法"),
    version: String(record(algorithm.manifest).version ?? ""),
    taskId: String(stage?.taskId ?? ""),
  };
}

export function tourFeature(
  data: GeoJsonFeatureCollection | null | undefined,
  change: TourChange,
) {
  return (
    data?.features.find(
      (feature) =>
        String(
          feature.properties.feature_id ??
            feature.properties.line_id ??
            feature.id,
        ) === change.suggestion.featureId,
    ) ??
    (change.action === "merge" &&
    String(change.feature.properties.host_feature_id ?? "").trim()
      ? data?.features.find(
          (feature) =>
            String(feature.properties.feature_id ?? feature.id) ===
            String(change.feature.properties.host_feature_id),
        )
      : undefined)
  );
}

export function tourLabels(
  change: TourChange,
  before?: Feature,
  after?: Feature,
  loading = false,
) {
  const p = change.feature.properties;
  const weight = (feature: Feature | undefined, fallback?: unknown) => {
    const value = feature?.properties.weight ?? fallback;
    if (value !== undefined && value !== null && value !== "")
      return String(value);
    // A layer still being read must not look like missing evidence.
    return loading ? "读取中…" : "原记录未提供";
  };
  switch (change.action) {
    case "reclassify":
    case "merge":
      return {
        title: change.action === "merge" ? "同单元图斑整理" : "岩性类别修正",
        before: String(
          before?.properties.geo_sym ??
            p.old_code ??
            change.suggestion.currentState,
        ),
        after: String(
          after?.properties.geo_sym ??
            p.new_code ??
            change.suggestion.suggestedState,
        ),
        note: change.suggestion.reason,
      };
    case "set_code":
      return {
        title: "地质代号修正",
        before: String(before?.properties.geo_sym ?? p.old_code ?? "未记录"),
        after: String(after?.properties.geo_sym ?? p.new_code ?? "未记录"),
        note: "名称与代号不一致，按本案例对照知识修正。",
      };
    case "exclude":
      return {
        title: "构造处置",
        before: "原构造线",
        after: "本轮不参与分析",
        note: "保留原记录，本轮不参与分析。",
      };
    case "downweight":
      return {
        title: "矿物证据降权",
        before: `证据权重 ${weight(before)}`,
        after: `证据权重 ${weight(after, p.weight)}`,
        note: "可能受到岩石背景影响，仍保留待核查。",
      };
    default:
      return {
        title: "获批修改",
        before: String(p.old_code || change.suggestion.currentState),
        after: String(p.new_code || change.suggestion.suggestedState),
        note: change.suggestion.reason,
      };
  }
}

function canonical(value: unknown): string {
  if (!Array.isArray(value)) return JSON.stringify(value);
  // Ring start positions and direction do not change a polygon footprint.
  if (Array.isArray(value[0]) && typeof value[0][0] === "number") {
    const points = value.map((item) => JSON.stringify(item));
    if (points.length > 1 && points[0] === points[points.length - 1]) {
      points.pop();
      const smallest = points.reduce((a, b) => (a < b ? a : b));
      const rotations = (items: string[]) =>
        items.flatMap((point, i) =>
          point === smallest
            ? [[...items.slice(i), ...items.slice(0, i)].join(",")]
            : [],
        );
      return `[${[...rotations(points), ...rotations([...points].reverse())].sort()[0]}]`;
    }
    return `[${points.join(",")}]`;
  }
  return `[${value.map(canonical).sort().join(",")}]`;
}

export function prospectSignature(feature: Feature) {
  return `${feature.properties.grade}:${canonical(record(feature.geometry).coordinates)}`;
}

export function prospectChanges(
  before: GeoJsonFeatureCollection,
  after: GeoJsonFeatureCollection,
) {
  const remaining = (
    source: GeoJsonFeatureCollection,
    target: GeoJsonFeatureCollection,
  ) => {
    const identities = new Map<string, number>();
    target.features.forEach((feature) => {
      const key = prospectSignature(feature);
      identities.set(key, (identities.get(key) ?? 0) + 1);
    });
    return featureCollection(
      source.features.filter((feature) => {
        const key = prospectSignature(feature),
          count = identities.get(key) ?? 0;
        if (!count) return true;
        identities.set(key, count - 1);
        return false;
      }),
    );
  };
  const changedBefore = remaining(before, after),
    changedAfter = remaining(after, before);
  const grades = [
    ...new Set(
      [...before.features, ...after.features].map((f) =>
        String(f.properties.grade),
      ),
    ),
  ].sort();
  const stats = (collection: GeoJsonFeatureCollection, grade: string) => {
    const features = collection.features.filter(
      (f) => f.properties.grade === grade,
    );
    const areas = features.map((f) => Number(f.properties.area_km2));
    return {
      count: features.length,
      area: areas.every(Number.isFinite)
        ? areas.reduce((sum, area) => sum + area, 0)
        : null,
    };
  };
  return {
    before: changedBefore,
    after: changedAfter,
    bounds: reviewBounds(
      featureCollection([...changedBefore.features, ...changedAfter.features]),
    ),
    grades: grades.map((grade) => ({
      grade,
      before: stats(before, grade),
      after: stats(after, grade),
    })),
  };
}
