import { BorderOutlined, CheckOutlined, MoreOutlined } from "@ant-design/icons";
import { Button, Dropdown, InputNumber, Modal, Tooltip } from "antd";
import { useEffect, useState } from "react";
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
  const [coordinates, setCoordinates] = useState(false);
  const [draft, setDraft] = useState<MonitorRegion>({
    west: 0,
    south: 0,
    east: 0,
    north: 0,
  });
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
  const selectView = () => {
    const bounds = map?.getBounds();
    if (!bounds) return;
    const region = {
      west: Math.max(-180, bounds.getWest()),
      south: Math.max(-85, bounds.getSouth()),
      east: Math.min(180, bounds.getEast()),
      north: Math.min(85, bounds.getNorth()),
    };
    if (validRegion(region)) w.setRegion(region);
  };
  const locate = () => {
    const bounds = w.source?.metadata.sourceSchema.bounds;
    if (bounds?.length === 4)
      map?.fitBounds(
        [
          [bounds[0]!, Math.max(-85, bounds[1]!)],
          [bounds[2]!, Math.min(85, bounds[3]!)],
        ],
        { padding: 50, duration: 700 },
      );
  };
  const label = w.region
    ? `${w.region.west.toFixed(4)}, ${w.region.south.toFixed(4)} — ${w.region.east.toFixed(4)}, ${w.region.north.toFixed(4)}`
    : "";
  return (
    <>
      <div
        className="monitor-region-controls"
        data-selected={Boolean(w.region)}
        data-region={w.region ? JSON.stringify(w.region) : undefined}
      >
        <Tooltip title={w.drawing ? "取消绘制" : "在地图上点击矩形的两个对角"}>
          <Button
            size="small"
            aria-label={w.drawing ? "取消绘制" : "绘制研究区"}
            icon={<BorderOutlined />}
            type={w.drawing ? "primary" : "default"}
            disabled={!map}
            onClick={() => w.setDrawing(!w.drawing)}
          >
            {w.drawing ? "取消" : w.region ? "重绘范围" : "框选范围"}
          </Button>
        </Tooltip>
        {w.region && (
          <Tooltip title={`已选研究区：${label}`}>
            <CheckOutlined
              className="monitor-region-check"
              aria-label="已选研究区"
            />
          </Tooltip>
        )}
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              {
                key: "locate",
                label: "定位原图",
                disabled: !map || !w.source?.metadata.sourceSchema.bounds,
                onClick: locate,
              },
              {
                key: "view",
                label: "使用当前视野",
                disabled: !map,
                onClick: selectView,
              },
              {
                key: "coordinates",
                label: "输入经纬度",
                onClick: () => {
                  setDraft(
                    w.region ?? { west: 0, south: 0, east: 0, north: 0 },
                  );
                  setCoordinates(true);
                },
              },
              {
                key: "clear",
                label: "清除范围",
                disabled: !w.region,
                onClick: () => w.setRegion(undefined),
              },
            ],
          }}
        >
          <Button
            size="small"
            type="text"
            aria-label="范围工具"
            icon={<MoreOutlined />}
          />
        </Dropdown>
        {w.drawing && (
          <span className="monitor-draw-hint" role="status">
            依次点击两个对角
          </span>
        )}
      </div>
      <Modal
        className="monitor-task-drawer monitor-region-modal"
        title="研究区经纬度"
        open={coordinates}
        width={360}
        onCancel={() => setCoordinates(false)}
        footer={
          <Button
            type="primary"
            disabled={!validRegion(draft)}
            onClick={() => {
              w.setRegion(draft);
              setCoordinates(false);
            }}
          >
            应用范围
          </Button>
        }
      >
        <div className="monitor-region-fields">
          {(
            [
              ["west", "西界"],
              ["south", "南界"],
              ["east", "东界"],
              ["north", "北界"],
            ] as const
          ).map(([key, name]) => (
            <label key={key}>
              {name}
              <InputNumber
                aria-label={`研究区${name}`}
                value={draft[key]}
                onChange={(value) =>
                  value != null &&
                  setDraft((previous) => ({ ...previous, [key]: value }))
                }
              />
            </label>
          ))}
        </div>
      </Modal>
    </>
  );
}
