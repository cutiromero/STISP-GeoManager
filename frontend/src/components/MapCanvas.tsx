import {
  recordMapBasemap,
  registerBasemapRestore,
} from "../map/basemapSnapshot";
import { projectTransformRequest } from "../projects/session";
import {
  FullscreenOutlined,
  HomeOutlined,
  RotateLeftOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { App, Button, Tooltip } from "antd";
import mapboxgl, {
  type Map as MapboxMap,
  type MapboxOptions,
  type MapSourceDataEvent,
} from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import tiandituTileProviderUrl from "../map/tiandituTileProvider.js?url";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import BasemapStatusIndicator from "./BasemapStatusIndicator";
import BasemapSwitcher from "./BasemapSwitcher";
import TiandituAttributionBadge from "./TiandituAttributionBadge";
import type { BasemapRetryProbe } from "../hooks/useBasemapStatus";
import {
  applyBasemapExpressionSafety,
  applyChineseBasemapLanguage,
  applySatelliteBasemapColorCorrection,
  mapLabelLanguage,
} from "../map/basemapStyle";
import {
  availableBasemapFallback,
  createBasemapCatalog,
  resolveBasemapDefinition,
  type BasemapDefinition,
  type BasemapId,
} from "../map/basemapCatalog";
import {
  readBasemapPreference,
  writeBasemapPreference,
} from "../map/basemapPreference";
import {
  basemapRecoveryAction,
  basemapRecoveryCooldownMs,
  rateLimitRecoverySwitchOptions,
  shouldBlockRateLimitedBasemapSelection,
  shouldSuppressRecoveredBasemapRateLimitError,
  type BasemapRecoveryReason,
  type BasemapRateLimitRecoveryState,
} from "../map/basemapRateLimitRecovery";
import {
  createBasemapRequestConcurrencyCoordinator,
  type BasemapRequestConcurrencyLease,
} from "../map/basemapRequestConcurrency";
import {
  areBasemapSourcesReady,
  basemapSwitchTimeoutMsForProvider,
  basemapErrorMessage,
  createStableReadinessGate,
  isBasemapRateLimitError,
  isHardTiandituSourceDataError,
  isHardBasemapStyleError,
  isTolerableTiandituTileError,
  isTrippedTiandituTransientError,
  readBasemapCamera,
  readTiandituTileFailure,
  resolveBasemapRateLimitFallback,
  resolveBasemapTechnicalFallback,
  restoreBasemapCamera,
  restoreSelectedFeatureState,
  type BasemapCameraSnapshot,
} from "../map/basemapSwitch";
import { tiandituTileProviderName } from "../map/tiandituTileProviderConfig";
import {
  basemapRecoveryNotificationKey,
  shouldForwardMapErrorToGlobalMessage,
} from "../map/mapErrorFeedback";
import {
  isBasemapResourceError,
  type ActiveBasemapDescriptor,
} from "../map/basemapStatus";
import { syncLoadedLayers } from "../map/loadedLayerSync";
import { getMapState, type FeatureStateTarget } from "../map/mapState";
import {
  bindGeometryDraw,
  type DrawMode,
  upsertPolygonLayer,
} from "../map/spatialDraw";
import {
  bindPlatformSymbolImageFallback,
  registerPlatformSymbolImages,
} from "../map/symbolImages";
import { removeLayerGroup } from "../map/vectorLayerSync";
import { fitBoundsOptions, readMapViewState } from "../map/mapViewport";
import type {
  Bootstrap,
  FeatureInfo,
  GeoJsonGeometry,
  LoadedLayer,
  MapViewState,
  SpatialFilter,
} from "../types";
import { normalizeDisplayLngLat, sourceIdFor } from "../utils/geometry";

const spatialFilterSourceId = "query-spatial-filter";
const spatialFilterFillId = "query-spatial-filter-fill";
const spatialFilterLineId = "query-spatial-filter-line";
const spatialRangeStyle = {
  fillColor: "#ef4444",
  fillOpacity: 0.16,
  lineColor: "#ef4444",
  lineOpacity: 0.95,
  lineWidth: 2,
};
const layerExtentStyle = {
  fillColor: "#000000",
  fillOpacity: 0.16,
  lineColor: "#000000",
  lineOpacity: 1,
  lineWidth: 2,
};

export interface LayerExtentOverlay {
  layer: LoadedLayer;
  geometry: GeoJsonGeometry;
}

disableMapboxEventRequests();
mapboxgl.addTileProvider(tiandituTileProviderName, tiandituTileProviderUrl);

interface Props {
  bootstrap: Bootstrap;
  basemapPreferenceScope: string;
  basemapSwitchDisabled?: boolean;
  loadedLayers: LoadedLayer[];
  drawMode: DrawMode | null;
  spatialFilter: SpatialFilter | null;
  layerExtentOverlays: LayerExtentOverlay[];
  onDrawComplete: (mode: DrawMode, geometry: GeoJsonGeometry) => void;
  onFeatureSelect?: (feature: FeatureInfo | null) => void;
  onMapReady?: (map: MapboxMap) => void;
  onMapDestroy?: () => void;
  onMapError?: (message: string) => void;
  onViewStateChange?: (view: MapViewState) => void;
  onBasemapSwitchingChange?: (switching: boolean) => void;
}

interface ActiveBasemapState {
  id: BasemapId;
  generation: number;
}

interface BasemapStyleLoadResult {
  ok: boolean;
  error?: unknown;
}

interface StyleRestoreSnapshot {
  camera: BasemapCameraSnapshot;
  selectedFeature: FeatureStateTarget | undefined;
}

interface BasemapSwitchOptions {
  force?: boolean;
  persist?: boolean;
  announce?: boolean;
  rollbackOnFailure?: boolean;
}

const basemapRequestConcurrency =
  createBasemapRequestConcurrencyCoordinator(mapboxgl);

export default function MapCanvas({
  bootstrap,
  basemapPreferenceScope,
  basemapSwitchDisabled = false,
  loadedLayers,
  drawMode,
  spatialFilter,
  layerExtentOverlays,
  onDrawComplete,
  onFeatureSelect,
  onMapReady,
  onMapDestroy,
  onMapError,
  onViewStateChange,
  onBasemapSwitchingChange,
}: Props) {
  const { message } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const mapRef = useRef<MapboxMap | null>(null);
  const [mapObject, setMapObject] = useState<MapboxMap | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const coordinatePanelRef = useRef<HTMLDivElement | null>(null);
  const pointerUpdateFrameRef = useRef<number | null>(null);
  const resizeFrameRef = useRef<number | null>(null);
  const activeLayerExtentSourceIdsRef = useRef<Set<string>>(new Set());
  const styleInitializedRef = useRef(false);
  const latestLoadedLayersRef = useRef(loadedLayers);
  const latestSpatialFilterRef = useRef(spatialFilter);
  const latestLayerExtentOverlaysRef = useRef(layerExtentOverlays);
  const latestOnFeatureSelectRef = useRef(onFeatureSelect);
  const latestOnBasemapSwitchingChangeRef = useRef(onBasemapSwitchingChange);
  const mountedRef = useRef(true);
  const basemapSwitchingRef = useRef(false);
  const basemapOperationSequenceRef = useRef(0);
  const basemapRequestConcurrencyLeaseRef =
    useRef<BasemapRequestConcurrencyLease | null>(null);
  const rateLimitRecoveryRef = useRef<BasemapRateLimitRecoveryState>({
    attemptId: 0,
    cooldownMs: 30_000,
    descriptor: null,
    phase: "idle",
    reason: "rate-limit",
    suppressUntil: 0,
  });
  const recoverRateLimitedBasemapRef = useRef<
    (
      definition: BasemapDefinition,
      descriptor: ActiveBasemapDescriptor,
      reason: BasemapRecoveryReason,
    ) => void
  >(() => undefined);
  const cancelBasemapStyleLoadRef = useRef<((reason?: unknown) => void) | null>(
    null,
  );
  latestLoadedLayersRef.current = loadedLayers;
  latestSpatialFilterRef.current = spatialFilter;
  latestLayerExtentOverlaysRef.current = layerExtentOverlays;
  latestOnFeatureSelectRef.current = onFeatureSelect;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyChineseBasemapLanguage(map);
  }, [i18n.resolvedLanguage]);
  latestOnBasemapSwitchingChangeRef.current = onBasemapSwitchingChange;
  const mapConfig = bootstrap.map;
  const mapboxToken = mapConfig.mapboxAccessToken;
  const basemapCatalog = useMemo(
    () =>
      createBasemapCatalog({
        mapboxAccessToken: mapboxToken,
        tiandituKey: mapConfig.tiandituAccessToken ?? "",
      }),
    [i18n.resolvedLanguage, mapConfig.tiandituAccessToken, mapboxToken],
  );
  const initialBasemapRef = useRef<BasemapDefinition | null>(null);
  if (!initialBasemapRef.current) {
    initialBasemapRef.current = availableBasemapFallback(basemapCatalog, {
      userPreference: readBasemapPreference(basemapPreferenceScope),
      systemDefault: mapConfig.defaultBasemap,
    });
  }
  const [activeBasemapState, setActiveBasemapState] =
    useState<ActiveBasemapState>(() => ({
      id: initialBasemapRef.current!.id,
      generation: 0,
    }));
  const [basemapSwitching, setBasemapSwitching] = useState(false);
  const activeBasemap =
    resolveBasemapDefinition(basemapCatalog, activeBasemapState.id) ??
    availableBasemapFallback(basemapCatalog);
  const activeBasemapRef = useRef(activeBasemap);
  activeBasemapRef.current = activeBasemap;
  const basemapGenerationRef = useRef(activeBasemapState.generation);
  basemapGenerationRef.current = activeBasemapState.generation;
  const activeBasemapDescriptor = useMemo<ActiveBasemapDescriptor>(
    () => ({
      id: activeBasemap.id,
      generation: activeBasemapState.generation,
      provider: activeBasemap.provider,
      sourceIds: activeBasemap.sourceIds,
      requireAllSourceIds: activeBasemap.requireAllSourceIds,
      readinessTimeoutMs: basemapSwitchTimeoutMsForProvider(
        activeBasemap.provider,
      ),
      resourceMarkers: activeBasemap.errorMarkers,
    }),
    [activeBasemap, activeBasemapState.generation],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      basemapOperationSequenceRef.current += 1;
      cancelBasemapStyleLoadRef.current?.(new Error("地图已卸载"));
      cancelBasemapStyleLoadRef.current = null;
    };
  }, []);

  const restoreStyleContents = useCallback(
    (
      map: MapboxMap,
      definition: BasemapDefinition,
      options: {
        fitNewLayers: boolean;
        snapshot?: StyleRestoreSnapshot;
      },
    ) => {
      recordMapBasemap(map, definition.id);
      const postProcess = definition.postProcess;
      if (postProcess.applyExpressionSafety) {
        applyBasemapExpressionSafety(map);
      }
      registerPlatformSymbolImages(map);
      map.setFog({
        color: "rgb(221, 232, 224)",
        "high-color": "rgb(52, 96, 123)",
        "horizon-blend": 0.08,
        "space-color": "rgb(8, 20, 28)",
        "star-intensity": 0.22,
      });
      if (postProcess.applySatelliteColorCorrection) {
        applySatelliteBasemapColorCorrection(map);
      }
      if (postProcess.applyChineseLanguage) {
        applyChineseBasemapLanguage(map);
      }
      if (postProcess.hideAdministrativeBoundaries) {
        hideAdministrativeBoundaries(map);
      }

      syncLoadedLayers(
        map,
        latestLoadedLayersRef.current,
        latestOnFeatureSelectRef.current,
        { fitNewLayers: options.fitNewLayers },
      );
      syncSpatialFilterOverlay(map, latestSpatialFilterRef.current);
      syncLayerExtentOverlays(
        map,
        latestLayerExtentOverlaysRef.current,
        activeLayerExtentSourceIdsRef.current,
      );
      if (options.snapshot) {
        restoreBasemapCamera(map, options.snapshot.camera);
        restoreSelectedFeatureState(map, options.snapshot.selectedFeature);
      }
      styleInitializedRef.current = true;
    },
    [],
  );

  const loadBasemapStyle = useCallback(
    (
      map: MapboxMap,
      definition: BasemapDefinition,
      snapshot: StyleRestoreSnapshot,
    ) => {
      const sequence = basemapOperationSequenceRef.current + 1;
      basemapOperationSequenceRef.current = sequence;
      cancelBasemapStyleLoadRef.current?.(
        new Error("新的底图切换已替代上一请求"),
      );
      styleInitializedRef.current = false;

      return new Promise<BasemapStyleLoadResult>((resolve) => {
        let settled = false;
        let styleLoaded = false;
        let lastBasemapError: unknown;
        let timeoutId: number | null = null;

        const basemapSourcesReady = () => {
          if (!styleLoaded || !isCurrentOperation()) return false;
          return areBasemapSourcesReady(map, definition);
        };
        const readinessGate = createStableReadinessGate(
          basemapSourcesReady,
          () => {
            if (lastBasemapError !== undefined) {
              settle(false, lastBasemapError);
              return;
            }
            settle(true);
          },
          100,
        );

        const cleanup = () => {
          map.off("style.load", handleStyleLoad);
          map.off("sourcedata", handleSourceData);
          map.off("idle", handleIdle);
          map.off("error", handleError);
          if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
          }
          readinessGate.cancel();
          if (cancelBasemapStyleLoadRef.current === cancel) {
            cancelBasemapStyleLoadRef.current = null;
          }
        };
        const settle = (ok: boolean, error?: unknown) => {
          if (settled) return;
          settled = true;
          cleanup();
          resolve({
            ok,
            error,
          });
        };
        const cancel = (reason?: unknown) =>
          settle(false, reason ?? new Error("底图切换已取消"));
        const isCurrentOperation = () =>
          basemapOperationSequenceRef.current === sequence;
        const checkBasemapReady = readinessGate.check;
        const handleStyleLoad = () => {
          if (!isCurrentOperation()) return;
          try {
            restoreStyleContents(map, definition, {
              fitNewLayers: false,
              snapshot,
            });
            styleLoaded = true;
            checkBasemapReady();
          } catch (error) {
            settle(false, error);
          }
        };
        const handleSourceData = (
          event: MapSourceDataEvent & { error?: unknown },
        ) => {
          if (
            !event.sourceId ||
            !definition.sourceIds.includes(event.sourceId)
          ) {
            return;
          }
          if (
            isHardTiandituSourceDataError({
              provider: definition.provider,
              sourceDataType: event.sourceDataType,
              error: event.error,
            })
          ) {
            const error =
              event.error ?? new Error("天地图瓦片源加载失败（HTTP 404）");
            lastBasemapError = error;
            settle(false, error);
            return;
          }
          checkBasemapReady();
        };
        const handleIdle = () => checkBasemapReady();
        const handleError = (event: { error?: unknown; sourceId?: string }) => {
          const descriptor: ActiveBasemapDescriptor = {
            id: definition.id,
            generation: sequence,
            provider: definition.provider,
            sourceIds: definition.sourceIds,
            requireAllSourceIds: definition.requireAllSourceIds,
            resourceMarkers: definition.errorMarkers,
          };
          if (!isBasemapResourceError(event, descriptor)) return;
          if (isTolerableTiandituTileError(event)) {
            checkBasemapReady();
            return;
          }
          lastBasemapError = event;
          if (isHardBasemapStyleError(event)) {
            settle(false, event);
          }
        };

        cancelBasemapStyleLoadRef.current = cancel;
        map.on("style.load", handleStyleLoad);
        map.on("sourcedata", handleSourceData);
        map.on("idle", handleIdle);
        map.on("error", handleError);
        const timeoutMs = basemapSwitchTimeoutMsForProvider(
          definition.provider,
        );
        timeoutId = window.setTimeout(
          () =>
            settle(
              false,
              new Error(
                `${definition.label}加载超过 ${Math.round(timeoutMs / 1_000)} 秒`,
              ),
            ),
          timeoutMs,
        );
        try {
          basemapRequestConcurrencyLeaseRef.current?.update(
            definition.provider,
          );
          map.setStyle(definition.style, {
            diff: false,
            localFontFamily: null,
            localIdeographFontFamily:
              '"Microsoft YaHei", "PingFang SC", sans-serif',
          });
        } catch (error) {
          settle(false, error);
        }
      });
    },
    [restoreStyleContents],
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const mapOptions: MapboxOptions = {
      transformRequest: projectTransformRequest,
      container: containerRef.current,
      style: activeBasemapRef.current.style,
      center: mapConfig.defaultCenter,
      zoom: mapConfig.defaultZoom,
      pitch: 0,
      bearing: 0,
      projection: "globe",
      language: mapLabelLanguage(),
      localIdeographFontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif',
      attributionControl: false,
      performanceMetricsCollection: false,
    };
    if (mapboxToken) {
      mapOptions.accessToken = mapboxToken;
    }
    const concurrencyLease = basemapRequestConcurrency.acquire(
      activeBasemapRef.current.provider,
    );
    basemapRequestConcurrencyLeaseRef.current = concurrencyLease;
    let map: MapboxMap;
    try {
      map = new mapboxgl.Map(mapOptions);
    } catch (error) {
      basemapRequestConcurrencyLeaseRef.current = null;
      concurrencyLease.release();
      throw error;
    }
    const unbindPlatformSymbolImageFallback =
      bindPlatformSymbolImageFallback(map);
    const handleStyleLoad = () => {
      if (basemapSwitchingRef.current) return;
      try {
        restoreStyleContents(map, activeBasemapRef.current, {
          fitNewLayers: true,
        });
      } catch (error) {
        onMapError?.(basemapErrorMessage(error));
      }
    };
    map.on("style.load", handleStyleLoad);
    const handleMapError = (event: { error?: unknown; sourceId?: string }) => {
      const definition = activeBasemapRef.current;
      const descriptor: ActiveBasemapDescriptor = {
        id: definition.id,
        generation: basemapGenerationRef.current,
        provider: definition.provider,
        sourceIds: definition.sourceIds,
        requireAllSourceIds: definition.requireAllSourceIds,
        resourceMarkers: definition.errorMarkers,
      };
      const isActiveBasemapError = isBasemapResourceError(event, descriptor);
      const isSustainedFailure = isTrippedTiandituTransientError(event);
      const tiandituFailure = readTiandituTileFailure(event);
      const isTiandituResourceEvent = Boolean(
        tiandituFailure || event.sourceId?.startsWith("basemap-tianditu-"),
      );
      const isServiceError = Boolean(
        tiandituFailure &&
        (tiandituFailure.failureKind === "credentials" ||
          tiandituFailure.failureKind === "permanent"),
      );
      if (isActiveBasemapError && isTolerableTiandituTileError(event)) {
        return;
      }
      const recovery = rateLimitRecoveryRef.current;
      const now = Date.now();
      const isRateLimitError = isBasemapRateLimitError(event);
      const recoveryReason: BasemapRecoveryReason | null = isRateLimitError
        ? "rate-limit"
        : isSustainedFailure
          ? "sustained-failure"
          : isServiceError
            ? "service-error"
            : null;
      if (
        shouldSuppressRecoveredBasemapRateLimitError({
          recovery,
          now,
          isRateLimitError,
          isSustainedFailure,
          isServiceError,
          matchesRecoveryDescriptor: Boolean(
            recovery.descriptor &&
            isBasemapResourceError(event, recovery.descriptor),
          ),
        })
      ) {
        return;
      }
      const registerRecovery = (phase: "idle" | "pending") => {
        if (!recoveryReason) return;
        const cooldownMs = basemapRecoveryCooldownMs(
          recoveryReason,
          tiandituFailure?.retryAfterMs,
        );
        rateLimitRecoveryRef.current = {
          attemptId: recovery.attemptId + 1,
          cooldownMs,
          descriptor,
          phase,
          reason: recoveryReason,
          suppressUntil: now + cooldownMs,
        };
      };
      if (basemapSwitchingRef.current) {
        if (
          isActiveBasemapError &&
          definition.provider === "tianditu" &&
          recoveryReason
        ) {
          registerRecovery("idle");
        }
        return;
      }
      if (
        isActiveBasemapError &&
        definition.provider === "tianditu" &&
        recoveryReason
      ) {
        registerRecovery("pending");
        recoverRateLimitedBasemapRef.current(
          definition,
          descriptor,
          recoveryReason,
        );
        return;
      }
      if (
        !shouldForwardMapErrorToGlobalMessage({
          activeBasemapError: isActiveBasemapError,
          errorProvider: isTiandituResourceEvent ? "tianditu" : null,
          provider: definition.provider,
        })
      ) {
        return;
      }
      onMapError?.(basemapErrorMessage(event));
    };
    map.on("error", handleMapError);
    map.addControl(
      new mapboxgl.ScaleControl({ unit: "metric" }),
      "bottom-left",
    );
    map.addControl(
      new mapboxgl.AttributionControl({ compact: true }),
      "bottom-right",
    );
    const updatePointerPanel = (lngLat: [number, number] | null) => {
      if (pointerUpdateFrameRef.current !== null) {
        window.cancelAnimationFrame(pointerUpdateFrameRef.current);
      }
      pointerUpdateFrameRef.current = window.requestAnimationFrame(() => {
        pointerUpdateFrameRef.current = null;
        const panel = coordinatePanelRef.current;
        if (!panel) return;
        panel.textContent = lngLat
          ? english
            ? `Longitude ${lngLat[0].toFixed(4)}  Latitude ${lngLat[1].toFixed(4)}`
            : `经度 ${lngLat[0].toFixed(4)}  纬度 ${lngLat[1].toFixed(4)}`
          : english
            ? "Coordinates --"
            : "经纬度 --";
      });
    };
    const updatePointer = (event: mapboxgl.MapMouseEvent) => {
      updatePointerPanel(
        map.isPointOnSurface(event.point)
          ? normalizeDisplayLngLat(event.lngLat)
          : null,
      );
    };
    const clearPointer = () => updatePointerPanel(null);
    map.on("mousemove", updatePointer);
    map.on("mouseleave", clearPointer);
    const emitViewState = () => {
      onViewStateChange?.(readMapViewState(map));
    };
    const resizeAndEmitViewState = () => {
      if (resizeFrameRef.current !== null) {
        return;
      }
      resizeFrameRef.current = window.requestAnimationFrame(() => {
        resizeFrameRef.current = null;
        map.resize();
        emitViewState();
      });
    };
    map.on("load", emitViewState);
    map.on("moveend", emitViewState);
    map.on("zoomend", emitViewState);
    map.on("rotateend", emitViewState);
    map.on("pitchend", emitViewState);
    window.addEventListener("resize", resizeAndEmitViewState);
    emitViewState();
    mapRef.current = map;
    recordMapBasemap(map, activeBasemapRef.current.id);
    setMapObject(map);
    onMapReady?.(map);

    return () => {
      map.off("load", emitViewState);
      map.off("moveend", emitViewState);
      map.off("zoomend", emitViewState);
      map.off("rotateend", emitViewState);
      map.off("pitchend", emitViewState);
      map.off("style.load", handleStyleLoad);
      map.off("error", handleMapError);
      unbindPlatformSymbolImageFallback();
      window.removeEventListener("resize", resizeAndEmitViewState);
      map.off("mousemove", updatePointer);
      map.off("mouseleave", clearPointer);
      if (pointerUpdateFrameRef.current !== null) {
        window.cancelAnimationFrame(pointerUpdateFrameRef.current);
        pointerUpdateFrameRef.current = null;
      }
      if (resizeFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeFrameRef.current);
        resizeFrameRef.current = null;
      }
      onMapDestroy?.();
      styleInitializedRef.current = false;
      basemapOperationSequenceRef.current += 1;
      cancelBasemapStyleLoadRef.current?.(new Error("地图正在重新初始化"));
      cancelBasemapStyleLoadRef.current = null;
      mapRef.current = null;
      setMapObject(null);
      map.remove();
      if (basemapRequestConcurrencyLeaseRef.current === concurrencyLease) {
        basemapRequestConcurrencyLeaseRef.current = null;
      }
      concurrencyLease.release();
    };
  }, [
    mapConfig,
    mapboxToken,
    onMapDestroy,
    onMapError,
    onMapReady,
    onViewStateChange,
    restoreStyleContents,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleInitializedRef.current) return;
    syncLoadedLayers(map, loadedLayers, onFeatureSelect);
  }, [loadedLayers, onFeatureSelect]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleInitializedRef.current || !map.isStyleLoaded()) return;
    syncSpatialFilterOverlay(map, spatialFilter);
  }, [spatialFilter]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleInitializedRef.current || !map.isStyleLoaded()) return;
    syncLayerExtentOverlays(
      map,
      layerExtentOverlays,
      activeLayerExtentSourceIdsRef.current,
    );
  }, [layerExtentOverlays]);

  useEffect(() => {
    const map = mapRef.current;
    if (
      !map ||
      !drawMode ||
      basemapSwitching ||
      !styleInitializedRef.current ||
      !map.isStyleLoaded()
    ) {
      return;
    }
    return bindGeometryDraw(map, drawMode, (geometry) =>
      onDrawComplete(drawMode, geometry),
    );
  }, [basemapSwitching, drawMode, onDrawComplete]);

  const switchBasemap = useCallback(
    async (id: BasemapId, options: BasemapSwitchOptions = {}) => {
      const map = mapRef.current;
      const target = resolveBasemapDefinition(basemapCatalog, id);
      if (drawMode || basemapSwitchDisabled) {
        if (options.announce !== false) {
          message.info(
            drawMode
              ? english
                ? "Finish drawing the current area first"
                : "请先完成当前范围绘制"
              : english
                ? "Basemaps cannot be switched during map export"
                : "地图导出期间暂不能切换底图",
          );
        }
        return false;
      }
      if (!map || !target) {
        if (options.announce !== false) {
          message.warning(
            english
              ? "The map is not ready. Try again shortly."
              : "地图尚未准备好，请稍后重试",
          );
        }
        return false;
      }
      if (!target.credentials.available) {
        if (options.announce !== false) {
          message.warning(
            target.credentials.reason ??
              (english ? "This basemap is unavailable" : "当前底图不可用"),
          );
        }
        return false;
      }
      const rateLimitRecovery = rateLimitRecoveryRef.current;
      if (
        shouldBlockRateLimitedBasemapSelection(
          rateLimitRecovery,
          target.id,
          Date.now(),
        )
      ) {
        if (options.announce !== false) {
          message.warning(
            basemapRecoveryCooldownMessage(rateLimitRecovery.reason, english),
          );
        }
        return false;
      }

      const previous = activeBasemapRef.current;
      if (previous.id === target.id && !options.force) return true;
      if (basemapSwitchingRef.current) {
        if (options.announce !== false) {
          message.info(
            english ? "Switching basemap..." : "底图正在切换，请稍候",
          );
        }
        return false;
      }

      const snapshot: StyleRestoreSnapshot = {
        camera: readBasemapCamera(map),
        selectedFeature: getMapState(map).selectedFeature,
      };
      const publishActiveBasemap = (definition: BasemapDefinition) => {
        const generation = basemapGenerationRef.current + 1;
        basemapGenerationRef.current = generation;
        activeBasemapRef.current = definition;
        if (mountedRef.current) {
          setActiveBasemapState({ id: definition.id, generation });
        }
      };
      const setSwitching = (switching: boolean) => {
        basemapSwitchingRef.current = switching;
        if (mountedRef.current) {
          setBasemapSwitching(switching);
          latestOnBasemapSwitchingChangeRef.current?.(switching);
        }
      };

      setSwitching(true);
      publishActiveBasemap(target);
      try {
        const result = await loadBasemapStyle(map, target, snapshot);
        if (!mountedRef.current || mapRef.current !== map) return false;
        if (result.ok) {
          if (options.persist !== false) {
            writeBasemapPreference(basemapPreferenceScope, target.id);
          }
          if (options.announce !== false) {
            message.success(
              english
                ? `Switched to ${target.label}`
                : `已切换到${target.label}`,
            );
          }
          return true;
        }

        const failureMessage = basemapErrorMessage(result.error);
        const technicalFallback = resolveBasemapTechnicalFallback(
          basemapCatalog,
          target.id,
        );
        if (options.rollbackOnFailure === false) {
          if (technicalFallback && technicalFallback.id !== target.id) {
            publishActiveBasemap(technicalFallback);
            const fallbackResult = await loadBasemapStyle(
              map,
              technicalFallback,
              snapshot,
            );
            if (!mountedRef.current || mapRef.current !== map) return false;
            if (fallbackResult.ok) return true;
          }
          return false;
        }
        if (previous.id === target.id) {
          if (technicalFallback && technicalFallback.id !== target.id) {
            publishActiveBasemap(technicalFallback);
            const fallbackResult = await loadBasemapStyle(
              map,
              technicalFallback,
              snapshot,
            );
            if (!mountedRef.current || mapRef.current !== map) return false;
            if (fallbackResult.ok) {
              message.error(
                english
                  ? `${target.label} failed to reload. The technical fallback basemap is active: ${failureMessage}`
                  : `${target.label}重新加载失败，已启用技术兜底底图：${failureMessage}`,
              );
              return false;
            }
          }
          message.error(
            english
              ? `${target.label} failed to reload: ${failureMessage}`
              : `${target.label}重新加载失败：${failureMessage}`,
          );
          return false;
        }

        publishActiveBasemap(previous);
        const rollback = await loadBasemapStyle(map, previous, snapshot);
        if (!mountedRef.current || mapRef.current !== map) return false;
        if (rollback.ok) {
          message.error(
            english
              ? `${target.label} failed to load. Restored ${previous.label}: ${failureMessage}`
              : `${target.label}加载失败，已恢复${previous.label}：${failureMessage}`,
          );
          return false;
        }

        if (technicalFallback && technicalFallback.id !== previous.id) {
          publishActiveBasemap(technicalFallback);
          const fallbackResult = await loadBasemapStyle(
            map,
            technicalFallback,
            snapshot,
          );
          if (!mountedRef.current || mapRef.current !== map) return false;
          if (fallbackResult.ok) {
            message.error(
              english
                ? `${target.label} and the previous basemap both failed. The technical fallback basemap is active.`
                : `${target.label}与原底图均未能加载，已启用技术兜底底图`,
            );
            return false;
          }
        }

        message.error(
          english
            ? "Basemap switching and recovery both failed. Check the network and run the diagnostic again."
            : "底图切换及恢复均失败，请检查网络后重新检测",
        );
        return false;
      } finally {
        setSwitching(false);
      }
    },
    [
      basemapCatalog,
      basemapPreferenceScope,
      basemapSwitchDisabled,
      drawMode,
      loadBasemapStyle,
      message,
    ],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    return registerBasemapRestore(map, (id) => switchBasemap(id));
  }, [switchBasemap, mapObject]);

  const recoverRateLimitedBasemap = useCallback(
    (
      failedDefinition: BasemapDefinition,
      failedDescriptor: ActiveBasemapDescriptor,
      reason: BasemapRecoveryReason,
    ) => {
      const recovery = rateLimitRecoveryRef.current;
      const recoveryAction = basemapRecoveryAction({
        recovery,
        failedDescriptor,
        failedBasemapId: failedDefinition.id,
        activeBasemapId: activeBasemapRef.current.id,
        activeGeneration: basemapGenerationRef.current,
        basemapSwitching: basemapSwitchingRef.current,
        drawModeActive: Boolean(drawMode),
        basemapSwitchDisabled,
      });
      if (recoveryAction === "defer" || recoveryAction === "ignore") return;
      if (recoveryAction === "discard") {
        recovery.phase = "idle";
        return;
      }
      const fallback = resolveBasemapRateLimitFallback(
        basemapCatalog,
        failedDefinition.id,
      );
      if (!fallback) {
        recovery.phase = "idle";
        return;
      }

      const attemptId = recovery.attemptId;
      recovery.phase = "running";
      recovery.suppressUntil = Date.now() + recovery.cooldownMs;

      void (async () => {
        try {
          const recovered = await switchBasemap(
            fallback.id,
            rateLimitRecoverySwitchOptions,
          );
          if (!mountedRef.current) return;
          if (recovered) {
            const recoveredDefinition = activeBasemapRef.current;
            message.open({
              key: basemapRecoveryNotificationKey,
              type: "warning",
              content: english
                ? `${failedDefinition.label}: ${basemapRecoveryReasonText(reason, true)}. Automatically switched to ${recoveredDefinition.label}.`
                : `${failedDefinition.label}${basemapRecoveryReasonText(reason)}，已自动切换到${recoveredDefinition.label}`,
              duration: 5,
            });
          } else {
            message.open({
              key: basemapRecoveryNotificationKey,
              type: "error",
              content: english
                ? `${failedDefinition.label}: ${basemapRecoveryReasonText(reason, true)}. Automatic recovery failed; run the diagnostic again later.`
                : `${failedDefinition.label}${basemapRecoveryReasonText(reason)}，自动恢复底图失败，请稍后重新检测`,
              duration: 5,
            });
          }
        } finally {
          const currentRecovery = rateLimitRecoveryRef.current;
          if (
            currentRecovery.descriptor?.id === failedDescriptor.id &&
            currentRecovery.descriptor.generation ===
              failedDescriptor.generation &&
            currentRecovery.reason === reason &&
            currentRecovery.attemptId === attemptId
          ) {
            currentRecovery.phase = "idle";
          }
        }
      })();
    },
    [basemapCatalog, basemapSwitchDisabled, drawMode, message, switchBasemap],
  );
  recoverRateLimitedBasemapRef.current = recoverRateLimitedBasemap;

  useEffect(() => {
    const recovery = rateLimitRecoveryRef.current;
    const descriptor = recovery.descriptor;
    if (recovery.phase !== "pending" || !descriptor) return;
    const definition = resolveBasemapDefinition(basemapCatalog, descriptor.id);
    if (!definition) {
      recovery.phase = "idle";
      return;
    }
    recoverRateLimitedBasemap(definition, descriptor, recovery.reason);
  }, [
    basemapCatalog,
    basemapSwitchDisabled,
    basemapSwitching,
    drawMode,
    recoverRateLimitedBasemap,
  ]);

  const retryActiveBasemap = useCallback<BasemapRetryProbe>(
    async ({ signal }) => {
      const ok = await switchBasemap(activeBasemapRef.current.id, {
        force: true,
        persist: false,
        announce: false,
      });
      if (signal.aborted) return;
      return {
        ok,
        // A forced reload measures whole-view readiness, not a tile RTT.
        latencyMs: null,
      };
    },
    [switchBasemap],
  );

  function resetView() {
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(
      [
        [50, 35],
        [100, 48],
      ],
      fitBoundsOptions(),
    );
  }

  return (
    <div className="map-shell">
      <div ref={containerRef} className="map-container" />
      <TiandituAttributionBadge provider={activeBasemap.provider} />
      <div className="map-toolbar">
        <BasemapSwitcher
          basemaps={basemapCatalog}
          activeId={activeBasemap.id}
          switching={basemapSwitching}
          disabled={Boolean(drawMode) || basemapSwitchDisabled}
          disabledReason={
            drawMode
              ? english
                ? "Finish drawing the current area first"
                : "请先完成当前范围绘制"
              : basemapSwitchDisabled
                ? english
                  ? "Basemaps cannot be switched during map export"
                  : "地图导出期间暂不能切换底图"
                : undefined
          }
          onSelect={(id) => void switchBasemap(id)}
        />
        <BasemapStatusIndicator
          map={mapObject}
          activeBasemap={activeBasemapDescriptor}
          activeBasemapName={activeBasemap.label}
          retryBasemap={
            basemapSwitching || drawMode || basemapSwitchDisabled
              ? undefined
              : retryActiveBasemap
          }
        />
        <div
          ref={coordinatePanelRef}
          className="map-coordinate-panel"
          role="status"
          aria-label={english ? "Pointer coordinates" : "鼠标位置经纬度"}
        >
          {english ? "Coordinates --" : "经纬度 --"}
        </div>
        <Tooltip title={english ? "Reset to project extent" : "复位到项目范围"}>
          <Button
            icon={<HomeOutlined style={{ fontSize: 16 }} />}
            onClick={resetView}
          />
        </Tooltip>
        <Tooltip title={english ? "Zoom in" : "放大"}>
          <Button
            icon={<ZoomInOutlined style={{ fontSize: 16 }} />}
            onClick={() => mapRef.current?.zoomIn()}
          />
        </Tooltip>
        <Tooltip title={english ? "Zoom out" : "缩小"}>
          <Button
            icon={<ZoomOutOutlined style={{ fontSize: 16 }} />}
            onClick={() => mapRef.current?.zoomOut()}
          />
        </Tooltip>
        <Tooltip title={english ? "Reset north" : "北向"}>
          <Button
            icon={<RotateLeftOutlined style={{ fontSize: 16 }} />}
            onClick={() => mapRef.current?.resetNorthPitch()}
          />
        </Tooltip>
        <Tooltip title={english ? "Full screen" : "全屏"}>
          <Button
            icon={<FullscreenOutlined style={{ fontSize: 16 }} />}
            onClick={() => containerRef.current?.requestFullscreen()}
          />
        </Tooltip>
      </div>
    </div>
  );
}

