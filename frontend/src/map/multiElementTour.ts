import type {
  AgentModificationSuggestion,
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { record, reviewBounds } from "./geologyReviewData";

type Feature = GeoJsonFeatureCollection["features"][number];
const sameId = (a: unknown, b: unknown) =>
  a !== undefined && a !== null && String(a) === String(b);
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
  const changed = (value: unknown) =>
    value === true ||
    value === 1 ||
    (typeof value === "string" && /^(?:true|1(?:\.0+)?)$/i.test(value.trim()));
  const seen = new Set<string>();
  const key = (featureId: unknown, ruleId: unknown, action: unknown) =>
    JSON.stringify([String(featureId), String(ruleId), action]);
  const rowIndex = new Map<
    string,
    Array<{ row: Record<string, unknown>; index: number }>
  >();
  rows.forEach((row, index) => {
    if (!changed(row.actual_changed)) return;
    const identity = key(row.feature_id, row.rule_id, row.action);
    const bucket = rowIndex.get(identity) ?? [];
    bucket.push({ row, index });
    rowIndex.set(identity, bucket);
  });
  const suggestionIndex = new Map<
    string,
    NonNullable<typeof review>["suggestions"][number]
  >();
  for (const item of review?.suggestions ?? []) {
    const identity = key(item.featureId, item.ruleId, item.action);
    if (approved.has(item.id) && !suggestionIndex.has(identity))
      suggestionIndex.set(identity, item);
  }
  const editIndex = new Map<string, typeof edits>();
  for (const edit of edits) {
    const identity = key(edit.feature_id, edit.rule_id, edit.action);
    const bucket = editIndex.get(identity) ?? [];
    bucket.push(edit);
    editIndex.set(identity, bucket);
  }
  return differences.features.flatMap((feature) => {
    const p = feature.properties;
    const identity = key(
      p.feature_id,
      p.rule_id,
      p.action ?? p.suggested_action,
    );
    const matches = (rowIndex.get(identity) ?? []).filter(
      ({ row }) =>
        sameId(row.feature_id, p.feature_id) &&
        sameId(row.rule_id, p.rule_id) &&
        row.action === (p.action ?? p.suggested_action) &&
        changed(row.actual_changed) &&
        (!p.issue_id || sameId(row.issue_id, p.issue_id)),
    );
    if (matches.length !== 1) return [];
    const { row, index } = matches[0]!;
    const suggestion = suggestionIndex.get(identity);
    if (
      !suggestion ||
      !(editIndex.get(identity) ?? []).some(
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
          rowIndex: Number(row._rowIndex ?? index + 1),
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
    (["merge", "reclassify", "set_code"].includes(change.action) &&
    String(change.feature.properties.host_feature_id ?? "").trim()
      ? data?.features.find(
          (feature) =>
            String(feature.properties.feature_id ?? feature.id) ===
            String(change.feature.properties.host_feature_id),
        )
      : undefined)
  );
}

export function isArchivePartition(change: TourChange) {
  return (
    change.action === "reclassify" &&
    change.suggestion.ruleId === "L-08" &&
    (change.feature.properties.archive_partition === true ||
      change.suggestion.observations?.scope === "anchored_cell_partition")
  );
}

/** The approval preview can cover more than the actually changed cells. */
export async function loadArchiveChangeGeometry(
  collection: GeoJsonFeatureCollection,
  load: (resourceId: number) => Promise<GeoJsonFeatureCollection>,
) {
  const requests = new Map<number, Promise<GeoJsonFeatureCollection>>();
  const features = await Promise.all(
    collection.features.map(async (feature) => {
      const p = feature.properties;
      if (p.archive_partition !== true) return feature;
      const resourceId = Number(p.display_resource_id);
      if (!Number.isSafeInteger(resourceId) || resourceId <= 0)
        return {
          ...feature,
          properties: { ...p, actual_geometry_unavailable: true },
        };
      if (!requests.has(resourceId)) requests.set(resourceId, load(resourceId));
      try {
        const map = await requests.get(resourceId)!;
        const approved = map.features.filter(
          ({ properties: row }) =>
            sameId(row.issue_id, p.issue_id) &&
            sameId(row.feature_id, p.feature_id) &&
            sameId(row.rule_id, p.rule_id),
        );
        if (approved.length === 1)
          return {
            ...feature,
            geometry: approved[0]!.geometry,
            properties: { ...p, actual_geometry: true },
          };
      } catch {
        // The task remains readable if an old spatial output is no longer available.
      }
      return {
        ...feature,
        properties: { ...p, actual_geometry_unavailable: true },
      };
    }),
  );
  return featureCollection(features);
}

function archiveUnit(change: TourChange, code: string) {
  const labels = record(change.feature.properties.lithology_unit_labels);
  const unit = record(labels[code]);
  const symbol =
    typeof unit.display_symbol === "string" ? unit.display_symbol.trim() : "";
  const name = typeof unit.name === "string" ? unit.name.trim() : "";
  return {
    code,
    label:
      name && symbol
        ? `${name}（${symbol}）`
        : name || symbol || `分类编号 ${code}`,
    mapLabel: symbol || code,
  };
}

export function archivePartitionDetails(change: TourChange) {
  const p = change.feature.properties;
  const observations = change.suggestion.observations ?? {};
  const before = archiveUnit(
    change,
    String(p.old_code ?? observations.observed_code ?? ""),
  );
  const rows = Array.isArray(observations.archive_local_targets)
    ? observations.archive_local_targets.map(record)
    : [];
  const targets = String(p.new_code ?? "")
    .split("/")
    .map((word) => word.trim())
    .filter(Boolean)
    .map((code) => {
      const pixels = Number(rows.find((value) => value.code === code)?.pixels);
      return {
        ...archiveUnit(change, code),
        pixels: Number.isSafeInteger(pixels) && pixels > 0 ? pixels : undefined,
      };
    });
  return { before, targets };
}

export function tourLabels(
  change: TourChange,
  before?: Feature,
  after?: Feature,
  loading = false,
) {
  const p = change.feature.properties;
  if (isArchivePartition(change)) {
    const partition = archivePartitionDetails(change);
    return {
      title: "归档对照 · 局部岩性改类",
      before: partition.before.mapLabel,
      after: partition.targets.map((unit) => unit.mapLabel).join(" / "),
      note: "归档分类是早期模型结果。对照用于发现分歧和核查局部接触关系，结论仍需结合原始影像和实地资料。",
    };
  }
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
          before?.properties.display_symbol ??
            before?.properties.geo_sym ??
            p.old_code ??
            change.suggestion.currentState,
        ),
        after: String(
          after?.properties.display_symbol ??
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
        title:
          change.suggestion.element === "alteration" ? "蚀变剔除" : "构造处置",
        before:
          change.suggestion.element === "alteration"
            ? "原蚀变图斑"
            : "原构造线",
        after: "已从最终成果删除",
        note: "最终成果不包含获批剔除对象；原始资料与修改记录保留。",
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
