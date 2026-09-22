import { api } from "../api/client";
import { rasterTileRendererVersion } from "../map/rasterLayerSync";
import { rasterSymbolizationFromRules } from "../symbolization";
import type {
  DataResource,
  LoadedLayer,
  LoadedLayerGroup,
  LoadedRasterLayer,
  LoadedVectorLayer,
  RasterRenderResult,
  WorkspaceSceneSnapshot,
} from "../types";
import { createVectorLayerGroup } from "../utils/layerFactory";
import type { AppNotification } from "./workspaceNotifications";
import { showGeojsonWarnings } from "./workspaceNotifications";
import { isLoadedVectorLayer } from "./workspaceSnapshot";

export interface WorkspaceRestoreProgress {
  percent: number;
  detail: string;
}

export interface WorkspaceRestoreIssue {
  layerName: string;
  resourceName: string;
  reason: string;
  action: "skipped" | "restored-with-warning";
}

export interface WorkspaceRestoreResult {
  groups: LoadedLayerGroup[];
  issues: WorkspaceRestoreIssue[];
}

interface RestoreWorkspaceGroupsOptions {
  savedGroups: WorkspaceSceneSnapshot["groups"];
  canQueryData: boolean;
  canLoadVectorLayer: boolean;
  canLoadRasterLayer: boolean;
  queryResultLimit: number;
  notification: AppNotification;
  onProgress?: (state: WorkspaceRestoreProgress) => void;
}

