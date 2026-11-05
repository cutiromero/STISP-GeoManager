import { agentApi } from "../api/agent";
import { requestJson } from "../api/client";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
  QueryResponse,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import { geologyReviewOutcome } from "../agent/geologyReviewOutcome";
import { getActiveProject, projectSignal } from "../projects/session";
import {
  previewSuggestions,
  queryReviewMapResult,
  reviewResourceIds,
  record,
  colorReviewMap,
  reviewBounds,
} from "./geologyReviewData";
import {
  actualTourChanges,
  featureCollection,
  type TourChange,
} from "./multiElementTour";
import type { ReviewOverlay } from "./reviewVectorLayers";
import { isMultiElementFamily } from "../agent/multiElementScenario";
import {
  queryWorkflowVectors,
  usesCleanGeologyResults,
} from "./workflowOutputMaps";

export type ComparisonRole = "before" | "after" | "changes";
export function comparisonFeatureKey(
  feature: GeoJsonFeatureCollection["features"][number],
) {
  const p = feature.properties;
  if (
    p.issue_id !== undefined &&
    p.issue_id !== null &&
    String(p.issue_id).trim()
  )
    return `issue:${p.issue_id}`;
  if (
    p.feature_id !== undefined &&
    p.feature_id !== null &&
    String(p.feature_id).trim() &&
    String(p.rule_id ?? p.kind ?? "").trim() &&
    String(p.suggested_action ?? p.action ?? p.kind ?? "").trim()
  )
    return `${p.feature_id}:${p.rule_id ?? p.kind ?? ""}:${p.suggested_action ?? p.action ?? ""}`;
  return null;
}
export type ComparisonLayerPlacement = {
  workflowId: string;
  title: string;
  roles: ComparisonRole[];
  element: string;
  displayData?: GeoJsonFeatureCollection;
};

export interface WorkbenchReviewComparison {
  workflow: AgentWorkflow;
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  beforeName: string;
  afterName: string;
  overlays?: ReviewOverlay[];
  tour?: TourChange[];
  loadOverlays?: (key?: string) => Promise<ReviewOverlay[]>;
  pagination?: AgentWorkflow["plan"]["pagination"];
  loadChanges?: (
    offset: number,
  ) => Promise<
    Pick<
      WorkbenchReviewComparison,
      "workflow" | "tour" | "differences" | "pagination"
    >
  >;
}

export type RegisterReviewLayer = (
  profile: ResourceProfileResponse,
  result: QueryResponse,
  placement?: ComparisonLayerPlacement,
) => Promise<void>;

