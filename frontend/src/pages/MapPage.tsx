import { selectedMapBasemap, restoreMapBasemap } from "../map/basemapSnapshot";
import { getActiveProject, projectSignal } from "../projects/session";
import { useProjectContext } from "../projects/ProjectContext";
import {
  AimOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  DatabaseOutlined,
  DownOutlined,
  FolderOpenOutlined,
  UpOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  ConfigProvider,
  Layout,
  Spin,
  Tabs,
  Tooltip,
} from "antd";
import type { LngLatBounds, Map as MapboxMap } from "mapbox-gl";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import DataPanel, {
  type DataResourceLoadReporter,
} from "../components/DataPanel";
import LayerDataTableModal from "../components/LayerDataTableModal";
import LayerPanel from "../components/LayerPanel";
import RightSidePanel from "../components/RightSidePanel";
import SpatialQueryWorkbench, {
  type SpatialQueryTarget,
  type SpatialQueryWorkbenchResult,
} from "../components/SpatialQueryWorkbench";
import WorkspaceScenePanel from "../components/WorkspaceScenePanel";
import WorkspaceHeader from "../components/WorkspaceHeader";
import MapCompositionPanel from "../components/map-composition/MapCompositionPanel";
import { useAppContext } from "../contexts/AppContext";
import { LayerContext, type LayerContextValue } from "../hooks/LayerContext";
import { useLayerGroups } from "../hooks/useLayerGroups";
import { useUniqueLayerLoad } from "../hooks/useUniqueLayerLoad";
import { useMapCompositions } from "../hooks/useMapCompositions";
import { useRasterRender } from "../hooks/useRasterRender";
import { useWorkspaceScenes } from "../hooks/useWorkspaceScenes";
import { workspaceSnapshot } from "../workspace/workspaceSnapshot";
import { effectiveMapLayers } from "../map/effectiveMapLayers";
import MapPanelChrome from "../map/MapPanelChrome";
import WorkbenchLegend from "../map/WorkbenchLegend";
import { useMapPanelLayout } from "../map/useMapPanelLayout";
import "../map/map-workbench-panels.css";
import {
  displayComparisonLayers,
  upsertComparisonLayer,
} from "../map/comparisonLayerGroups";
import type { ComparisonLayerPlacement } from "../map/geologyWorkbenchCompareData";
import { reviewBounds } from "../map/geologyReviewData";
import ComputeOutputMapPreview from "../map/ComputeOutputMapPreview";
import { clearFeatureState, getMapState } from "../map/mapState";
import {
  claimMapErrorNotification,
  mapErrorNotificationKey,
  summarizeMapErrorForUser,
} from "../map/mapErrorFeedback";
import {
  exportMapRangeImage,
  inferBasemapTileZoomRange,
  type MapImageExportOptions,
  type TileZoomRange,
} from "../map/mapExport";
import type { DrawMode } from "../map/spatialDraw";
import { workspacePanelTheme } from "../theme";
import {
  isQueryableLoadedLayer,
  loadedQueryResources,
} from "../utils/spatialQueryTargets";
import {
  boundsFromUnknown,
  defaultCompositionLayout,
  type MapBounds,
} from "../map-composition/layout";
import type {
  AttributeFilter,
  DataSchemaSummary,
  DataResource,
  DataResourceProfile,
  FeatureInfo,
  GeoJsonFeatureCollection,
  GeoJsonGeometry,
  LoadedLayer,
  LoadedRasterLayer,
  LoadedVectorLayer,
  MapViewState,
  MapComposition,
  ResourceFilters,
  ResourceListItem,
  ResourceQueryResult,
  RasterJob,
  ResourceVisualizationSummary,
  SpatialFilter,
  WorkspaceScene,
  WorkspaceSceneSummary,
} from "../types";
import {
  findTaxonomyNode,
  flattenTaxonomy,
  taxonomyTree,
} from "../utils/taxonomy";
import { downloadBlob } from "../utils/download";
import {
  boundsFromImageCoordinates,
  combinedFeatureBounds,
  fitGeojsonBounds,
  geometryFromBoundsText,
  rectangleGeometry,
  sourceIdFor,
} from "../utils/geometry";
import {
  createRasterLayerGroup,
  createVectorLayerGroup,
} from "../utils/layerFactory";
import {
  isGeographicResource,
  resourceSpatialExtent,
} from "../utils/resources";
import { isAbortError } from "../utils/rasterRenderTasks";
import { resourceLayerKey } from "../utils/uniqueLoadedLayers";
import { showGeojsonWarnings } from "../workspace/workspaceNotifications";

type DrawPurpose = "query";
type LeftPanelTabKey = "data" | "layers" | "projects" | "topics";
const leftPanelTabKeys = new Set<string>([
  "data",
  "layers",
  "projects",
  "topics",
]);

interface SpatialQueryContext {
  target: SpatialQueryTarget;
  targetName: string;
  resource: ResourceListItem;
  profile: DataResourceProfile;
  query: {
    attributeFilters: AttributeFilter[];
    spatialFilter: SpatialFilter | null;
  };
}

function rasterDataLoadProgress(job: RasterJob, english = false) {
  const percent =
    job.status === "ready"
      ? 95
      : Math.min(94, Math.max(15, job.progressPercent));
  const message =
    job.status === "queued"
      ? english
        ? "Raster loading job is queued"
        : "栅格加载任务正在排队"
      : job.status === "ready"
        ? english
          ? "Raster tile service is ready"
          : "栅格瓦片服务准备完成"
        : job.status === "failed"
          ? english
            ? "Raster loading job failed"
            : "栅格加载任务执行失败"
          : english
            ? "Generating display-ready raster tiles"
            : "正在生成可显示的栅格瓦片";
  return { percent, message };
}

const emptyPermissions = {
  canAccessAdmin: false,
  canManageFeaturePermissions: false,
  canCreateUser: false,
  canViewOperationLogs: false,
  canViewAllOperationLogs: false,
  canViewOwnOperationLogs: false,
  canViewGroupOperationLogs: false,
  canViewSystemLogs: false,
  canManageSystemSettings: false,
  canManageDataBackup: false,
  canManageAuth: false,
  canViewDashboardResourceCard: false,
  canViewDashboardLayerCard: false,
  canViewDashboardRasterCard: false,
  canViewDashboardUserCard: false,
  canViewDashboardActiveUsersCard: false,
  canViewDashboardSystemCard: false,
  canViewDataOverview: false,
  canBrowseData: true,
  canQueryData: true,
  canUploadData: false,
  canViewDataResources: false,
  canCreateDataResources: false,
  canChangeDataResources: false,
  canDeleteDataResources: false,
  canLoadVectorLayer: true,
  canLoadRasterLayer: true,
  canUseCustomSymbolization: false,
  canUseAiInterpretation: false,
  canExportData: false,
  canViewWorkspaces: true,
  canCreateWorkspaces: false,
  canChangeWorkspaces: false,
  canDeleteWorkspaces: false,
  canViewMapCompositions: true,
  canCreateMapCompositions: false,
  canChangeMapCompositions: false,
  canDeleteMapCompositions: false,
  canExportMapCompositions: false,
  canPublishMapCompositions: false,
  canRestoreMapCompositions: false,
  canViewResultArtifacts: false,
  canImportResultArtifacts: false,
  canDownloadResultArtifacts: false,
  canPublishResultArtifacts: false,
  canDeleteResultArtifacts: false,
  canManageRasterData: false,
};

const MapCanvas = lazy(() => import("../components/MapCanvas"));
const GeologyReviewWorkspace = lazy(
  () => import("../map/GeologyReviewWorkspace"),
);
const GeologyWorkbenchCompare = lazy(
  () => import("../map/GeologyWorkbenchCompare"),
);
const MapCompositionEditor = lazy(
  () => import("../components/map-composition/MapCompositionEditor"),
);

const EXPORT_POLL_INITIAL_DELAY_MS = 900;
const EXPORT_POLL_MAX_DELAY_MS = 4000;
const EXPORT_POLL_TIMEOUT_MS = 120_000;
const EXPORT_POLL_TIMEOUT_MESSAGE =
  "导出任务等待超时，请稍后重试或在任务中心查看状态";

interface LayerExportMessageApi {
  warning: (content: string) => unknown;
  error: (content: string) => unknown;
  success: (content: string) => unknown;
}

interface UseLayerExportOptions {
  canExportData: boolean;
  permissionDeniedMessage: string;
  message: LayerExportMessageApi;
}

export function useLayerExport({
  canExportData,
  permissionDeniedMessage,
  message,
}: UseLayerExportOptions): LayerContextValue["exportLayers"] {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      const controller = abortControllerRef.current;
      abortControllerRef.current = null;
      controller?.abort();
    },
    [],
  );

  return useCallback(
    async (items, options, onProgress) => {
      if (!canExportData) {
        message.warning(permissionDeniedMessage);
        return;
      }

      abortControllerRef.current?.abort();
      const controller = new AbortController();
      abortControllerRef.current = controller;
      const { signal } = controller;

      try {
        const job = await api.exportLayersAsync({
          epsg: options.epsg,
          reproject: options.reproject,
          clip: options.clip,
          clipGeometry: options.clipGeometry,
          format: options.format,
          items,
        });
        throwIfExportAborted(signal);
        onProgress?.({
          status: job.status,
          percent: job.progressPercent,
          messages: job.messages,
        });
        if (job.status === "failed") {
          throw new Error(
            job.error || (english ? "Export failed" : "导出失败"),
          );
        }

        const pollStartedAt = Date.now();
        let pollDelayMs = EXPORT_POLL_INITIAL_DELAY_MS;
        let status = job.status;
        while (status !== "ready") {
          const elapsedMs = Date.now() - pollStartedAt;
          const remainingMs = EXPORT_POLL_TIMEOUT_MS - elapsedMs;
          if (remainingMs <= 0) {
            throw new Error(
              english
                ? "Export job timed out. Try again later or check its status in the job center."
                : EXPORT_POLL_TIMEOUT_MESSAGE,
            );
          }
          await waitForExportPollDelay(
            Math.min(pollDelayMs, remainingMs),
            signal,
          );
          throwIfExportAborted(signal);
          if (Date.now() - pollStartedAt >= EXPORT_POLL_TIMEOUT_MS) {
            throw new Error(
              english
                ? "Export job timed out. Try again later or check its status in the job center."
                : EXPORT_POLL_TIMEOUT_MESSAGE,
            );
          }

          const next = await api.rasterJob(job.id);
          throwIfExportAborted(signal);
          if (Date.now() - pollStartedAt >= EXPORT_POLL_TIMEOUT_MS) {
            throw new Error(
              english
                ? "Export job timed out. Try again later or check its status in the job center."
                : EXPORT_POLL_TIMEOUT_MESSAGE,
            );
          }
          onProgress?.({
            status: next.status,
            percent: next.progressPercent,
            messages: next.messages,
          });
          if (next.status === "failed") {
            throw new Error(
              next.error || (english ? "Export failed" : "导出失败"),
            );
          }
          status = next.status;
          pollDelayMs = Math.min(
            Math.round(pollDelayMs * 1.5),
            EXPORT_POLL_MAX_DELAY_MS,
          );
        }

        throwIfExportAborted(signal);
        const { blob, filename } = await api.downloadExport(job.id);
        throwIfExportAborted(signal);
        downloadBlob(blob, filename);
        message.success(english ? "Export job completed" : "导出任务已完成");
      } catch (error) {
        if (signal.aborted || isExportAbortError(error)) {
          return;
        }
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Export failed"
              : "导出失败",
        );
        throw error;
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }
    },
    [canExportData, english, message, permissionDeniedMessage],
  );
}

