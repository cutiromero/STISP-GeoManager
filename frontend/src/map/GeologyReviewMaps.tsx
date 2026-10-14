import mapboxgl, { type Map as MapboxMap } from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { Alert } from "antd";
import { useEffect, useRef, useState } from "react";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import { geologicalColor, record, reviewLegend } from "./geologyReviewData";

export default function GeologyReviewMaps({
  before,
  after,
  differences,
  bounds,
  onSelect,
  accessToken,
  previewLabel = "建议修改范围 · 尚未执行",
}: {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  bounds: [number, number, number, number] | null;
  onSelect: (index: number) => void;
  accessToken: string;
  previewLabel?: string;
}) {
  const left = useRef<HTMLDivElement>(null),
    right = useRef<HTMLDivElement>(null);
  const maps = useRef<MapboxMap[]>([]);
  const latest = useRef({ before, after, differences, bounds, onSelect });
  const [error, setError] = useState("");
  const [ready, setReady] = useState([false, false]);
  latest.current = { before, after, differences, bounds, onSelect };
  useEffect(() => {
    if (!left.current || !right.current) return;
    let syncing = false,
      disposed = false;
    setError("");
    setReady([false, false]);
    const observer = new ResizeObserver(() =>
      maps.current.forEach((map) => map.resize()),
    );
    try {
      for (const container of [left.current, right.current]) {
        maps.current.push(
          new mapboxgl.Map({
            container,
            style: {
              version: 8,
              sources: {},
              layers: [
                {
                  id: "background",
                  type: "background",
                  paint: { "background-color": "#f4f7fb" },
                },
              ],
            },
            center: [96, 36],
            zoom: 8,
            attributionControl: false,
            collectResourceTiming: false,
            performanceMetricsCollection: false,
            accessToken,
          }),
        );
      }
      maps.current.forEach((map, index) => {
        map.addControl(
          new mapboxgl.NavigationControl({ showCompass: false }),
          "top-right",
        );
        map.on("error", () => {
          if (!disposed) setError("地图渲染失败，请刷新或核对图件后重试。");
        });
        map.on("idle", () => {
          if (!disposed)
            setReady((value) =>
              value[index]
                ? value
                : value.map((item, position) =>
                    position === index ? true : item,
                  ),
            );
        });
        map.on("move", () => {
          const other = maps.current[1 - index];
          if (disposed || syncing || !other) return;
          syncing = true;
          try {
            other.jumpTo({
              center: map.getCenter(),
              zoom: map.getZoom(),
              bearing: map.getBearing(),
              pitch: map.getPitch(),
            });
          } finally {
            syncing = false;
          }
        });
        map.on("load", () => {
          if (disposed) return;
          const state = latest.current;
          const data = index ? (state.after ?? state.before) : state.before;
          map.addSource("geological-units", {
            type: "geojson",
            data: data as mapboxgl.GeoJSONSourceSpecification["data"],
          });
          const classes = [
            ...new Set(
              [...state.before.features, ...(state.after?.features ?? [])].map(
                (feature) => String(feature.properties.class),
              ),
            ),
          ];
          const color: mapboxgl.ExpressionSpecification = [
            "match",
            ["to-string", ["get", "class"]],
          ];
          classes.forEach((value) => color.push(value, geologicalColor(value)));
          color.push("#d4dce5");
          map.addLayer({
            id: "units",
            type: "fill",
            source: "geological-units",
            paint: { "fill-color": color, "fill-opacity": 0.95 },
          });
          map.addLayer({
            id: "unit-boundaries",
            type: "line",
            source: "geological-units",
            paint: { "line-color": "#66768c", "line-width": 0.8 },
          });
          const highlighted = {
            ...state.differences,
            features: state.differences.features.map((feature, position) => ({
              ...feature,
              properties: { ...feature.properties, review_index: position },
            })),
          };
          map.addSource("actual-differences", {
            type: "geojson",
            data: highlighted as mapboxgl.GeoJSONSourceSpecification["data"],
          });
          map.addLayer({
            id: "change-fill",
            type: "fill",
            source: "actual-differences",
            paint: { "fill-color": "#e99032", "fill-opacity": 0.22 },
          });
          map.addLayer({
            id: "change-outline",
            type: "line",
            source: "actual-differences",
            paint: {
              "line-color": "#c86612",
              "line-width": 3,
              "line-dasharray": [3, 2],
            },
          });
          map.on("click", "change-fill", (event) => {
            const row = Number(
              record(record(event.features?.[0]).properties).review_index,
            );
            if (
              Number.isInteger(row) &&
              row >= 0 &&
              row < latest.current.differences.features.length
            )
              latest.current.onSelect(row);
          });
          map.on("mouseenter", "change-fill", () => {
            map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", "change-fill", () => {
            map.getCanvas().style.cursor = "";
          });
          if (state.bounds)
            map.fitBounds(state.bounds, {
              padding: 35,
              maxZoom: 16,
              duration: 0,
            });
        });
      });
      observer.observe(left.current);
      observer.observe(right.current);
    } catch {
      setError("当前浏览器无法显示地图，请启用 WebGL 或更换浏览器后重试。");
    }
    return () => {
      disposed = true;
      observer.disconnect();
      maps.current.forEach((map) => map.remove());
      maps.current = [];
    };
  }, [before, after, differences, accessToken]);
  useEffect(() => {
    const primary = maps.current[0];
    if (bounds && primary?.isStyleLoaded())
      primary.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 350 });
  }, [bounds]);
  return (
    <>
      {error && <Alert type="error" showIcon title={error} />}
      <div className="geology-review-map-pair">
        <section>
          <header>待检查地质图</header>
          <div
            ref={left}
            className="geology-review-map-canvas"
            aria-label="待检查地质图地图"
            aria-busy={!ready[0]}
          />
        </section>
        <section>
          <header>{after ? "修正后地质图" : previewLabel}</header>
          <div
            ref={right}
            className="geology-review-map-canvas"
            aria-label={after ? "修正后地质图地图" : "建议修改范围地图"}
            aria-busy={!ready[1]}
          />
        </section>
      </div>
      <div className="geology-review-map-legend" aria-label="统一地质类别配色">
        {reviewLegend(before, ...(after ? [after] : [])).map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {item.name}
          </span>
        ))}
        <span>
          <i className="geology-review-change-swatch" />
          {after ? "实际修改范围" : "建议修改范围"}
        </span>
      </div>
    </>
  );
}
