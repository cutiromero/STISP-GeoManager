import type { Map as MapboxMap } from "mapbox-gl";
import type { MapViewState } from "../types";

export function readMapViewState(map: MapboxMap): MapViewState {
  const bounds = map.getBounds();
  const center = normalizeLngLat(map.getCenter());
  if (!bounds) {
    return {
      center,
      bounds: [center[0], center[1], center[0], center[1]],
      zoom: map.getZoom(),
      bearing: map.getBearing(),
      pitch: map.getPitch(),
    };
  }
  const southWest = bounds.getSouthWest();
  const northEast = bounds.getNorthEast();

  return {
    center,
    bounds: [
      clamp(southWest.lng, -180, 180),
      clamp(southWest.lat, -90, 90),
      clamp(northEast.lng, -180, 180),
      clamp(northEast.lat, -90, 90),
    ],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

export function fitBoundsOptions(basePadding = 72) {
  return {
    padding: basePadding,
    duration: 900,
    essential: true,
  };
}

export function rasterFitBoundsOptions(basePadding = 80) {
  return {
    ...fitBoundsOptions(basePadding),
    maxZoom: 19,
    bearing: 0,
    pitch: 0,
  };
}

function normalizeLngLat(lngLat: {
  lng: number;
  lat: number;
}): [number, number] {
  return [clamp(lngLat.lng, -180, 180), clamp(lngLat.lat, -90, 90)];
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
