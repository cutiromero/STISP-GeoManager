import { Button, InputNumber, Space } from "antd";
import { useEffect } from "react";
import type { Map } from "mapbox-gl";
import { bindGeometryDraw, upsertPolygonLayer } from "../map/spatialDraw";
import {
  validRegion,
  type MonitorRegion,
  type MonitoringWorkspace,
} from "./useMonitoringWorkspace";

export default function MonitorRegionControls({
  map,
  workspace: w,
}: {
  map?: Map;
  workspace: MonitoringWorkspace;
}) {
  useEffect(() => {
    if (!map?.getStyle() || !w.drawing) return;
    return bindGeometryDraw(map, "rectangle", (geometry) => {
      if (geometry.type !== "Polygon") return;
      const points = (geometry.coordinates as number[][][])[0]!;
      const xs = points.map((point) => point[0]!);
      const ys = points.map((point) => point[1]!);
      const region = {
        west: Math.min(...xs),
        south: Math.min(...ys),
        east: Math.max(...xs),
        north: Math.max(...ys),
      };
      if (validRegion(region)) w.setRegion(region);
      w.setDrawing(false);
    });
  }, [map, w.drawing]);
  useEffect(() => {
    if (!map?.getStyle() || !validRegion(w.region)) return;
    const { west, south, east, north } = w.region;
    upsertPolygonLayer(
      map,
      "monitor-roi",
      "monitor-roi-fill",
      "monitor-roi-line",
      {
        type: "Polygon",
        coordinates: [
          [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ],
        ],
      },
      {
        fillColor: "#68dfc7",
        fillOpacity: 0.08,
        lineColor: "#68dfc7",
        lineOpacity: 1,
        lineWidth: 2,
      },
    );
    return () => {
      if (!map.getStyle()) return;
      for (const id of ["monitor-roi-fill", "monitor-roi-line"])
        if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource("monitor-roi")) map.removeSource("monitor-roi");
    };
  }, [map, w.region]);
  return (
    <div className="monitor-region-controls">
      <Space wrap>
        <Button
          size="small"
          disabled={!map || !w.source?.metadata.sourceSchema.bounds}
          onClick={() => {
            const bounds = w.source?.metadata.sourceSchema.bounds;
            if (bounds?.length === 4)
              map?.fitBounds(
                [
                  [bounds[0]!, Math.max(-85, bounds[1]!)],
                  [bounds[2]!, Math.min(85, bounds[3]!)],
                ],
                { padding: 50, duration: 700 },
              );
          }}
        >
          定位原图
        </Button>
        <Button
          size="small"
          type={w.drawing ? "primary" : "default"}
          disabled={!map}
          onClick={() => w.setDrawing(!w.drawing)}
        >
          {w.drawing ? "取消绘制" : "绘制研究区"}
        </Button>
        <Button
          size="small"
          disabled={!map}
          onClick={() => {
            const bounds = map?.getBounds();
            if (!bounds) return;
            const region = {
              west: Math.max(-180, bounds.getWest()),
              south: Math.max(-85, bounds.getSouth()),
              east: Math.min(180, bounds.getEast()),
              north: Math.min(85, bounds.getNorth()),
            };
            if (validRegion(region)) w.setRegion(region);
          }}
        >
          使用当前视野
        </Button>
        {w.region && (
          <Button size="small" onClick={() => w.setRegion(undefined)}>
            清除范围
          </Button>
        )}
      </Space>
      {w.drawing && <p role="status">在地图上依次点击矩形的两个对角</p>}
      <details>
        <summary>
          {w.region
            ? `研究区 ${w.region.west.toFixed(3)} / ${w.region.south.toFixed(3)} — ${w.region.east.toFixed(3)} / ${w.region.north.toFixed(3)}`
            : "经纬度范围"}
        </summary>
        <div className="monitor-region-fields">
          {(
            [
              ["west", "西界"],
              ["south", "南界"],
              ["east", "东界"],
              ["north", "北界"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <InputNumber
                size="small"
                aria-label={`研究区${label}`}
                value={w.region?.[key]}
                onChange={(value) =>
                  value != null &&
                  w.setRegion(
                    (previous) =>
                      ({
                        west: 0,
                        south: 0,
                        east: 0,
                        north: 0,
                        ...previous,
                        [key]: value,
                      }) as MonitorRegion,
                  )
                }
              />
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}
