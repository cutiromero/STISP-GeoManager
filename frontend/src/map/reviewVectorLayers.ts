import type {
  Map as MapboxMap,
  ExpressionSpecification,
  GeoJSONSourceSpecification,
} from "mapbox-gl";
import type {
  GeoJsonFeatureCollection,
  GeoJsonGeometry,
} from "../api/generated/types.gen";
import { record } from "./geologyReviewData";

export type ReviewOverlay = {
  key: string;
  label: string;
  before?: GeoJsonFeatureCollection;
  after?: GeoJsonFeatureCollection;
  color: string;
};

export function reviewOverlayColor(fallback: string): ExpressionSpecification {
  const state: ExpressionSpecification = [
    "coalesce",
    ["get", "state"],
    ["get", "status"],
  ];
  return [
    "case",
    ["has", "fill_color"],
    ["get", "fill_color"],
    ["==", ["get", "grade"], "A"],
    "#db9a35",
    ["==", ["get", "grade"], "B"],
    "#537fc0",
    ["==", state, "downweight"],
    "#ad8b54",
    ["==", state, "review"],
    "#b483b2",
    ["==", state, "exclude"],
    "#8d9baa",
    fallback,
  ];
}

export function reviewOverlayOpacity(): ExpressionSpecification {
  const state: ExpressionSpecification = [
    "coalesce",
    ["get", "state"],
    ["get", "status"],
  ];
  return [
    "case",
    ["==", state, "exclude"],
    0.25,
    ["==", state, "downweight"],
    0.5,
    1,
  ];
}

export function addReviewOverlay(
  map: MapboxMap,
  id: string,
  data: GeoJsonFeatureCollection,
  color: string,
  onFeature: (feature: GeoJsonFeatureCollection["features"][number]) => void,
) {
  map.addSource(id, {
    type: "geojson",
    data: data as GeoJSONSourceSpecification["data"],
  });
  const paint = reviewOverlayColor(color);
  map.addLayer({
    id: `${id}-fill`,
    type: "fill",
    source: id,
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: { "fill-color": paint, "fill-opacity": 0.2 },
  });
  map.addLayer({
    id: `${id}-line`,
    type: "line",
    source: id,
    filter: [
      "all",
      ["!=", ["geometry-type"], "Point"],
      ["!=", ["coalesce", ["get", "state"], ["get", "status"]], "exclude"],
    ],
    paint: {
      "line-color": paint,
      "line-width": 2.1,
      "line-opacity": reviewOverlayOpacity(),
    },
  });
  map.addLayer({
    id: `${id}-excluded`,
    type: "line",
    source: id,
    filter: [
      "all",
      ["==", ["geometry-type"], "LineString"],
      ["==", ["coalesce", ["get", "state"], ["get", "status"]], "exclude"],
    ],
    paint: {
      "line-color": "#8d9baa",
      "line-width": 1.6,
      "line-dasharray": [3, 2],
    },
  });
  map.addLayer({
    id: `${id}-point`,
    type: "circle",
    source: id,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 5,
      "circle-color": [
        "case",
        [
          "in",
          ["to-string", ["get", "inferred"]],
          ["literal", ["true", "True", "1"]],
        ],
        "#ffffff",
        paint,
      ],
      "circle-stroke-color": paint,
      "circle-stroke-width": 2,
    },
  });
  for (const layer of [
    `${id}-fill`,
    `${id}-line`,
    `${id}-excluded`,
    `${id}-point`,
  ]) {
    map.on("click", layer, (event) => {
      const feature = record(event.features?.[0]);
      if (feature.geometry)
        onFeature({
          type: "Feature",
          ...(typeof feature.id === "string" || typeof feature.id === "number"
            ? { id: feature.id }
            : {}),
          geometry: feature.geometry as GeoJsonGeometry,
          properties: record(feature.properties),
        });
    });
    map.on("mouseenter", layer, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", layer, () => {
      map.getCanvas().style.cursor = "";
    });
  }
}