function basemapRecoveryReasonText(
  reason: BasemapRecoveryReason,
  english = false,
) {
  if (reason === "rate-limit")
    return english ? "request rate limited" : "请求受限";
  if (reason === "service-error")
    return english
      ? "credential or service configuration issue"
      : "凭证或服务配置异常";
  return english ? "persistent loading failure" : "持续加载失败";
}

function basemapRecoveryCooldownMessage(
  reason: BasemapRecoveryReason,
  english = false,
) {
  if (reason === "rate-limit")
    return english
      ? "Tianditu is in a rate-limit cooldown. Try again later."
      : "天地图服务正在限流冷却，请稍后再试";
  if (reason === "service-error") {
    return english
      ? "Tianditu credentials or service configuration are in cooldown. Try again later."
      : "天地图凭证或服务配置异常正在冷却，请稍后再试";
  }
  return english
    ? "The Tianditu service is in cooldown after an error. Try again later."
    : "天地图服务异常正在冷却，请稍后再试";
}

function disableMapboxEventRequests() {
  const descriptor = Object.getOwnPropertyDescriptor(
    mapboxgl.config,
    "EVENTS_URL",
  );
  if (descriptor?.value === null) return;
  Object.defineProperty(mapboxgl.config, "EVENTS_URL", {
    configurable: true,
    enumerable: descriptor?.enumerable ?? true,
    value: null,
  });
}

