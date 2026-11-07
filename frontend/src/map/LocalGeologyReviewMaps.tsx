import AutomaticReviewMarkers from "./AutomaticReviewMarkers";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import type {
  ComputeMapPreview,
  AgentAutomaticReviewMap,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import type { ReviewOverlay } from "./reviewVectorLayers";
import { sharedComparisonMaps } from "./comparisonColors";
import type { ReviewMapSpotlight } from "./reviewMapSpotlight";
import "./geology-review-workspace.css";
import {
  geologicalColor,
  reviewBounds,
  reviewLegend,
} from "./geologyReviewData";
import {
  projectReviewPosition,
  reviewGeometry,
  reviewViewport,
  zoomReviewViewport,
  type ReviewViewport,
} from "./localReviewGeometry";

type Feature = GeoJsonFeatureCollection["features"][number];
type Props = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
  bounds: [number, number, number, number] | null;
  onSelect: (index: number) => void;
  previewLabel?: string;
  inspectionOnly?: boolean;
  single?: boolean;
  singleSide?: "before" | "after";
  automaticPositions?: AgentAutomaticReviewMap["points"];
  overlays?: ReviewOverlay[];
  onInspect?: (feature: Feature) => void;
  beforeLabel?: string;
  afterLabel?: string;
  compactLegend?: boolean;
  spotlight?: ReviewMapSpotlight | null;
  rasterOverlays?: {
    key: string;
    before?: ComputeMapPreview;
    after?: ComputeMapPreview;
  }[];
};
const emptyOverlays: NonNullable<Props["overlays"]> = [];

function featureColor(feature: Feature, fallback: string) {
  if (typeof feature.properties.fill_color === "string")
    return feature.properties.fill_color;
  const { grade, state, status } = feature.properties;
  if (grade === "A") return "#db9a35";
  if (grade === "B") return "#537fc0";
  return (
    (
      {
        downweight: "#ad8b54",
        review: "#b483b2",
        exclude: "#8d9baa",
      } as Record<string, string>
    )[String(state ?? status)] ?? fallback
  );
}

