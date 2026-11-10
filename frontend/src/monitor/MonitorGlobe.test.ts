import mapboxgl from "mapbox-gl";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyChineseBasemapLanguage,
  createBasemapStyle,
} from "../map/basemapStyle";
import { createMockMonitorSource } from "./mockSource";
import { connectionFeatures } from "./MonitorGlobe";
import { installMonitorMapboxMock } from "./test/monitorMapbox";

afterEach(() => vi.restoreAllMocks());

describe("监测地图边界", () => {
  it("替身从真实默认导出替换构造器，支持加载、中文底图、点位及资源释放", async () => {
    const state = installMonitorMapboxMock();
    const container = { append: vi.fn() } as unknown as HTMLElement;
    const element = { remove: vi.fn() } as unknown as HTMLButtonElement;
    const options = {
      container,
      style: createBasemapStyle({
        defaultBasemap: "osm",
        mapboxAccessToken: "",
      }),
      projection: "globe",
      center: [102, 30] as [number, number],
      zoom: 3,
    };
    const map = new mapboxgl.Map(options);
    const load = vi.fn(() => applyChineseBasemapLanguage(map));
    map.on("load", load);
    await Promise.resolve();
    const fixture = state.maps[0]!;
    expect(state.maps).toHaveLength(1);
    expect(fixture.options).toBe(options);
    expect(load).toHaveBeenCalledOnce();
    expect(fixture.api.setLanguage).toHaveBeenCalledWith("zh-Hans");
    expect(map.getStyle().layers).toHaveLength(1);
    const marker = new mapboxgl.Marker({ element })
      .setLngLat([102, 30])
      .addTo(map);
    expect(state.points).toEqual([element]);
    expect(container.append).toHaveBeenCalledWith(element);
    map.stop();
    expect(fixture.api.stop).toHaveBeenCalledOnce();
    expect(fixture.api.setCenter).not.toHaveBeenCalled();
    marker.remove();
    expect(element.remove).toHaveBeenCalledOnce();
    map.remove();
    fixture.emit("load");
    expect(load).toHaveBeenCalledOnce();
    expect(fixture.api.remove).toHaveBeenCalledOnce();
  });

  it("替身保留多监听器、移除事件、图层和可更新的 GeoJSON 数据源", () => {
    const state = installMonitorMapboxMock();
    const map = new mapboxgl.Map({
      container: {} as HTMLElement,
      style: createBasemapStyle({
        defaultBasemap: "osm",
        mapboxAccessToken: "",
      }),
    });
    const fixture = state.maps[0]!;
    const first = vi.fn();
    const second = vi.fn();
    map.on("dragstart", first);
    map.on("dragstart", second);
    map.off("dragstart", first);
    fixture.emit("dragstart");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
    const data = { type: "FeatureCollection" as const, features: [] };
    map.addSource("monitor-links", { type: "geojson", data });
    map.addLayer({
      id: "monitor-links",
      type: "line",
      source: "monitor-links",
    });
    expect(map.getLayer("monitor-links")).toEqual({
      id: "monitor-links",
      type: "line",
      source: "monitor-links",
    });
    const source = map.getSource("monitor-links") as mapboxgl.GeoJSONSource;
    source.setData(data);
    expect(fixture.sources.get("monitor-links")!.setData).toHaveBeenCalledWith(
      data,
    );
    map.remove();
  });

  it("十二个点位的连线使用本次快照坐标，生成完整弧线并跳过缺失端点", async () => {
    const snapshot = await createMockMonitorSource().getSnapshot();
    expect(snapshot.stations).toHaveLength(12);
    const data = connectionFeatures(snapshot);
    expect(data.features).toHaveLength(snapshot.connections.length);
    for (const [index, feature] of data.features.entries()) {
      const connection = snapshot.connections[index]!;
      expect(feature.properties.kind).toBe(connection.kind);
      expect(feature.geometry.coordinates).toHaveLength(49);
      expect(feature.geometry.coordinates[0]).toEqual(
        snapshot.stations.find((station) => station.id === connection.from)!
          .coordinates,
      );
      expect(feature.geometry.coordinates.at(-1)).toEqual(
        snapshot.stations.find((station) => station.id === connection.to)!
          .coordinates,
      );
    }
    expect(connectionFeatures({ ...snapshot, stations: [] }).features).toEqual(
      [],
    );
  });
});
