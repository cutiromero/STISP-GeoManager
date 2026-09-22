import { App } from "antd";
import type { Map as MapboxMap } from "mapbox-gl";
import { useCallback, useEffect, useRef } from "react";
import { api } from "../api/client";
import type { RasterSymbolization } from "../symbolization";
import { rasterSymbolizationFromRules } from "../symbolization";
import type {
  LoadedRasterLayer,
  RasterJob,
  RasterRenderResult,
} from "../types";
import {
  isAbortError,
  RasterRenderTaskRegistry,
  type RasterRenderTask,
  waitForAbortableDelay,
} from "../utils/rasterRenderTasks";

export type RasterRenderProgressHandler = (job: RasterJob) => void;

export function rasterLayerWithRenderResult(
  current: LoadedRasterLayer,
  result: RasterRenderResult,
): LoadedRasterLayer {
  return {
    ...current,
    tileUrl: result.tileUrl,
    tileMinZoom: result.minZoom,
    tileMaxZoom: result.maxZoom,
    tileSampling: result.tileSampling,
    imageCoordinates: result.imageCoordinates,
    summary: "XYZ 瓦片已就绪",
    renderStatus: "ready",
    renderProgress: 100,
    symbolization: {
      ...rasterSymbolizationFromRules(result.rules),
      opacity: current.symbolization.opacity,
    },
    metadata: {
      ...current.metadata,
      加载方式: "XYZ 瓦片",
      样式哈希: result.styleHash,
    },
  };
}

