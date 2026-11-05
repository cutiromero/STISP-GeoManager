import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";

export type ReviewOverlay = {
  key: string;
  label: string;
  before?: GeoJsonFeatureCollection;
  after?: GeoJsonFeatureCollection;
  color: string;
};
