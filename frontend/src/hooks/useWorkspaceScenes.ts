import { selectedMapBasemap, restoreMapBasemap } from "../map/basemapSnapshot";
import { App } from "antd";
import type { Map as MapboxMap } from "mapbox-gl";
import type { RefObject } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  LoadedLayerGroup,
  MapViewState,
  WorkspaceSceneSummary,
  WorkspaceAccessGroup,
  WorkspaceSceneSnapshot,
  WorkspaceScene,
} from "../types";
import {
  openWorkspaceProgressNotification,
  showWorkspaceRestoreEmptyResult,
  showWorkspaceRestoreIssues,
} from "../workspace/workspaceNotifications";
import { restoreWorkspaceGroups } from "../workspace/workspaceRestore";
import {
  isWorkspaceInventoryChange,
  notifyWorkspaceInventoryChanged,
  workspaceInventoryChangedEvent,
} from "../workspace/workspaceSync";
import { workspaceSnapshot } from "../workspace/workspaceSnapshot";
import { uniqueLoadedLayerGroups } from "../utils/uniqueLoadedLayers";

interface UseWorkspaceScenesOptions {
  canViewWorkspaces: boolean;
  canQueryData: boolean;
  canLoadVectorLayer: boolean;
  canLoadRasterLayer: boolean;
  queryResultLimit: number;
  groups: LoadedLayerGroup[];
  selectedLayerId: string | null;
  currentMapView: MapViewState | null;
  mapRef: RefObject<MapboxMap | null>;
  replaceGroups: (groups: LoadedLayerGroup[]) => void;
  setSelectedLayerId: (layerId: string | null) => void;
  onWorkspaceLoaded: () => void;
}

