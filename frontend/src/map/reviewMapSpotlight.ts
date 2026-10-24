import mapboxgl, { type Map as MapboxMap } from "mapbox-gl";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import { reviewBounds } from "./geologyReviewData";
import { addReviewOverlay, reviewOverlayOpacity } from "./reviewVectorLayers";

export type ReviewMapSpotlight = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection;
  beforeLabel?: string;
  afterLabel?: string;
};

/** Update only the current object; navigating a story never resends the full map. */
export function applyReviewSpotlight(
  map: MapboxMap,
  side: number,
  spotlight: ReviewMapSpotlight | null | undefined,
  overlayKeys: string[],
  onFeature: (feature: GeoJsonFeatureCollection["features"][number]) => void,
): (() => void) | undefined {
  if (!map.getSource("geological-units")) return;
  const active = Boolean(spotlight);
  map.setPaintProperty("units", "fill-opacity", active ? 0.12 : 0.95);
  map.setPaintProperty("unit-boundaries", "line-opacity", active ? 0.18 : 1);
  for (const key of overlayKeys) {
    const id = `review-${key}`;
    if (map.getLayer(`${id}-fill`)) {
      map.setPaintProperty(`${id}-fill`, "fill-opacity", active ? 0.035 : 0.2);
      map.setPaintProperty(
        `${id}-line`,
        "line-opacity",
        active ? 0.12 : reviewOverlayOpacity(),
      );
      map.setPaintProperty(`${id}-excluded`, "line-opacity", active ? 0.12 : 1);
      map.setPaintProperty(`${id}-point`, "circle-opacity", active ? 0.12 : 1);
      map.setPaintProperty(
        `${id}-point`,
        "circle-stroke-opacity",
        active ? 0.12 : 1,
      );
    }
  }
  for (const id of ["change-fill", "change-outline", "change-point"])
    if (map.getLayer(id))
      map.setLayoutProperty(id, "visibility", active ? "none" : "visible");
  const id = "story-focus";
  const layers = ["fill", "line", "excluded", "point"].map(
    (suffix) => `${id}-${suffix}`,
  );
  if (!spotlight) {
    for (const layer of layers)
      if (map.getLayer(layer))
        map.setLayoutProperty(layer, "visibility", "none");
    return;
  }
  const data = side ? spotlight.after : spotlight.before;
  const source = map.getSource(id) as mapboxgl.GeoJSONSource | undefined;
  if (source)
    source.setData(data as mapboxgl.GeoJSONSourceSpecification["data"]);
  else {
    addReviewOverlay(map, id, data, side ? "#286ba8" : "#cf7628", onFeature);
    map.setPaintProperty(`${id}-fill`, "fill-opacity", [
      "case",
      ["boolean", ["get", "_review_outlineOnly"], false],
      0,
      0.6,
    ]);
    map.setPaintProperty(`${id}-line`, "line-width", 3.5);
    map.setPaintProperty(`${id}-excluded`, "line-width", 3.5);
    map.setPaintProperty(`${id}-point`, "circle-radius", 8);
  }
  for (const layer of layers)
    map.setLayoutProperty(layer, "visibility", "visible");
  const label = side ? spotlight.afterLabel : spotlight.beforeLabel;
  const bounds = reviewBounds(data);
  if (!label || !bounds) return;
  const element = document.createElement("div");
  element.className = "geology-review-focus-label";
  element.textContent = label;
  const marker = new mapboxgl.Marker({
    element,
    anchor: "bottom",
    offset: [0, -12],
  })
    .setLngLat([(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2])
    .addTo(map);
  return () => marker.remove();
}
