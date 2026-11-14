import { AimOutlined, ExpandOutlined, GlobalOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type {
  MonitoringProduct,
  ProjectMonitorConfig,
  RasterRenderResult,
  ResourceListItem,
} from "../api/generated/types.gen";
import { createRasterDisplaySwap } from "./rasterDisplaySwap";
import { useMonitorLayerStatus } from "./MonitorLayerStatus";
import { workbenchLegends, type LiveLayerLegend } from "../map/liveLegendData";
import { createRasterLayerGroup } from "../utils/layerFactory";
import { rasterSymbolizationFromRules } from "../symbolization";
import { currentLocale } from "../i18n";
import { projectUrl } from "../projects/session";
import {
  RasterRenderTaskRegistry,
  waitForAbortableDelay,
} from "../utils/rasterRenderTasks";
import { monitorResourceProfile } from "./resourceProfiles";
import { useMonitorMap } from "./useMonitorMap";

const layerIds = [
  "product-fill",
  "product-line",
  "product-point",
  "product-raster",
];

export default function ProductMap({
  product,
  config,
  animated,
  resource,
  visibleCodes,
  onMapReady,
  focusProduct = false,
  focusKey,
  information = true,
}: {
  product?: MonitoringProduct;
  config: ProjectMonitorConfig;
  animated: boolean;
  resource?: ResourceListItem;
  visibleCodes?: number[];
  onMapReady?: (map: mapboxgl.Map | undefined) => void;
  focusProduct?: boolean;
  focusKey?: number;
  information?: boolean;
}) {
  const { t } = useTranslation();
  const { container, map, mapError, regionalView, focus, showBounds } =
    useMonitorMap(config.initialView, animated);
  const boundsRef = useRef<[number, number, number, number] | undefined>(
    undefined,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [legend, setLegend] = useState<LiveLayerLegend>();
  const target = resource ?? product?.resource;
  const title = product?.name ?? target?.name ?? "";
  const focused = useRef<number | undefined>(undefined);
  const hasProduct = Boolean(target);
  const report = useMonitorLayerStatus();
  const activeResource = useRef("");
  const swap = useRef<ReturnType<typeof createRasterDisplaySwap> | undefined>(
    undefined,
  );
  const swapMap = useRef<mapboxgl.Map | undefined>(undefined);
  const styles = useRef(new Map<string, RasterRenderResult>());
  useEffect(
    () =>
      report({
        title,
        loading,
        updating: loading && Boolean(swap.current?.hasActive()),
        error: error || (mapError ? t("monitor.mapError") : undefined),
        legend: information ? legend : undefined,
      }),
    [report, title, loading, error, mapError, legend, information, t],
  );
  useEffect(() => {
    onMapReady?.(map);
    return () => onMapReady?.(undefined);
  }, [map, onMapReady]);
  useEffect(() => {
    if (!map || !hasProduct) return;
    const element = document.createElement("button");
    element.type = "button";
    element.setAttribute("role", "button");
    element.className = "monitor-map-cluster";
    element.setAttribute("aria-label", t("remoteMonitor.openDistribution"));
    const label = document.createElement("span");
    label.textContent = t("monitor.studyArea");
    const action = document.createElement("strong");
    action.textContent = t("remoteMonitor.openDistribution");
    element.append(label, action);
    element.addEventListener("click", () => focus(true));
    const marker = new mapboxgl.Marker({ element })
      .setLngLat(config.initialView.center as [number, number])
      .addTo(map);
    return () => {
      marker.remove();
    };
  }, [map, hasProduct, t]);
  useEffect(() => {
    if (!map) return;
    let disposed = false;
    if (swapMap.current !== map) {
      swapMap.current = map;
      swap.current = createRasterDisplaySwap(map);
      activeResource.current = "";
    }
    const identity = target ? `${target.id}:${target.updatedAt}` : "";
    if (activeResource.current !== identity) {
      swap.current?.clear();
      for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource("product")) map.removeSource("product");
      activeResource.current = identity;
      boundsRef.current = undefined;
      setLegend(undefined);
    }
    setError(undefined);
    setLoading(Boolean(target));
    if (!target) return;
    const registry = new RasterRenderTaskRegistry();
    const task = registry.start("product");
    const signal = task.controller.signal;
    const load = async () => {
      const profile = await monitorResourceProfile(target, signal);
      signal.throwIfAborted();
      let bounds = profile.bounds;
      if (profile.raster) {
        const styleKey = `${identity}:${visibleCodes?.join(",") ?? "default"}`;
        let result = styles.current.get(styleKey);
        if (!result) {
          if (visibleCodes !== undefined && swap.current?.hasActive())
            await waitForAbortableDelay(75, signal);
          let job = await api.renderRasterAsync(
            {
              datasetId: profile.raster.id,
              ...(visibleCodes !== undefined &&
              profile.raster.defaultRules.mode === "unique"
                ? {
                    rulesMode: "custom" as const,
                    rules: {
                      ...profile.raster.defaultRules,
                      uniqueValues: rasterSymbolizationFromRules(
                        profile.raster.defaultRules,
                      ).uniqueValues.map((row) => ({
                        ...row,
                        color: visibleCodes.includes(row.value)
                          ? row.color
                          : "#00000000",
                      })),
                    },
                  }
                : { rulesMode: "default" as const }),
            },
            { signal },
          );
          while (job.status !== "ready") {
            if (job.status === "failed")
              throw new Error(job.error || t("remoteMonitor.renderFailed"));
            await waitForAbortableDelay(900, signal);
            job = await api.rasterJob(job.id, { signal });
          }
          signal.throwIfAborted();
          result = job.result as RasterRenderResult | undefined;
          if (
            !result ||
            result.delivery !== "xyz" ||
            result.datasetId !== profile.raster.id
          )
            throw new Error(t("remoteMonitor.renderFailed"));
          if (styles.current.size >= 16)
            styles.current.delete(styles.current.keys().next().value!);
          styles.current.set(styleKey, result);
        }
        signal.throwIfAborted();
        bounds = result.bounds4326;
        await swap.current!.show(result, signal);
        const layer = createRasterLayerGroup(target, profile)?.children[0];
        if (layer?.layerType === "raster")
          setLegend(
            workbenchLegends(
              [
                {
                  ...layer,
                  tileUrl: result.tileUrl,
                  renderStatus: "ready",
                  symbolization: {
                    ...rasterSymbolizationFromRules(result.rules),
                    opacity: result.tileSampling === "nearest" ? 100 : 90,
                  },
                },
              ],
              currentLocale() === "en-US",
            )[0],
          );
      } else if (profile.vectorTiles) {
        const preview = profile.vectorTiles;
        const color = product?.scene === "spartina" ? "#66e0a3" : "#ffb46a";
        setLegend({
          id: String(product?.id ?? target.id),
          title,
          opacity: 0.65,
          updating: false,
          entries: [
            {
              id: "target",
              label:
                product?.scene === "spartina"
                  ? t("remoteMonitor.spartina")
                  : title,
              color,
              shape: "polygon",
            },
          ],
        });
        map.addSource("product", {
          type: "vector",
          tiles: [
            projectUrl(preview.rawTileUrl || preview.tileUrl)
              .replace(/%7B/g, "{")
              .replace(/%7D/g, "}"),
          ],
          bounds: preview.bounds,
          minzoom: preview.minZoom,
          maxzoom: preview.maxZoom,
        });
        map.addLayer({
          id: "product-fill",
          type: "fill",
          source: "product",
          "source-layer": preview.sourceLayer,
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: { "fill-color": color, "fill-opacity": 0.65 },
        });
        map.addLayer({
          id: "product-line",
          type: "line",
          source: "product",
          "source-layer": preview.sourceLayer,
          filter: [
            "match",
            ["geometry-type"],
            ["Polygon", "LineString"],
            true,
            false,
          ],
          paint: { "line-color": color, "line-width": 1 },
        });
        map.addLayer({
          id: "product-point",
          type: "circle",
          source: "product",
          "source-layer": preview.sourceLayer,
          filter: ["==", ["geometry-type"], "Point"],
          paint: { "circle-color": color, "circle-radius": 4 },
        });
      } else {
        throw new Error(t("remoteMonitor.tilesPending"));
      }
      if (bounds.length === 4 && bounds.every(Number.isFinite)) {
        boundsRef.current = bounds as [number, number, number, number];
        if (focusProduct && focused.current !== (focusKey ?? target.id)) {
          focused.current = focusKey ?? target.id;
          showBounds(boundsRef.current);
        }
      }
    };
    void load()
      .catch((failure: unknown) => {
        if (!disposed && (!signal.aborted || task.timedOut)) {
          if (
            failure &&
            typeof failure === "object" &&
            "status" in failure &&
            [401, 403, 404].includes(Number(failure.status))
          ) {
            swap.current?.clear();
            styles.current.clear();
            for (const id of layerIds)
              if (map.getLayer(id)) map.removeLayer(id);
            if (map.getSource("product")) map.removeSource("product");
            setLegend(undefined);
          }
          setError(
            task.timedOut
              ? t("remoteMonitor.renderTimeout")
              : failure instanceof Error
                ? failure.message
                : t("remoteMonitor.renderFailed"),
          );
        }
      })
      .finally(() => {
        if (!disposed && (!signal.aborted || task.timedOut)) setLoading(false);
        registry.finish(task);
      });
    return () => {
      disposed = true;
      registry.cancelAll();
      swap.current?.cancel();
    };
  }, [
    map,
    product?.id,
    target?.id,
    target?.updatedAt,
    visibleCodes?.join(","),
    t,
  ]);
  return (
    <>
      <div
        className="remote-product-map monitor-planet-stage"
        data-view={regionalView ? "region" : "globe"}
        aria-label={t("remoteMonitor.map")}
      >
        <div
          ref={container}
          className="monitor-map remote-product-map-canvas"
        />
      </div>
      <div className="monitor-map-controls">
        <Tooltip title={t("monitor.globalView")} placement="left">
          <Button
            shape="circle"
            aria-label={t("monitor.globalView")}
            icon={<GlobalOutlined />}
            disabled={!map}
            onClick={() => focus(false)}
          />
        </Tooltip>
        <Tooltip title={t("monitor.regionView")} placement="left">
          <Button
            shape="circle"
            aria-label={t("monitor.regionView")}
            icon={<AimOutlined />}
            disabled={!map || loading || !target}
            onClick={() => focus(true)}
          />
        </Tooltip>
        {target && (
          <Tooltip title={t("remoteMonitor.fullExtent")} placement="left">
            <Button
              shape="circle"
              aria-label={t("remoteMonitor.fullExtent")}
              icon={<ExpandOutlined />}
              disabled={!map || loading}
              onClick={() => {
                if (boundsRef.current) showBounds(boundsRef.current);
              }}
            />
          </Tooltip>
        )}
      </div>
    </>
  );
}
