import type {
  AnyLayer,
  GeoJSONSource,
  Map as MapboxMap,
  MapMouseEvent,
} from "mapbox-gl";
import type { GeoJsonGeometry, SpatialFilter } from "../types";
import { geometryFromPoints } from "../utils/geometry";
import { removeLayerGroup } from "./vectorLayerSync";

const previewSourceId = "query-draw-preview";
const previewFillId = "query-draw-preview-fill";
const previewLineId = "query-draw-preview-line";
const defaultRangeStyle: PolygonLayerStyle = {
  fillColor: "#ef4444",
  fillOpacity: 0.16,
  lineColor: "#ef4444",
  lineOpacity: 0.95,
  lineWidth: 2,
};
const polygonGeometryTypes = ["Polygon", "MultiPolygon"];
const lineGeometryTypes = [
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
];
export type DrawMode = SpatialFilter["mode"];

export interface PolygonLayerStyle {
  fillColor: string;
  fillOpacity: number;
  lineColor: string;
  lineOpacity: number;
  lineWidth: number;
  beforeId?: string;
}

function showDrawPreview(map: MapboxMap, geometry: GeoJsonGeometry) {
  upsertPolygonLayer(
    map,
    previewSourceId,
    previewFillId,
    previewLineId,
    geometry,
    { ...defaultRangeStyle, fillOpacity: 0.18 },
  );
}

function clearDrawPreview(map: MapboxMap) {
  removeLayerGroup(map, previewSourceId, [previewFillId, previewLineId], {
    cleanInteraction: false,
  });
}

export function bindGeometryDraw(
  map: MapboxMap,
  mode: DrawMode,
  onComplete: (geometry: GeoJsonGeometry) => void,
) {
  clearDrawPreview(map);
  const canvas = map.getCanvas();
  canvas.dataset.drawing = "true";
  canvas.style.cursor = "crosshair";
  map.doubleClickZoom.disable();
  let start: [number, number] | null = null;
  let polygonPoints: Array<[number, number]> = [];

  const handleClick = (event: MapMouseEvent) => {
    const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];
    if (mode === "polygon") {
      polygonPoints = [...polygonPoints, point];
      if (polygonPoints.length >= 2) {
        showDrawPreview(map, polygonPreviewGeometry(polygonPoints));
      }
      return;
    }
    if (!start) {
      start = point;
      return;
    }
    const geometry = geometryFromPoints(mode, start, point);
    showDrawPreview(map, geometry);
    onComplete(geometry);
  };

  const handleMouseMove = (event: MapMouseEvent) => {
    const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];
    if (mode === "polygon" && polygonPoints.length > 0) {
      showDrawPreview(map, polygonPreviewGeometry(polygonPoints, point));
    } else if (start) {
      showDrawPreview(map, geometryFromPoints(mode, start, point));
    }
  };

  const handleDoubleClick = (event: MapMouseEvent) => {
    if (mode !== "polygon" || polygonPoints.length < 3) return;
    event.preventDefault();
    const geometry: GeoJsonGeometry = {
      type: "Polygon",
      coordinates: [[...polygonPoints, polygonPoints[0]]],
    };
    showDrawPreview(map, geometry);
    onComplete(geometry);
  };

  map.on("click", handleClick);
  map.on("mousemove", handleMouseMove);
  map.on("dblclick", handleDoubleClick);

  return () => {
    map.off("click", handleClick);
    map.off("mousemove", handleMouseMove);
    map.off("dblclick", handleDoubleClick);
    map.doubleClickZoom.enable();
    delete canvas.dataset.drawing;
    canvas.style.cursor = "";
    clearDrawPreview(map);
  };
}

export function upsertPolygonLayer(
  map: MapboxMap,
  sourceId: string,
  fillId: string,
  lineId: string,
  geometry: GeoJsonGeometry,
  style: PolygonLayerStyle = defaultRangeStyle,
) {
  const data = {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry }],
  };
  if (!map.getSource(sourceId)) {
    map.addSource(sourceId, { type: "geojson", data: data as never });
  } else {
    (map.getSource(sourceId) as GeoJSONSource).setData(data as never);
  }
  upsertStyledLayer(
    map,
    {
      id: fillId,
      type: "fill",
      source: sourceId,
      filter: ["match", ["geometry-type"], polygonGeometryTypes, true, false],
      paint: {
        "fill-color": style.fillColor,
        "fill-opacity": style.fillOpacity,
      },
    },
    style.beforeId,
  );
  upsertStyledLayer(
    map,
    {
      id: lineId,
      type: "line",
      source: sourceId,
      filter: ["match", ["geometry-type"], lineGeometryTypes, true, false],
      paint: {
        "line-color": style.lineColor,
        "line-width": style.lineWidth,
        "line-opacity": style.lineOpacity,
      },
    },
    style.beforeId,
  );
}

function upsertStyledLayer(map: MapboxMap, layer: AnyLayer, beforeId?: string) {
  if (!map.getLayer(layer.id)) {
    map.addLayer(layer, beforeId);
  } else {
    if ("filter" in layer) {
      map.setFilter(layer.id, layer.filter);
    }
    const writableMap = map as unknown as {
      setPaintProperty: (
        layerId: string,
        property: string,
        value: unknown,
      ) => void;
    };
    for (const [property, value] of Object.entries(layer.paint ?? {})) {
      writableMap.setPaintProperty(layer.id, property, value);
    }
  }
  if (beforeId && map.getLayer(beforeId) && map.getLayer(layer.id)) {
    map.moveLayer(layer.id, beforeId);
  }
}

function polygonPreviewGeometry(
  points: Array<[number, number]>,
  cursor?: [number, number],
): GeoJsonGeometry {
  const coordinates = cursor ? [...points, cursor] : points;
  if (coordinates.length < 3) {
    return { type: "LineString", coordinates };
  }
  return {
    type: "Polygon",
    coordinates: [[...coordinates, coordinates[0]]],
  };
}
