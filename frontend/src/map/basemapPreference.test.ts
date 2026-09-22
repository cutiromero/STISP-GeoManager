import { describe, expect, it } from "vitest";
import {
  basemapPreferenceKey,
  readBasemapPreference,
  writeBasemapPreference,
} from "./basemapPreference";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("basemapPreference", () => {
  it("does not restore the old Tianditu preference after the Mapbox default upgrade", () => {
    const storage = memoryStorage({
      "geomanager.basemap.v1:user:8": "tianditu-imagery",
    });
    expect(readBasemapPreference("user:8", storage)).toBeNull();
    writeBasemapPreference("user:8", "mapbox-streets", storage);
    expect(readBasemapPreference("user:8", storage)).toBe("mapbox-streets");
  });
  it("isolates a saved preference by user scope", () => {
    const storage = memoryStorage();

    expect(writeBasemapPreference("user:8", "tianditu-vector", storage)).toBe(
      true,
    );

    expect(readBasemapPreference("user:8", storage)).toBe("tianditu-vector");
    expect(readBasemapPreference("user:9", storage)).toBeNull();
  });

  it("ignores an unknown or obsolete stored id", () => {
    const key = basemapPreferenceKey("user:8");
    const storage = memoryStorage({ [key]: "unknown-provider" });

    expect(readBasemapPreference("user:8", storage)).toBeNull();
  });

  it("persists the Tianditu imagery preference", () => {
    const storage = memoryStorage();

    expect(writeBasemapPreference("user:9", "tianditu-imagery", storage)).toBe(
      true,
    );
    expect(readBasemapPreference("user:9", storage)).toBe("tianditu-imagery");
  });

  it("does not restore or persist the hidden OSM technical fallback", () => {
    const key = basemapPreferenceKey("user:8");
    const storage = memoryStorage({ [key]: "osm" });

    expect(readBasemapPreference("user:8", storage)).toBeNull();
    expect(writeBasemapPreference("user:8", "osm", storage)).toBe(false);
  });

  it("does not break map startup when storage access fails", () => {
    const storage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };

    expect(readBasemapPreference("user:8", storage)).toBeNull();
    expect(writeBasemapPreference("user:8", "mapbox-streets", storage)).toBe(
      false,
    );
  });
});
