import {
  cloneDefaultGroupSymbolization,
  cloneDefaultRasterSymbolization,
  cloneDefaultVectorSymbolization,
  rasterSymbolizationFromRules,
} from "../symbolization";
import { vectorSymbolizationWithDefaultTemplate } from "../symbolizationTemplates";
import type {
  AttributeFilter,
  DataResource,
  DataResourceProfile,
  LoadedLayerGroup,
  LoadedRasterLayer,
  LoadedVectorLayer,
  ResourceListItem,
  ResourceQueryResult,
  SpatialFilter,
} from "../types";
import {
  resourceCategoryName,
  resourceFormatLabel,
  resourceProvider,
  resourceSpatialExtent,
} from "./resources";

export function createVectorLayerGroup(
  resource: ResourceListItem,
  profile: DataResourceProfile,
  queryResult: ResourceQueryResult,
  query?: {
    attributeFilters: AttributeFilter[];
    spatialFilter: SpatialFilter | null;
  },
  options: {
    name?: string;
    metadata?: Record<string, string | number | boolean | null | undefined>;
  } = {},
): LoadedLayerGroup {
  const now = new Date();
  const groupId = `query-${resource.id}-${now.getTime()}`;
  const displayName = options.name ?? resource.name;
  const summary = `${queryResult.returnedCount}/${queryResult.totalCount} 条 · ${profile.geometryType || "空间数据"}`;
  const metadata = {
    数据名称: resource.name,
    数据类型: resource.dataType,
    数据分类: resourceCategoryName(resource),
    数据来源: resource.source,
    提供单位: resourceProvider(resource),
    空间范围: resourceSpatialExtent(resource),
    坐标系统: resource.coordinateSystem,
    文件格式: resourceFormatLabel(resource),
    返回条数: queryResult.returnedCount,
    命中条数: queryResult.totalCount,
    加载时间: now.toLocaleString("zh-CN", { hour12: false }),
    ...options.metadata,
  };
  const vectorSymbolization = vectorSymbolizationWithDefaultTemplate({
    resource,
    fields: queryResult.fields,
    geojson: queryResult.geojson,
    base: cloneDefaultVectorSymbolization(),
  });
  return {
    id: groupId,
    name: displayName,
    sourceResource: resource,
    visible: true,
    summary,
    createdAt: now.toISOString(),
    metadata,
    symbolization: cloneDefaultGroupSymbolization(),
    children: [
      {
        id: `${groupId}-vector`,
        name: displayName,
        layerType: "vector",
        sourceResource: resource,
        geojson: queryResult.geojson,
        geometryType: profile.geometryType,
        visible: true,
        summary,
        metadata: {
          ...metadata,
          图层类型: "矢量",
          几何类型: profile.geometryType,
        },
        symbolization: vectorSymbolization,
        fields: queryResult.fields,
        query,
      } satisfies LoadedVectorLayer,
    ],
  };
}

export function createRasterLayerGroup(
  resource: DataResource,
  profile: DataResourceProfile,
): LoadedLayerGroup | null {
  if (!profile.raster) return null;
  const raster = profile.raster;
  const now = new Date();
  const groupId = `raster-${raster.id}-${now.getTime()}`;
  const layerId = `${groupId}-xyz`;
  const symbolization = raster.defaultRules
    ? rasterSymbolizationFromRules(raster.defaultRules)
    : cloneDefaultRasterSymbolization();
  if (raster.rasterKind === "categorical") {
    // A partially transparent thematic layer makes the basemap look like
    // extra boundary colors even when every class pixel is exact.
    symbolization.opacity = 100;
  }
  const summary = `${raster.bandCount} 波段 · ${raster.metadata.size.join(" x ") || "栅格"}`;
  const metadata = {
    数据名称: resource.name,
    数据类型: "栅格",
    文件格式: resource.fileFormat,
    坐标系统: resource.coordinateSystem,
    波段数: raster.bandCount,
    加载时间: now.toLocaleString("zh-CN", { hour12: false }),
  };
  return {
    id: groupId,
    name: resource.name,
    sourceResource: resource,
    visible: true,
    summary,
    createdAt: now.toISOString(),
    metadata,
    symbolization: cloneDefaultGroupSymbolization(),
    children: [
      {
        id: layerId,
        name: resource.name,
        layerType: "raster",
        sourceResource: resource,
        rasterDatasetId: raster.id,
        rasterLayerId: raster.mapLayerId,
        rasterKind: raster.rasterKind,
        tileSampling:
          raster.rasterKind === "categorical" ? "nearest" : undefined,
        rasterMetadata: raster.metadata,
        imageCoordinates: raster.imageCoordinates,
        geometryType: "Raster",
        visible: true,
        summary: "等待后台符号化",
        metadata: { ...metadata, 图层类型: "栅格", 加载方式: "XYZ 瓦片" },
        symbolization,
        fields: [],
        renderStatus: "queued",
        renderProgress: 0,
        renderMessages: [],
      } satisfies LoadedRasterLayer,
    ],
  };
}

export function createEmptyLayerGroup(name: string): LoadedLayerGroup {
  const now = new Date();
  const timestamp = now.getTime();
  const groupId = `manual-${timestamp}-${Math.random().toString(36).slice(2, 8)}`;
  const sourceResource: ResourceListItem = {
    id: -timestamp,
    name,
    code: groupId,
    dataType: "vector",
    spatialClass: "spatial",
    domainType: "vector",
    category: null,
    categoryPath: [],
    classificationStatus: "pending",
    availableViews: ["map", "table", "metadata"],
    defaultView: "map",
    source: "手动创建",
    provider: "当前用户",
    dataDate: null,
    spatialExtent: "",
    coordinateSystem: "",
    fileFormat: "",
    description: "手动创建的图层组",
    qualityNote: "",
    sizeBytes: 0,
    itemCount: 0,
    status: "active",
    isQueryable: false,
    isRenderable: false,
    updatedAt: now.toISOString(),
  };
  return {
    id: groupId,
    name,
    sourceResource,
    isManual: true,
    visible: true,
    summary: "手动图层组",
    createdAt: now.toISOString(),
    metadata: {
      图层组类型: "手动创建",
      创建时间: now.toLocaleString("zh-CN", { hour12: false }),
    },
    symbolization: cloneDefaultGroupSymbolization(),
    children: [],
  };
}