const VectorFeatures = memo(function VectorFeatures({
  data,
  layer,
  color,
  opacity = 1,
  outlineOnly = false,
  radius,
  onFeature,
}: {
  data: GeoJsonFeatureCollection;
  layer: string;
  color?: string;
  opacity?: number;
  outlineOnly?: boolean;
  radius: number;
  onFeature?: (feature: Feature, index: number) => void;
}) {
  const geometries = useMemo(
    () => data.features.map((feature) => reviewGeometry(feature.geometry)),
    [data],
  );
  return (
    <g data-layer={layer} opacity={opacity}>
      {data.features.map((feature, index) => {
        const shape = geometries[index]!;
        const state = String(
          feature.properties.state ?? feature.properties.status ?? "",
        );
        const outline =
          outlineOnly || feature.properties._review_outlineOnly === true;
        const fill = color
          ? outline
            ? color
            : featureColor(feature, color)
          : String(
              feature.properties.fill_color ??
                geologicalColor(String(feature.properties.class)),
            );
        const excluded = state === "exclude";
        const inferred = ["true", "True", "1"].includes(
          String(feature.properties.inferred),
        );
        const select = () => onFeature?.(feature, index);
        return (
          <g
            className={onFeature ? "geology-review-feature" : undefined}
            key={String(
              feature.id ??
                feature.properties.feature_id ??
                JSON.stringify(feature),
            )}
            data-feature-id={String(
              feature.properties.feature_id ??
                feature.properties.line_id ??
                feature.id ??
                "",
            )}
            data-geometry={feature.geometry.type}
            opacity={
              outline ? 1 : excluded ? 0.25 : state === "downweight" ? 0.5 : 1
            }
            onClick={select}
            role={onFeature ? "button" : undefined}
            tabIndex={onFeature ? 0 : undefined}
            aria-label={
              onFeature
                ? String(
                    feature.properties.name ??
                      feature.properties.feature_id ??
                      `图斑 ${index + 1}`,
                  )
                : undefined
            }
            onKeyDown={
              onFeature
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      select();
                    }
                  }
                : undefined
            }
            style={{ cursor: onFeature ? "pointer" : undefined }}
          >
            {shape.path && (
              <path
                d={shape.path}
                fill={shape.polygon && !outline ? fill : "none"}
                fillRule="evenodd"
                fillOpacity={
                  color && !outline
                    ? 0.22
                    : Number(feature.properties.fill_opacity ?? 0.95)
                }
                stroke={
                  color || !shape.polygon
                    ? fill
                    : String(feature.properties.stroke_color ?? "#66768c")
                }
                strokeWidth={outline ? 3.5 : color ? 2.1 : 0.8}
                strokeDasharray={
                  excluded ||
                  layer === "actual-differences" ||
                  feature.properties._review_navigation === true
                    ? "3 2"
                    : undefined
                }
                vectorEffect="non-scaling-stroke"
              />
            )}
            {onFeature && shape.path && (
              <path
                className="geology-review-feature-highlight"
                d={shape.path}
                fill="none"
                stroke="#006cd1"
                strokeWidth={3}
                vectorEffect="non-scaling-stroke"
                pointerEvents="none"
              />
            )}
            {onFeature &&
              shape.points.map((point) => (
                <circle
                  key={`focus:${point.join(",")}`}
                  className="geology-review-feature-highlight"
                  cx={point[0]}
                  cy={point[1]}
                  r={radius * 1.5}
                  fill="none"
                  stroke="#006cd1"
                  strokeWidth={3}
                  vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
              ))}
            {shape.points.map((point) => (
              <circle
                key={point.join(",")}
                cx={point[0]}
                cy={point[1]}
                r={radius}
                fill={outline ? "none" : inferred ? "#fff" : fill}
                stroke={fill}
                strokeWidth={outline ? 3 : 2}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </g>
        );
      })}
    </g>
  );
});

export default function LocalGeologyReviewMaps({
  before: originalBefore,
  after: originalAfter,
  differences,
  bounds,
  onSelect,
  previewLabel = "建议修改范围，尚未执行",
  inspectionOnly = false,
  single = false,
  singleSide = "before",
  overlays: originalOverlays = emptyOverlays,
  onInspect,
  beforeLabel = "待检查地质图",
  afterLabel = "修正后地质图",
  compactLegend = false,
  spotlight,
  rasterOverlays = [],
  automaticPositions,
}: Props) {
  const [before, after] = useMemo(
    () => sharedComparisonMaps(originalBefore, originalAfter),
    [originalBefore, originalAfter],
  );
  const overlays = useMemo(
    () =>
      originalOverlays.map((overlay) => {
        if (!overlay.before || !overlay.after) return overlay;
        const [before, after] = sharedComparisonMaps(
          overlay.before,
          overlay.after,
        );
        return { ...overlay, before, after: after ?? undefined };
      }),
    [originalOverlays],
  );
  const fitted = useMemo(
    () => reviewViewport(bounds ?? reviewBounds(before) ?? [95, 35, 97, 37]),
    [bounds, before],
  );
  const [view, setView] = useState(fitted);
  const drag = useRef<{
    x: number;
    y: number;
    view: ReviewViewport;
    scale: number;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const containers = useRef<Array<HTMLDivElement | null>>([]);
  const [mapSize, setMapSize] = useState({ width: 600, height: 400 });
  useEffect(() => {
    const element = containers.current[singleSide === "after" ? 1 : 0];
    if (!element) return;
    const update = () =>
      setMapSize({
        width: Math.max(1, element.clientWidth),
        height: Math.max(1, element.clientHeight),
      });
    const observer = new ResizeObserver(update);
    observer.observe(element);
    update();
    return () => observer.disconnect();
  }, [singleSide]);
  useEffect(() => setView(fitted), [fitted]);
  useEffect(() => {
    const preventPageScroll = (event: WheelEvent) => event.preventDefault();
    const elements = containers.current.filter((element) => element !== null);
    elements.forEach((element) =>
      element.addEventListener("wheel", preventPageScroll, { passive: false }),
    );
    return () =>
      elements.forEach((element) =>
        element.removeEventListener("wheel", preventPageScroll),
      );
  }, []);
  const legend = (
    <>
      {reviewLegend(before, ...(after ? [after] : [])).map((item) => (
        <span key={item.key}>
          <i style={{ background: item.color }} />
          {item.name}
        </span>
      ))}
    </>
  );
  return (
    <>
      <div className={`geology-review-map-pair${single ? " is-single" : ""}`}>
        {(single ? [singleSide === "after" ? 1 : 0] : [0, 1]).map((side) => {
          const units = side ? (after ?? before) : before;
          const focus =
            spotlight && (side ? spotlight.after : spotlight.before);
          const focusBounds = focus && reviewBounds(focus);
          const label = side ? spotlight?.afterLabel : spotlight?.beforeLabel;
          const labelPosition =
            focusBounds &&
            projectReviewPosition([
              (focusBounds[0] + focusBounds[2]) / 2,
              (focusBounds[1] + focusBounds[3]) / 2,
            ]);
          const radius = Math.max(view.width, view.height) / 140;
          return (
            <section key={side}>
              <header>
                {side ? (after ? afterLabel : previewLabel) : beforeLabel}
              </header>
              <div
                ref={(element) => {
                  containers.current[side] = element;
                }}
                className="geology-review-map-canvas geology-review-local-map"
                aria-label={
                  side
                    ? after
                      ? "修正后地质图地图"
                      : inspectionOnly
                        ? "检查后原图地图"
                        : "建议修改范围地图"
                    : "待检查地质图地图"
                }
                aria-busy={false}
              >
                <div className="geology-review-local-controls">
                  <button
                    type="button"
                    aria-label="放大地图"
                    onClick={() =>
                      setView((current) => zoomReviewViewport(current, 0.5))
                    }
                  >
                    ＋
                  </button>
                  <button
                    type="button"
                    aria-label="缩小地图"
                    onClick={() =>
                      setView((current) => zoomReviewViewport(current, 2))
                    }
                  >
                    −
                  </button>
                  <button
                    type="button"
                    aria-label="重置地图范围"
                    onClick={() => setView(fitted)}
                  >
                    ⌂
                  </button>
                </div>
                <svg
                  width="100%"
                  height="100%"
                  viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
                  aria-label="本地矢量图层"
                  role="group"
                  tabIndex={0}
                  onWheel={(event) => {
                    const matrix = event.currentTarget.getScreenCTM();
                    if (!matrix) return;
                    const anchor = new DOMPoint(
                      event.clientX,
                      event.clientY,
                    ).matrixTransform(matrix.inverse());
                    setView((current) =>
                      zoomReviewViewport(
                        current,
                        Math.exp(
                          Math.max(-1, Math.min(1, event.deltaY * 0.002)),
                        ),
                        [anchor.x, anchor.y],
                      ),
                    );
                  }}
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    const matrix = event.currentTarget.getScreenCTM();
                    if (!matrix) return;
                    drag.current = {
                      x: event.clientX,
                      y: event.clientY,
                      view,
                      scale: matrix.a,
                      moved: false,
                    };
                    suppressClick.current = false;
                  }}
                  onPointerMove={(event) => {
                    const start = drag.current;
                    if (!start) return;
                    const deltaX = event.clientX - start.x,
                      deltaY = event.clientY - start.y;
                    if (!start.moved && Math.hypot(deltaX, deltaY) < 3) return;
                    start.moved = true;
                    suppressClick.current = true;
                    event.currentTarget.setPointerCapture(event.pointerId);
                    setView({
                      ...start.view,
                      x: start.view.x - deltaX / start.scale,
                      y: start.view.y - deltaY / start.scale,
                    });
                  }}
                  onPointerUp={() => {
                    drag.current = null;
                  }}
                  onPointerCancel={() => {
                    drag.current = null;
                  }}
                  onClickCapture={(event) => {
                    if (suppressClick.current) {
                      event.stopPropagation();
                      suppressClick.current = false;
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    const moves: Record<string, [number, number]> = {
                      ArrowLeft: [-1, 0],
                      ArrowRight: [1, 0],
                      ArrowUp: [0, -1],
                      ArrowDown: [0, 1],
                    };
                    const move = moves[event.key];
                    if (move) {
                      event.preventDefault();
                      setView((current) => ({
                        ...current,
                        x: current.x + (move[0] * current.width) / 10,
                        y: current.y + (move[1] * current.height) / 10,
                      }));
                    } else if (event.key === "+" || event.key === "-") {
                      event.preventDefault();
                      setView((current) =>
                        zoomReviewViewport(
                          current,
                          event.key === "+" ? 0.5 : 2,
                        ),
                      );
                    }
                  }}
                >
                  <VectorFeatures
                    data={units}
                    layer="geological-units"
                    opacity={
                      spotlight && spotlight.dimBackground !== false ? 0.15 : 1
                    }
                    radius={radius}
                    onFeature={onInspect}
                  />
                  {side === 1 && automaticPositions && (
                    <AutomaticReviewMarkers
                      points={automaticPositions}
                      view={view}
                      width={mapSize.width}
                      height={mapSize.height}
                    />
                  )}
                  {rasterOverlays.map((layer) => {
                    const image = side === 0 ? layer.before : layer.after;
                    if (!image) return null;
                    const [west, north] = projectReviewPosition(
                      image.imageCoordinates[0],
                    );
                    const [east, south] = projectReviewPosition(
                      image.imageCoordinates[2],
                    );
                    return (
                      <image
                        key={layer.key}
                        data-layer={layer.key}
                        href={image.imageUrl}
                        x={west}
                        y={north}
                        width={east - west}
                        height={south - north}
                        preserveAspectRatio="none"
                        style={{
                          imageRendering:
                            layer.key === "prospect-confidence"
                              ? "auto"
                              : "pixelated",
                        }}
                      />
                    );
                  })}
                  {overlays.map((overlay) => {
                    const data = side
                      ? (overlay.after ?? overlay.before)
                      : overlay.before;
                    return data ? (
                      <VectorFeatures
                        key={overlay.key}
                        data={data}
                        layer={`review-${overlay.key}`}
                        color={overlay.color}
                        opacity={spotlight ? 0.12 : 1}
                        radius={radius}
                        onFeature={onInspect}
                      />
                    ) : null;
                  })}
                  {!spotlight && (
                    <VectorFeatures
                      data={differences}
                      layer="actual-differences"
                      color="#c86612"
                      radius={radius}
                      onFeature={(_, index) => onSelect(index)}
                    />
                  )}
                  {focus && (
                    <VectorFeatures
                      data={focus}
                      layer="story-focus"
                      color={side ? "#006cd1" : "#ce287a"}
                      outlineOnly={spotlight?.outlineOnly}
                      radius={radius * 1.6}
                      onFeature={onInspect}
                    />
                  )}
                  {label && labelPosition && (
                    <text
                      x={labelPosition[0]}
                      y={labelPosition[1] - radius * 2}
                      fontSize={radius * 2.2}
                      textAnchor="middle"
                      fill="#1d3753"
                      stroke="#fff"
                      strokeWidth={radius * 0.4}
                      paintOrder="stroke"
                      pointerEvents="none"
                    >
                      {label}
                    </text>
                  )}
                </svg>
              </div>
            </section>
          );
        })}
      </div>
      <div className="geology-review-map-legend" aria-label="统一地质类别配色">
        {rasterOverlays
          .filter((layer) => layer.key.startsWith("alteration:"))
          .flatMap(
            (layer) =>
              (layer.after ?? layer.before)?.metadata.colorTable
                ?.filter((item) => !item.color.endsWith("00"))
                .map((item) => (
                  <span key={`${layer.key}:${item.value}`}>
                    <i style={{ background: item.color }} />
                    {item.label}
                  </span>
                )) ?? [],
          )}
        {overlays.flatMap((overlay) => {
          const classes = new Map<string, string>();
          for (const feature of [
            ...(overlay.before?.features ?? []),
            ...(overlay.after?.features ?? []),
          ]) {
            if (
              typeof feature.properties.legend_label === "string" &&
              typeof feature.properties.fill_color === "string"
            )
              classes.set(
                feature.properties.legend_label,
                feature.properties.fill_color,
              );
          }
          return classes.size
            ? [...classes].map(([label, color]) => (
                <span key={`${overlay.key}:${label}`}>
                  <i style={{ background: color }} />
                  {overlay.label} / {label}
                </span>
              ))
            : [
                <span key={overlay.key}>
                  <i style={{ background: overlay.color }} />
                  {overlay.label}
                </span>,
              ];
        })}
        {overlays.some((overlay) => overlay.key === "intersections") && (
          <span>● 几何交汇 / ○ 推测交汇</span>
        )}
        {compactLegend ? (
          <details className="geology-review-lithology-legend">
            <summary>查看岩性配色</summary>
            <div>{legend}</div>
          </details>
        ) : (
          legend
        )}
        {differences.features.length > 0 && (
          <span>
            <i className="geology-review-change-swatch" />
            {after
              ? "实际修改范围"
              : inspectionOnly
                ? "检查问题范围"
                : "建议修改范围"}
          </span>
        )}
      </div>
    </>
  );
}
