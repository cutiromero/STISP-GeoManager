import { computeApi } from "../api/compute";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { record } from "./geologyReviewData";

export async function queryWorkflowVectors(
  workflow: AgentWorkflow,
  stageName: string,
  keys: string[],
): Promise<GeoJsonFeatureCollection> {
  const stage = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  )
    .map(record)
    .find((item) => item.name === stageName);
  if (!stage || stage.status !== "completed")
    return { type: "FeatureCollection", features: [] };
  const results = (Array.isArray(stage.results) ? stage.results : []).map(
    record,
  );
  const collections = await Promise.all(
    keys.map(async (key) => {
      const output = results.find(
        (item) => item.key === key && item.kind === "vector",
      );
      if (
        !output ||
        !Number.isSafeInteger(output.outputId) ||
        Number(output.outputId) <= 0
      )
        throw new Error(`任务缺少完整空间输出：${stageName}.${key}`);
      const result = await computeApi.vectorPreview(Number(output.outputId));
      if (!result.geojson)
        throw new Error(`空间输出无法读取：${stageName}.${key}`);
      return result.geojson;
    }),
  );
  return {
    type: "FeatureCollection",
    features: collections.flatMap((item) => item.features),
  };
}
