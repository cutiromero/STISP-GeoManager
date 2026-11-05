import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";

export type ReviewMapSpotlight = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection;
  beforeLabel?: string;
  afterLabel?: string;
  outlineOnly?: boolean;
  dimBackground?: boolean;
};
