import type { Map as MapboxMap } from "mapbox-gl";
import { createContext, type RefObject, useContext } from "react";
import type {
  GroupSymbolization,
  RasterSymbolization,
  VectorSymbolization,
} from "../symbolization";
import type {
  ExportLayerItem,
  GeoJsonGeometry,
  LoadedLayer,
  LoadedLayerGroup,
  LoadedRasterLayer,
  WorkspaceSceneSummary,
  WorkspaceAccessGroup,
} from "../types";

export type DropPlacement = "before" | "after";
export type LayerDropPlacement = DropPlacement | "inside";
export type ExportFormat = "geojson" | "shapefile";
export interface ExportOptions {
  epsg: number | null;
  reproject: boolean;
  clip: boolean;
  clipGeometry: GeoJsonGeometry | null;
  format: ExportFormat;
}

export type ExportProgressHandler = (state: {
  status: "queued" | "running" | "ready" | "failed";
  percent: number;
  messages: string[];
}) => void;

export interface LayerContextValue {
  groups: LoadedLayerGroup[];
  selectedLayerId: string | null;
  selectLayer: (groupId: string, layerId: string) => void;
  openLayerTable: (groupId: string, layerId: string) => void;
  addGroup: (group: LoadedLayerGroup) => void;
  replaceGroups: (groups: LoadedLayerGroup[]) => void;
  updateLayer: (
    groupId: string,
    layerId: string,
    updater: (layer: LoadedLayer) => LoadedLayer,
  ) => void;
  updateRasterLayer: (
    groupId: string,
    layerId: string,
    updater: (layer: LoadedRasterLayer) => LoadedRasterLayer,
  ) => void;
  setGroupVisibility: (groupId: string, visible: boolean) => void;
  setGroupName: (groupId: string, name: string) => void;
  setGroupSymbolization: (groupId: string, value: GroupSymbolization) => void;
  setLayerVisibility: (
    groupId: string,
    layerId: string,
    visible: boolean,
  ) => void;
  isLayerExtentVisible: (layerId: string) => boolean;
  setLayerExtentVisibility: (layerId: string, visible: boolean) => void;
  setLayerName: (groupId: string, layerId: string, name: string) => void;
  setLayerSymbolization: (
    groupId: string,
    layerId: string,
    value: VectorSymbolization | RasterSymbolization,
  ) => void;
  removeGroup: (groupId: string) => void;
  removeLayer: (groupId: string, layerId: string) => void;
  reorderGroups: (
    sourceGroupId: string,
    targetGroupId: string,
    placement: DropPlacement,
  ) => void;
  moveLayer: (
    sourceGroupId: string,
    sourceLayerId: string,
    targetGroupId: string,
    targetLayerId: string | null,
    placement: LayerDropPlacement,
  ) => void;
  extractLayer: (
    sourceGroupId: string,
    sourceLayerId: string,
    targetGroupId: string,
    placement: DropPlacement,
  ) => void;
  startRasterRender: (
    groupId: string,
    layerId: string,
    symbolization: RasterSymbolization,
    layer: LoadedRasterLayer,
    rulesMode: "default" | "custom",
  ) => void;
  locateLayer: (groupId: string, layerId: string) => void;
  locateGroup: (groupId: string) => void;
  mapRef: RefObject<MapboxMap | null>;
  canUseCustomSymbolization: boolean;
  canExportData: boolean;
  exportClipGeometry: GeoJsonGeometry | null;
  clearExportClipGeometry: () => void;
  exportLayers: (
    items: ExportLayerItem[],
    options: ExportOptions,
    onProgress?: ExportProgressHandler,
  ) => Promise<void>;
  workspaceScenes: WorkspaceSceneSummary[];
  workspaceAccessGroups: WorkspaceAccessGroup[];
  canCreateWorkspaces: boolean;
  saveWorkspace: (values: {
    name: string;
    description?: string;
    targetId?: number;
    expectedUpdatedAt?: string;
    accessGroupIds?: number[];
  }) => Promise<void>;
}

export const LayerContext = createContext<LayerContextValue | null>(null);

export function useLayerContext(): LayerContextValue {
  const ctx = useContext(LayerContext);
  if (!ctx)
    throw new Error(
      "useLayerContext must be used within LayerContext.Provider",
    );
  return ctx;
}
