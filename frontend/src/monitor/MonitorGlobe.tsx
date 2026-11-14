import { AimOutlined, GlobalOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import mapboxgl, {
  type GeoJSONSource,
  type GeoJSONSourceSpecification,
} from "mapbox-gl";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { riskColors, typeColors } from "./state";
import type { MonitorEvent, MonitorSnapshot } from "./types";
import { useMonitorMap } from "./useMonitorMap";
export { globeFit, isRegionalZoom } from "./globeView";

export function connectionFeatures(
  snapshot: MonitorSnapshot,
): Exclude<GeoJSONSourceSpecification["data"], string | undefined> {
  const stations = new Map(
    snapshot.stations.map((station) => [station.id, station]),
  );
  return {
    type: "FeatureCollection",
    features: snapshot.connections.flatMap((connection) => {
      const from = stations.get(connection.from)?.coordinates;
      const to = stations.get(connection.to)?.coordinates;
      if (!from || !to) return [];
      const distance = Math.hypot(to[0] - from[0], to[1] - from[1]);
      return [
        {
          type: "Feature" as const,
          properties: { kind: connection.kind },
          geometry: {
            type: "LineString" as const,
            coordinates: Array.from({ length: 49 }, (_, step) => {
              const fraction = step / 48;
              return [
                from[0] + (to[0] - from[0]) * fraction,
                from[1] +
                  (to[1] - from[1]) * fraction +
                  Math.sin(fraction * Math.PI) * distance * 0.18,
              ];
            }),
          },
        },
      ];
    }),
  };
}

export default function MonitorGlobe({
  snapshot,
  lastEvent,
  animated,
  onSelect,
  initialView,
}: {
  snapshot: MonitorSnapshot;
  lastEvent?: MonitorEvent;
  animated: boolean;
  onSelect: (id: string) => void;
  initialView: ProjectMonitorConfig["initialView"];
}) {
  const { t } = useTranslation();
  const { container, map, mapError, regionalView, focus } = useMonitorMap(
    initialView,
    animated,
  );
  const latest = useRef({ snapshot, onSelect });
  latest.current = { snapshot, onSelect };
  const markers = useRef(
    new Map<
      string,
      {
        marker: mapboxgl.Marker;
        element: HTMLButtonElement;
        coordinates: [number, number];
      }
    >(),
  );
  const overview = useRef<
    { marker: mapboxgl.Marker; element: HTMLButtonElement } | undefined
  >(undefined);
  useEffect(() => {
    if (!map) return;
    map.addSource("monitor-links", {
      type: "geojson",
      data: connectionFeatures(latest.current.snapshot),
    });
    map.addLayer({
      id: "monitor-links-glow",
      type: "line",
      source: "monitor-links",
      paint: {
        "line-color": "#52dccc",
        "line-width": 7,
        "line-opacity": 0.12,
        "line-blur": 4,
      },
    });
    map.addLayer({
      id: "monitor-links",
      type: "line",
      source: "monitor-links",
      paint: {
        "line-color": "#65ded2",
        "line-width": 1.4,
        "line-opacity": 0.8,
        "line-dasharray": [3, 2],
      },
    });
    const element = document.createElement("button");
    element.type = "button";
    element.className = "monitor-map-cluster";
    element.setAttribute("aria-label", t("monitor.openStudyArea"));
    const label = document.createElement("span");
    label.textContent = t("monitor.studyArea");
    const count = document.createElement("strong");
    element.append(label, count);
    element.addEventListener("click", () => focus(true));
    const marker = new mapboxgl.Marker({ element })
      .setLngLat(initialView.center as [number, number])
      .addTo(map);
    overview.current = { marker, element };
    return () => {
      markers.current.forEach((item) => item.marker.remove());
      markers.current.clear();
      overview.current?.marker.remove();
      overview.current = undefined;
    };
  }, [map]);
  useEffect(() => {
    if (!map) return;
    (map.getSource("monitor-links") as GeoJSONSource | undefined)?.setData(
      connectionFeatures(snapshot),
    );
    const count = overview.current?.element.querySelector("strong");
    if (count)
      count.textContent = `${snapshot.stations.length} ${t("monitor.siteUnit")}`;
    const identities = new Set(snapshot.stations.map((station) => station.id));
    for (const [identity, point] of markers.current)
      if (!identities.has(identity)) {
        point.marker.remove();
        markers.current.delete(identity);
      }
    for (const station of snapshot.stations) {
      let point = markers.current.get(station.id);
      if (!point) {
        const element = document.createElement("button");
        element.type = "button";
        element.className = "monitor-map-point";
        element.setAttribute("aria-label", station.name);
        const core = document.createElement("span");
        core.className = "monitor-point-core";
        core.setAttribute("aria-hidden", "true");
        element.append(core);
        element.addEventListener("click", () =>
          latest.current.onSelect(station.id),
        );
        const marker = new mapboxgl.Marker({ element })
          .setLngLat(station.coordinates)
          .addTo(map);
        point = { marker, element, coordinates: [...station.coordinates] };
        markers.current.set(station.id, point);
      } else if (
        point.coordinates[0] !== station.coordinates[0] ||
        point.coordinates[1] !== station.coordinates[1]
      ) {
        point.marker.setLngLat(station.coordinates);
        point.coordinates = [...station.coordinates];
      }
      point.element.style.setProperty(
        "--point-color",
        riskColors[station.level],
      );
      point.element.style.setProperty("--type-color", typeColors[station.type]);
      point.element.dataset.level = station.level;
      point.element.title = `${station.name} · ${t(`monitor.level.${station.level}`)}`;
      point.element.querySelector(".monitor-point-flash")?.remove();
      if (animated && station.id === lastEvent?.station.id) {
        const flash = document.createElement("span");
        flash.className = "monitor-point-flash";
        point.element.append(flash);
      }
    }
  }, [map, snapshot, lastEvent, animated, t]);
  return (
    <>
      <div
        className="monitor-planet-stage"
        data-view={regionalView ? "region" : "globe"}
      >
        <div
          ref={container}
          className="monitor-map"
          aria-label={t("monitor.globeLabel")}
        />
      </div>
      {mapError && (
        <div className="monitor-map-notice" role="status">
          {t("monitor.mapError")}
        </div>
      )}
      <div className="monitor-map-controls">
        <Tooltip title={t("monitor.globalView")} placement="left">
          <Button
            shape="circle"
            aria-label={t("monitor.globalView")}
            icon={<GlobalOutlined />}
            onClick={() => focus(false)}
          />
        </Tooltip>
        <Tooltip title={t("monitor.regionView")} placement="left">
          <Button
            shape="circle"
            aria-label={t("monitor.regionView")}
            icon={<AimOutlined />}
            onClick={() => focus(true)}
          />
        </Tooltip>
      </div>
    </>
  );
}
