import mapboxgl, { type MapOptions, type StyleSpecification } from "mapbox-gl";
import { vi } from "vitest";

export function createMonitorMapMock(options: MapOptions) {
  const sources = new Map<string, { setData: ReturnType<typeof vi.fn> }>();
  const events = new Map<string, Set<() => void>>();
  const style = options.style as StyleSpecification;
  const layers = new Map<string, unknown>(
    (style.layers ?? []).map((layer) => [layer.id, layer]),
  );
  const api = {
    on: vi.fn((name: string, callback: () => void) => {
      if (!events.has(name)) events.set(name, new Set());
      events.get(name)!.add(callback);
      return api;
    }),
    off: vi.fn((name: string, callback: () => void) => {
      events.get(name)?.delete(callback);
      return api;
    }),
    getStyle: vi.fn(() => ({ ...style, layers: Array.from(layers.values()) })),
    getLayer: vi.fn((id: string) => layers.get(id)),
    addLayer: vi.fn((layer: { id: string }) => layers.set(layer.id, layer)),
    addSource: vi.fn((id: string, source: { data: unknown }) => {
      sources.set(id, { ...source, setData: vi.fn() });
    }),
    getSource: vi.fn((id: string) => sources.get(id)),
    removeSource: vi.fn((id: string) => sources.delete(id)),
    removeLayer: vi.fn((id: string) => layers.delete(id)),
    fitBounds: vi.fn(),
    getContainer: vi.fn(() => options.container),
    setLanguage: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    setFog: vi.fn(),
    resize: vi.fn(),
    stop: vi.fn(),
    getCenter: vi.fn(() => ({ lng: 84, lat: 40 })),
    getZoom: vi.fn(() => 2),
    isPointOnSurface: vi.fn(() => true),
    setCenter: vi.fn(),
    flyTo: vi.fn(),
    jumpTo: vi.fn(),
    remove: vi.fn(() => events.clear()),
  };
  return {
    value: api as unknown as mapboxgl.Map,
    api,
    options,
    sources,
    layers,
    emit: (name: string) => events.get(name)?.forEach((callback) => callback()),
  };
}

export function installMonitorMapboxMock() {
  const maps: ReturnType<typeof createMonitorMapMock>[] = [];
  const points: HTMLButtonElement[] = [];
  vi.spyOn(mapboxgl, "Map").mockImplementation(
    class {
      constructor(options: MapOptions) {
        if (typeof options.container !== "string")
          options.container.classList?.add("mapboxgl-map");
        const map = createMonitorMapMock(options);
        maps.push(map);
        queueMicrotask(() => map.emit("load"));
        return map.value;
      }
    } as typeof mapboxgl.Map,
  );
  vi.spyOn(mapboxgl, "Marker").mockImplementation(
    class {
      constructor({ element }: { element: HTMLButtonElement }) {
        if (element.hasAttribute && !element.hasAttribute("role"))
          element.setAttribute("role", "img");
        points.push(element);
        const marker = {
          setLngLat: vi.fn(() => marker),
          addTo: vi.fn((map: mapboxgl.Map) => {
            map.getContainer().append(element);
            return marker;
          }),
          remove: vi.fn(() => element.remove()),
        };
        return marker;
      }
    } as typeof mapboxgl.Marker,
  );
  return { maps, points };
}
