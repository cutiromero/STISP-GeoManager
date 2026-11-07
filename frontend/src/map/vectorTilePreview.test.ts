import { beforeEach, afterEach, describe, expect, it } from "vitest";
import { cloneDefaultVectorSymbolization } from "../symbolization";
import { createEmptyLayerGroup } from "../utils/layerFactory";
import {
  attachVectorTilePreview,
  vectorTileSourceOptions,
} from "./vectorTilePreview";
import {
  exactViewportExportQuery,
  viewportQueryPayload,
} from "./viewportVectorQuery";
import { featureStateTarget } from "./mapState";
import { upsertLayer } from "./styleHelpers";
import { vi } from "vitest";
import type { LoadedVectorLayer } from "../types";
import type { Map as MapboxMap, MapboxGeoJSONFeature } from "mapbox-gl";

const preview = {
  revision: "0".repeat(24),
  tileUrl: "/api/tiles/{z}/{x}/{y}.pbf",
  rawTileUrl: "/api/tiles/{z}/{x}/{y}.pbf?aggregate=0",
  sourceLayer: "features" as const,
  minZoom: 0 as const,
  maxZoom: 10 as const,
  bounds: [-180, -80, 180, 80],
  clustered: true,
  featureCount: 39953,
};
function layer(): LoadedVectorLayer {
  return {
    id: "p",
    name: "灾害",
    layerType: "vector",
    sourceResource: createEmptyLayerGroup("p").sourceResource,
    geojson: { type: "FeatureCollection", features: [] },
    geometryType: "Point",
    visible: true,
    summary: "",
    metadata: {},
    fields: [],
    symbolization: cloneDefaultVectorSymbolization(),
  };
}
describe("prepared vector previews", () => {
  beforeEach(() =>
    vi.stubGlobal("window", { location: { origin: "http://localhost" } }),
  );
  afterEach(() => vi.unstubAllGlobals());
  it("uses aggregate tiles by default and raw tiles when disabled or heatmap", () => {
    const l = attachVectorTilePreview(layer(), preview);
    expect(vectorTileSourceOptions(l).tiles[0]).not.toContain("aggregate=0");
    l.symbolization.cluster.enabled = false;
    expect(vectorTileSourceOptions(l).tiles[0]).toContain("aggregate=0");
    l.symbolization.cluster.enabled = true;
    l.symbolization.pointMode = "heatmap";
    expect(vectorTileSourceOptions(l).tiles[0]).toContain("aggregate=0");
  });
  it("exports original points with stable source IDs, never cluster nodes", () => {
    const l = attachVectorTilePreview(layer(), preview);
    const body = viewportQueryPayload([80, 40, 90, 45], 30000, "Point");
    l.metadata.视野查询键 = JSON.stringify([7, "revision", body]);
    const query = exactViewportExportQuery(l)!;
    expect(query).toEqual({
      attributeFilters: [],
      spatialFilter: body.spatialFilter,
      limit: 1500,
      sourceFeatureIds: true,
    });
    expect(query.displayGeometry).toBeUndefined();
  });
  it("addresses a selected vector feature by source-layer as well as source and fid", () => {
    expect(
      featureStateTarget({
        id: 42,
        source: "loaded-gas",
        sourceLayer: "features",
      } as MapboxGeoJSONFeature),
    ).toEqual({ id: 42, source: "loaded-gas", sourceLayer: "features" });
  });
  it("adds the vector source-layer to styles while preserving ordinary GeoJSON styles", () => {
    const map = {
      style: {},
      getSource: vi.fn(() => ({ type: "vector" })),
      getLayer: vi.fn(),
      addLayer: vi.fn(),
    } as unknown as MapboxMap;
    upsertLayer(map, { id: "gas-line", type: "line", source: "loaded-gas" });
    expect(map.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ "source-layer": "features" }),
    );
  });
});
