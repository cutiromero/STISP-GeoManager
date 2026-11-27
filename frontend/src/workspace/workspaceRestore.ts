import { restoreVectorStyle } from "./restoreVectorStyle";
import { isLargeVectorResource } from "../map/viewportVectorQuery";
import { api } from "../api/client";
import { tilePreviewResult } from "../map/vectorTilePreview";
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
import { isAbortError } from "../utils/rasterRenderTasks";

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
  checkScope?: () => void;
}

export async function restoreWorkspaceGroups({
  savedGroups,
  canQueryData,
  canLoadVectorLayer,
  canLoadRasterLayer,
  queryResultLimit,
  notification,
  onProgress,
  checkScope = () => {},
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
    checkScope();
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
      if (savedLayer.layerType === "vector") {
        const embedded = isLoadedVectorLayer(savedLayer);
        if (!savedLayer.query && !embedded) {
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
          checkScope();
          const resource = profile.resource ?? savedLayer.sourceResource;
          if (embedded && !savedLayer.query) {
            restoredChildren.push({ ...savedLayer, sourceResource: resource });
            processedLayers += 1;
            updateRestoreProgress(`已恢复图层：${savedLayer.name}`);
            continue;
          }
          const query = savedLayer.query!;
          const unfiltered = !query.attributeFilters.length && !query.spatialFilter;
          const deferred =
            unfiltered &&
            isLargeVectorResource({
              ...resource,
              itemCount: profile.featureCount ?? resource.itemCount,
            });
          const tiled = unfiltered && profile.vectorTiles;
          const result =
            tiled || deferred
              ? tilePreviewResult(resource, profile)
              : await api.queryResource(resource, {
                  attributeFilters: query.attributeFilters,
                  spatialFilter: query.spatialFilter,
                  limit: queryResultLimit,
                  displayGeometry: true,
                });
          checkScope();
          showGeojsonWarnings(notification, result.warnings);
          const queryGroup = createVectorLayerGroup(
            resource,
            profile,
            result,
            query,
          );
          const restoredVectorLayer = queryGroup.children[0];
          if (restoredVectorLayer?.layerType === "vector") {
            restoredChildren.push({
              ...restoredVectorLayer,
              id: savedLayer.id,
              name: savedLayer.name,
              visible: savedLayer.visible,
              summary: tiled
                ? restoredVectorLayer.summary
                : deferred
                  ? "按当前地图范围加载"
                  : savedLayer.summary,
              metadata: tiled
                ? { ...savedLayer.metadata, ...restoredVectorLayer.metadata }
                : deferred
                  ? { ...savedLayer.metadata, 视野查询键: "", 视野刷新时间: 0 }
                  : savedLayer.metadata,
              symbolization: restoreVectorStyle(
                restoredVectorLayer.symbolization,
                savedLayer.symbolization as LoadedVectorLayer["symbolization"],
              ),
              fields: savedLayer.fields,
              ...(deferred ? { viewportOnly: true } : {}),
            });
          }
        } catch (error) {
          if (isAbortError(error)) throw error;
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: sourceUnavailable(error) ??
              (error instanceof Error ? error.message : "原始矢量数据不可用"),
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
      let currentResource = savedLayer.sourceResource;
      try {
        const profile = await api.resourceProfile(savedLayer.sourceResource);
        checkScope();
        currentResource = profile.resource ?? currentResource;
        currentRaster = profile.raster ?? undefined;
        rasterKind =
          (savedLayer.symbolization as LoadedRasterLayer["symbolization"])
            .mode === "unique"
            ? "categorical"
            : (profile.raster?.rasterKind ?? rasterKind);
        if (!profile.raster) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: "原始栅格数据未就绪或已不可用",
            action: "restored-with-warning",
          });
        }
      } catch (error) {
        if (isAbortError(error)) throw error;
        const unavailable = sourceUnavailable(error);
        if (unavailable) {
          issues.push({
            layerName: savedLayer.name,
            resourceName: savedLayer.sourceResource.name,
            reason: unavailable,
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
      const savedStyleHash =
        currentRaster?.id === savedLayer.rasterDatasetId && currentRaster
          ? savedRasterStyleHash(savedLayer.tileUrl, currentRaster.id)
          : undefined;
      // Renderer version alone does not prove that the persisted style still
      // matches its source or that a static pyramid survived cache cleanup.
      const refreshSnapshotTiles =
        !currentRaster ||
        currentRaster.id !== savedLayer.rasterDatasetId ||
        !usesCurrentRasterRenderer(savedLayer.tileUrl, currentRaster?.id) ||
        rasterKind === "categorical" ||
        Boolean(savedStyleHash);
      let refreshedRender: RasterRenderResult | undefined;
      let refreshError =
        refreshSnapshotTiles && !currentRaster
          ? "无法校验原始栅格，已停止加载旧版瓦片"
          : undefined;
      if (refreshSnapshotTiles && currentRaster) {
        updateRestoreProgress(`正在准备栅格显示：${savedLayer.name}`);
        try {
          const result = await renderSnapshotRaster(
            currentRaster.id,
            currentRaster.mapLayerId,
            savedLayer.symbolization as LoadedRasterLayer["symbolization"],
            savedLayer.rasterRulesMode ?? "custom",
            savedStyleHash,
            checkScope,
          );
          if (result.datasetId !== currentRaster.id || !usesCurrentRasterRenderer(result.tileUrl, currentRaster.id)) {
            throw new Error("栅格服务返回了不匹配的瓦片地址");
          }
          refreshedRender = result;
        } catch (error) {
          if (isAbortError(error)) throw error;
          refreshError =
            error instanceof Error ? error.message : "栅格显示准备失败";
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
            opacity: savedSymbolization.opacity ?? 100,
            colorPolicy: savedSymbolization.colorPolicy,
          }
        : savedSymbolization;
      restoredChildren.push({
        id: savedLayer.id,
        name: savedLayer.name,
        layerType: "raster",
        sourceResource: currentResource as DataResource,
        tileUrl: refreshSnapshotTiles
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
        rasterDatasetId: refreshSnapshotTiles
          ? currentRaster?.id
          : savedLayer.rasterDatasetId,
        rasterLayerId: refreshSnapshotTiles
          ? currentRaster?.mapLayerId
          : savedLayer.rasterLayerId,
        rasterKind,
        rasterRulesMode: savedLayer.rasterRulesMode,
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
          ? ["栅格显示已更新并就绪"]
          : refreshError
            ? [refreshError]
            : savedLayer.renderMessages,
        geometryType: savedLayer.geometryType,
        visible: savedLayer.visible,
        summary: refreshedRender
          ? "XYZ 瓦片已就绪"
          : refreshError
            ? "栅格显示准备失败"
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

async function renderSnapshotRaster(
  datasetId: number,
  layerId: number | null,
  symbolization: LoadedRasterLayer["symbolization"],
  rulesMode: "default" | "custom",
  styleHash: string | undefined,
  checkScope: () => void,
): Promise<RasterRenderResult> {
  const rules = symbolization as unknown as Record<string, unknown>;
  let job: Awaited<ReturnType<typeof api.renderRasterAsync>>;
  try {
    job = await api.renderRasterAsync(
      styleHash
        ? { datasetId, layerId, styleHash }
        : { datasetId, layerId, rules, rulesMode },
    );
  } catch (error) {
    if (!styleHash || !isStatusError(error, 404)) throw error;
    checkScope();
    // Very old snapshots may no longer have a registered style. Recreating
    // client rules still passes the backend custom-symbolization permission.
    job = await api.renderRasterAsync({ datasetId, layerId, rules, rulesMode });
  }
  const deadline = Date.now() + 120_000;
  while (job.status === "queued" || job.status === "running") {
    if (Date.now() >= deadline) {
      throw new Error("栅格显示准备等待超时");
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 900));
    checkScope();
    job = await api.rasterJob(job.id);
  }
  checkScope();
  if (
    job.status === "ready" &&
    job.result &&
    typeof job.result === "object" &&
    "tileUrl" in job.result
  ) {
    return job.result as RasterRenderResult;
  }
  throw new Error(job.error || "栅格显示准备失败");
}

function usesCurrentRasterRenderer(tileUrl: string | undefined, datasetId: number | undefined) {
  return Boolean(
    datasetId &&
    tileUrl?.startsWith(`/api/raster/tiles/${datasetId}/`) &&
    new RegExp(`(?:[?&])rv=${rasterTileRendererVersion}(?:[&#]|$)`).test(tileUrl)
  );
}

function savedRasterStyleHash(tileUrl: string | undefined, datasetId: number) {
  return tileUrl?.match(
    new RegExp(`^/api/raster/tiles/${datasetId}/([a-f0-9]{24})/`),
  )?.[1];
}

function sourceUnavailable(error: unknown) {
  if (isStatusError(error, 401)) return "登录已失效，请重新登录";
  if (isStatusError(error, 403)) return "当前账号无权访问此数据，请联系管理员申请权限";
  if (isStatusError(error, 404) || isStatusError(error, 410))
    return "工程引用的资源已失效或已删除";
  return undefined;
}

function isStatusError(error: unknown, status: number) {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    error.status === status
  );
}
