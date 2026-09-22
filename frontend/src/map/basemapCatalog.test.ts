import { describe, expect, it } from "vitest";
import {
  availableBasemapFallback,
  createBasemapCatalog,
  resolveBasemapDefinition,
  tiandituMapboxGlyphs,
} from "./basemapCatalog";
import { tiandituTileProviderName } from "./tiandituTileProviderConfig";

describe("basemapCatalog", () => {
  it("provides four user choices and keeps OSM as an internal fallback", () => {
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
      tiandituKey: "tianditu-test-key",
    });

    expect(catalog.map((basemap) => basemap.id)).toEqual([
      "mapbox-satellite",
      "mapbox-streets",
      "tianditu-vector",
      "tianditu-imagery",
      "osm",
    ]);
    expect(
      catalog
        .filter((basemap) => basemap.selectable)
        .map((basemap) => basemap.id),
    ).toEqual([
      "mapbox-satellite",
      "mapbox-streets",
      "tianditu-vector",
      "tianditu-imagery",
    ]);
    expect(catalog[0].id).toBe("mapbox-satellite");
    expect(resolveBasemapDefinition(catalog, "osm")?.selectable).toBe(false);
  });

  it("marks Mapbox choices unavailable when their token is missing", () => {
    const catalog = createBasemapCatalog({ tiandituKey: "test-key" });

    for (const id of ["mapbox-satellite", "mapbox-streets"] as const) {
      const basemap = resolveBasemapDefinition(catalog, id);
      expect(basemap?.credentials).toMatchObject({
        available: false,
        missing: ["mapboxAccessToken"],
        reason: "未配置 Mapbox Token",
      });
    }
  });

  it("marks Tianditu unavailable when its key is missing", () => {
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
    });

    for (const id of ["tianditu-vector", "tianditu-imagery"] as const) {
      expect(resolveBasemapDefinition(catalog, id)?.credentials).toMatchObject({
        available: false,
        missing: ["tiandituKey"],
        reason: "未配置天地图 Key",
      });
    }
  });

  it("keeps Tianditu usable without Mapbox while warning about business fonts", () => {
    const catalog = createBasemapCatalog({ tiandituKey: "test-key" });
    const tianditu = resolveBasemapDefinition(catalog, "tianditu-vector");

    expect(tianditu?.credentials).toMatchObject({
      available: true,
      degraded: true,
      missing: ["mapboxAccessToken"],
    });
    expect(tianditu?.credentials.warning).toContain("业务文字字体能力受限");
    expect(typeof tianditu?.style).toBe("object");
    expect(
      typeof tianditu?.style === "object" ? tianditu.style.glyphs : null,
    ).toBe(tiandituMapboxGlyphs);
  });

  it("builds vec_w and cva_w WMTS sources from the supplied encoded key", () => {
    const rawKey = "test key/+?&";
    const catalog = createBasemapCatalog({ tiandituKey: rawKey });
    const tianditu = resolveBasemapDefinition(catalog, "tianditu-vector");
    expect(tianditu).toBeDefined();
    expect(tianditu?.requireAllSourceIds).toBe(true);
    expect(typeof tianditu?.style).toBe("object");
    if (!tianditu || typeof tianditu.style === "string") {
      throw new Error("天地图应使用内联样式");
    }

    expect(Object.keys(tianditu.style.sources)).toEqual(tianditu.sourceIds);
    const vectorSource = tianditu.style.sources[tianditu.sourceIds[0]] as {
      url?: string;
      tiles?: string[];
      maxzoom?: number;
      provider?: string;
    };
    const labelSource = tianditu.style.sources[tianditu.sourceIds[1]] as {
      url?: string;
      tiles?: string[];
      maxzoom?: number;
      provider?: string;
    };
    expect(vectorSource.tiles).toBeUndefined();
    expect(labelSource.tiles).toBeUndefined();
    expect(vectorSource.maxzoom).toBeUndefined();
    expect(labelSource.maxzoom).toBeUndefined();
    expect(vectorSource.provider).toBe(tiandituTileProviderName);
    expect(labelSource.provider).toBe(tiandituTileProviderName);
    expect(vectorSource.url).toContain("/vec_w/wmts");
    expect(labelSource.url).toContain("/cva_w/wmts");
    expect(vectorSource.url).toContain("REQUEST=GetCapabilities");
    expect(labelSource.url).toContain("REQUEST=GetCapabilities");
    const encodedKey = encodeURIComponent(rawKey);
    for (const url of [vectorSource.url, labelSource.url]) {
      expect(url).toContain(`tk=${encodedKey}`);
      expect(url).not.toContain(rawKey);
    }
    expect(tianditu.style.layers?.map((layer) => layer.id)).toEqual([
      tianditu.sourceIds[0],
      tianditu.sourceIds[1],
    ]);
  });

  it("overzooms the last reliable img_w level while retaining detailed labels", () => {
    const rawKey = "test imagery key/+?&";
    const catalog = createBasemapCatalog({ tiandituKey: rawKey });
    const imagery = resolveBasemapDefinition(catalog, "tianditu-imagery");
    expect(imagery).toBeDefined();
    expect(imagery?.requireAllSourceIds).toBe(true);
    expect(typeof imagery?.style).toBe("object");
    if (!imagery || typeof imagery.style === "string") {
      throw new Error("天地图影像应使用内联样式");
    }

    expect(Object.keys(imagery.style.sources)).toEqual(imagery.sourceIds);
    const imageSource = imagery.style.sources[imagery.sourceIds[0]] as {
      url?: string;
      tiles?: string[];
      maxzoom?: number;
      provider?: string;
    };
    const labelSource = imagery.style.sources[imagery.sourceIds[1]] as {
      url?: string;
      tiles?: string[];
      maxzoom?: number;
      provider?: string;
    };
    expect(imageSource.tiles).toBeUndefined();
    expect(labelSource.tiles).toBeUndefined();
    expect(imageSource.maxzoom).toBeUndefined();
    expect(labelSource.maxzoom).toBeUndefined();
    expect(imageSource.provider).toBe(tiandituTileProviderName);
    expect(labelSource.provider).toBe(tiandituTileProviderName);
    expect(imageSource.url).toContain("/img_w/wmts");
    expect(labelSource.url).toContain("/cia_w/wmts");
    const encodedKey = encodeURIComponent(rawKey);
    for (const url of [imageSource.url, labelSource.url]) {
      expect(url).toContain(`tk=${encodedKey}`);
      expect(url).not.toContain(rawKey);
    }
    expect(imagery.style.layers?.map((layer) => layer.id)).toEqual([
      imagery.sourceIds[0],
      imagery.sourceIds[1],
    ]);
    expect(
      imagery.style.layers?.every((layer) => layer.maxzoom === undefined),
    ).toBe(true);
  });

  it("uses the explicit preference and fallback order", () => {
    const allAvailable = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
      tiandituKey: "tianditu-test-key",
    });
    expect(
      availableBasemapFallback(allAvailable, {
        userPreference: "streets",
        systemDefault: "satellite",
      }).id,
    ).toBe("mapbox-streets");
    expect(
      availableBasemapFallback(allAvailable, {
        userPreference: "unknown",
        systemDefault: "tianditu-imagery",
      }).id,
    ).toBe("tianditu-imagery");
    expect(
      availableBasemapFallback(allAvailable, {
        userPreference: "osm",
        systemDefault: "osm",
      }).id,
    ).toBe("mapbox-satellite");
    expect(availableBasemapFallback(allAvailable).id).toBe("mapbox-satellite");

    const tiandituOnly = createBasemapCatalog({
      tiandituKey: "tianditu-test-key",
    });
    expect(availableBasemapFallback(tiandituOnly).id).toBe("tianditu-vector");

    const noCredentials = createBasemapCatalog({});
    expect(
      availableBasemapFallback(noCredentials, { systemDefault: "osm" }).id,
    ).toBe("osm");
    expect(availableBasemapFallback(noCredentials).id).toBe("osm");
  });

  it("resolves legacy configuration aliases without guessing unknown values", () => {
    const catalog = createBasemapCatalog({
      mapboxAccessToken: "mapbox-test-token",
      tiandituKey: "tianditu-test-key",
    });

    expect(resolveBasemapDefinition(catalog, "satellite")?.id).toBe(
      "mapbox-satellite",
    );
    expect(resolveBasemapDefinition(catalog, "streets")?.id).toBe(
      "mapbox-streets",
    );
    expect(resolveBasemapDefinition(catalog, "osm")?.id).toBe("osm");
    expect(resolveBasemapDefinition(catalog, "not-a-basemap")).toBeUndefined();
  });
});