export function useWorkspaceScenes({
  canViewWorkspaces,
  canQueryData,
  canLoadVectorLayer,
  canLoadRasterLayer,
  queryResultLimit,
  groups,
  selectedLayerId,
  currentMapView,
  mapRef,
  replaceGroups,
  setSelectedLayerId,
  onWorkspaceLoaded,
}: UseWorkspaceScenesOptions) {
  const { message, notification } = App.useApp();
  const [workspaceScenes, setWorkspaceScenes] = useState<
    WorkspaceSceneSummary[]
  >([]);
  const [workspaceAccessGroups, setWorkspaceAccessGroups] = useState<
    WorkspaceAccessGroup[]
  >([]);

  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [workspaceQuery, setWorkspaceQuery] = useState({ q: "", offset: 0 });
  const queryRef = useRef({ q: "", offset: 0 });
  const requestSequence = useRef(0);
  const inFlight = useRef<Promise<WorkspaceSceneSummary[]> | null>(null);
  const lastRefresh = useRef(0);
  const sceneLoads = useRef(new Map<number, Promise<void>>());
  const [isRestoringWorkspace, setIsRestoringWorkspace] = useState(false);
  const loadWorkspaceScenes = useCallback(
    async (query?: { q?: string; offset?: number }) => {
      if (query) {
        queryRef.current = { q: query.q ?? "", offset: query.offset ?? 0 };
        setWorkspaceQuery(queryRef.current);
      }
      const sequence = ++requestSequence.current;
      lastRefresh.current = Date.now();
      if (!canViewWorkspaces) {
        setWorkspaceScenes([]);
        setWorkspaceAccessGroups([]);
        return [];
      }
      try {
        let sceneResponse = await api.workspaces({
          ...queryRef.current,
          limit: 24,
        });
        if (sequence !== requestSequence.current) return [];
        const lastOffset = Math.max(
          0,
          Math.floor((sceneResponse.total - 1) / 24) * 24,
        );
        if (queryRef.current.offset > lastOffset) {
          queryRef.current = { ...queryRef.current, offset: lastOffset };
          setWorkspaceQuery(queryRef.current);
          sceneResponse = await api.workspaces({
            ...queryRef.current,
            limit: 24,
          });
          if (sequence !== requestSequence.current) return [];
        }
        setWorkspaceTotal(sceneResponse.total);
        setWorkspaceScenes(sceneResponse.items);
        setWorkspaceAccessGroups(sceneResponse.availableAccessGroups);
        return sceneResponse.items;
      } catch (error) {
        if (sequence !== requestSequence.current) return [];
        message.warning(
          error instanceof Error ? error.message : "搜索内容加载失败",
        );
        return [];
      }
    },
    [canViewWorkspaces, message],
  );

  useEffect(() => {
    function refreshFromEvent(event: Event) {
      const detail = event instanceof CustomEvent ? event.detail : undefined;
      if (isWorkspaceInventoryChange(detail)) {
        void loadWorkspaceScenes();
      }
    }
    function refreshFromStorage(event: StorageEvent) {
      if (event.key !== workspaceInventoryChangedEvent || !event.newValue) {
        return;
      }
      try {
        if (isWorkspaceInventoryChange(JSON.parse(event.newValue))) {
          void loadWorkspaceScenes();
        }
      } catch {
        return;
      }
    }
    function refreshOnFocus() {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastRefresh.current > 15_000 &&
        !inFlight.current
      ) {
        inFlight.current = loadWorkspaceScenes().finally(() => {
          inFlight.current = null;
        });
      }
    }
    window.addEventListener(workspaceInventoryChangedEvent, refreshFromEvent);
    window.addEventListener("storage", refreshFromStorage);
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnFocus);
    return () => {
      window.removeEventListener(
        workspaceInventoryChangedEvent,
        refreshFromEvent,
      );
      window.removeEventListener("storage", refreshFromStorage);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnFocus);
    };
  }, [loadWorkspaceScenes]);

  const saveWorkspace = useCallback(
    async (values: {
      name: string;
      description?: string;
      targetId?: number;
      accessGroupIds?: number[];
      expectedUpdatedAt?: string;
    }) => {
      const label = "工程";
      const notificationKey = `workspace-save-project-${Date.now()}`;
      const targetName = values.name.trim();
      try {
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: values.targetId ? `正在覆盖${label}` : `正在保存${label}`,
          percent: 15,
          status: "active",
          detail: "正在整理当前图层、视图和符号化配置",
        });
        const snapshot = workspaceSnapshot(
          groups,
          selectedLayerId,
          currentMapView,
          selectedMapBasemap(mapRef.current),
        );
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: values.targetId ? `正在覆盖${label}` : `正在保存${label}`,
          percent: 55,
          status: "active",
          detail: "正在写入工作区快照",
        });
        const saved = values.targetId
          ? await api.updateWorkspace(values.targetId, {
              expectedUpdatedAt: values.expectedUpdatedAt,
              kind: "project",
              name: targetName,
              description: values.description?.trim() ?? "",
              snapshot,
              accessGroupIds: values.accessGroupIds ?? [],
            })
          : await api.createWorkspace({
              kind: "project",
              name: targetName,
              description: values.description?.trim() ?? "",
              snapshot,
              accessGroupIds: values.accessGroupIds ?? [],
            });
        if ("id" in saved) {
          setWorkspaceScenes((current) => {
            const others = current.filter((item) => item.id !== saved.id);
            return [saved, ...others];
          });
          notifyWorkspaceInventoryChanged("workspace");
        }
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: values.targetId ? `${label}已覆盖` : `${label}已保存`,
          percent: 100,
          status: "success",
          detail: targetName,
        });
      } catch (error) {
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: `${label}保存失败`,
          percent: 100,
          status: "exception",
          detail: error instanceof Error ? error.message : `${label}保存失败`,
        });
        throw error;
      }
    },
    [currentMapView, groups, notification, selectedLayerId],
  );

  const loadWorkspaceScene = useCallback(
    async (scene: WorkspaceSceneSummary | number) => {
      const sceneId = typeof scene === "number" ? scene : scene.id;
      const existing = sceneLoads.current.get(sceneId);
      if (existing) return existing;
      const load = async () => {
        const notificationKey = `workspace-load-${sceneId}`;
        const detail =
          typeof scene === "number"
            ? await api.workspace(scene)
            : "snapshot" in scene
              ? (scene as WorkspaceScene)
              : await api.workspace(scene.id);
        const label = detail.kind === "project" ? "工程" : "专题";
        const snapshot = detail.snapshot as WorkspaceSceneSnapshot;
        if (mapRef.current)
          await restoreMapBasemap(mapRef.current, snapshot.basemapId);
        if (!Array.isArray(snapshot.groups)) {
          message.warning("该工作区快照不包含可恢复的图层");
          return;
        }
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: `正在加载${label}`,
          percent: 8,
          status: "active",
          detail: detail.name,
        });
        const restoreResult = await restoreWorkspaceGroups({
          savedGroups: snapshot.groups,
          canQueryData,
          canLoadVectorLayer,
          canLoadRasterLayer,
          queryResultLimit,
          notification,
          onProgress: (state) => {
            openWorkspaceProgressNotification(notification, {
              key: notificationKey,
              title: `正在加载${label}`,
              percent: state.percent,
              status: "active",
              detail: state.detail,
            });
          },
        });
        const restoredGroups = uniqueLoadedLayerGroups(restoreResult.groups);
        if (restoredGroups.length === 0) {
          showWorkspaceRestoreEmptyResult(notification, {
            key: notificationKey,
            label,
            issues: restoreResult.issues,
          });
          if (restoreResult.issues.length === 0) {
            message.warning("该工作区快照没有可恢复的图层");
          }
          return;
        }
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: `正在加载${label}`,
          percent: 90,
          status: "active",
          detail: "正在应用图层和地图视图",
        });
        replaceGroups(restoredGroups);
        const restoredLayers = restoredGroups.flatMap(
          (group) => group.children,
        );
        setSelectedLayerId(
          restoredLayers.some((layer) => layer.id === snapshot.selectedLayerId)
            ? (snapshot.selectedLayerId ?? null)
            : (restoredLayers[0]?.id ?? null),
        );
        onWorkspaceLoaded();
        if (snapshot.mapView && mapRef.current) {
          mapRef.current.flyTo({
            center: snapshot.mapView.center,
            zoom: snapshot.mapView.zoom,
            bearing: snapshot.mapView.bearing,
            pitch: snapshot.mapView.pitch,
            duration: 800,
            essential: true,
          });
        }
        openWorkspaceProgressNotification(notification, {
          key: notificationKey,
          title: `${label}已加载`,
          percent: 100,
          status: "success",
          detail: detail.name,
        });
        showWorkspaceRestoreIssues(notification, restoreResult.issues);
      };
      setIsRestoringWorkspace(true);
      const pending = load();
      sceneLoads.current.set(sceneId, pending);
      try {
        await pending;
      } finally {
        sceneLoads.current.delete(sceneId);
        setIsRestoringWorkspace(sceneLoads.current.size > 0);
      }
    },
    [
      mapRef,
      message,
      notification,
      onWorkspaceLoaded,
      replaceGroups,
      canLoadVectorLayer,
      canLoadRasterLayer,
      canQueryData,
      queryResultLimit,
      setSelectedLayerId,
    ],
  );

  const loadWorkspaceSceneById = useCallback(
    async (sceneId: number) => {
      await loadWorkspaceScene(sceneId);
    },
    [loadWorkspaceScene],
  );

  const updateWorkspaceScene = useCallback((scene: WorkspaceSceneSummary) => {
    setWorkspaceScenes((current) =>
      current.map((item) => (item.id === scene.id ? scene : item)),
    );
    notifyWorkspaceInventoryChanged("workspace");
  }, []);

  const deleteWorkspaceScene = useCallback((id: number) => {
    setWorkspaceScenes((current) => current.filter((item) => item.id !== id));
    notifyWorkspaceInventoryChanged("workspace");
  }, []);

  return {
    isRestoringWorkspace,
    workspaceScenes,
    workspaceTotal,
    workspaceQuery,
    workspaceAccessGroups,
    loadWorkspaceScenes,
    saveWorkspace,
    loadWorkspaceScene,
    loadWorkspaceSceneById,
    updateWorkspaceScene,
    deleteWorkspaceScene,
  };
}
