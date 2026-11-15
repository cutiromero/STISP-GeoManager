import { useEffect, useState } from "react";
import type { Map } from "mapbox-gl";
import { api, requestJson } from "../api/client";
import type {
  MonitoringSourcePreview,
  RasterRenderResult,
} from "../api/generated/types.gen";
import { projectUrl } from "../projects/session";
import { monitorResourceProfile } from "./resourceProfiles";
import { upsertPolygonLayer } from "../map/spatialDraw";
import { waitForAbortableDelay } from "../utils/rasterRenderTasks";
import type { MonitoringWorkspace } from "./useMonitoringWorkspace";

export default function MonitorRawLayer({
  map,
  workspace: w,
}: {
  map?: Map;
  workspace: MonitoringWorkspace;
}) {
  const [status, setStatus] = useState("");
  const source = w.source;
  useEffect(() => {
    if (!map?.getStyle() || !source || !w.sourceVisible) {
      setStatus("");
      return;
    }
    const controller = new AbortController();
    const signal = controller.signal;
    const timer = setTimeout(
      () => controller.abort(new Error("预览准备超时，请重试")),
      120000,
    );
    const bounds = source.metadata.sourceSchema.bounds;
    if (bounds?.length === 4) {
      const [west, south, east, north] = bounds as [
        number,
        number,
        number,
        number,
      ];
      if (east - west < 350)
        upsertPolygonLayer(
          map,
          "raw-coverage",
          "raw-coverage-fill",
          "raw-coverage-line",
          {
            type: "Polygon",
            coordinates: [
              [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
              ],
            ],
          },
          {
            fillColor: "#64bce9",
            fillOpacity: 0.02,
            lineColor: "#64bce9",
            lineOpacity: 0.7,
            lineWidth: 1,
          },
        );
    }
    setStatus("准备原始图层…");
    const load = async () => {
      const native = source.metadata.sourceSchema.kind === "native_cube";
      let sampling: "nearest" | "linear" = "nearest";
      if (native) {
        if (!w.time) {
          setStatus("请选择观测时期");
          return;
        }
        let job = await requestJson<MonitoringSourcePreview>(
          "/api/ecology/monitoring/source-preview/",
          {
            method: "POST",
            body: {
              scene: w.scene,
              resourceId: source.resource.id,
              product: w.product,
              ordinal: w.time.ordinal,
            },
            signal,
          },
        );
        while (job.status !== "ready") {
          if (job.status === "failed")
            throw new Error(job.error || "原始图层预览失败");
          await waitForAbortableDelay(900, signal);
          job = await requestJson<MonitoringSourcePreview>(
            `/api/ecology/monitoring/source-preview/${job.id}/`,
            { signal },
          );
        }
        signal.throwIfAborted();
        if (!map.getStyle() || !job.imageUrl || !job.bounds) return;
        const [west, south, east, north] = job.bounds as [
          number,
          number,
          number,
          number,
        ];
        map.addSource("monitor-raw", {
          type: "image",
          url: projectUrl(job.imageUrl),
          coordinates: [
            [west, north],
            [east, north],
            [east, south],
            [west, south],
          ],
        });
      } else {
        const profile = await monitorResourceProfile(source.resource, signal);
        if (!profile.raster) throw new Error("原始资料尚未准备地图显示");
        let job = await api.renderRasterAsync(
          { datasetId: profile.raster.id, rulesMode: "default" },
          { signal },
        );
        while (job.status !== "ready") {
          if (job.status === "failed")
            throw new Error(job.error || "原始图层预览失败");
          await waitForAbortableDelay(900, signal);
          job = await api.rasterJob(job.id, { signal });
        }
        signal.throwIfAborted();
        const result = job.result as RasterRenderResult | undefined;
        if (!map.getStyle() || !result?.tileUrl) return;
        sampling = result.tileSampling;
        map.addSource("monitor-raw", {
          type: "raster",
          tiles: [
            projectUrl(result.tileUrl)
              .replace(/%7B/g, "{")
              .replace(/%7D/g, "}"),
          ],
          tileSize: 256,
          bounds: result.bounds4326 as [number, number, number, number],
          maxzoom: result.maxZoom,
        });
      }
      signal.throwIfAborted();
      if (!map.getStyle()) return;
      const before = map
        .getStyle()
        ?.layers?.find(
          (layer) =>
            layer.id.startsWith("product-") || layer.id === "monitor-roi-fill",
        )?.id;
      map.addLayer(
        {
          id: "monitor-raw-layer",
          type: "raster",
          source: "monitor-raw",
          paint: {
            "raster-opacity": w.sourceOpacity / 100,
            "raster-resampling": sampling,
          },
        },
        before,
      );
      setStatus("");
    };
    void load()
      .catch((reason) => {
        if (!signal.aborted)
          setStatus(
            reason instanceof Error ? reason.message : "无法显示原始图层",
          );
        else if (
          signal.reason instanceof Error &&
          signal.reason.message.includes("超时")
        )
          setStatus(signal.reason.message);
      })
      .finally(() => clearTimeout(timer));
    return () => {
      clearTimeout(timer);
      controller.abort();
      if (!map.getStyle()) return;
      for (const id of [
        "monitor-raw-layer",
        "raw-coverage-fill",
        "raw-coverage-line",
      ])
        if (map.getLayer(id)) map.removeLayer(id);
      for (const id of ["monitor-raw", "raw-coverage"])
        if (map.getSource(id)) map.removeSource(id);
    };
  }, [
    map,
    source?.resource.id,
    source?.resource.updatedAt,
    source?.metadata.indexVersion,
    w.sourceVisible,
    w.time?.ordinal,
    w.product,
  ]);
  useEffect(() => {
    if (map?.getStyle() && map.getLayer("monitor-raw-layer"))
      map.setPaintProperty(
        "monitor-raw-layer",
        "raster-opacity",
        w.sourceOpacity / 100,
      );
  }, [map, w.sourceOpacity]);
  return status ? (
    <span className="monitor-source-status" role="status">
      {status}
    </span>
  ) : null;
}