export function useRasterRender(
  updateLayer: (
    groupId: string,
    layerId: string,
    updater: (layer: LoadedRasterLayer) => LoadedRasterLayer,
  ) => void,
) {
  const { message } = App.useApp();
  const mapInstanceRef = useRef<MapboxMap | null>(null);
  const taskRegistryRef = useRef<RasterRenderTaskRegistry | null>(null);
  if (taskRegistryRef.current === null) {
    taskRegistryRef.current = new RasterRenderTaskRegistry();
  }

  const cancelAllRasterTasks = useCallback(() => {
    taskRegistryRef.current?.cancelAll();
  }, []);

  const setMapInstance = useCallback(
    (map: MapboxMap | null) => {
      mapInstanceRef.current = map;
      if (!map) {
        cancelAllRasterTasks();
      }
    },
    [cancelAllRasterTasks],
  );

  useEffect(() => cancelAllRasterTasks, [cancelAllRasterTasks]);

  const applyResult = useCallback(
    (groupId: string, layerId: string, result: RasterRenderResult) => {
      updateLayer(groupId, layerId, (current) =>
        rasterLayerWithRenderResult(current, result),
      );
    },
    [updateLayer],
  );

  const pollJob = useCallback(
    async (
      jobId: string,
      task: RasterRenderTask,
      onProgress?: RasterRenderProgressHandler,
    ): Promise<RasterRenderResult> => {
      const registry = taskRegistryRef.current;
      if (!registry) {
        throw new Error("栅格渲染任务管理器未初始化");
      }
      while (registry.isCurrent(task) && !task.controller.signal.aborted) {
        await waitForAbortableDelay(900, task.controller.signal);
        if (!registry.isCurrent(task)) {
          throw new DOMException("栅格渲染任务已取消", "AbortError");
        }
        const job = await api.rasterJob(jobId, {
          signal: task.controller.signal,
        });
        if (!registry.isCurrent(task) || task.controller.signal.aborted) {
          throw new DOMException("栅格渲染任务已取消", "AbortError");
        }
        onProgress?.(job);
        const result = rasterRenderResultFromJob(job);
        if (result) return result;
      }
      throw new DOMException("栅格渲染任务已取消", "AbortError");
    },
    [],
  );

  const runRasterRender = useCallback(
    async (
      taskKey: string,
      symbolization: RasterSymbolization,
      layer: LoadedRasterLayer,
      rulesMode: "default" | "custom",
      onProgress?: RasterRenderProgressHandler,
    ): Promise<RasterRenderResult> => {
      const registry = taskRegistryRef.current;
      if (!registry) {
        throw new Error("栅格渲染任务管理器未初始化");
      }
      const task = registry.start(taskKey);
      try {
        const job = await api.renderRasterAsync(
          {
            datasetId: layer.rasterDatasetId,
            layerId: layer.rasterLayerId,
            rules:
              rulesMode === "custom"
                ? (symbolization as unknown as Record<string, unknown>)
                : undefined,
            rulesMode,
          },
          { signal: task.controller.signal },
        );
        if (!registry.isCurrent(task) || task.controller.signal.aborted) {
          throw new DOMException("栅格渲染任务已取消", "AbortError");
        }
        onProgress?.(job);
        const immediateResult = rasterRenderResultFromJob(job);
        if (immediateResult) return immediateResult;
        return await pollJob(job.id, task, onProgress);
      } catch (error) {
        if (task.timedOut) {
          throw new Error("栅格渲染等待超时，请稍后重试");
        }
        throw error;
      } finally {
        registry.finish(task);
      }
    },
    [pollJob],
  );

  const prepareRasterLayer = useCallback(
    async (
      layer: LoadedRasterLayer,
      onProgress?: RasterRenderProgressHandler,
    ) => {
      const result = await runRasterRender(
        `initial-load:${layer.id}`,
        layer.symbolization,
        layer,
        "default",
        onProgress,
      );
      return rasterLayerWithRenderResult(layer, result);
    },
    [runRasterRender],
  );

  const startRasterRender = useCallback(
    async (
      groupId: string,
      layerId: string,
      symbolization: RasterSymbolization,
      layer: LoadedRasterLayer,
      rulesMode: "default" | "custom" = "custom",
    ) => {
      const isUniqueValueRender =
        rulesMode === "custom" && symbolization.mode === "unique";
      const completionMessage = isUniqueValueRender
        ? `${layer.name}唯一值颜色渲染完成，地图已自动更新`
        : null;
      updateLayer(groupId, layerId, (current) => ({
        ...current,
        summary: "后台符号化中",
        renderStatus: "running",
        renderProgress: 5,
        renderMessages: ["提交符号化任务"],
        tileUrl: current.tileUrl,
      }));
      if (isUniqueValueRender) {
        message.info(
          `${layer.name}唯一值颜色正在后台生成；期间地图保留当前样式，完成后会自动更新`,
          4,
        );
      }

      try {
        const result = await runRasterRender(
          `${groupId}:${layerId}`,
          symbolization,
          layer,
          rulesMode,
          (job) => {
            updateLayer(groupId, layerId, (current) => ({
              ...current,
              renderJobId: job.id,
              renderStatus: job.status,
              renderProgress: job.progressPercent,
              renderMessages: job.messages,
            }));
          },
        );
        applyResult(groupId, layerId, result);
        if (completionMessage) {
          message.success(completionMessage);
        }
      } catch (error) {
        if (isAbortError(error)) {
          return;
        }
        updateLayer(groupId, layerId, (current) => ({
          ...current,
          summary: "符号化失败",
          renderStatus: "failed",
          renderMessages: [
            error instanceof Error ? error.message : "符号化失败",
          ],
        }));
        message.error(error instanceof Error ? error.message : "符号化失败");
      }
    },
    [applyResult, message, runRasterRender, updateLayer],
  );

  return { prepareRasterLayer, startRasterRender, setMapInstance };
}

function rasterRenderResultFromJob(job: RasterJob): RasterRenderResult | null {
  if (job.status === "failed") {
    throw new Error(
      job.error || job.messages[job.messages.length - 1] || "栅格渲染任务失败",
    );
  }
  if (job.status !== "ready") return null;
  if (!job.result) {
    throw new Error("栅格渲染任务已完成，但未返回瓦片结果");
  }
  return job.result as RasterRenderResult;
}
