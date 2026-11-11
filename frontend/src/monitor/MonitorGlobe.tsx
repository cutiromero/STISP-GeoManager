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

const rotationResumeMs = 1800;

export function globeFit(width: number, height: number) {
  const diameter = Math.max(120, Math.min(width * 0.86, height * 0.86));
  const zoom = Math.min(3.5, Math.log2((diameter * Math.PI) / 512));
  return { zoom, diameter: (512 * 2 ** zoom) / Math.PI };
}

export function isRegionalZoom(zoom: number, width: number, height: number) {
  return zoom > globeFit(width, height).zoom + 0.8;
}

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
  const overview = useRef<{ marker: mapboxgl.Marker; element: HTMLButtonElement } | undefined>(undefined);
  const markers = useRef(
    new Map<string, { marker: mapboxgl.Marker; element: HTMLButtonElement }>(),
  );
  const latest = useRef({ snapshot, onSelect, animated });
  latest.current = { snapshot, onSelect, animated };
  const pausedUntil = useRef(0);
  const interacting = useRef(false);
  const hovered = useRef(false);
  const regional = useRef(false);
  const [regionalView, setRegionalView] = useState(false);
  const [mapError, setMapError] = useState(false);
  const [ready, setReady] = useState(false);
  const { mapboxAccessToken, defaultBasemap } = bootstrap.map;

  useEffect(() => {
    if (!container.current) return;
    let map: MapboxMap;
    const host = container.current;
    const fit = () => {
      const view = globeFit(host.clientWidth, host.clientHeight);
      host.parentElement?.style.setProperty(
        "--planet-diameter",
        `${view.diameter}px`,
      );
      return view;
    };
    setReady(false);
    setMapError(false);
    try {
      map = new mapboxgl.Map({
        container: container.current,
        accessToken: mapboxAccessToken,
        style: createBasemapStyle(bootstrap.map),
        projection: "globe",
        ...camera,
        zoom: fit().zoom,
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
          map.setPaintProperty(layer.id, "raster-saturation", -0.25);
          map.setPaintProperty(layer.id, "raster-brightness-max", 0.85);
        }
        if (layer.type === "symbol" || layer.type === "line")
          map.setLayoutProperty(layer.id, "visibility", "none");
      }
      map.setFog({
        color: "rgba(126, 172, 208, 0.45)",
        "high-color": "rgba(48, 83, 132, 0.2)",
        "space-color": "rgba(0, 0, 0, 0)",
        "star-intensity": 0,
        "horizon-blend": 0.08,
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
      const element = document.createElement("button");
      element.type = "button";
      element.className = "monitor-map-cluster";
      element.setAttribute("aria-label", t("monitor.openStudyArea"));
      const label = document.createElement("span");
      label.textContent = t("monitor.studyArea");
      const count = document.createElement("strong");
      count.textContent = `${latest.current.snapshot.stations.length} ${t("monitor.siteUnit")}`;
      element.append(label, count);
      element.addEventListener("click", () => focus(true));
      const marker = new mapboxgl.Marker({ element }).setLngLat(camera.center).addTo(map);
      overview.current = { marker, element };
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
      if (!interacting.current) return;
      interacting.current = false;
      pause();
    };
    const error = () => setMapError(true);
    const move = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      hovered.current = map.isPointOnSurface([
        event.clientX - rect.left,
        event.clientY - rect.top,
      ]);
    };
    const leave = () => {
      hovered.current = false;
      if (!interacting.current) pausedUntil.current = 0;
    };
    const zoomed = () => {
      regional.current = isRegionalZoom(map.getZoom(), host.clientWidth, host.clientHeight);
      setRegionalView(regional.current);
      for (const layer of map.getStyle().layers ?? [])
        if (!layer.id.startsWith("monitor-") && (layer.type === "symbol" || layer.type === "line"))
          map.setLayoutProperty(
            layer.id,
            "visibility",
            regional.current ? "visible" : "none",
          );
    };
    map.on("load", load);
    map.on("error", error);
    map.on("dragstart", start);
    map.on("dragend", end);
    map.on("zoomstart", pause);
    map.on("rotatestart", start);
    map.on("rotateend", end);
    map.on("zoomend", zoomed);
    host.addEventListener("pointermove", move);
    host.addEventListener("pointerleave", leave);
    host.addEventListener("pointerdown", start);
    host.addEventListener("wheel", pause, { passive: true });
    host.addEventListener("keydown", pause);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    const resize = new ResizeObserver(() => {
      map.resize();
      const view = fit();
      if (!regional.current) map.jumpTo({ zoom: view.zoom });
    });
    resize.observe(host);
    return () => {
      resize.disconnect();
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerleave", leave);
      host.removeEventListener("pointerdown", start);
      host.removeEventListener("wheel", pause);
      host.removeEventListener("keydown", pause);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      markers.current.forEach(({ marker }) => marker.remove());
      markers.current.clear();
      overview.current?.marker.remove();
      overview.current = undefined;
      map.remove();
      mapRef.current = undefined;
    };
  }, [mapboxAccessToken, defaultBasemap, initialView]);

  useEffect(() => {
    if (!ready) return;
    (
      mapRef.current?.getSource("monitor-links") as GeoJSONSource | undefined
    )?.setData(connectionFeatures(snapshot));
    const count = overview.current?.element.querySelector("strong");
    if (count) count.textContent = `${snapshot.stations.length} ${t("monitor.siteUnit")}`;
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
        !hovered.current &&
        time > pausedUntil.current &&
        !regional.current
      ) {
        const center = map.getCenter();
        map.setCenter([center.lng - elapsed * 0.00075, center.lat]);
      }
      frame = requestAnimationFrame(spin);
    };
    frame = requestAnimationFrame(spin);
    return () => cancelAnimationFrame(frame);
  }, [animated, ready]);

  const focus = (regional: boolean) => {
    pausedUntil.current = performance.now() + rotationResumeMs;
    const host = container.current;
    const view = host ? globeFit(host.clientWidth, host.clientHeight) : camera;
    mapRef.current?.flyTo({
      ...camera,
      zoom: regional ? initialView.regionZoom : view.zoom,
      duration: latest.current.animated ? 1400 : 0,
    });
  };
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
