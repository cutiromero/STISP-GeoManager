import { useEffect, useRef } from "react";
import type { Map as MapboxMap } from "mapbox-gl";
import { api, hasCurrentVectorPreview } from "../api/client";
import { attachVectorTilePreview } from "../map/vectorTilePreview";
import type {
  LoadedLayer,
  LoadedLayerGroup,
  ResourceQueryResult,
} from "../types";
import {
  applyViewportResult,
  isViewportVectorLayer,
  viewportQueryPayload,
} from "../map/viewportVectorQuery";

export function useViewportVectorLayers(options: {
  map: MapboxMap | null;
  scope: string;
  enabled: boolean;
  resolveTilePreviews?: boolean;
  groups: LoadedLayerGroup[];
  limit: number;
  updateLayer: (
    groupId: string,
    layerId: string,
    update: (layer: LoadedLayer) => LoadedLayer,
  ) => void;
  onError: (message: string) => void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const targets = options.groups
    .filter((g) => g.visible)
    .flatMap((g) =>
      g.children
        .filter((l) => l.visible && isViewportVectorLayer(l))
        .map((l) => [
          g.id,
          l.id,
          l.sourceResource.id,
          l.sourceResource.updatedAt,
        ]),
    );
  const signature = JSON.stringify(targets);
  useEffect(() => {
    const { map, scope } = options;
    if (!map || !options.enabled || !targets.length) return;
    let revision = 0,
      disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const cache = new Map<
      string,
      { at: number; result: ResourceQueryResult }
    >();
    async function refresh() {
      const current = ++revision;
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      const bounds = map!.getBounds();
      if (!bounds || map!.isMoving()) return;
      const box: [number, number, number, number] = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ].map((v) => +v.toFixed(5)) as [number, number, number, number];
      const context = latest.current;
      const layers = context.groups
        .filter((g) => g.visible)
        .flatMap((g) =>
          g.children
            .filter((l) => l.visible && isViewportVectorLayer(l))
            .map((l) => ({ groupId: g.id, layer: l })),
        )
        .sort(
          (a, b) =>
            Number(b.layer.geometryType.toLowerCase().includes("line")) -
            Number(a.layer.geometryType.toLowerCase().includes("line")),
        );
      try {
        // Prioritize pipelines and use the backend's two display-query slots.
        let cursor = 0;
        async function loadNext() {
          while (cursor < layers.length) {
            const { groupId, layer } = layers[cursor++]!;
            if (layer.layerType !== "vector" || !isViewportVectorLayer(layer))
              continue;
            if (disposed || signal.aborted || latest.current.scope !== scope)
              return;
            const body = viewportQueryPayload(
              box,
              context.limit,
              layer.geometryType,
            );
            let preview = layer.vectorTiles;
            if (
              context.resolveTilePreviews &&
              !hasCurrentVectorPreview(layer.sourceResource, preview)
            ) {
              preview =
                (await api.resourceProfile(layer.sourceResource, { signal }))
                  .vectorTiles ?? undefined;
            }
            const key = JSON.stringify([
              layer.sourceResource.id,
              layer.sourceResource.updatedAt,
              body,
            ]);
            if (preview) {
              if (
                disposed ||
                signal.aborted ||
                latest.current.scope !== scope ||
                current !== revision
              )
                return;
              const prepared = preview;
              context.updateLayer(groupId, layer.id, (l) =>
                l.layerType === "vector"
                  ? {
                      ...(l.vectorTiles?.revision === prepared.revision
                        ? l
                        : {
                            ...attachVectorTilePreview(l, prepared),
                            ...(l.vectorTiles
                              ? { symbolization: l.symbolization }
                              : {}),
                          }),
                      metadata: {
                        ...l.metadata,
                        加载方式: "分级矢量瓦片",
                        展示范围: "当前地图视野",
                        显示要素总数: prepared.featureCount,
                        视野查询键: key,
                        视野刷新时间: Date.now(),
                      },
                    }
                  : l,
              );
              continue;
            }
            if (
              !layer.vectorTiles &&
              layer.metadata.视野查询键 === key &&
              Date.now() - Number(layer.metadata.视野刷新时间) < 30000
            )
              continue;
            const cached = cache.get(key);
            const result =
              cached && Date.now() - cached.at < 30000
                ? cached.result
                : await api.queryResource(layer.sourceResource, body, signal);
            if (
              disposed ||
              current !== revision ||
              signal.aborted ||
              latest.current.scope !== scope
            )
              return;
            cache.set(key, { at: Date.now(), result });
            while (cache.size > 24) cache.delete(cache.keys().next().value!);
            context.updateLayer(groupId, layer.id, (l) =>
              l.layerType === "vector" && isViewportVectorLayer(l)
                ? applyViewportResult(
                    { ...l, vectorTiles: undefined },
                    result,
                    key,
                  )
                : l,
            );
          }
        }
        await Promise.all([loadNext(), loadNext()]);
      } catch (error) {
        if (!disposed && current === revision && !signal.aborted) {
          controller?.abort();
          latest.current.onError(
            error instanceof Error ? error.message : "当前视野加载失败",
          );
        }
      }
    }
    function cancel() {
      revision++;
      controller?.abort();
      clearTimeout(timer);
    }
    function schedule() {
      cancel();
      timer = setTimeout(() => void refresh(), 350);
    }
    map.on("movestart", cancel);
    map.on("moveend", schedule);
    schedule();
    return () => {
      disposed = true;
      cancel();
      cache.clear();
      map.off("movestart", cancel);
      map.off("moveend", schedule);
    };
  }, [
    options.map,
    options.scope,
    options.enabled,
    options.resolveTilePreviews,
    options.limit,
    signature,
  ]);
}