function waitForExportPollDelay(delayMs: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(createExportAbortError());
      return;
    }

    const handleAbort = () => {
      window.clearTimeout(timer);
      reject(createExportAbortError());
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

function throwIfExportAborted(signal: AbortSignal) {
  if (signal.aborted) {
    throw createExportAbortError();
  }
}

function createExportAbortError() {
  return new DOMException("导出任务已取消", "AbortError");
}

function isExportAbortError(error: unknown) {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

interface LastGeoInsightCache {
  resource: ResourceListItem | null;
  profile: DataResourceProfile | null;
  layer: LoadedLayer | null;
  feature: FeatureInfo | null;
  summary: ResourceVisualizationSummary | null;
}

let lastGeoInsightCache: LastGeoInsightCache | null = null;

export function mapUrlResourceIds(params: URLSearchParams) {
  return [
    ...new Set(
      (params.get("resources") || params.get("resourceId") || "")
        .split(",")
        .filter((value) => /^[1-9]\d*$/.test(value))
        .map(Number),
    ),
  ]
    .filter(Number.isSafeInteger)
    .slice(0, 12);
}

export function useMapUrlResources(options: {
  params: URLSearchParams;
  currentProject: string;
  projects: { id: number }[];
  chooseProject?: (id: string) => void;
  ready: boolean;
  loadingResources: boolean;
  resources: ResourceListItem[];
  english: boolean;
  showExisting: (id: number) => Promise<boolean>;
  load: (resource: ResourceListItem) => Promise<boolean>;
  onStart: () => void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const ids = mapUrlResourceIds(options.params);
  const key = `${options.currentProject}:${options.params.get("projectTagId") ?? ""}:${ids.join(",")}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  const loaded = useRef(new Set<string>());
  const attempted = useRef("");
  const loading = useRef(false);
  const mounted = useRef(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [completed, setCompleted] = useState<{ key: string; ids: number[] }>({
    key: "",
    ids: [],
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (
      !ids.length ||
      !options.ready ||
      options.loadingResources ||
      attempted.current === key ||
      loading.current
    )
      return;
    const requestedProject = options.params.get("projectTagId");
    if (requestedProject && requestedProject !== options.currentProject) {
      if (!options.projects.length && options.chooseProject) return;
      attempted.current = key;
      if (
        options.projects.some(
          (entry) => String(entry.id) === requestedProject,
        ) &&
        options.chooseProject
      ) {
        setError(
          options.english
            ? "Switch to the result's project to load these layers."
            : "切换到成果所属项目后，将自动加载这些图层。",
        );
        options.chooseProject(requestedProject);
      } else
        setError(
          options.english
            ? "You cannot access the result's project."
            : "当前账号不能访问成果所属项目，请检查项目权限。",
        );
      return;
    }
    attempted.current = key;
    loading.current = true;
    setError("");
    options.onStart();
    void (async () => {
      const unavailable: string[] = [];
      for (const id of ids) {
        if (
          !mounted.current ||
          currentKey.current !== key ||
          !latest.current.ready
        )
          break;
        const resourceKey = `${options.currentProject}:${id}`;
        if (loaded.current.has(resourceKey)) continue;
        const resource = latest.current.resources.find(
          (entry) => entry.id === id,
        );
        if (!resource) {
          unavailable.push(
            options.english ? "Unavailable data" : "不可访问的数据",
          );
          continue;
        }
        if (resource.dataType !== "raster" && !resource.isQueryable) continue;
        try {
          if (
            (await latest.current.showExisting(id)) ||
            (await latest.current.load(resource))
          )
            loaded.current.add(resourceKey);
          else unavailable.push(resource.name);
        } catch {
          unavailable.push(resource.name);
        }
      }
      if (mounted.current && currentKey.current === key && unavailable.length)
        setError(
          `${options.english ? "Some layers could not be loaded" : "部分图层未能加载"}：${unavailable.join("、")}`,
        );
      if (mounted.current && currentKey.current === key)
        setCompleted({
          key,
          ids: ids.filter((id) =>
            loaded.current.has(`${options.currentProject}:${id}`),
          ),
        });
    })()
      .catch((reason) => {
        if (mounted.current && currentKey.current === key)
          setError(
            reason instanceof Error
              ? reason.message
              : options.english
                ? "Failed to load result layers"
                : "成果图层加载失败",
          );
      })
      .finally(() => {
        loading.current = false;
        if (mounted.current && currentKey.current !== key)
          setRevision((value) => value + 1);
      });
  }, [
    key,
    revision,
    options.ready,
    options.loadingResources,
    options.resources,
    options.projects,
  ]);
  const retry = () => {
    attempted.current = "";
    setRevision((value) => value + 1);
  };
  return {
    error,
    retry,
    loadedResourceIds: completed.key === key ? completed.ids : [],
  };
}

export function mapUrlResourceBounds(
  layers: LoadedLayer[],
  resourceIds: number[],
) {
  if (resourceIds.length < 2) return null;
  const requested = new Set(resourceIds);
  const selected = layers.filter((layer) =>
    requested.has(layer.sourceResource.id),
  );
  if (
    resourceIds.some(
      (id) => !selected.some((layer) => layer.sourceResource.id === id),
    )
  )
    return null;
  let bounds = combinedFeatureBounds(
    selected.flatMap((layer) =>
      layer.layerType === "vector" ? [layer.geojson] : [],
    ),
  );
  for (const layer of selected) {
    if (layer.layerType !== "raster" || !layer.imageCoordinates) continue;
    const extent = boundsFromImageCoordinates(layer.imageCoordinates);
    if (!extent) continue;
    if (!bounds) bounds = extent;
    else {
      bounds.extend(extent.getSouthWest());
      bounds.extend(extent.getNorthEast());
    }
  }
  return bounds;
}

export default function MapPage() {
  const [params] = useSearchParams();
  const workflowId = params.get("geologyReview");
  if (workflowId)
    return (
      <Suspense
        fallback={
          <div className="map-canvas-loading">
            <Spin />
          </div>
        }
      >
        <GeologyReviewWorkspace
          workflowId={workflowId}
          projectTagId={params.get("projectTagId")}
          suggestionId={params.get("suggestion")}
        />
      </Suspense>
    );
  return <MapWorkspace />;
}

function MapWorkspace() {
  const { bootstrap, user } = useAppContext();
  const projectContext = useProjectContext();
  const { message, notification } = App.useApp();
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const [searchParams, setSearchParams] = useSearchParams();
  const comparisonWorkflowId = searchParams.get("geologyCompare")?.trim() ?? "";
  const comparisonVisible =
    Boolean(comparisonWorkflowId) && searchParams.get("mapMode") !== "single";
  const initialGeoInsightCache = lastGeoInsightCache;

  const [resources, setResources] = useState<ResourceListItem[]>([]);
  const [loadingResources, setLoadingResources] = useState(false);
  const [dataSchema, setDataSchema] = useState<DataSchemaSummary | null>(null);
  const [resourceSearchKeyword, setResourceSearchKeyword] = useState("");
  const [selectedResource, setSelectedResource] =
    useState<ResourceListItem | null>(
      () => initialGeoInsightCache?.resource ?? null,
    );
  const [resourceProfile, setResourceProfile] =
    useState<DataResourceProfile | null>(
      () => initialGeoInsightCache?.profile ?? null,
    );
  const [spatialTargetResource, setSpatialTargetResource] =
    useState<ResourceListItem | null>(null);
  const [spatialTargetResourceProfile, setSpatialTargetResourceProfile] =
    useState<DataResourceProfile | null>(null);
  const [spatialTargetLayerId, setSpatialTargetLayerId] = useState<
    string | null
  >(null);
  const [spatialFilter, setSpatialFilter] = useState<SpatialFilter | null>(
    null,
  );
  const [spatialQuerying, setSpatialQuerying] = useState(false);
  const [spatialQueryData, setSpatialQueryData] =
    useState<ResourceQueryResult | null>(null);
  const [spatialQueryContext, setSpatialQueryContext] =
    useState<SpatialQueryContext | null>(null);
  const [spatialQueryResult, setSpatialQueryResult] =
    useState<SpatialQueryWorkbenchResult | null>(null);
  const [spatialWorkbenchOpen, setSpatialWorkbenchOpen] = useState(false);
  const [activeDraw, setActiveDraw] = useState<{
    purpose: DrawPurpose;
    mode: NonNullable<DrawMode>;
  } | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [querying, setQuerying] = useState(false);
  const [selectedFeature, setSelectedFeature] = useState<FeatureInfo | null>(
    () => initialGeoInsightCache?.feature ?? null,
  );
  const [visualizationSummary, setVisualizationSummary] =
    useState<ResourceVisualizationSummary | null>(
      () => initialGeoInsightCache?.summary ?? null,
    );
  const [visualizationSummaryLoading, setVisualizationSummaryLoading] =
    useState(false);
  const [visualizationSummaryError, setVisualizationSummaryError] = useState<
    string | null
  >(null);
  const [loadingSpatialTargetProfile, setLoadingSpatialTargetProfile] =
    useState(false);
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(
    () => initialGeoInsightCache?.layer?.id ?? null,
  );
  const [rememberedGeoInsight, setRememberedGeoInsight] =
    useState<LastGeoInsightCache | null>(() => initialGeoInsightCache);
  const [activeLeftPanel, setActiveLeftPanel] =
    useState<LeftPanelTabKey>("data");
  const [mobileMapPanel, setMobileMapPanel] = useState<
    "map" | "left" | "right"
  >("map");
  const [tableLayer, setTableLayer] = useState<LoadedLayer | null>(null);
  const [visibleLayerExtentIds, setVisibleLayerExtentIds] = useState<
    Set<string>
  >(() => new Set());
  const [currentMapView, setCurrentMapView] = useState<MapViewState | null>(
    null,
  );
  const [mapObject, setMapObject] = useState<MapboxMap | null>(null);
  const [basemapSwitching, setBasemapSwitching] = useState(false);
  const [mapExporting, setMapExporting] = useState(false);
  const [editingComposition, setEditingComposition] =
    useState<MapComposition | null>(null);
  const [exportTileZoomRange, setExportTileZoomRange] = useState<TileZoomRange>(
    { min: 0, max: 22 },
  );
  const mapInstanceRef = useRef<MapboxMap | null>(null);
  const panelLayout = useMapPanelLayout(
    `user:${user?.id ?? "anonymous"}`,
    () => {
      mapInstanceRef.current?.resize();
    },
  );
  const resourceRequestSequenceRef = useRef(0);
  const resourceProfileRequestSequenceRef = useRef(0);
  const spatialProfileRequestSequenceRef = useRef(0);
  const spatialQuerySequenceRef = useRef(0);
  const latestResourceFiltersRef = useRef<ResourceFilters>({});
  const loadedSceneIdRef = useRef<number | null>(null);
  const loadedCompositionIdRef = useRef<number | null>(null);
  const mapErrorNotificationHistoryRef = useRef(new Map<string, number>());
  const permissions = {
    ...(user?.permissions ?? emptyPermissions),
    ...(getActiveProject() === "1"
      ? {
          canBrowseData: true,
          canQueryData: true,
          canLoadVectorLayer: true,
          canLoadRasterLayer: true,
          canViewWorkspaces: true,
          canViewMapCompositions: true,
        }
      : {}),
  };
  const userRoles = user?.roles ?? [];
  const categoryOptions = useMemo(
    () =>
      flattenTaxonomy(taxonomyTree(dataSchema)).map((node) => ({
        value: node.categoryCode,
        label: node.path.join(" / "),
      })),
    [dataSchema],
  );
  const selectedCategoryCode = useMemo(() => {
    const value = searchParams.get("categoryCode");
    return (
      findTaxonomyNode(taxonomyTree(dataSchema), value)?.categoryCode ?? null
    );
  }, [dataSchema, searchParams]);
  const urlResourceFilters = useMemo<ResourceFilters>(() => {
    const keyword = searchParams.get("resourceQ")?.trim() ?? "";
    return {
      ...(keyword ? { q: keyword } : {}),
      ...(selectedCategoryCode ? { categoryCode: selectedCategoryCode } : {}),
    };
  }, [searchParams, selectedCategoryCode]);

  const layerGroups = useLayerGroups(
    `${user ? `user-${user.id}` : "anonymous"}:project-${getActiveProject()}`,
  );
  const uniqueLayerLoad = useUniqueLayerLoad({
    scope: `${user?.id ?? "anonymous"}:${getActiveProject()}`,
    groups: layerGroups.groups,
    onExisting: async (group, layer) => {
      layerGroups.setGroupVisibility(group.id, true);
      layerGroups.setLayerVisibility(group.id, layer.id, true);
      setSelectedLayerId(layer.id);
      setActiveLeftPanel("layers");
      await locateLayer(group.id, layer.id);
      message.info(
        english
          ? "This data is already loaded; showing the existing layer"
          : "该数据已加载，已定位现有图层",
      );
    },
    onLoading: () => {
      message.info(
        english ? "This data is already loading" : "该数据正在加载，请稍候",
      );
    },
  });
  const { prepareRasterLayer, startRasterRender, setMapInstance } =
    useRasterRender(layerGroups.updateRasterLayer);
  const permissionDeniedMessage = english
    ? `Current role "${userRoles.length > 0 ? userRoles.join(", ") : "unassigned"}" is not authorized`
    : `当前角色"${userRoles.length > 0 ? userRoles.join("、") : "未分配角色"}"无权限`;
  const exportLayers = useLayerExport({
    canExportData: permissions.canExportData,
    permissionDeniedMessage,
    message,
  });
  const handleWorkspaceLoaded = useCallback(() => {
    setTableLayer(null);
    setSelectedFeature(null);
  }, []);
  const {
    workspaceScenes,
    workspaceTotal,
    workspaceQuery,
    workspaceAccessGroups,
    loadWorkspaceScenes,
    loadWorkspaceScene,
    loadWorkspaceSceneById,
    saveWorkspace,
    updateWorkspaceScene,
    deleteWorkspaceScene,
  } = useWorkspaceScenes({
    canViewWorkspaces: permissions.canViewWorkspaces,
    canQueryData: permissions.canQueryData,
    canLoadVectorLayer: permissions.canLoadVectorLayer,
    canLoadRasterLayer: permissions.canLoadRasterLayer,
    queryResultLimit: bootstrap.limits.queryResultLimit,
    groups: layerGroups.groups,
    selectedLayerId,
    currentMapView,
    mapRef: mapInstanceRef,
    replaceGroups: layerGroups.replaceGroups,
    setSelectedLayerId,
    onWorkspaceLoaded: handleWorkspaceLoaded,
  });
  const mapCompositions = useMapCompositions(
    permissions.canViewMapCompositions,
  );

  const mapLayers = useMemo(
    () => effectiveMapLayers(layerGroups.groups),
    [layerGroups.groups],
  );

  const allLayers = useMemo(
    () => layerGroups.groups.flatMap((group) => group.children),
    [layerGroups.groups],
  );
  const comparisonSources = useRef(new Map<number, GeoJsonFeatureCollection>());
  const registerComparisonLayer = async (
    profile: DataResourceProfile,
    result: ResourceQueryResult,
    placement?: ComparisonLayerPlacement,
  ) => {
    if (!permissions.canQueryData || !permissions.canLoadVectorLayer)
      throw new Error(permissionDeniedMessage);
    const signal = projectSignal();
    const projectId = getActiveProject();
    const resource = profile.resource;
    if (placement) {
      if (signal.aborted || getActiveProject() !== projectId)
        throw new DOMException("项目已切换", "AbortError");
      comparisonSources.current.set(
        resource.id,
        placement.displayData ?? result.geojson,
      );
      layerGroups.setGroups((current) =>
        upsertComparisonLayer(current, profile, result, placement),
      );
      setActiveLeftPanel("layers");
      return;
    }
    await uniqueLayerLoad.load(
      resourceLayerKey({ sourceResource: resource, layerType: "vector" }),
      async () => {
        if (signal.aborted || getActiveProject() !== projectId)
          throw new DOMException("项目已切换", "AbortError");
        const group = createVectorLayerGroup(resource, profile, result, {
          attributeFilters: [],
          spatialFilter: null,
        });
        layerGroups.addGroup(group);
        setSelectedLayerId(group.children[0]?.id ?? null);
        setActiveLeftPanel("layers");
        return true;
      },
    );
    if (signal.aborted || getActiveProject() !== projectId)
      throw new DOMException("项目已切换", "AbortError");
    // Reuse the registered layer while replacing any earlier partial query
    // with this complete, validated comparison response.
    const existing = layerGroups.groups.find((group) =>
      group.children.some(
        (layer) =>
          layer.layerType === "vector" &&
          resourceLayerKey(layer) === `resource:${resource.id}`,
      ),
    );
    const layer = existing?.children.find(
      (item) => resourceLayerKey(item) === `resource:${resource.id}`,
    );
    if (existing && layer?.layerType === "vector")
      layerGroups.updateLayer(existing.id, layer.id, (current) =>
        current.layerType === "vector"
          ? {
              ...current,
              geojson: result.geojson,
              fields: result.fields,
              summary: `${result.returnedCount}/${result.totalCount} 条，${profile.geometryType || "空间数据"}`,
              metadata: {
                ...current.metadata,
                返回条数: result.returnedCount,
                命中条数: result.totalCount,
              },
            }
          : current,
      );
  };
  useEffect(() => {
    if (!comparisonVisible && mapObject)
      requestAnimationFrame(() => mapObject.resize());
  }, [comparisonVisible, mapObject]);
  const spatialQueryResources = useMemo(
    () => loadedQueryResources(allLayers),
    [allLayers],
  );
  const spatialQueryResourcesRef = useRef(spatialQueryResources);
  spatialQueryResourcesRef.current = spatialQueryResources;
  useEffect(() => {
    const resourceRemoved =
      spatialTargetResource &&
      !spatialQueryResources.some(
        (resource) => resource.id === spatialTargetResource.id,
      );
    const layerRemoved =
      spatialTargetLayerId &&
      !allLayers.some(
        (layer) =>
          layer.id === spatialTargetLayerId && isQueryableLoadedLayer(layer),
      );
    if (resourceRemoved) {
      spatialProfileRequestSequenceRef.current += 1;
      setSpatialTargetResource(null);
      setSpatialTargetResourceProfile(null);
      setLoadingSpatialTargetProfile(false);
    }
    if (layerRemoved) setSpatialTargetLayerId(null);
    if (resourceRemoved || layerRemoved) clearSpatialQueryState();
  }, [
    allLayers,
    spatialQueryResources,
    spatialTargetResource,
    spatialTargetLayerId,
  ]);
  const compositionSourceText = useMemo(() => {
    const sources = new Set(
      allLayers
        .map((layer) => layer.sourceResource.source?.trim())
        .filter((value): value is string => Boolean(value)),
    );
    return sources.size > 0
      ? english
        ? `Data sources: ${Array.from(sources).join(", ")}`
        : `数据来源：${Array.from(sources).join("、")}`
      : english
        ? "Data sources: resources loaded by the platform"
        : "数据来源：平台已加载数据资源";
  }, [allLayers, english]);
  const compositionFallbackBounds = useMemo<MapBounds>(
    () => boundsFromUnknown(currentMapView?.bounds, [50, 35, 100, 48]),
    [currentMapView?.bounds],
  );
  const loadedSourceIds = useMemo(
    () => new Set(allLayers.map((layer) => sourceIdFor(layer.id))),
    [allLayers],
  );

  const syncExportTileZoomRange = useCallback(
    (map: MapboxMap | null = mapInstanceRef.current) => {
      if (!map) {
        setExportTileZoomRange({ min: 0, max: 22 });
        return;
      }
      let nextRange: TileZoomRange;
      try {
        nextRange = inferBasemapTileZoomRange(map.getStyle(), loadedSourceIds);
      } catch {
        return;
      }
      setExportTileZoomRange((currentRange) =>
        currentRange.min === nextRange.min && currentRange.max === nextRange.max
          ? currentRange
          : nextRange,
      );
    },
    [loadedSourceIds],
  );

  const selectedLayer = useMemo(() => {
    if (!selectedLayerId) {
      return null;
    }
    return allLayers.find((layer) => layer.id === selectedLayerId) ?? null;
  }, [allLayers, selectedLayerId]);

  const spatialTargetLayer = useMemo(() => {
    if (!spatialTargetLayerId) {
      return null;
    }
    return allLayers.find((layer) => layer.id === spatialTargetLayerId) ?? null;
  }, [allLayers, spatialTargetLayerId]);

  const rangeSourceLayer = spatialTargetLayer ?? selectedLayer;

  useEffect(() => {
    if (!selectedLayerId) {
      return;
    }
    setSelectedFeature((current) =>
      current && current.layerId !== selectedLayerId ? null : current,
    );
  }, [selectedLayerId]);

  const activeInsightLayer = useMemo(() => {
    if (selectedFeature) {
      return (
        allLayers.find((layer) => layer.id === selectedFeature.layerId) ??
        selectedLayer
      );
    }
    return selectedLayer;
  }, [allLayers, selectedFeature, selectedLayer]);

  const activeInsightResource = useMemo(
    () => activeInsightLayer?.sourceResource ?? selectedResource,
    [activeInsightLayer, selectedResource],
  );

  const activeInsightProfile = useMemo(() => {
    if (
      !activeInsightResource ||
      resourceProfile?.resource.id !== activeInsightResource.id
    ) {
      return null;
    }
    return resourceProfile;
  }, [activeInsightResource, resourceProfile]);

  useEffect(() => {
    if (
      !activeInsightResource &&
      !activeInsightLayer &&
      !activeInsightProfile &&
      !selectedFeature &&
      !visualizationSummary
    ) {
      return;
    }

    setRememberedGeoInsight((current) => {
      const nextResource =
        activeInsightResource ??
        activeInsightLayer?.sourceResource ??
        current?.resource ??
        null;
      const nextProfile =
        activeInsightProfile ??
        (nextResource && current?.profile?.resource.id === nextResource.id
          ? current.profile
          : null);
      const nextSummary =
        visualizationSummary &&
        nextResource &&
        visualizationSummary.resource.id === nextResource.id
          ? visualizationSummary
          : nextResource && current?.summary?.resource.id === nextResource.id
            ? current.summary
            : null;
      const nextLayer =
        activeInsightLayer ??
        (nextResource && current?.layer?.sourceResource.id === nextResource.id
          ? current.layer
          : null);
      const cachedFeature = selectedFeature ?? current?.feature ?? null;
      const nextFeature =
        cachedFeature && (!nextLayer || cachedFeature.layerId === nextLayer.id)
          ? cachedFeature
          : null;

      if (!nextResource && !nextLayer && !nextSummary) {
        return current;
      }

      const nextCache: LastGeoInsightCache = {
        resource: nextResource,
        profile: nextProfile,
        layer: nextLayer,
        feature: nextFeature,
        summary: nextSummary,
      };
      lastGeoInsightCache = nextCache;
      return nextCache;
    });
  }, [
    activeInsightLayer,
    activeInsightProfile,
    activeInsightResource,
    selectedFeature,
    visualizationSummary,
  ]);

  const rightPanelSelectedLayer =
    activeInsightLayer ?? rememberedGeoInsight?.layer ?? null;
  const rightPanelSelectedResource =
    activeInsightResource ??
    rightPanelSelectedLayer?.sourceResource ??
    rememberedGeoInsight?.resource ??
    null;
  const rightPanelSelectedResourceProfile =
    activeInsightProfile ??
    (rightPanelSelectedResource &&
    rememberedGeoInsight?.profile?.resource.id === rightPanelSelectedResource.id
      ? rememberedGeoInsight.profile
      : null);
  const rightPanelVisualizationSummary =
    visualizationSummary ??
    (rightPanelSelectedResource &&
    rememberedGeoInsight?.summary?.resource.id === rightPanelSelectedResource.id
      ? rememberedGeoInsight.summary
      : null);
  const rightPanelSelectedFeature = (() => {
    const feature = selectedFeature ?? rememberedGeoInsight?.feature ?? null;
    if (!feature) {
      return null;
    }
    return !rightPanelSelectedLayer ||
      feature.layerId === rightPanelSelectedLayer.id
      ? feature
      : null;
  })();
  const rightPanelVisualizationSummaryLoading =
    Boolean(activeInsightResource) && visualizationSummaryLoading;

  const spatialWorkbenchStatus = activeDraw
    ? english
      ? "Drawing spatial area"
      : "正在绘制空间范围"
    : spatialQuerying
      ? english
        ? "Running spatial query"
        : "正在执行空间查询"
      : spatialQueryResult
        ? english
          ? `${spatialQueryResult.totalCount} matches; ${spatialQueryResult.returnedCount} returned`
          : `命中 ${spatialQueryResult.totalCount} 条，返回 ${spatialQueryResult.returnedCount} 条`
        : spatialFilter
          ? english
            ? "Spatial query area set"
            : "已设置空间查询范围"
          : english
            ? "Draw an area, select a query target, and load results"
            : "范围绘制、查询对象与结果加载";

  useEffect(() => {
    if (!permissions.canBrowseData || !activeInsightResource) {
      setVisualizationSummary(null);
      setVisualizationSummaryError(null);
      setVisualizationSummaryLoading(false);
      return;
    }

    let ignore = false;
    setVisualizationSummaryLoading(true);
    setVisualizationSummaryError(null);
    api
      .resourceVisualizationSummary(activeInsightResource, {
        topN: 10,
        histogramBins: 8,
      })
      .then((summary) => {
        if (!ignore) {
          setVisualizationSummary(summary);
        }
      })
      .catch((error) => {
        if (!ignore) {
          setVisualizationSummary(null);
          setVisualizationSummaryError(
            error instanceof Error
              ? error.message
              : english
                ? "Failed to load visualization summary"
                : "可视化摘要加载失败",
          );
        }
      })
      .finally(() => {
        if (!ignore) {
          setVisualizationSummaryLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [activeInsightResource, permissions.canBrowseData]);

  const setLayerExtentVisibility = useCallback(
    (layerId: string, visible: boolean) => {
      setVisibleLayerExtentIds((current) => {
        if (current.has(layerId) === visible) {
          return current;
        }
        const next = new Set(current);
        if (visible) {
          next.add(layerId);
        } else {
          next.delete(layerId);
        }
        return next;
      });
    },
    [],
  );

  useEffect(() => {
    const activeLayerIds = new Set(allLayers.map((layer) => layer.id));
    setVisibleLayerExtentIds((current) => {
      const next = new Set(
        [...current].filter((layerId) => activeLayerIds.has(layerId)),
      );
      return next.size === current.size ? current : next;
    });
    setSpatialTargetLayerId((current) =>
      current && !activeLayerIds.has(current) ? null : current,
    );
  }, [allLayers]);

  const layerExtentOverlays = useMemo(() => {
    return allLayers.flatMap((layer) => {
      if (!visibleLayerExtentIds.has(layer.id)) {
        return [];
      }
      const geometry = layerExtentGeometryFor(layer);
      return geometry ? [{ layer, geometry }] : [];
    });
  }, [allLayers, visibleLayerExtentIds]);

  const isLayerExtentVisible = useCallback(
    (layerId: string) => visibleLayerExtentIds.has(layerId),
    [visibleLayerExtentIds],
  );

  const sharedSpatialGeometry = spatialFilter?.geometry ?? null;

  function layerExtentGeometryFor(layer: LoadedLayer) {
    return geometryFromBoundsText(
      layer.metadata.空间范围 ?? resourceSpatialExtent(layer.sourceResource),
    );
  }

  const loadResources = useCallback(
    async (filters: ResourceFilters) => {
      const requestId = ++resourceRequestSequenceRef.current;
      latestResourceFiltersRef.current = filters;
      setLoadingResources(true);
      try {
        const response = await api.resources({
          ...filters,
          spatialClass: "spatial",
        });
        const items = response.items.filter(isGeographicResource);
        if (requestId !== resourceRequestSequenceRef.current) {
          return items;
        }
        setResources(items);
        setSelectedResource((current) =>
          current && !items.some((item) => item.id === current.id)
            ? null
            : current,
        );
        setResourceProfile((current) =>
          current && !items.some((item) => item.id === current.resource.id)
            ? null
            : current,
        );
        setSpatialTargetResource((current) =>
          current && !items.some((item) => item.id === current.id)
            ? null
            : current,
        );
        setSpatialTargetResourceProfile((current) =>
          current && !items.some((item) => item.id === current.resource.id)
            ? null
            : current,
        );
        return items;
      } catch (error) {
        if (requestId === resourceRequestSequenceRef.current) {
          message.error(
            error instanceof Error
              ? error.message
              : english
                ? "Failed to load data resources"
                : "数据资源加载失败",
          );
        }
        return [];
      } finally {
        if (requestId === resourceRequestSequenceRef.current) {
          setLoadingResources(false);
        }
      }
    },
    [message],
  );

  useEffect(() => {
    void loadWorkspaceScenes();
  }, [loadWorkspaceScenes]);

  useEffect(() => {
    void mapCompositions.load();
  }, [mapCompositions.load]);

  useEffect(() => {
    if (!permissions.canBrowseData) {
      setDataSchema(null);
      return;
    }
    let ignore = false;
    api
      .dataSchemaSummary()
      .then((result) => {
        if (!ignore) {
          setDataSchema(result);
        }
      })
      .catch(() => {
        if (!ignore) {
          setDataSchema(null);
        }
      });
    return () => {
      ignore = true;
    };
  }, [permissions.canBrowseData]);

  useEffect(() => {
    const keyword = urlResourceFilters.q?.trim() ?? "";
    setResourceSearchKeyword(keyword);
    if (!permissions.canBrowseData) {
      return;
    }
    void loadResources(urlResourceFilters);
  }, [loadResources, permissions.canBrowseData, urlResourceFilters]);

  async function fetchResourceProfile(resource: ResourceListItem) {
    const requestSequence = ++resourceProfileRequestSequenceRef.current;
    setSelectedResource(resource);
    setResourceProfile(null);
    setLoadingProfile(true);
    try {
      const profile = await api.resourceProfile(resource);
      if (requestSequence === resourceProfileRequestSequenceRef.current) {
        setResourceProfile(profile);
      }
      return profile;
    } catch (error) {
      if (requestSequence === resourceProfileRequestSequenceRef.current) {
        setResourceProfile(null);
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to read fields and metadata"
              : "读取字段和元信息失败",
        );
      }
      return null;
    } finally {
      if (requestSequence === resourceProfileRequestSequenceRef.current) {
        setLoadingProfile(false);
      }
    }
  }

  async function fetchSpatialTargetResourceProfile(resource: ResourceListItem) {
    const requestSequence = ++spatialProfileRequestSequenceRef.current;
    setSpatialTargetResource(resource);
    setSpatialTargetResourceProfile(null);
    setLoadingSpatialTargetProfile(true);
    try {
      const profile = await api.resourceProfile(resource);
      if (requestSequence === spatialProfileRequestSequenceRef.current) {
        setSpatialTargetResourceProfile(profile);
      }
      return profile;
    } catch (error) {
      if (requestSequence === spatialProfileRequestSequenceRef.current) {
        setSpatialTargetResourceProfile(null);
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to read query-target metadata"
              : "读取查询对象元信息失败",
        );
      }
      return null;
    } finally {
      if (requestSequence === spatialProfileRequestSequenceRef.current) {
        setLoadingSpatialTargetProfile(false);
      }
    }
  }

  async function handleSelectResource(resource: ResourceListItem) {
    await fetchResourceProfile(resource);
  }

  const handleLeftPanelChange = useCallback((key: string) => {
    if (isLeftPanelTabKey(key)) {
      setActiveLeftPanel(key);
    }
  }, []);

  const handleDrawComplete = useCallback(
    (mode: NonNullable<DrawMode>, geometry: GeoJsonGeometry) => {
      setSpatialFilter({ mode, geometry });
      setActiveDraw(null);
    },
    [],
  );

  const setQueryDrawMode = useCallback(
    (mode: DrawMode | null) => {
      if (mode && basemapSwitching) {
        message.warning(
          english
            ? "Wait for the basemap switch to finish before drawing an area"
            : "底图正在切换，请等待完成后再绘制范围",
        );
        return;
      }
      setActiveDraw(mode ? { purpose: "query", mode } : null);
    },
    [basemapSwitching, message],
  );

  async function handleQueryAndLoad(attributeFilters: AttributeFilter[]) {
    if (!permissions.canQueryData || !permissions.canLoadVectorLayer) {
      message.warning(permissionDeniedMessage);
      return;
    }
    if (!selectedResource) {
      message.warning(
        english ? "Select a data resource first" : "请先选择数据资源",
      );
      return;
    }
    if (!resourceProfile) {
      message.warning(
        english
          ? "Wait for fields and metadata to finish loading"
          : "请先等待字段和元信息加载完成",
      );
      return;
    }
    await loadVectorResource(
      selectedResource,
      resourceProfile,
      attributeFilters,
      {
        spatialFilter,
        errorMessage: english ? "Query and load failed" : "查询并加载失败",
      },
    );
  }

  async function handleQuickLoadResource(
    resource: ResourceListItem,
    reportProgress: DataResourceLoadReporter = () => undefined,
  ) {
    if (
      await uniqueLayerLoad.showExisting(
        resourceLayerKey({
          sourceResource: resource,
          layerType: resource.dataType === "raster" ? "raster" : "vector",
        }),
      )
    ) {
      reportProgress({
        percent: 100,
        message: english ? "Showing existing layer" : "已定位现有图层",
      });
      return true;
    }
    reportProgress({
      percent: 8,
      message: english
        ? "Reading data-resource metadata"
        : "正在读取数据资源元信息",
    });
    const profile = await fetchResourceProfile(resource);
    if (!profile) {
      return false;
    }
    if (resource.isRenderable && resource.dataType === "raster") {
      return await loadRasterResource(resource, profile, reportProgress);
    }
    if (resource.isQueryable) {
      reportProgress({
        percent: 30,
        message: english
          ? "Querying and building vector layer"
          : "正在查询并构建矢量图层",
      });
      return await loadVectorResource(resource, profile, [], {
        spatialFilter: null,
        errorMessage: english ? "Load failed" : "加载失败",
        trackQuerying: false,
        reportProgress,
      });
    }
    return false;
  }

  const quickLoadResourceRef = useRef(handleQuickLoadResource);
  quickLoadResourceRef.current = handleQuickLoadResource;
  const urlResources = useMapUrlResources({
    params: searchParams,
    currentProject: getActiveProject(),
    projects: projectContext?.projects ?? [],
    chooseProject: projectContext?.choose,
    ready: Boolean(mapObject),
    loadingResources,
    resources,
    english,
    onStart: () => {
      setActiveLeftPanel("layers");
      setMobileMapPanel("map");
    },
    load: async (resource) =>
      (await quickLoadResourceRef.current(resource)) === true,
    showExisting: async (id) => {
      const group = layerGroups.groups.find((entry) =>
        entry.children.some((layer) => layer.sourceResource.id === id),
      );
      const layer = group?.children.find(
        (entry) => entry.sourceResource.id === id,
      );
      if (!group || !layer) return false;
      layerGroups.setGroupVisibility(group.id, true);
      layerGroups.setLayerVisibility(group.id, layer.id, true);
      setSelectedLayerId(layer.id);
      await locateLayer(group.id, layer.id);
      return true;
    },
  });
  const fittedUrlResources = useRef("");
  useEffect(() => {
    if (!mapObject || urlResources.loadedResourceIds.length < 2) return;
    const fitKey = `${getActiveProject()}:${urlResources.loadedResourceIds.join(",")}`;
    if (fittedUrlResources.current === fitKey) return;
    const bounds = mapUrlResourceBounds(
      layerGroups.groups.flatMap((group) => group.children),
      urlResources.loadedResourceIds,
    );
    if (!bounds) return;
    let disposed = false;
    void mapFitBoundsOptions(mapObject).then((options) => {
      if (disposed) return;
      fittedUrlResources.current = fitKey;
      mapObject.fitBounds(bounds, options);
    });
    return () => {
      disposed = true;
    };
  }, [mapObject, layerGroups.groups, urlResources.loadedResourceIds]);

  async function handleLoadRaster(reportProgress: DataResourceLoadReporter) {
    if (!permissions.canLoadRasterLayer) {
      message.warning(permissionDeniedMessage);
      return;
    }
    if (selectedResource?.dataType !== "raster" || !resourceProfile?.raster) {
      message.warning(
        english
          ? "Select a preprocessed raster resource first"
          : "请先选择已完成预处理的栅格数据",
      );
      return;
    }
    await loadRasterResource(selectedResource, resourceProfile, reportProgress);
  }

  async function loadRasterResource(
    resource: DataResource,
    profile: DataResourceProfile,
    reportProgress: DataResourceLoadReporter,
  ) {
    if (!permissions.canLoadRasterLayer) {
      message.warning(permissionDeniedMessage);
      return false;
    }
    return uniqueLayerLoad.load(
      resourceLayerKey({ sourceResource: resource, layerType: "raster" }),
      async () => loadNewRasterResource(resource, profile, reportProgress),
    );
  }

  async function loadNewRasterResource(
    resource: DataResource,
    profile: DataResourceProfile,
    reportProgress: DataResourceLoadReporter,
  ) {
    const group = createRasterLayerGroup(resource, profile);
    if (!group) {
      message.error(
        english
          ? "Raster metadata is incomplete and cannot be loaded"
          : "栅格元信息不完整，无法加载",
      );
      return false;
    }
    const pendingLayer = group.children[0] as LoadedRasterLayer;
    reportProgress({
      percent: 15,
      message: english
        ? "Preparing raster tile service"
        : "正在准备栅格瓦片服务",
    });
    let child: LoadedRasterLayer;
    try {
      child = await prepareRasterLayer(pendingLayer, (job) => {
        reportProgress(rasterDataLoadProgress(job, english));
      });
    } catch (error) {
      if (isAbortError(error)) return false;
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Failed to load raster"
            : "栅格加载失败",
      );
      return false;
    }
    reportProgress({
      percent: 98,
      message: english
        ? "Tile service is ready; adding it to the 3D globe"
        : "瓦片服务已就绪，正在添加到三维地球",
    });
    layerGroups.addGroup({ ...group, children: [child] });
    setSelectedLayerId(child.id);
    const map = mapInstanceRef.current;
    const bounds = child.imageCoordinates
      ? boundsFromImageCoordinates(child.imageCoordinates)
      : null;
    if (map && bounds) {
      void import("../map/mapViewport").then(({ rasterFitBoundsOptions }) => {
        map.fitBounds(bounds, rasterFitBoundsOptions());
      });
    }
    reportProgress({
      percent: 100,
      message: english
        ? "Raster imagery loaded on the 3D globe"
        : "栅格影像已加载到三维地球",
    });
    return true;
  }

  async function loadVectorResource(
    resource: ResourceListItem,
    profile: DataResourceProfile,
    attributeFilters: AttributeFilter[],
    options: {
      spatialFilter: SpatialFilter | null;
      errorMessage: string;
      trackQuerying?: boolean;
      reportProgress?: DataResourceLoadReporter;
    },
  ) {
    if (!permissions.canQueryData || !permissions.canLoadVectorLayer) {
      message.warning(permissionDeniedMessage);
      return false;
    }
    return uniqueLayerLoad.load(
      resourceLayerKey({
        sourceResource: resource,
        layerType: "vector",
        query: { attributeFilters, spatialFilter: options.spatialFilter },
      }),
      async () =>
        loadNewVectorResource(resource, profile, attributeFilters, options),
    );
  }

  async function loadNewVectorResource(
    resource: ResourceListItem,
    profile: DataResourceProfile,
    attributeFilters: AttributeFilter[],
    options: {
      spatialFilter: SpatialFilter | null;
      errorMessage: string;
      trackQuerying?: boolean;
      reportProgress?: DataResourceLoadReporter;
    },
  ) {
    const trackQuerying = options.trackQuerying !== false;
    if (trackQuerying) setQuerying(true);
    try {
      const result = await api.queryResource(resource, {
        attributeFilters,
        spatialFilter: options.spatialFilter,
        limit: bootstrap.limits.queryResultLimit,
      });
      options.reportProgress?.({
        percent: 82,
        message: english
          ? "Query complete; creating map layer"
          : "数据查询完成，正在创建地图图层",
      });
      showGeojsonWarnings(notification, result.warnings);
      const resultMessage = english
        ? `Query matched ${result.totalCount} records; ${result.returnedCount} returned`
        : `查询命中 ${result.totalCount} 条，返回 ${result.returnedCount} 条`;
      if (result.returnedCount === 0) {
        message.warning(resultMessage);
        return false;
      }
      const group = createVectorLayerGroup(resource, profile, result, {
        attributeFilters,
        spatialFilter: options.spatialFilter,
      });
      layerGroups.addGroup(group);
      setSelectedLayerId(group.children[0]?.id ?? null);
      options.reportProgress?.({
        percent: 100,
        message: english
          ? "Vector data loaded on the 3D globe"
          : "矢量数据已加载到三维地球",
      });
      message.success(resultMessage);
      return true;
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : options.errorMessage,
      );
      return false;
    } finally {
      if (trackQuerying) setQuerying(false);
    }
  }

  const handleMapReady = useCallback(
    (map: MapboxMap) => {
      mapInstanceRef.current = map;
      setMapObject(map);
      setMapInstance(map);
    },
    [setMapInstance],
  );

  const handleMapDestroy = useCallback(() => {
    mapInstanceRef.current = null;
    setMapObject(null);
    setMapInstance(null);
  }, [setMapInstance]);

  const handleMapError = useCallback(
    (errorMessage: string) => {
      if (
        !claimMapErrorNotification(
          mapErrorNotificationHistoryRef.current,
          errorMessage,
        )
      )
        return;
      message.open({
        key: mapErrorNotificationKey,
        type: "error",
        content: english
          ? `Map loading issue: ${summarizeMapErrorForUser(errorMessage, 160, true)}`
          : `地图加载异常：${summarizeMapErrorForUser(errorMessage)}`,
        duration: 5,
      });
    },
    [message],
  );

  useEffect(() => {
    if (!mapObject) return;
    const sync = () => syncExportTileZoomRange(mapObject);
    mapObject.on("load", sync);
    mapObject.on("idle", sync);
    return () => {
      mapObject.off("load", sync);
      mapObject.off("idle", sync);
    };
  }, [mapObject, syncExportTileZoomRange]);

  const locateLayer = useCallback(
    async (groupId: string, layerId: string) => {
      const map = mapInstanceRef.current;
      if (!map) {
        message.warning(english ? "The map is not ready" : "地图尚未准备好");
        return;
      }
      const targetGroup = layerGroups.groups.find((g) => g.id === groupId);
      const targetLayer = targetGroup?.children.find((l) => l.id === layerId);
      if (!targetLayer) {
        message.warning(
          english
            ? "The current layer has no locatable data"
            : "当前图层没有可定位的数据",
        );
        return;
      }
      if (
        targetLayer.layerType === "raster" &&
        targetLayer.imageCoordinates?.length
      ) {
        const bounds = boundsFromImageCoordinates(targetLayer.imageCoordinates);
        if (bounds) {
          const { rasterFitBoundsOptions } = await import("../map/mapViewport");
          map.fitBounds(bounds, rasterFitBoundsOptions());
          return;
        }
      }
      if (targetLayer.layerType !== "vector" || !targetLayer.geojson) {
        message.warning(
          english
            ? "The current layer has no locatable data"
            : "当前图层没有可定位的数据",
        );
        return;
      }
      fitGeojsonBounds(
        map,
        targetLayer.geojson,
        bootstrap.map.defaultCenter,
        bootstrap.map.defaultZoom,
        await mapFitBoundsOptions(map),
      );
    },
    [
      bootstrap.map.defaultCenter,
      bootstrap.map.defaultZoom,
      layerGroups.groups,
      message,
    ],
  );

  const locateGroup = useCallback(
    async (groupId: string) => {
      const map = mapInstanceRef.current;
      if (!map) {
        message.warning(english ? "The map is not ready" : "地图尚未准备好");
        return;
      }
      const targetGroup = layerGroups.groups.find((g) => g.id === groupId);
      if (!targetGroup) return;
      const geojsons = targetGroup.children
        .filter((l): l is LoadedVectorLayer => l.layerType === "vector")
        .map((l) => l.geojson);
      const rasterBounds = targetGroup.children
        .filter((l) => l.layerType === "raster" && l.imageCoordinates?.length)
        .map((l) => {
          const coords = (l as LoadedRasterLayer).imageCoordinates;
          return coords ? boundsFromImageCoordinates(coords) : null;
        })
        .filter(Boolean) as LngLatBounds[];
      if (geojsons.length === 0 && rasterBounds.length === 0) {
        message.warning(
          english
            ? "This layer group has no locatable data"
            : "该图层组没有可定位的数据",
        );
        return;
      }
      const bounds = combinedFeatureBounds(geojsons);
      for (const rasterBound of rasterBounds) {
        if (bounds) {
          bounds.extend(rasterBound.getSouthWest());
          bounds.extend(rasterBound.getNorthEast());
        }
      }
      const firstRasterBound = rasterBounds[0];
      if (!bounds && firstRasterBound) {
        const { rasterFitBoundsOptions } = await import("../map/mapViewport");
        map.fitBounds(firstRasterBound, rasterFitBoundsOptions());
        return;
      }
      if (!bounds) {
        message.warning(
          english
            ? "Unable to calculate the layer-group extent"
            : "无法计算图层组范围",
        );
        return;
      }
      map.fitBounds(bounds, await mapFitBoundsOptions(map));
    },
    [layerGroups.groups, message],
  );

  const handleSelectionChange = useCallback(
    (featureIds: (string | number)[]) => {
      const map = mapInstanceRef.current;
      if (!map) return;

      // 清除之前的选中状态
      clearFeatureState(map, "selectedFeature", "selected");

      if (
        featureIds.length > 0 &&
        tableLayer &&
        tableLayer.layerType === "vector"
      ) {
        const sourceId = sourceIdFor(tableLayer.id);

        // 设置所有选中要素的状态
        for (const featureId of featureIds) {
          const target = { source: sourceId, id: featureId };
          map.setFeatureState(target, { selected: true });
        }

        // 更新地图内部状态（使用第一个选中的要素）
        const selectedFeatureId = featureIds[0];
        if (selectedFeatureId === undefined) return;
        const state = getMapState(map);
        state.selectedFeature = { source: sourceId, id: selectedFeatureId };

        // 查找第一个选中要素的属性信息
        const feature = tableLayer.geojson.features.find((f) => {
          const fId = f.id;
          if (typeof fId === "string" || typeof fId === "number") {
            return featureIds.includes(fId);
          }
          return false;
        });

        if (feature) {
          setSelectedFeature({
            layerId: tableLayer.id,
            layerName: tableLayer.name,
            properties: (feature.properties ?? {}) as Record<string, unknown>,
          });
        }
      } else {
        setSelectedFeature(null);
      }
    },
    [tableLayer],
  );

  const exportCurrentMapPng = useCallback(
    async (options: MapImageExportOptions) => {
      if (!permissions.canExportData) {
        message.warning(permissionDeniedMessage);
        return;
      }
      const map = mapInstanceRef.current;
      if (!map) {
        message.warning(english ? "The map is not ready" : "地图尚未准备好");
        return;
      }
      if (basemapSwitching) {
        message.warning(
          english
            ? "Wait for the basemap switch to finish before exporting"
            : "底图正在切换，请等待完成后再导出",
        );
        return;
      }
      try {
        map.getStyle();
      } catch {
        message.warning(
          english
            ? "The basemap has not finished loading. Export again shortly."
            : "底图尚未加载完成，请稍后再导出",
        );
        return;
      }
      if (!map.isStyleLoaded()) {
        message.warning(
          english
            ? "The basemap has not finished loading. Export again shortly."
            : "底图尚未加载完成，请稍后再导出",
        );
        return;
      }
      if (!sharedSpatialGeometry) {
        message.warning(
          english
            ? "Use the area tool to define an export area first"
            : "请先使用范围工具划定导出范围",
        );
        return;
      }
      setMapExporting(true);
      try {
        const blob = await exportMapRangeImage(map, sharedSpatialGeometry, {
          ...options,
          accessToken: bootstrap.map.mapboxAccessToken,
        });
        const extension = options.format === "png" ? "png" : "jpg";
        downloadBlob(
          blob,
          `map-2d-z${options.tileZoom}-${options.dpi}dpi-${new Date()
            .toISOString()
            .slice(0, 19)
            .replace(/[-:T]/g, "")}.${extension}`,
        );
        message.success(
          english
            ? `Map exported as ${extension.toUpperCase()}`
            : `地图 ${extension.toUpperCase()} 已导出`,
        );
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to export map image"
              : "地图图片导出失败",
        );
      } finally {
        setMapExporting(false);
      }
    },
    [
      basemapSwitching,
      bootstrap.map.mapboxAccessToken,
      message,
      permissionDeniedMessage,
      permissions.canExportData,
      sharedSpatialGeometry,
    ],
  );

  function handleUseCurrentViewRange() {
    if (!currentMapView) {
      message.warning(
        english ? "The map view is not ready" : "地图视图尚未就绪",
      );
      return;
    }
    const [west, south, east, north] = currentMapView.bounds;
    if (![west, south, east, north].every(Number.isFinite)) {
      message.warning(
        english ? "The current view extent is invalid" : "当前视图范围无效",
      );
      return;
    }
    setSpatialFilter({
      mode: "rectangle",
      geometry: rectangleGeometry([west, south], [east, north]),
    });
    setActiveDraw(null);
  }

  function handleUseSelectedLayerRange() {
    if (!rangeSourceLayer) {
      message.warning(
        english
          ? "Select a layer in the spatial query workspace or layer tree first"
          : "请先在空间查询工作台或图层树选择图层",
      );
      return;
    }
    const geometry = layerExtentGeometryFor(rangeSourceLayer);
    if (!geometry) {
      message.warning(
        english
          ? "The current layer has no usable spatial extent"
          : "当前图层没有可用空间范围",
      );
      return;
    }
    setSpatialFilter({ mode: "rectangle", geometry });
    setActiveDraw(null);
  }

  function handleClearSpatialFilter() {
    setSpatialFilter(null);
    setActiveDraw(null);
  }

  function handleImportSpatialFilter(filter: SpatialFilter) {
    setSpatialFilter(filter);
    setActiveDraw(null);
    void locateImportedSpatialFilter(filter.geometry);
  }

  async function locateImportedSpatialFilter(geometry: GeoJsonGeometry) {
    const map = mapInstanceRef.current;
    if (!map) return;
    try {
      fitGeojsonBounds(
        map,
        geojsonFromGeometry(geometry),
        bootstrap.map.defaultCenter,
        bootstrap.map.defaultZoom,
        await mapFitBoundsOptions(map),
      );
    } catch {
      message.warning(
        english
          ? "The spatial area was imported, but the map could not locate it"
          : "空间范围已导入，但地图定位失败",
      );
    }
  }

  function clearSpatialQueryState() {
    spatialQuerySequenceRef.current += 1;
    setSpatialQuerying(false);
    setSpatialQueryData(null);
    setSpatialQueryContext(null);
    setSpatialQueryResult(null);
  }

  async function handleSelectSpatialTargetResource(resourceId: number | null) {
    clearSpatialQueryState();
    if (resourceId === null) {
      spatialProfileRequestSequenceRef.current += 1;
      setLoadingSpatialTargetProfile(false);
      setSpatialTargetResource(null);
      setSpatialTargetResourceProfile(null);
      return;
    }
    const resource = spatialQueryResources.find(
      (item) => item.id === resourceId,
    );
    if (!resource) {
      message.warning(
        english
          ? "Load a queryable vector resource into the layer tree first"
          : "请先将可查询的矢量资源加载到图层树",
      );
      return;
    }
    if (resource.dataType !== "vector" || !resource.isQueryable) {
      message.warning(
        english
          ? "Select a queryable vector resource"
          : "请选择可查询的矢量资源",
      );
      return;
    }
    await fetchSpatialTargetResourceProfile(resource);
  }

  function handleSelectSpatialTargetLayer(layerId: string | null) {
    clearSpatialQueryState();
    if (layerId === null) {
      setSpatialTargetLayerId(null);
      return;
    }
    const layer = allLayers.find((item) => item.id === layerId);
    if (!layer || layer.layerType !== "vector") {
      message.warning(
        english ? "Select a loaded vector layer" : "请选择已加载的矢量图层",
      );
      return;
    }
    setSpatialTargetLayerId(layerId);
  }

  async function resolveSpatialQueryContext(
    target: SpatialQueryTarget,
    queryFilter: SpatialFilter,
  ): Promise<SpatialQueryContext | null> {
    const query = {
      attributeFilters: [],
      spatialFilter: queryFilter,
    };
    if (target === "selectedResource") {
      if (
        !spatialTargetResource ||
        !spatialQueryResources.some(
          (resource) => resource.id === spatialTargetResource.id,
        )
      ) {
        message.warning(
          english
            ? "Select a resource in the spatial query workspace first"
            : "请先在空间查询工作台选择资源",
        );
        return null;
      }
      if (
        spatialTargetResource.dataType !== "vector" ||
        !spatialTargetResource.isQueryable ||
        !spatialTargetResourceProfile
      ) {
        message.warning(
          english
            ? "The current resource is not a queryable vector resource"
            : "当前资源不是可查询的矢量资源",
        );
        return null;
      }
      return {
        target,
        targetName: spatialTargetResource.name,
        resource: spatialTargetResource,
        profile: spatialTargetResourceProfile,
        query,
      };
    }

    if (!spatialTargetLayer || spatialTargetLayer.layerType !== "vector") {
      message.warning(
        english
          ? "Select a vector layer in the spatial query workspace first"
          : "请先在空间查询工作台选择矢量图层",
      );
      return null;
    }
    const resource = spatialTargetLayer.sourceResource;
    if (
      resource.id <= 0 ||
      resource.dataType !== "vector" ||
      !resource.isQueryable
    ) {
      message.warning(
        english
          ? "The current layer has no queryable source resource"
          : "当前图层没有可反查的可查询来源资源",
      );
      return null;
    }
    const profile =
      spatialTargetResource?.id === resource.id && spatialTargetResourceProfile
        ? spatialTargetResourceProfile
        : selectedResource?.id === resource.id && resourceProfile
          ? resourceProfile
          : await api.resourceProfile(resource);
    return {
      target,
      targetName: spatialTargetLayer.name,
      resource,
      profile,
      query,
    };
  }

  async function handleRunSpatialQuery(target: SpatialQueryTarget) {
    if (!permissions.canQueryData || !permissions.canLoadVectorLayer) {
      message.warning(permissionDeniedMessage);
      return;
    }
    if (!spatialFilter?.geometry) {
      message.warning(
        english ? "Set a spatial query area first" : "请先设置空间查询范围",
      );
      return;
    }

    const sequence = ++spatialQuerySequenceRef.current;
    setSpatialQuerying(true);
    setSpatialQueryData(null);
    setSpatialQueryContext(null);
    setSpatialQueryResult(null);
    try {
      const context = await resolveSpatialQueryContext(target, spatialFilter);
      if (
        !context ||
        sequence !== spatialQuerySequenceRef.current ||
        !spatialQueryResourcesRef.current.some(
          (resource) => resource.id === context.resource.id,
        )
      ) {
        return;
      }
      const result = await api.queryResource(context.resource, {
        ...context.query,
        limit: bootstrap.limits.queryResultLimit,
      });
      if (
        sequence !== spatialQuerySequenceRef.current ||
        !spatialQueryResourcesRef.current.some(
          (resource) => resource.id === context.resource.id,
        )
      )
        return;
      showGeojsonWarnings(notification, result.warnings);
      setSpatialQueryData(result);
      setSpatialQueryContext(context);
      setSpatialQueryResult({
        id: `spatial-query-${context.resource.id}-${Date.now()}`,
        target,
        targetName: context.targetName,
        resourceName: context.resource.name,
        rangeMode: spatialFilter.mode,
        totalCount: result.totalCount,
        returnedCount: result.returnedCount,
        limit: result.limit,
        limitExceeded: result.limitExceeded,
        bounds: result.bounds,
        elapsedMs: result.elapsedMs,
        warningCount: result.warnings.length,
        loadedLayerName: null,
      });

      const resultMessage = spatialQueryMessage(result, english);
      if (result.returnedCount === 0) {
        message.warning(resultMessage);
      } else if (result.limitExceeded) {
        message.warning(resultMessage);
      } else {
        message.success(resultMessage);
      }
    } catch (error) {
      if (sequence !== spatialQuerySequenceRef.current) return;
      message.error(
        error instanceof Error
          ? error.message
          : english
            ? "Spatial query failed"
            : "空间查询执行失败",
      );
    } finally {
      if (sequence === spatialQuerySequenceRef.current)
        setSpatialQuerying(false);
    }
  }

  function createSpatialResultGroup() {
    if (!spatialQueryData || !spatialQueryContext || !spatialQueryResult) {
      return null;
    }
    if (spatialQueryData.returnedCount === 0) {
      return null;
    }
    const name =
      spatialQueryResult.loadedLayerName ??
      (english
        ? `Spatial query results - ${spatialQueryContext.targetName}`
        : `空间查询结果 - ${spatialQueryContext.targetName}`);
    return createVectorLayerGroup(
      spatialQueryContext.resource,
      spatialQueryContext.profile,
      spatialQueryData,
      spatialQueryContext.query,
      {
        name,
        metadata: english
          ? {
              "Query type": "Spatial query",
              "Query target": spatialQueryContext.targetName,
              "Query source":
                spatialQueryContext.target === "selectedLayer"
                  ? "Current layer"
                  : "Current resource",
              "Source resource": spatialQueryContext.resource.name,
              "Spatial area": spatialQueryContext.query.spatialFilter
                ? spatialFilterModeLabel(
                    spatialQueryContext.query.spatialFilter.mode,
                    true,
                  )
                : "Not set",
              "Total matches": spatialQueryData.totalCount,
              "Returned records": spatialQueryData.returnedCount,
              "Return limit": spatialQueryData.limit,
              Truncated: spatialQueryData.limitExceeded ? "Yes" : "No",
              "Backend time (ms)": spatialQueryData.elapsedMs,
            }
          : {
              查询类型: "空间查询",
              查询对象: spatialQueryContext.targetName,
              查询来源:
                spatialQueryContext.target === "selectedLayer"
                  ? "当前图层"
                  : "当前资源",
              来源资源: spatialQueryContext.resource.name,
              空间范围: spatialQueryContext.query.spatialFilter
                ? spatialFilterModeLabel(
                    spatialQueryContext.query.spatialFilter.mode,
                  )
                : "未设置",
              命中总数: spatialQueryData.totalCount,
              返回条数: spatialQueryData.returnedCount,
              返回上限: spatialQueryData.limit,
              结果截断: spatialQueryData.limitExceeded ? "是" : "否",
              后端耗时ms: spatialQueryData.elapsedMs,
            },
      },
    );
  }

  function handleLoadSpatialResult() {
    const group = createSpatialResultGroup();
    const layer = group?.children[0];
    if (!group || !layer) {
      message.warning(
        english
          ? "No spatial query results are available to load"
          : "暂无可加载的空间查询结果",
      );
      return;
    }
    void uniqueLayerLoad.load(resourceLayerKey(layer), async () => {
      layerGroups.addGroup(group);
      setSelectedLayerId(group.children[0]?.id ?? null);
      setSpatialQueryResult((current) =>
        current ? { ...current, loadedLayerName: group.name } : current,
      );
      message.success(
        english
          ? "Spatial query results loaded as a layer"
          : "空间查询结果已加载为图层",
      );
      return true;
    });
  }

  async function handleLocateSpatialResult() {
    if (!spatialQueryData || spatialQueryData.returnedCount === 0) {
      message.warning(
        english
          ? "No spatial query results are available to locate"
          : "暂无可定位的空间查询结果",
      );
      return;
    }
    const map = mapInstanceRef.current;
    if (!map) {
      message.warning(english ? "The map is not ready" : "地图尚未准备好");
      return;
    }
    fitGeojsonBounds(
      map,
      spatialQueryData.geojson,
      bootstrap.map.defaultCenter,
      bootstrap.map.defaultZoom,
      await mapFitBoundsOptions(map),
    );
  }

  function handleOpenSpatialResultTable() {
    const group = createSpatialResultGroup();
    const layer = group?.children.find(
      (item): item is LoadedVectorLayer => item.layerType === "vector",
    );
    if (!layer) {
      message.warning(
        english
          ? "No spatial query results are available to view"
          : "暂无可查看的空间查询结果",
      );
      return;
    }
    setTableLayer(layer);
  }

  function handleExportSpatialResult() {
    if (!spatialQueryData || !spatialQueryContext || !spatialQueryResult) {
      message.warning(
        english
          ? "No spatial query results are available to export"
          : "暂无可导出的空间查询结果",
      );
      return;
    }
    if (spatialQueryData.returnedCount === 0) {
      message.warning(
        english
          ? "The spatial query result is empty and cannot be exported"
          : "空间查询结果为空，无法导出",
      );
      return;
    }
    void exportLayers(
      [
        {
          layerType: "vector",
          name:
            spatialQueryResult.loadedLayerName ??
            (english
              ? `Spatial query results - ${spatialQueryContext.targetName}`
              : `空间查询结果 - ${spatialQueryContext.targetName}`),
          resourceId: spatialQueryContext.resource.id,
          geojson: spatialQueryData.geojson,
          sourceCrs:
            spatialQueryContext.resource.coordinateSystem || "EPSG:4326",
        },
      ],
      {
        epsg: 4326,
        reproject: true,
        clip: false,
        clipGeometry: null,
        format: "geojson",
      },
    ).catch(() => undefined);
  }

  function handleClearSpatialResult() {
    setSpatialQueryData(null);
    setSpatialQueryContext(null);
    setSpatialQueryResult(null);
  }

  useEffect(() => {
    const sceneIdText = searchParams.get("sceneId")?.trim();
    if (!sceneIdText) {
      loadedSceneIdRef.current = null;
      return;
    }
    const sceneId = Number(sceneIdText);
    if (!Number.isInteger(sceneId) || sceneId <= 0) {
      message.warning(
        english
          ? "Invalid project or thematic-map parameter"
          : "工程或专题参数无效",
      );
      return;
    }
    if (loadedSceneIdRef.current === sceneId) {
      return;
    }
    loadedSceneIdRef.current = sceneId;
    async function loadSceneFromUrl() {
      try {
        await loadWorkspaceSceneById(sceneId);
      } catch (error) {
        loadedSceneIdRef.current = null;
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load project or thematic map"
              : "工程或专题加载失败",
        );
      }
    }
    void loadSceneFromUrl();
  }, [english, loadWorkspaceSceneById, message, searchParams]);

  const layerContextValue: LayerContextValue = {
    groups: layerGroups.groups,
    selectedLayerId,
    selectLayer: (_groupId, layerId) => {
      setSelectedLayerId(layerId);
      setSelectedFeature((current) =>
        current && current.layerId !== layerId ? null : current,
      );
    },
    openLayerTable: (_groupId, layerId) => {
      const layer =
        layerGroups.groups
          .flatMap((group) => group.children)
          .find((item) => item.id === layerId) ?? null;
      setTableLayer(layer);
    },
    addGroup: layerGroups.addGroup,
    replaceGroups: layerGroups.replaceGroups,
    updateLayer: layerGroups.updateLayer,
    updateRasterLayer: layerGroups.updateRasterLayer,
    setGroupVisibility: layerGroups.setGroupVisibility,
    setGroupName: layerGroups.setGroupName,
    setGroupSymbolization: layerGroups.setGroupSymbolization,
    setLayerVisibility: layerGroups.setLayerVisibility,
    isLayerExtentVisible,
    setLayerExtentVisibility,
    setLayerName: layerGroups.setLayerName,
    setLayerSymbolization: layerGroups.setLayerSymbolization,
    removeGroup: layerGroups.removeGroup,
    removeLayer: layerGroups.removeLayer,
    reorderGroups: layerGroups.reorderGroups,
    moveLayer: layerGroups.moveLayer,
    extractLayer: layerGroups.extractLayer,
    startRasterRender: (groupId, layerId, symbolization, layer, rulesMode) =>
      void startRasterRender(groupId, layerId, symbolization, layer, rulesMode),
    locateLayer,
    locateGroup,
    mapRef: mapInstanceRef,
    canUseCustomSymbolization: permissions.canUseCustomSymbolization,
    canExportData: permissions.canExportData,
    exportClipGeometry: sharedSpatialGeometry,
    clearExportClipGeometry: () => setSpatialFilter(null),
    exportLayers,
    workspaceScenes,
    workspaceAccessGroups,
    canCreateWorkspaces: permissions.canCreateWorkspaces,
    saveWorkspace,
  };

  const handleCreateMapComposition = useCallback(
    async (scene: WorkspaceSceneSummary) => {
      if (!permissions.canCreateMapCompositions) {
        message.warning(permissionDeniedMessage);
        return;
      }
      try {
        await loadWorkspaceScene(scene);
        const snapshot = (await api.workspace(scene.id)).snapshot as {
          mapView?: { bounds?: unknown } | null;
        };
        const bounds = boundsFromUnknown(
          snapshot.mapView?.bounds,
          compositionFallbackBounds,
        );
        const baseName = english
          ? `${scene.name} thematic map`
          : `${scene.name}专题图`;
        const sameNames = new Set(
          mapCompositions.items
            .filter((item) => item.projectId === scene.id)
            .map((item) => item.name),
        );
        let name = baseName;
        let suffix = 2;
        while (sameNames.has(name)) {
          name = english
            ? `${baseName} (${suffix})`
            : `${baseName}（${suffix}）`;
          suffix += 1;
        }
        const created = await mapCompositions.create(scene.id, name, {
          ...defaultCompositionLayout(name, bounds, compositionSourceText),
          basemapId: selectedMapBasemap(mapInstanceRef.current),
        });
        setEditingComposition(created);
        setActiveLeftPanel("topics");
        message.success(
          english ? "Map-output draft created" : "出图草稿已创建",
        );
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to create map-output draft"
              : "出图草稿创建失败",
        );
      }
    },
    [
      compositionFallbackBounds,
      compositionSourceText,
      english,
      loadWorkspaceScene,
      mapCompositions,
      message,
      permissionDeniedMessage,
      permissions.canCreateMapCompositions,
    ],
  );

  const handleOpenMapComposition = useCallback(
    async (composition: MapComposition) => {
      try {
        const project =
          workspaceScenes.find((scene) => scene.id === composition.projectId) ??
          (await api.workspace(composition.projectId));
        await loadWorkspaceScene(project);
        const basemapId = composition.layout.basemapId;
        if (mapInstanceRef.current && typeof basemapId === "string")
          await restoreMapBasemap(mapInstanceRef.current, basemapId);
        setEditingComposition(composition);
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load source project"
              : "来源工程加载失败",
        );
      }
    },
    [english, loadWorkspaceScene, message, workspaceScenes],
  );

  useEffect(() => {
    const compositionIdText = searchParams.get("compositionId")?.trim();
    if (!compositionIdText) {
      loadedCompositionIdRef.current = null;
      return;
    }
    const compositionId = Number(compositionIdText);
    if (!Number.isInteger(compositionId) || compositionId <= 0) {
      message.warning(
        english ? "Invalid thematic-map parameter" : "专题参数无效",
      );
      return;
    }
    if (loadedCompositionIdRef.current === compositionId) {
      return;
    }
    loadedCompositionIdRef.current = compositionId;
    api
      .mapComposition(compositionId)
      .then(handleOpenMapComposition)
      .catch((error) => {
        loadedCompositionIdRef.current = null;
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load thematic map"
              : "专题加载失败",
        );
      });
  }, [english, handleOpenMapComposition, message, searchParams]);

  const handleLoadMapCompositionSource = useCallback(
    async (composition: MapComposition) => {
      try {
        const project =
          workspaceScenes.find((scene) => scene.id === composition.projectId) ??
          (await api.workspace(composition.projectId));
        await loadWorkspaceScene(project);
        setActiveLeftPanel("projects");
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : english
              ? "Failed to load source project"
              : "来源工程加载失败",
        );
      }
    },
    [english, loadWorkspaceScene, message, workspaceScenes],
  );

  const handleRestoredMapCompositionProject = useCallback(
    async (project: WorkspaceScene) => {
      await loadWorkspaceScenes();
      await loadWorkspaceScene(project);
      setActiveLeftPanel("projects");
    },
    [loadWorkspaceScene, loadWorkspaceScenes],
  );

  const renderDataPanel = () => (
    <DataPanel
      resources={resources}
      profile={resourceProfile}
      selectedResourceId={selectedResource?.id ?? null}
      loadingResources={loadingResources}
      loadingProfile={loadingProfile}
      querying={querying}
      permissions={permissions}
      categoryOptions={categoryOptions}
      selectedCategoryCode={selectedCategoryCode}
      searchKeyword={resourceSearchKeyword}
      onFilterResources={loadResources}
      onSelectResource={handleSelectResource}
      onQuickLoadResource={async (resource, reportProgress) => {
        await handleQuickLoadResource(resource, reportProgress);
      }}
      onQueryAndLoad={handleQueryAndLoad}
      onLoadRaster={handleLoadRaster}
    />
  );
  return (
    <Layout className="workspace">
      <WorkspaceHeader
        activeTab="map"
        canBrowseData={permissions.canBrowseData}
        resources={resources}
        workspaceScenes={workspaceScenes}
        mapCompositions={mapCompositions.items}
        dataSchema={dataSchema}
        searchKeyword={resourceSearchKeyword}
        onGlobalSearch={(keyword) => {
          setResourceSearchKeyword(keyword);
        }}
        onQuickLoadResource={(resource) =>
          void handleQuickLoadResource(resource)
        }
        onLoadWorkspaceScene={loadWorkspaceScene}
        onLoadMapComposition={(composition) =>
          void handleOpenMapComposition(composition)
        }
        onSearchFocus={() => {
          if (permissions.canViewWorkspaces) {
            void loadWorkspaceScenes();
          }
          if (permissions.canViewMapCompositions) {
            void mapCompositions.load();
          }
        }}
      />
      <div
        ref={panelLayout.containerRef}
        style={panelLayout.style}
        className={`workspace-body workspace-map-resizable ${
          spatialWorkbenchOpen
            ? "workspace-body-spatial-open"
            : "workspace-body-spatial-collapsed"
        }`}
      >
        <div
          className="mobile-map-panel-switcher"
          role="group"
          aria-label={
            english ? "Mobile map panel switcher" : "移动端地图面板切换"
          }
        >
          <Button
            size="small"
            type={mobileMapPanel === "map" ? "primary" : "text"}
            aria-pressed={mobileMapPanel === "map"}
            onClick={() => setMobileMapPanel("map")}
          >
            {english ? "Map" : "地图"}
          </Button>
          <Button
            size="small"
            type={mobileMapPanel === "left" ? "primary" : "text"}
            aria-pressed={mobileMapPanel === "left"}
            onClick={() => setMobileMapPanel("left")}
          >
            {english ? "Data and layers" : "数据与图层"}
          </Button>
          <Button
            size="small"
            type={mobileMapPanel === "right" ? "primary" : "text"}
            aria-pressed={mobileMapPanel === "right"}
            onClick={() => setMobileMapPanel("right")}
          >
            {english ? "Data insights" : "数据洞察"}
          </Button>
        </div>
        <main className="map-stage">
          {urlResources.error && (
            <div
              style={{
                position: "absolute",
                top: 16,
                left: "50%",
                transform: "translateX(-50%)",
                zIndex: 8,
                width: "min(520px, 90%)",
              }}
            >
              <Alert
                type="warning"
                title={urlResources.error}
                action={
                  <Button size="small" onClick={urlResources.retry}>
                    {english ? "Retry" : "重试加载"}
                  </Button>
                }
              />
            </div>
          )}
          <div
            className={`geology-workbench-single-map ${comparisonVisible ? "is-covered" : ""}`}
            style={{ width: "100%", height: "100%" }}
            aria-hidden={comparisonVisible}
          >
            <Suspense
              fallback={
                <div className="map-canvas-loading">
                  <Spin size="large" />
                </div>
              }
            >
              <MapCanvas
                bootstrap={bootstrap}
                basemapPreferenceScope={`user:${user?.id ?? "anonymous"}`}
                basemapSwitchDisabled={mapExporting}
                loadedLayers={mapLayers}
                drawMode={activeDraw?.mode ?? null}
                spatialFilter={spatialFilter}
                layerExtentOverlays={layerExtentOverlays}
                onDrawComplete={handleDrawComplete}
                onFeatureSelect={setSelectedFeature}
                onMapReady={handleMapReady}
                onMapDestroy={handleMapDestroy}
                onMapError={handleMapError}
                onViewStateChange={setCurrentMapView}
                onBasemapSwitchingChange={setBasemapSwitching}
              />
            </Suspense>
          </div>
          {comparisonWorkflowId && (
            <Suspense
              fallback={
                <div className="map-canvas-loading">
                  <Spin />
                </div>
              }
            >
              <GeologyWorkbenchCompare
                key={`${getActiveProject()}:${comparisonWorkflowId}`}
                workflowId={comparisonWorkflowId}
                projectId={getActiveProject()}
                projectTagId={searchParams.get("projectTagId")}
                suggestionId={searchParams.get("suggestion")}
                accessToken={bootstrap.map.mapboxAccessToken}
                canLoad={
                  permissions.canQueryData && permissions.canLoadVectorLayer
                }
                comparisonVisible={comparisonVisible}
                registerLayer={registerComparisonLayer}
                selectedObject={selectedFeature?.properties ?? null}
                onLayerDisplay={(side, changes, current) => {
                  layerGroups.setGroups((groups) =>
                    displayComparisonLayers(
                      groups,
                      comparisonWorkflowId,
                      side,
                      changes,
                      comparisonSources.current,
                    ),
                  );
                  const bounds = reviewBounds(current ?? changes);
                  if (bounds && mapInstanceRef.current && !comparisonVisible)
                    mapInstanceRef.current.fitBounds(
                      [
                        [bounds[0], bounds[1]],
                        [bounds[2], bounds[3]],
                      ],
                      { padding: 75, maxZoom: 16, duration: 350 },
                    );
                }}
                onVisibilityChange={(visible) => {
                  const next = new URLSearchParams(searchParams);
                  if (visible) next.delete("mapMode");
                  else next.set("mapMode", "single");
                  setSearchParams(next, { replace: true });
                }}
                onSuggestionChange={(id) => {
                  const next = new URLSearchParams(searchParams);
                  if (id) next.set("suggestion", id);
                  else next.delete("suggestion");
                  setSearchParams(next, { replace: true });
                }}
                onSwitchProject={
                  searchParams.get("projectTagId") !== getActiveProject() &&
                  projectContext?.projects.some(
                    (item) =>
                      String(item.id) === searchParams.get("projectTagId"),
                  )
                    ? () =>
                        projectContext?.choose(
                          searchParams.get("projectTagId")!,
                        )
                    : undefined
                }
              />
            </Suspense>
          )}
          {/^[1-9]\d*$/.test(searchParams.get("computeOutputId") ?? "") && (
            <ComputeOutputMapPreview
              key={searchParams.get("computeOutputId")}
              outputId={Number(searchParams.get("computeOutputId"))}
              projectTagId={searchParams.get("projectTagId")}
              map={mapObject}
              onClose={() => {
                const next = new URLSearchParams(searchParams);
                next.delete("computeOutputId");
                setSearchParams(next, { replace: true });
              }}
            />
          )}
          {!comparisonVisible && (
            <WorkbenchLegend
              layers={mapLayers}
              english={english}
              mobileHidden={mobileMapPanel !== "map"}
            />
          )}
        </main>
        <aside
          className={`floating-panel floating-panel-left ${panelLayout.layout.leftCollapsed ? "map-panel-is-collapsed" : ""} ${
            mobileMapPanel === "left"
              ? "mobile-map-panel-visible"
              : "mobile-map-panel-hidden"
          }`}
        >
          <MapPanelChrome
            side="left"
            title={english ? "Data and layers" : "数据与图层"}
            collapsed={panelLayout.layout.leftCollapsed}
            width={panelLayout.layout.left}
            english={english}
            onToggle={() => panelLayout.toggle("left")}
            onResizeStart={(event) => panelLayout.beginResize("left", event)}
            onResize={(amount) => panelLayout.resize("left", amount)}
          />
          <div className="map-panel-content">
            <ConfigProvider theme={workspacePanelTheme}>
              <LayerContext.Provider value={layerContextValue}>
                <Tabs
                  className="workspace-side-tabs workspace-left-tabs"
                  activeKey={activeLeftPanel}
                  onChange={handleLeftPanelChange}
                  size="small"
                  items={[
                    {
                      key: "data",
                      label: (
                        <span className="tab-label">
                          <DatabaseOutlined style={{ fontSize: 14 }} />
                          {english ? "Data" : "数据"}
                        </span>
                      ),
                      children: renderDataPanel(),
                    },
                    {
                      key: "layers",
                      label: (
                        <span className="tab-label">
                          <ApartmentOutlined style={{ fontSize: 14 }} />
                          {english ? "Layers" : "图层"}
                        </span>
                      ),
                      children: <LayerPanel />,
                    },
                    {
                      key: "projects",
                      label: (
                        <span className="tab-label">
                          <FolderOpenOutlined style={{ fontSize: 14 }} />
                          {english ? "Projects" : "工程"}
                        </span>
                      ),
                      children: (
                        <WorkspaceScenePanel
                          kind="project"
                          total={workspaceTotal}
                          query={workspaceQuery}
                          onQuery={loadWorkspaceScenes}
                          items={workspaceScenes.filter(
                            (scene) => scene.kind === "project",
                          )}
                          accessGroups={workspaceAccessGroups}
                          onLoad={loadWorkspaceScene}
                          onRefresh={loadWorkspaceScenes}
                          onUpdate={updateWorkspaceScene}
                          onDelete={deleteWorkspaceScene}
                          onCreateComposition={handleCreateMapComposition}
                        />
                      ),
                    },
                    {
                      key: "topics",
                      label: (
                        <span className="tab-label">
                          <AppstoreOutlined style={{ fontSize: 14 }} />
                          {english ? "Thematic maps" : "专题"}
                        </span>
                      ),
                      children: (
                        <MapCompositionPanel
                          items={mapCompositions.items}
                          availableAudienceGroups={
                            mapCompositions.availableAudienceGroups
                          }
                          availableProjectAccessGroups={workspaceAccessGroups}
                          loading={mapCompositions.loading}
                          onRefresh={mapCompositions.load}
                          onOpen={handleOpenMapComposition}
                          onLoadSource={handleLoadMapCompositionSource}
                          onRestored={handleRestoredMapCompositionProject}
                          onChanged={mapCompositions.update}
                          onDeleted={mapCompositions.remove}
                        />
                      ),
                    },
                  ]}
                />
                <LayerDataTableModal
                  layer={tableLayer}
                  open={Boolean(tableLayer)}
                  onClose={() => setTableLayer(null)}
                  onSelectionChange={handleSelectionChange}
                />
              </LayerContext.Provider>
            </ConfigProvider>
          </div>
        </aside>
        <aside
          className={`floating-panel floating-panel-right ${panelLayout.layout.rightCollapsed ? "map-panel-is-collapsed" : ""} ${
            mobileMapPanel === "right"
              ? "mobile-map-panel-visible"
              : "mobile-map-panel-hidden"
          }`}
          aria-label={english ? "Feature information panel" : "要素信息面板"}
        >
          <MapPanelChrome
            side="right"
            title={english ? "Data insights" : "数据洞察"}
            collapsed={panelLayout.layout.rightCollapsed}
            width={panelLayout.layout.right}
            english={english}
            onToggle={() => panelLayout.toggle("right")}
            onResizeStart={(event) => panelLayout.beginResize("right", event)}
            onResize={(amount) => panelLayout.resize("right", amount)}
          />
          <div className="map-panel-content">
            <ConfigProvider theme={workspacePanelTheme}>
              <LayerContext.Provider value={layerContextValue}>
                <RightSidePanel
                  selectedFeature={rightPanelSelectedFeature}
                  selectedResource={rightPanelSelectedResource}
                  selectedResourceProfile={rightPanelSelectedResourceProfile}
                  selectedLayer={rightPanelSelectedLayer}
                  visualizationSummary={rightPanelVisualizationSummary}
                  visualizationSummaryLoading={
                    rightPanelVisualizationSummaryLoading
                  }
                  visualizationSummaryError={visualizationSummaryError}
                  currentView={currentMapView}
                  mapConfig={bootstrap.map}
                />
              </LayerContext.Provider>
            </ConfigProvider>
          </div>
        </aside>
        <aside
          id="spatial-query-workbench-panel"
          className={`floating-panel-bottom spatial-workbench-panel ${
            spatialWorkbenchOpen
              ? "spatial-workbench-panel-open"
              : "spatial-workbench-panel-collapsed"
          }`}
          aria-label={english ? "Spatial query panel" : "空间查询面板"}
          aria-expanded={spatialWorkbenchOpen}
        >
          <ConfigProvider theme={workspacePanelTheme}>
            {spatialWorkbenchOpen ? (
              <>
                <Tooltip
                  title={
                    english
                      ? "Hide spatial query workspace"
                      : "隐藏空间查询工作台"
                  }
                >
                  <Button
                    className="spatial-workbench-collapse-button"
                    type="text"
                    icon={<DownOutlined style={{ fontSize: 14 }} />}
                    aria-label={
                      english
                        ? "Hide spatial query workspace"
                        : "隐藏空间查询工作台"
                    }
                    onClick={() => setSpatialWorkbenchOpen(false)}
                  />
                </Tooltip>
                <SpatialQueryWorkbench
                  layers={allLayers}
                  selectedResource={spatialTargetResource}
                  selectedResourceProfile={spatialTargetResourceProfile}
                  selectedLayer={spatialTargetLayer}
                  exportClipGeometry={sharedSpatialGeometry}
                  spatialFilter={spatialFilter}
                  activeDraw={activeDraw}
                  spatialQuerying={spatialQuerying}
                  spatialQueryResult={spatialQueryResult}
                  canExportData={permissions.canExportData}
                  exportTileZoomRange={exportTileZoomRange}
                  canUseCurrentViewRange={Boolean(currentMapView)}
                  canUseSelectedLayerRange={Boolean(
                    rangeSourceLayer &&
                    layerExtentGeometryFor(rangeSourceLayer),
                  )}
                  loadingResourceProfile={loadingSpatialTargetProfile}
                  onSelectTargetResource={handleSelectSpatialTargetResource}
                  onSelectTargetLayer={handleSelectSpatialTargetLayer}
                  onStartQueryDraw={setQueryDrawMode}
                  onClearSpatialFilter={handleClearSpatialFilter}
                  onImportSpatialFilter={handleImportSpatialFilter}
                  onUseCurrentViewRange={handleUseCurrentViewRange}
                  onUseSelectedLayerRange={handleUseSelectedLayerRange}
                  onRunSpatialQuery={handleRunSpatialQuery}
                  onLoadSpatialResult={handleLoadSpatialResult}
                  onLocateSpatialResult={handleLocateSpatialResult}
                  onOpenSpatialResultTable={handleOpenSpatialResultTable}
                  onExportSpatialResult={handleExportSpatialResult}
                  onClearSpatialResult={handleClearSpatialResult}
                  onExportMapPng={exportCurrentMapPng}
                />
              </>
            ) : (
              <button
                className="spatial-workbench-peek-card"
                type="button"
                aria-label={
                  english
                    ? "Open spatial query workspace"
                    : "打开空间查询工作台"
                }
                aria-controls="spatial-query-workbench-panel"
                aria-expanded={spatialWorkbenchOpen}
                onClick={() => setSpatialWorkbenchOpen(true)}
              >
                <span className="spatial-workbench-peek-icon" aria-hidden>
                  <AimOutlined style={{ fontSize: 15 }} />
                </span>
                <span className="spatial-workbench-peek-copy">
                  <strong>
                    {english
                      ? "Open spatial query workspace"
                      : "打开空间查询工作台"}
                  </strong>
                  <small>{spatialWorkbenchStatus}</small>
                </span>
                <span className="spatial-workbench-peek-action">
                  <span>{english ? "Open" : "打开"}</span>
                  <UpOutlined style={{ fontSize: 13 }} />
                </span>
              </button>
            )}
          </ConfigProvider>
        </aside>
      </div>
      <Suspense fallback={null}>
        <MapCompositionEditor
          open={Boolean(editingComposition)}
          composition={editingComposition}
          map={mapObject}
          groups={layerGroups.groups}
          workspaceSnapshot={workspaceSnapshot(
            layerGroups.groups,
            selectedLayerId,
            currentMapView,
            selectedMapBasemap(mapObject),
          )}
          fallbackBounds={compositionFallbackBounds}
          sourceText={compositionSourceText}
          accessToken={bootstrap.map.mapboxAccessToken}
          canExport={permissions.canExportMapCompositions}
          onClose={() => setEditingComposition(null)}
          onSaved={(composition) => {
            mapCompositions.update(composition);
            setEditingComposition(composition);
          }}
        />
      </Suspense>
    </Layout>
  );
}

async function mapFitBoundsOptions(_map: MapboxMap) {
  const { fitBoundsOptions } = await import("../map/mapViewport");
  return fitBoundsOptions();
}

function geojsonFromGeometry(
  geometry: GeoJsonGeometry,
): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry,
        properties: {},
      },
    ],
  };
}

function isLeftPanelTabKey(key: string): key is LeftPanelTabKey {
  return leftPanelTabKeys.has(key);
}

function spatialFilterModeLabel(mode: SpatialFilter["mode"], english = false) {
  const labels: Record<SpatialFilter["mode"], string> = {
    rectangle: english ? "Rectangle area" : "矩形范围",
    circle: english ? "Circular area" : "圆形范围",
    ellipse: english ? "Elliptical area" : "椭圆范围",
    polygon: english ? "Polygon area" : "多边形范围",
  };
  return labels[mode];
}

function spatialQueryMessage(result: ResourceQueryResult, english = false) {
  const base = english
    ? `Spatial query matched ${result.totalCount} records; ${result.returnedCount} returned`
    : `空间查询命中 ${result.totalCount} 条，返回 ${result.returnedCount} 条`;
  if (result.returnedCount === 0) {
    return base;
  }
  if (result.limitExceeded) {
    return english
      ? `${base}; truncated at the return limit`
      : `${base}，已按上限截断`;
  }
  return base;
}
