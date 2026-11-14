import { useEffect, useState, type CSSProperties } from "react";
import type { Map as MapboxMap } from "mapbox-gl";
import type {
  MonitoringProduct,
  ProjectMonitorConfig,
  ResourceListItem,
} from "../api/generated/types.gen";
import ProductMap from "./ProductMap";

export type LandcoverView = "classification" | "original" | "overlay" | "swipe";

export default function LandcoverComparisonMap({
  product,
  original,
  displayResource,
  overview,
  config,
  animated,
  mode,
  visibleCodes,
}: {
  product?: MonitoringProduct;
  original?: ResourceListItem;
  displayResource?: ResourceListItem;
  overview?: ResourceListItem;
  config: ProjectMonitorConfig;
  animated: boolean;
  mode: LandcoverView;
  visibleCodes: number[];
}) {
  const [primary, setPrimary] = useState<MapboxMap>();
  const [reference, setReference] = useState<MapboxMap>();
  const [position, setPosition] = useState(50);
  const compare = Boolean(
    (product || displayResource) &&
    original &&
    ["overlay", "swipe"].includes(mode),
  );
  useEffect(() => {
    if (!primary || !reference) return;
    let syncing = false;
    const sync = (from: MapboxMap, to: MapboxMap) => {
      if (syncing) return;
      syncing = true;
      try {
        const center = from.getCenter();
        to.jumpTo({
          center: [center.lng, center.lat],
          zoom: from.getZoom(),
          bearing: from.getBearing(),
          pitch: from.getPitch(),
        });
      } finally {
        syncing = false;
      }
    };
    const first = () => sync(primary, reference);
    const second = () => sync(reference, primary);
    first();
    primary.on("move", first);
    reference.on("move", second);
    return () => {
      primary.off("move", first);
      reference.off("move", second);
    };
  }, [primary, reference]);
  return (
    <div className="landcover-map" data-mode={mode}>
      {compare && (
        <div className="landcover-reference">
          <ProductMap
            resource={original}
            information={false}
            config={config}
            animated={false}
            onMapReady={setReference}
          />
        </div>
      )}
      <div
        className="landcover-primary"
        style={
          {
            "--landcover-clip":
              compare && mode === "swipe"
                ? `inset(0 ${100 - position}% 0 0)`
                : "none",
            "--landcover-class-opacity":
              compare && mode === "overlay" ? position / 100 : 1,
          } as CSSProperties
        }
      >
        <ProductMap
          product={mode === "original" ? undefined : product}
          resource={
            mode === "original"
              ? (original ?? overview)
              : (displayResource ??
                (product ? undefined : (original ?? overview)))
          }
          config={config}
          animated={compare ? false : animated}
          onMapReady={setPrimary}
          focusProduct
          focusKey={original?.id ?? product?.resource.id ?? overview?.id}
          visibleCodes={
            product && mode !== "original" ? visibleCodes : undefined
          }
        />
      </div>
      {compare && ["swipe", "overlay"].includes(mode) && (
        <label className="landcover-compare-control">
          <span>{mode === "swipe" ? "对比位置" : "分类透明度"}</span>
          <input
            type="range"
            min={0}
            max={100}
            value={position}
            onChange={(event) => setPosition(Number(event.target.value))}
          />
        </label>
      )}
    </div>
  );
}