export async function loadWorkbenchReviewComparison(options: {
  workflowId: string;
  projectId: string;
  projectTagId: string | null;
  registerLayer: RegisterReviewLayer;
  isCurrent?: () => boolean;
  onPrimary?: (value: WorkbenchReviewComparison) => void;
  deferOverlays?: boolean;
  suggestionId?: string;
}): Promise<WorkbenchReviewComparison> {
  const signal = projectSignal();
  const assertCurrent = () => {
    if (
      signal.aborted ||
      getActiveProject() !== options.projectId ||
      options.isCurrent?.() === false
    )
      throw new DOMException("已停止读取此前项目的检查成果", "AbortError");
  };
  assertCurrent();
  if (options.projectTagId && options.projectTagId !== options.projectId)
    throw new Error("请切换到检查任务所属项目后查看");
  const workflow = await agentApi.workflow(options.workflowId, {
    view: "compare",
    signal,
    suggestionId: options.suggestionId,
  });
  assertCurrent();
  if (
    !(
      workflow.workflowType === "geology_map_review" ||
      isMultiElementFamily(workflow.workflowType)
    )
  )
    throw new Error("此入口用于地质成果智能检查与修正，请打开对应案例");
  if (String(workflow.projectId) !== options.projectId)
    throw new Error("检查任务不属于当前项目，请切换项目后查看");
  const reads = new Map<
    number,
    Promise<{ profile: ResourceProfileResponse; result: QueryResponse }>
  >();
  const read = (id: number, mixed = false, allowEmpty = false) => {
    if (!reads.has(id))
      reads.set(
        id,
        (async () => {
          assertCurrent();
          const [profile, result] = await Promise.all([
            requestJson<ResourceProfileResponse>(
              `/api/catalog/resources/${id}/profile/`,
            ),
            queryReviewMapResult(id, {
              mixed,
              allowEmpty,
              loadStyle: false,
              displayGeometry: isMultiElementFamily(workflow.workflowType),
            }),
          ]);
          assertCurrent();
          if (profile.resource.id !== id || !profile.resource.isQueryable)
            throw new Error("检查成果元信息不一致或不支持地图查询");
          colorReviewMap(result.geojson, profile.defaultVisualization ?? {});
          return { profile, result };
        })().catch((error: unknown) => {
          reads.delete(id);
          throw error;
        }),
      );
    return reads.get(id)!;
  };
  const register = async (
    id: number,
    roles: ComparisonRole[],
    element: string,
    displayData?: GeoJsonFeatureCollection,
  ) => {
    const item = await read(id, true, true);
    await options.registerLayer(item.profile, item.result, {
      workflowId: workflow.id,
      title:
        workflow.workflowType === "geology_multi_element_reasoning"
          ? "海德乌拉综合推理"
          : workflow.workflowType === "geology_generic"
            ? "地质综合推理"
            : "地质成果检查修正",
      roles,
      element,
      displayData,
    });
    assertCurrent();
  };
  if (isMultiElementFamily(workflow.workflowType)) {
    const map = workflow.plan.multiElementMap;
    if (!map?.before?.lithology || !map.before.faults)
      throw new Error("综合推理记录缺少本次岩性和构造输入");
    const beforeInputs = map.before;
    if (map.after && !workflow.modificationReview?.approvedSuggestionIds.length)
      throw new Error("修正成果缺少已保存的批准记录，请先核对任务状态");
    const check = (
      Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
    )
      .map(record)
      .find((stage) => stage.name === "check");
    const outputs = Array.isArray(check?.outputs)
      ? check.outputs.map(record)
      : [];
    const beforeAlterations =
      map.beforeAlterations ??
      (Number(
        outputs.find((output) => output.key === "alterations")?.resourceId,
      ) ||
        undefined);
    const roles = new Map<
      number,
      { roles: ComparisonRole[]; element: string }
    >();
    const add = (
      id: number | undefined,
      role: ComparisonRole,
      element: string,
    ) => {
      if (!id) return;
      const item = roles.get(id) ?? { roles: [], element };
      if (!item.roles.includes(role)) item.roles.push(role);
      roles.set(id, item);
    };
    add(map.before.lithology, "before", "岩性");
    add(map.before.faults, "before", "构造");
    add(beforeAlterations, "before", "矿物");
    add(map.beforeIntersections, "before", "构造交汇");
    add(map.beforeProspects, "before", "调查建议");
    add(map.after?.lithology, "after", "岩性");
    add(map.after?.faults, "after", "构造");
    add(map.alterations, "after", "矿物");
    add(map.intersections, "after", "构造交汇");
    add(map.afterProspects, "after", "调查建议");
    (map.changes ?? []).forEach((id) => add(id, "changes", "修改范围"));
    const [primaryBefore, primaryAfter] = await Promise.all([
      read(map.before.lithology, true),
      map.after?.lithology
        ? read(map.after.lithology, true)
        : Promise.resolve(null),
    ]);
    assertCurrent();
    options.onPrimary?.({
      workflow,
      before: primaryBefore.result.geojson,
      after: primaryAfter?.result.geojson ?? null,
      differences: featureCollection([]),
      beforeName: primaryBefore.profile.resource.name,
      afterName: primaryAfter?.profile.resource.name ?? "检查方案，尚未执行",
    });
    await Promise.all([
      register(map.before.lithology, ["before"], "岩性"),
      ...(map.after?.lithology
        ? [register(map.after.lithology, ["after"], "岩性")]
        : []),
    ]);
    const collection = async (id?: number) =>
      id ? (await read(id, true, true)).result.geojson : featureCollection([]);
    const loadChanges = async (offset: number) => {
      const page = await agentApi.workflow(options.workflowId, {
        view: "compare",
        offset,
        limit: 25,
        signal,
        suggestionId:
          Number(record(workflow.plan.pagination).total) === 0
            ? options.suggestionId
            : undefined,
      });
      assertCurrent();
      if (page.planHash !== workflow.planHash)
        throw new Error("成果已更新，请刷新对比页");
      const features = page.plan.compareFeatures as
        | GeoJsonFeatureCollection
        | undefined;
      const tour = actualTourChanges(page, features ?? featureCollection([]));
      const differences = featureCollection(tour.map((item) => item.feature));
      await Promise.all(
        (map.changes ?? []).map(async (id) => {
          const profile = await requestJson<ResourceProfileResponse>(
            `/api/catalog/resources/${id}/profile/`,
          );
          assertCurrent();
          const geojson = featureCollection(
            differences.features.filter(
              (feature) => feature.properties.display_resource_id === id,
            ),
          );
          await options.registerLayer(
            profile,
            {
              resourceId: id,
              resourceName: profile.resource.name,
              geojson,
              fields: profile.fields,
              totalCount: geojson.features.length,
              returnedCount: geojson.features.length,
              limit: 25,
              limitExceeded: false,
              elapsedMs: 0,
              warnings: [],
              bounds: reviewBounds(geojson) ?? [],
            },
            {
              workflowId: workflow.id,
              title: "地质推理成果",
              roles: ["changes"],
              element: "修改范围",
              displayData: geojson,
            },
          );
        }),
      );
      return {
        workflow: page,
        tour,
        differences,
        pagination: page.plan
          .pagination as WorkbenchReviewComparison["pagination"],
      };
    };
    const before = await read(map.before.lithology, true),
      after = map.after?.lithology
        ? await read(map.after.lithology, true)
        : null;
    const loadOverlays = async (key?: string): Promise<ReviewOverlay[]> => {
      const elements: Record<string, string> = {
        faults: "构造",
        alterations: "矿物",
        intersections: "构造交汇",
        prospects: "调查建议",
      };
      const needed = [...roles].filter(
        ([, placement]) =>
          !placement.roles.includes("changes") &&
          placement.element !== "岩性" &&
          (!key || placement.element === elements[key]),
      );
      await Promise.all(needed.map(([id]) => read(id, true, true)));
      for (const [id, placement] of needed) {
        await register(id, placement.roles, placement.element);
      }
      const loaders: Array<() => Promise<ReviewOverlay>> = [
        async () => ({
          key: "faults",
          label: "构造",
          before: await collection(beforeInputs.faults),
          after: await collection(
            map.after?.faults ??
              (usesCleanGeologyResults(workflow) && map.after
                ? undefined
                : beforeInputs.faults),
          ),
          color: "#76566d",
        }),
        async () => ({
          key: "alterations",
          label: "有效蚀变",
          before: beforeAlterations
            ? await collection(beforeAlterations)
            : await queryWorkflowVectors(workflow, "check", ["alterations"]),
          after: await collection(map.alterations),
          color: "#648e91",
        }),
        async () => ({
          key: "intersections",
          label: "构造交汇",
          before: map.beforeIntersections
            ? await collection(map.beforeIntersections)
            : await queryWorkflowVectors(workflow, "relations", [
                "before_intersections",
              ]),
          after: await collection(map.intersections),
          color: "#b4526e",
        }),
        async () => ({
          key: "prospects",
          label: "调查建议",
          before: await collection(map.beforeProspects),
          after: await collection(map.afterProspects),
          color: "#537fc0",
        }),
      ];
      return Promise.all(
        loaders
          .filter(
            (_, index) =>
              !key ||
              ["faults", "alterations", "intersections", "prospects"][index] ===
                key,
          )
          .map((loader) => loader()),
      );
    };
    const overlayPromises = new Map<string, Promise<ReviewOverlay[]>>();
    const cachedOverlays = (key?: string): Promise<ReviewOverlay[]> => {
      const identity = key ?? "all";
      if (!overlayPromises.has(identity))
        overlayPromises.set(
          identity,
          (key
            ? loadOverlays(key)
            : Promise.all(
                ["faults", "alterations", "intersections", "prospects"].map(
                  (item) => cachedOverlays(item),
                ),
              ).then((items) => items.flat())
          ).catch((error: unknown) => {
            overlayPromises.delete(identity);
            throw error;
          }),
        );
      return overlayPromises.get(identity)!;
    };
    return {
      workflow,
      before: before.result.geojson,
      after: after?.result.geojson ?? null,
      differences: featureCollection([]),
      beforeName: before.profile.resource.name,
      afterName: after?.profile.resource.name ?? "检查方案，尚未执行",
      overlays: options.deferOverlays ? undefined : await cachedOverlays(),
      loadOverlays: cachedOverlays,
      pagination: workflow.plan
        .pagination as WorkbenchReviewComparison["pagination"],
      loadChanges,
    };
  }
  const ids = reviewResourceIds(workflow);
  const outcome = geologyReviewOutcome(workflow);
  if (!ids.before) throw new Error("检查记录尚无可用的待检查地质图");
  if (outcome && (ids.after || ids.differences))
    throw new Error("检查记录与修正成果不一致，请核对任务状态");
  if (
    (ids.after || ids.differences) &&
    !workflow.modificationReview?.approvedSuggestionIds.length
  )
    throw new Error("修正成果缺少已保存的批准记录，请先核对任务状态");
  if (Boolean(ids.after) !== Boolean(ids.differences))
    throw new Error("修正结果与实际修改范围尚未全部就绪，请稍后刷新");
  const before = await read(ids.before);
  const after = ids.after ? await read(ids.after) : null;
  const actual = ids.differences
    ? await read(ids.differences, false, true)
    : null;
  await register(ids.before, ["before"], "地质图");
  if (ids.after) await register(ids.after, ["after"], "地质图");
  if (ids.differences) await register(ids.differences, ["changes"], "修改范围");
  return {
    workflow,
    before: before.result.geojson,
    after: after?.result.geojson ?? null,
    differences: outcome
      ? { type: "FeatureCollection", features: [] }
      : (actual?.result.geojson ?? previewSuggestions(workflow)),
    beforeName: before.profile.resource.name,
    afterName: after?.profile.resource.name ?? "建议修改范围，尚未执行",
  };
}