function layerExtentSourceIdFor(layerId: string) {
  return `layer-extent-${sourceIdFor(layerId)}`;
}

function syncSpatialFilterOverlay(
  map: MapboxMap,
  spatialFilter: SpatialFilter | null,
) {
  if (spatialFilter) {
    upsertPolygonLayer(
      map,
      spatialFilterSourceId,
      spatialFilterFillId,
      spatialFilterLineId,
      spatialFilter.geometry,
      spatialRangeStyle,
    );
    return;
  }
  removeLayerGroup(
    map,
    spatialFilterSourceId,
    [spatialFilterFillId, spatialFilterLineId],
    { cleanInteraction: false },
  );
}

function syncLayerExtentOverlays(
  map: MapboxMap,
  overlays: LayerExtentOverlay[],
  activeSourceIds: Set<string>,
) {
  const nextSourceIds = new Set<string>();
  for (const overlay of overlays) {
    const sourceId = layerExtentSourceIdFor(overlay.layer.id);
    const fillId = `${sourceId}-fill`;
    const lineId = `${sourceId}-line`;
    const beforeId = firstStyleLayerIdForLayer(map, overlay.layer);
    nextSourceIds.add(sourceId);
    upsertPolygonLayer(map, sourceId, fillId, lineId, overlay.geometry, {
      ...layerExtentStyle,
      beforeId,
    });
  }

  for (const sourceId of activeSourceIds) {
    if (!nextSourceIds.has(sourceId)) {
      removeLayerGroup(
        map,
        sourceId,
        [`${sourceId}-fill`, `${sourceId}-line`],
        {
          cleanInteraction: false,
        },
      );
    }
  }

  activeSourceIds.clear();
  for (const sourceId of nextSourceIds) {
    activeSourceIds.add(sourceId);
  }
}

function firstStyleLayerIdForLayer(map: MapboxMap, layer: LoadedLayer) {
  const sourceId = sourceIdFor(layer.id);
  const candidates =
    layer.layerType === "raster"
      ? [`${sourceId}-raster`]
      : [
          `${sourceId}-fill`,
          `${sourceId}-line`,
          `${sourceId}-heatmap`,
          `${sourceId}-point`,
          `${sourceId}-symbol`,
        ];
  return candidates.find((id) => map.getLayer(id));
}

function hideAdministrativeBoundaries(map: MapboxMap) {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    const sourceLayer =
      "source-layer" in layer && layer["source-layer"]
        ? String(layer["source-layer"])
        : "";
    const searchText = `${layer.id} ${sourceLayer}`.toLowerCase();
    const isBoundaryLayer =
      layer.type === "line" &&
      (searchText.includes("admin") || searchText.includes("boundary"));
    if (isBoundaryLayer && map.getLayer(layer.id)) {
      map.setLayoutProperty(layer.id, "visibility", "none");
    }
  }
}
