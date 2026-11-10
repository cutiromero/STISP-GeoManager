import { AimOutlined, GlobalOutlined } from "@ant-design/icons";
import { Button } from "antd";
import mapboxgl, {
  type GeoJSONSource,
  type GeoJSONSourceSpecification,
  type Map as MapboxMap,
} from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../contexts/AppContext";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import {
  applyChineseBasemapLanguage,
  createBasemapStyle,
} from "../map/basemapStyle";
import { projectTransformRequest } from "../projects/session";
import { riskColors, typeColors } from "./state";
import type { MonitorEvent, MonitorSnapshot } from "./types";

const rotationResumeMs = 15000;

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
  const camera = {
    center: initialView.center as [number, number],
    zoom: initialView.zoom,
  };
  const { t } = useTranslation();
  const { bootstrap } = useAppContext();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | undefined>(undefined);
  const markers = useRef(
    new Map<string, { marker: mapboxgl.Marker; element: HTMLButtonElement }>(),
  );
  const latest = useRef({ snapshot, onSelect, animated });
  latest.current = { snapshot, onSelect, animated };
  const pausedUntil = useRef(0);
  const interacting = useRef(false);
  const [mapError, setMapError] = useState(false);
  const [ready, setReady] = useState(false);
  const { mapboxAccessToken, defaultBasemap } = bootstrap.map;

  useEffect(() => {
    if (!container.current) return;
    let map: MapboxMap;
    setReady(false);
    setMapError(false);
    try {
      map = new mapboxgl.Map({
        container: container.current,
        accessToken: mapboxAccessToken,
        style: createBasemapStyle(bootstrap.map),
        projection: "globe",
        ...camera,
        minZoom: 0,
        maxZoom: 22,
        transformRequest: projectTransformRequest,
        attributionControl: true,
      });
    } catch {
      setMapError(true);
      return;
    }
    mapRef.current = map;
    const load = () => {
      applyChineseBasemapLanguage(map);
      for (const layer of map.getStyle().layers ?? []) {
        if (layer.type === "raster") {
          map.setPaintProperty(layer.id, "raster-saturation", -0.75);
          map.setPaintProperty(layer.id, "raster-brightness-max", 0.42);
        }
      }
      map.setFog({
        color: "#183748",
        "high-color": "#081624",
        "space-color": "#050c17",
        "star-intensity": 0.4,
        "horizon-blend": 0.12,
      });
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
      for (const station of latest.current.snapshot.stations) {
        const element = document.createElement("button");
        element.type = "button";
        element.className = "monitor-map-point";
        element.setAttribute("aria-label", station.name);
        element.title = station.name;
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
        markers.current.set(station.id, { marker, element });
      }
      setReady(true);
    };
    const pause = () => {
      pausedUntil.current = performance.now() + rotationResumeMs;
    };
    const start = () => {
      interacting.current = true;
      pause();
    };
    const end = () => {
      interacting.current = false;
      pause();
    };
    const error = () => setMapError(true);
    map.on("load", load);
    map.on("error", error);
    map.on("dragstart", start);
    map.on("dragend", end);
    map.on("zoomstart", pause);
    map.on("rotatestart", start);
    map.on("rotateend", end);
    const host = container.current;
    host.addEventListener("pointerdown", start);
    host.addEventListener("wheel", pause, { passive: true });
    host.addEventListener("keydown", pause);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(host);
    return () => {
      resize.disconnect();
      host.removeEventListener("pointerdown", start);
      host.removeEventListener("wheel", pause);
      host.removeEventListener("keydown", pause);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      markers.current.forEach(({ marker }) => marker.remove());
      markers.current.clear();
      map.remove();
      mapRef.current = undefined;
    };
  }, [mapboxAccessToken, defaultBasemap, initialView]);

  useEffect(() => {
    if (!ready) return;
    (
      mapRef.current?.getSource("monitor-links") as GeoJSONSource | undefined
    )?.setData(connectionFeatures(snapshot));
    for (const station of snapshot.stations) {
      const point = markers.current.get(station.id);
      if (!point) continue;
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
  }, [snapshot, ready, lastEvent, animated, t]);

  useEffect(() => {
    if (!animated) {
      mapRef.current?.stop();
      return;
    }
    if (!ready) return;
    let frame = 0;
    let previous = performance.now();
    const spin = (time: number) => {
      const map = mapRef.current;
      if (!map) return;
      const elapsed = Math.min(100, time - previous);
      previous = time;
      if (
        !interacting.current &&
        time > pausedUntil.current &&
        map.getZoom() < 4.5
      ) {
        const center = map.getCenter();
        map.setCenter([center.lng - elapsed * 0.00035, center.lat]);
      }
      frame = requestAnimationFrame(spin);
    };
    frame = requestAnimationFrame(spin);
    return () => cancelAnimationFrame(frame);
  }, [animated, ready]);

  const focus = (regional: boolean) => {
    pausedUntil.current = performance.now() + rotationResumeMs;
    mapRef.current?.flyTo({
      ...camera,
      zoom: regional ? initialView.regionZoom : camera.zoom,
      duration: animated ? 1400 : 0,
    });
  };
  return (
    <>
      <div
        ref={container}
        className="monitor-map"
        aria-label={t("monitor.globeLabel")}
      />
      {mapError && (
        <div className="monitor-map-notice" role="status">
          {t("monitor.mapError")}
        </div>
      )}
      <div className="monitor-map-controls">
        <Button icon={<GlobalOutlined />} onClick={() => focus(false)}>
          {t("monitor.globalView")}
        </Button>
        <Button icon={<AimOutlined />} onClick={() => focus(true)}>
          {t("monitor.regionView")}
        </Button>
      </div>
    </>
  );
}
