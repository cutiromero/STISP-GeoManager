import type { Map as MapboxMap, StyleSpecification } from "mapbox-gl";
import type { BasemapId } from "./basemapCatalog";

const restorers = new WeakMap<MapboxMap, (id: BasemapId) => Promise<unknown>>();
const selections = new WeakMap<MapboxMap, BasemapId>();
export const basemapMaxZoom = (id: BasemapId) =>
  id.startsWith("tianditu") ? 18 : id === "osm" ? 19 : 22;
export function basemapIdFromStyle(style: StyleSpecification): BasemapId {
  const sources = style.sources ?? {};
  if (sources["basemap-tianditu-imagery"]) return "tianditu-imagery";
  if (sources["basemap-tianditu-vector"]) return "tianditu-vector";
  if (sources["osm-raster"]) return "osm";
  if (
    Object.entries(sources).some(([id, value]) =>
      /satellite/.test(id + JSON.stringify(value)),
    )
  )
    return "mapbox-satellite";
  return "mapbox-streets";
}
export function selectedMapBasemap(
  map: MapboxMap | null,
): BasemapId | undefined {
  if (!map) return undefined;
  const selection = selections.get(map);
  if (selection) return selection;
  if (!map.isStyleLoaded()) return undefined;
  return basemapIdFromStyle(map.getStyle());
}
export function recordMapBasemap(map: MapboxMap, id: BasemapId) {
  selections.set(map, id);
}
export function registerBasemapRestore(
  map: MapboxMap,
  restore: (id: BasemapId) => Promise<unknown>,
) {
  restorers.set(map, restore);
  return () => {
    restorers.delete(map);
  };
}
export async function restoreMapBasemap(map: MapboxMap, id?: string) {
  if (!id) return; // Existing snapshots predate basemap persistence.
  if (
    ![
      "mapbox-satellite",
      "mapbox-streets",
      "tianditu-vector",
      "tianditu-imagery",
      "osm",
    ].includes(id)
  )
    throw new Error("工程底图标识无效 / Invalid project basemap");
  if (selectedMapBasemap(map) === id) return;
  const restore = restorers.get(map);
  if (!restore) throw new Error("地图尚未准备好 / Map is not ready");
  await restore(id as BasemapId);
  if (selectedMapBasemap(map) !== id)
    throw new Error(
      "工程底图加载失败，请检查底图服务配置 / Project basemap is unavailable",
    );
}
