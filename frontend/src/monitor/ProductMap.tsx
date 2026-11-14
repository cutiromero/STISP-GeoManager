import { AimOutlined, ExpandOutlined, GlobalOutlined } from "@ant-design/icons";
import { Alert, Button, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type {
  MonitoringProduct,
  ProjectMonitorConfig,
  RasterRenderResult,
} from "../api/generated/types.gen";
import { versionedRasterTileUrl } from "../map/rasterLayerSync";
import { workbenchLegends, type LiveLayerLegend } from "../map/liveLegendData";
import { createRasterLayerGroup } from "../utils/layerFactory";
import { rasterSymbolizationFromRules } from "../symbolization";
import { currentLocale } from "../i18n";
import { projectUrl } from "../projects/session";
import {
  RasterRenderTaskRegistry,
  waitForAbortableDelay,
} from "../utils/rasterRenderTasks";
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
}: {
  product?: MonitoringProduct;
  config: ProjectMonitorConfig;
  animated: boolean;
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
  const hasProduct = Boolean(product);
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
    for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource("product")) map.removeSource("product");
    boundsRef.current = undefined;
    setError(undefined);
    setLegend(undefined);
    setLoading(Boolean(product));
    if (!product) return;
    const registry = new RasterRenderTaskRegistry();
    const task = registry.start("product");
    const signal = task.controller.signal;
    const load = async () => {
      const profile = await api.resourceProfile(product.resource, { signal });
      signal.throwIfAborted();
      let bounds = profile.bounds;
      if (profile.raster) {
        let job = await api.renderRasterAsync(
          { datasetId: profile.raster.id, rulesMode: "default" },
          { signal },
        );
        while (job.status !== "ready") {
          if (job.status === "failed")
            throw new Error(job.error || t("remoteMonitor.renderFailed"));
          await waitForAbortableDelay(900, signal);
          job = await api.rasterJob(job.id, { signal });
        }
        signal.throwIfAborted();
        const result = job.result as RasterRenderResult | undefined;
        if (
          !result ||
          result.delivery !== "xyz" ||
          result.datasetId !== profile.raster.id
        )
          throw new Error(t("remoteMonitor.renderFailed"));
        bounds = result.bounds4326;
        map.addSource("product", {
          type: "raster",
          tiles: [projectUrl(versionedRasterTileUrl(result.tileUrl))],
          tileSize: 256,
          minzoom: result.minZoom,
          maxzoom: result.maxZoom,
          bounds: bounds as [number, number, number, number],
        });
        map.addLayer({
          id: "product-raster",
          type: "raster",
          source: "product",
          paint: {
            "raster-opacity": result.tileSampling === "nearest" ? 1 : 0.9,
            "raster-resampling": result.tileSampling,
            "raster-fade-duration": result.tileSampling === "nearest" ? 0 : 300,
          },
        });
        const layer = createRasterLayerGroup(product.resource, profile)
          ?.children[0];
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
        const color = product.scene === "spartina" ? "#66e0a3" : "#ffb46a";
        setLegend({
          id: String(product.id),
          title: product.name,
          opacity: 0.65,
          updating: false,
          entries: [
            {
              id: "target",
              label:
                product.scene === "spartina"
                  ? t("remoteMonitor.spartina")
                  : product.name,
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
      }
    };
    void load()
      .catch((failure: unknown) => {
        if (!disposed && (!signal.aborted || task.timedOut)) {
          for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id);
          if (map.getSource("product")) map.removeSource("product");
          setLegend(undefined);
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
    };
  }, [map, product?.id, product?.resource.id, product?.resource.updatedAt, t]);
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
        {legend && regionalView && (
          <aside
            className="remote-map-legend"
            aria-label={t("remoteMonitor.legend")}
          >
            <strong>{t("remoteMonitor.legend")}</strong>
            {legend.note && <p>{legend.note}</p>}
            {legend.gradient && (
              <div className="remote-legend-gradient">
                <div
                  style={{
                    background: `linear-gradient(90deg, ${legend.gradient.colors.join(",")})`,
                    opacity: legend.opacity,
                  }}
                />
                <span>{legend.gradient.low}</span>
                <span>{legend.gradient.high}</span>
              </div>
            )}
            {legend.entries.map((entry) => (
              <div className="remote-legend-entry" key={entry.id}>
                <span
                  style={{
                    backgroundColor: entry.color,
                    opacity: legend.opacity,
                  }}
                />
                <span>{entry.label}</span>
              </div>
            ))}
          </aside>
        )}

        {product && regionalView && (
          <div className="remote-map-caption">{product.name}</div>
        )}
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
            disabled={!map || loading || !product}
            onClick={() => focus(true)}
          />
        </Tooltip>
        {product && (
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
      {loading && (
        <div className="monitor-layer-loading" role="status">
          {t("remoteMonitor.loadingMap")}
        </div>
      )}
      {(error || mapError) && (
        <div className="monitor-map-notice">
          <Alert
            type="warning"
            title={error || t("remoteMonitor.mapUnavailable")}
          />
        </div>
      )}
    </>
  );
}