export async function restoreWorkspaceGroups({
  savedGroups,
  canQueryData,
  canLoadVectorLayer,
  canLoadRasterLayer,
  queryResultLimit,
  notification,
  onProgress,
}: RestoreWorkspaceGroupsOptions): Promise<WorkspaceRestoreResult> {
  if (!Array.isArray(savedGroups)) {
    return { groups: [], issues: [] };
  }
  const totalLayers = savedGroups.reduce(
    (total, group) => total + (group.children?.length ?? 0),
    0,
  );
  let processedLayers = 0;
  const updateRestoreProgress = (detail: string) => {
    if (!onProgress) {
      return;
    }
    const layerProgress =
      totalLayers > 0 ? Math.round((processedLayers / totalLayers) * 70) : 70;
    onProgress({
      percent: Math.min(85, 10 + layerProgress),
      detail,
    });
  };
  const restored: LoadedLayerGroup[] = [];
  const issues: WorkspaceRestoreIssue[] = [];
  for (const savedGroup of savedGroups) {
    const restoredChildren: LoadedLayer[] = [];
    for (const savedLayer of savedGroup.children ?? []) {
      updateRestoreProgress(`正在恢复图层：${savedLayer.name}`);
      if (isLoadedVectorLayer(savedLayer)) {
        restoredChildren.push(savedLayer);
        processedLayers += 1;
        updateRestoreProgress(`已恢复图层：${savedLayer.name}`);
        continue;
      }
      if (savedLayer.layerType === "vector") {
        if (!savedLayer.query) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "缺少原始查询条件",
            action: "skipped",
          });
          processedLayers += 1;
          updateRestoreProgress(`已跳过图层：${savedLayer.name}`);
          continue;
        }
        if (!canQueryData || !canLoadVectorLayer) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "当前账号无权重新查询或加载原始矢量数据",
            action: "skipped",
          });
          processedLayers += 1;
          updateRestoreProgress(`已跳过图层：${savedLayer.name}`);
          continue;
        }
        try {
          const profile = await api.resourceProfile(savedLayer.sourceResource);
          const result = await api.queryResource(savedLayer.sourceResource, {
            attributeFilters: savedLayer.query.attributeFilters,
            spatialFilter: savedLayer.query.spatialFilter,
            limit: queryResultLimit,
          });
          showGeojsonWarnings(notification, result.warnings);
          const queryGroup = createVectorLayerGroup(
            savedLayer.sourceResource,
            profile,
            result,
            savedLayer.query,
          );
          const restoredVectorLayer = queryGroup.children[0];
          if (restoredVectorLayer?.layerType === "vector") {
            restoredChildren.push({
              ...restoredVectorLayer,
              id: savedLayer.id,
              name: savedLayer.name,
              visible: savedLayer.visible,
              summary: savedLayer.summary,
              metadata: savedLayer.metadata,
              symbolization:
                savedLayer.symbolization as LoadedVectorLayer["symbolization"],
              fields: savedLayer.fields,
            });
          }
        } catch (error) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason:
              error instanceof Error ? error.message : "原始矢量数据不可用",
            action: "skipped",
          });
        }
        processedLayers += 1;
        updateRestoreProgress(`已处理图层：${savedLayer.name}`);
        continue;
      }
      if (!canLoadRasterLayer) {
        issues.push({
          layerName: savedLayer.name,
          resourceName: savedLayer.sourceResource.name,
          reason: "当前账号无权加载原始栅格数据，请联系管理员申请权限",
          action: "skipped",
        });
        processedLayers += 1;
        updateRestoreProgress(`已跳过图层：${savedLayer.name}`);
        continue;
      }
      let rasterKind = savedLayer.rasterKind;
      let currentRaster:
        | Awaited<ReturnType<typeof api.resourceProfile>>["raster"]
        | undefined;
      try {
        const profile = await api.resourceProfile(savedLayer.sourceResource);
        currentRaster = profile.raster ?? undefined;
        rasterKind = profile.raster?.rasterKind ?? rasterKind;
        if (!profile.raster) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "原始栅格数据未就绪或已不可用",
            action: "restored-with-warning",
          });
        } else if (
          savedLayer.rasterDatasetId &&
          profile.raster.id !== savedLayer.rasterDatasetId
        ) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "原始栅格数据已变更，已使用快照中的瓦片引用恢复",
            action: "restored-with-warning",
          });
        }
      } catch (error) {
        if (isForbiddenError(error)) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "当前账号无权访问原始栅格数据，请联系管理员申请权限",
            action: "skipped",
          });
          processedLayers += 1;
          updateRestoreProgress(`已跳过图层：${savedLayer.name}`);
          continue;
        }
        issues.push({
          layerName: savedLayer.name,
          resourceName: savedLayer.sourceResource.name,
          reason:
            error instanceof Error ? error.message : "原始栅格数据无法校验",
          action: "restored-with-warning",
        });
      }
      const refreshLegacyCategoricalTiles =
        rasterKind === "categorical" &&
        !usesCurrentRasterRenderer(savedLayer.tileUrl);
      let refreshedRender: RasterRenderResult | undefined;
      let refreshError =
        refreshLegacyCategoricalTiles && !currentRaster
          ? "无法校验原始分类栅格，已停止加载旧版瓦片"
          : undefined;
      if (refreshLegacyCategoricalTiles && currentRaster) {
        updateRestoreProgress(`正在升级分类栅格瓦片：${savedLayer.name}`);
        try {
          refreshedRender = await renderCategoricalSnapshot(
            currentRaster.id,
            currentRaster.mapLayerId,
            savedLayer.symbolization as LoadedRasterLayer["symbolization"],
          );
          if (!usesCurrentRasterRenderer(refreshedRender.tileUrl)) {
            throw new Error("分类栅格服务返回了旧版瓦片地址");
          }
        } catch (error) {
          refreshError =
            error instanceof Error ? error.message : "分类栅格瓦片升级失败";
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: refreshError,
            action: "restored-with-warning",
          });
        }
      }
      const savedSymbolization =
        savedLayer.symbolization as LoadedRasterLayer["symbolization"];
      const restoredSymbolization = refreshedRender
        ? {
            ...rasterSymbolizationFromRules(refreshedRender.rules),
            opacity: savedSymbolization.opacity,
          }
        : savedSymbolization;
      restoredChildren.push({
        id: savedLayer.id,
        name: savedLayer.name,
        layerType: "raster",
        sourceResource: savedLayer.sourceResource as DataResource,
        tileUrl: refreshLegacyCategoricalTiles
          ? refreshedRender?.tileUrl
          : savedLayer.tileUrl,
        tileMinZoom: refreshedRender?.minZoom ?? savedLayer.tileMinZoom,
        tileMaxZoom: refreshedRender?.maxZoom ?? savedLayer.tileMaxZoom,
        tileSampling:
          refreshedRender?.tileSampling ??
          savedLayer.tileSampling ??
          (rasterKind === "categorical" ? "nearest" : undefined),
        imageCoordinates:
          refreshedRender?.imageCoordinates ?? savedLayer.imageCoordinates,
        rasterDatasetId: refreshLegacyCategoricalTiles
          ? currentRaster?.id
          : savedLayer.rasterDatasetId,
        rasterLayerId: refreshLegacyCategoricalTiles
          ? currentRaster?.mapLayerId
          : savedLayer.rasterLayerId,
        rasterKind,
        rasterMetadata: currentRaster?.metadata ?? savedLayer.rasterMetadata,
        renderStatus: refreshedRender
          ? "ready"
          : refreshError
            ? "failed"
            : savedLayer.renderStatus,
        renderProgress: refreshedRender
          ? 100
          : refreshError
            ? 0
            : savedLayer.renderProgress,
        renderMessages: refreshedRender
          ? ["分类栅格静态瓦片已升级并就绪"]
          : refreshError
            ? [refreshError]
            : savedLayer.renderMessages,
        geometryType: savedLayer.geometryType,
        visible: savedLayer.visible,
        summary: refreshedRender
          ? "XYZ 瓦片已就绪"
          : refreshError
            ? "分类栅格瓦片升级失败"
            : savedLayer.summary,
        metadata: refreshedRender
          ? {
              ...savedLayer.metadata,
              加载方式: "XYZ 瓦片",
              样式哈希: refreshedRender.styleHash,
            }
          : savedLayer.metadata,
        symbolization: restoredSymbolization,
        fields: savedLayer.fields,
      });
      processedLayers += 1;
      updateRestoreProgress(`已恢复图层：${savedLayer.name}`);
    }
    if (restoredChildren.length > 0 || savedGroup.isManual) {
      restored.push({ ...savedGroup, children: restoredChildren });
    }
  }
  return { groups: restored, issues };
}

async function renderCategoricalSnapshot(
  datasetId: number,
  layerId: number | null,
  symbolization: LoadedRasterLayer["symbolization"],
): Promise<RasterRenderResult> {
  const rules = symbolization as unknown as Record<string, unknown>;
  let job = await api.renderRasterAsync({
    datasetId,
    layerId,
    rules,
    rulesMode: "custom",
  });
  const deadline = Date.now() + 120_000;
  while (job.status === "queued" || job.status === "running") {
    if (Date.now() >= deadline) {
      throw new Error("分类栅格瓦片升级等待超时");
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 900));
    job = await api.rasterJob(job.id);
  }
  if (
    job.status === "ready" &&
    job.result &&
    typeof job.result === "object" &&
    "tileUrl" in job.result
  ) {
    return job.result as RasterRenderResult;
  }
  throw new Error(job.error || "分类栅格瓦片升级失败");
}

function usesCurrentRasterRenderer(tileUrl: string | undefined) {
  if (!tileUrl) {
    return false;
  }
  return new RegExp(`(?:[?&])rv=${rasterTileRendererVersion}(?:[&#]|$)`).test(
    tileUrl,
  );
}

function isForbiddenError(error: unknown) {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    error.status === 403
  );
}
