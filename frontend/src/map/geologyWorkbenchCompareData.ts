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
} from "./geologyReviewData";

export interface WorkbenchReviewComparison {
  workflow: AgentWorkflow;
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  beforeName: string;
  afterName: string;
}

export type RegisterReviewLayer = (
  profile: ResourceProfileResponse,
  result: QueryResponse,
) => Promise<void>;

export async function loadWorkbenchReviewComparison(options: {
  workflowId: string;
  projectId: string;
  projectTagId: string | null;
  registerLayer: RegisterReviewLayer;
  isCurrent?: () => boolean;
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
  const workflow = await agentApi.workflow(options.workflowId);
  assertCurrent();
  if (workflow.workflowType !== "geology_map_review")
    throw new Error("此入口用于地质成果智能检查与修正，请打开对应案例");
  if (String(workflow.projectId) !== options.projectId)
    throw new Error("检查任务不属于当前项目，请切换项目后查看");
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
  const read = async (id: number, allowEmpty = false) => {
    assertCurrent();
    const [profile, result] = await Promise.all([
      requestJson<ResourceProfileResponse>(
        `/api/catalog/resources/${id}/profile/`,
      ),
      queryReviewMapResult(id, { allowEmpty }),
    ]);
    assertCurrent();
    if (profile.resource.id !== id || !profile.resource.isQueryable)
      throw new Error("检查成果元信息不一致或不支持地图查询");
    await options.registerLayer(profile, result);
    assertCurrent();
    return { name: profile.resource.name, geojson: result.geojson };
  };
  const before = await read(ids.before);
  const after = ids.after ? await read(ids.after) : null;
  const actual = ids.differences ? await read(ids.differences, true) : null;
  return {
    workflow,
    before: before.geojson,
    after: after?.geojson ?? null,
    differences: outcome
      ? { type: "FeatureCollection", features: [] }
      : (actual?.geojson ?? previewSuggestions(workflow)),
    beforeName: before.name,
    afterName: after?.name ?? "建议修改范围，尚未执行",
  };
}
