import mapboxgl, {
  type Map as MapboxMap,
  type ExpressionSpecification,
} from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useRef, useState } from "react";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import {
  applyChineseBasemapLanguage,
  createBasemapStyle,
} from "../map/basemapStyle";
import { projectTransformRequest } from "../projects/session";
import { globeFit, isRegionalZoom } from "./globeView";

const resumeAfterMs = 1800;

export function useMonitorMap(
  initialView: ProjectMonitorConfig["initialView"],
  animated: boolean,
) {
  const { bootstrap } = useAppContext();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | undefined>(undefined);
  const [map, setMap] = useState<MapboxMap>();
  const [mapError, setMapError] = useState(false);
  const [regionalView, setRegionalView] = useState(false);
  const regional = useRef(false);
  const pausedUntil = useRef(0);
  const interacting = useRef(false);
  const hovered = useRef(false);
  const latest = useRef({ initialView, animated, mapConfig: bootstrap.map });
  latest.current = { initialView, animated, mapConfig: bootstrap.map };
  const styleKey = JSON.stringify(
    Object.entries(bootstrap.map).sort(([left], [right]) =>
      left.localeCompare(right),
    ),
  );
  const [longitude, latitude] = initialView.center;

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let instance: MapboxMap;
    let disposed = false;
    const baseVisibility = new Map<
      string,
      "visible" | "none" | ExpressionSpecification
    >();
    const fit = () => {
      const view = globeFit(host.clientWidth, host.clientHeight);
      host.parentElement?.style.setProperty(
        "--planet-diameter",
        `${view.diameter}px`,
      );
      return view;
    };
    setMap(undefined);
    setMapError(false);
    setRegionalView(false);
    regional.current = false;
    interacting.current = false;
    hovered.current = false;
    try {
      instance = new mapboxgl.Map({
        container: host,
        accessToken: latest.current.mapConfig.mapboxAccessToken,
        style: createBasemapStyle(latest.current.mapConfig),
        projection: "globe",
        center: [longitude!, latitude!],
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
    mapRef.current = instance;
    const pause = () => {
      pausedUntil.current = performance.now() + resumeAfterMs;
    };
    const start = () => {
      interacting.current = true;
      pause();
    };
    const end = () => {
      if (interacting.current) {
        interacting.current = false;
        pause();
      }
    };
    const updateRegion = () => {
      regional.current = isRegionalZoom(
        instance.getZoom(),
        host.clientWidth,
        host.clientHeight,
      );
      setRegionalView(regional.current);
      for (const [id, visibility] of baseVisibility)
        if (instance.getLayer(id))
          instance.setLayoutProperty(
            id,
            "visibility",
            regional.current ? visibility : "none",
          );
    };
    const load = () => {
      if (disposed) return;
      applyChineseBasemapLanguage(instance);
      for (const layer of instance.getStyle().layers ?? []) {
        if (layer.type === "raster") {
          instance.setPaintProperty(layer.id, "raster-saturation", -0.25);
          instance.setPaintProperty(layer.id, "raster-brightness-max", 0.85);
        }
        if (layer.type === "symbol" || layer.type === "line") {
          baseVisibility.set(layer.id, layer.layout?.visibility ?? "visible");
          instance.setLayoutProperty(layer.id, "visibility", "none");
        }
      }
      instance.setFog({
        color: "rgba(126, 172, 208, 0.45)",
        "high-color": "rgba(48, 83, 132, 0.2)",
        "space-color": "rgba(0, 0, 0, 0)",
        "star-intensity": 0,
        "horizon-blend": 0.08,
      });
      setMap(instance);
    };
    const error = () => {
      if (!disposed) setMapError(true);
    };
    const move = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      hovered.current = instance.isPointOnSurface([
        event.clientX - rect.left,
        event.clientY - rect.top,
      ]);
    };
    const leave = () => {
      hovered.current = false;
    };
    instance.on("load", load);
    instance.on("error", error);
    instance.on("dragstart", start);
    instance.on("dragend", end);
    instance.on("zoomstart", pause);
    instance.on("rotatestart", start);
    instance.on("rotateend", end);
    instance.on("zoomend", updateRegion);
    host.addEventListener("pointermove", move);
    host.addEventListener("pointerleave", leave);
    host.addEventListener("pointerdown", start);
    host.addEventListener("wheel", pause, { passive: true });
    host.addEventListener("keydown", pause);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    window.addEventListener("blur", end);
    const resize = new ResizeObserver(() => {
      instance.resize();
      const view = fit();
      if (!regional.current) instance.jumpTo({ zoom: view.zoom });
    });
    resize.observe(host);
    return () => {
      disposed = true;
      resize.disconnect();
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerleave", leave);
      host.removeEventListener("pointerdown", start);
      host.removeEventListener("wheel", pause);
      host.removeEventListener("keydown", pause);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      window.removeEventListener("blur", end);
      instance.remove();
      if (mapRef.current === instance) mapRef.current = undefined;
    };
  }, [styleKey, longitude, latitude]);

  useEffect(() => {
    if (!map) return;
    if (!animated) {
      map.stop();
      return;
    }
    let frame = 0;
    let previous = performance.now();
    const spin = (time: number) => {
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
  }, [map, animated]);

  const focus = (studyArea: boolean) => {
    const instance = mapRef.current;
    const host = container.current;
    if (!instance || !host) return;
    pausedUntil.current = performance.now() + resumeAfterMs;
    regional.current = studyArea;
    setRegionalView(studyArea);
    instance.flyTo({
      center: latest.current.initialView.center as [number, number],
      zoom: studyArea
        ? latest.current.initialView.regionZoom
        : globeFit(host.clientWidth, host.clientHeight).zoom,
      duration: latest.current.animated ? 1400 : 0,
    });
  };
  const showBounds = (bounds: [number, number, number, number]) => {
    regional.current = true;
    setRegionalView(true);
    pausedUntil.current = performance.now() + resumeAfterMs;
    mapRef.current?.fitBounds(bounds, {
      padding: 55,
      maxZoom: 11,
      duration: latest.current.animated ? 1000 : 0,
    });
  };
  return { container, map, mapError, regionalView, focus, showBounds };
}
