import { App } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MapComposition, WorkspaceAccessGroup } from "../types";
import type { MapCompositionLayout } from "../map-composition/layout";
import {
  isWorkspaceInventoryChange,
  notifyWorkspaceInventoryChanged,
  workspaceInventoryChangedEvent,
} from "../workspace/workspaceSync";

export function useMapCompositions(canView: boolean) {
  const { message } = App.useApp();
  const [items, setItems] = useState<MapComposition[]>([]);
  const [availableAudienceGroups, setAvailableAudienceGroups] = useState<
    WorkspaceAccessGroup[]
  >([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!canView) {
      setItems([]);
      setAvailableAudienceGroups([]);
      return [];
    }
    setLoading(true);
    try {
      const response = await api.mapCompositions();
      setItems(response.items);
      setAvailableAudienceGroups(response.availableAudienceGroups);
      return response.items;
    } catch (error) {
      message.warning(
        error instanceof Error ? error.message : "专题出图稿加载失败",
      );
      return [];
    } finally {
      setLoading(false);
    }
  }, [canView, message]);

  useEffect(() => {
    function refreshFromEvent(event: Event) {
      const detail = event instanceof CustomEvent ? event.detail : undefined;
      if (isWorkspaceInventoryChange(detail)) {
        void load();
      }
    }
    function refreshFromStorage(event: StorageEvent) {
      if (event.key !== workspaceInventoryChangedEvent || !event.newValue) {
        return;
      }
      try {
        if (isWorkspaceInventoryChange(JSON.parse(event.newValue))) {
          void load();
        }
      } catch {
        return;
      }
    }
    function refreshOnFocus() {
      if (document.visibilityState === "visible") {
        void load();
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
  }, [load]);

  const create = useCallback(
    async (projectId: number, name: string, layout: MapCompositionLayout) => {
      const created = await api.createMapComposition({
        projectId,
        name,
        description: "",
        layout,
      });
      setItems((current) => [created, ...current]);
      notifyWorkspaceInventoryChanged("composition");
      return created;
    },
    [],
  );

  const update = useCallback((composition: MapComposition) => {
    setItems((current) =>
      current.map((item) => (item.id === composition.id ? composition : item)),
    );
    notifyWorkspaceInventoryChanged("composition");
  }, []);

  const remove = useCallback((compositionId: number) => {
    setItems((current) => current.filter((item) => item.id !== compositionId));
    notifyWorkspaceInventoryChanged("composition");
  }, []);

  return {
    items,
    availableAudienceGroups,
    loading,
    load,
    create,
    update,
    remove,
  };
}
