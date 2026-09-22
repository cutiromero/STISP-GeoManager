import {
  AimOutlined,
  AreaChartOutlined,
  BarChartOutlined,
  BgColorsOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  ExclamationCircleOutlined,
  FileImageOutlined,
  RadarChartOutlined,
  SlidersOutlined,
} from "@ant-design/icons";
import { Empty, Select, Spin, Tabs, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CSSProperties, ReactNode, SyntheticEvent } from "react";
import {
  satelliteBasemapThumbnailFilter,
  shouldUseMapboxBasemap,
  type MapBasemapConfig,
} from "../map/basemapStyle";
import type {
  DataDomainType,
  DataResourceProfile,
  FeatureInfo,
  LoadedLayer,
  LoadedRasterLayer,
  MapViewState,
  ResourceListItem,
  ResourceVisualizationSummary,
} from "../types";
import {
  rasterSymbolizationFromRules,
  type RasterSymbolization,
} from "../symbolization";
import FeatureDetailPanel from "./FeatureDetailPanel";

const thumbnailMinIndicatorSizePx = 10;
const thumbnailTileSize = 256;
const thumbnailMaxMercatorLat = 85.05112878;
const thumbnailContextPaddingRatio = 1.85;
const thumbnailMinTileScale = 0.12;
const thumbnailMaxTileScale = 1;
const thumbnailMinZoom = 1;
const thumbnailMaxZoom = 10;
const thumbnailZoomOffset = 2;
const thumbnailTileRetryDelayMs = 2500;
const osmTileSubdomains = ["a", "b", "c"] as const;
const osmThumbnailTileUrlPattern =
  /^https:\/\/([abc])\.tile\.openstreetmap\.org\/\d+\/\d+\/\d+\.png$/i;
export const thumbnailFallbackTileUrl =
  "data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA=";

export interface ThumbnailMapTile {
  center: [number, number];
  tileZoom: number;
  scale: number;
  tileUrlTemplate: string;
}

export const thumbnailMapTile: ThumbnailMapTile = {
  center: [81, 41],
  tileZoom: 5,
  scale: 0.38,
  tileUrlTemplate: "/api/map/thumbnail-tiles/{z}/{x}/{y}.png",
};

export function thumbnailMapTileForBasemap(
  _mapConfig: MapBasemapConfig,
): ThumbnailMapTile {
  return thumbnailMapTile;
}

interface ThumbnailTile {
  key: string;
  url: string;
  left: number;
  top: number;
  width: number;
  height: number;
}
interface ThumbnailExtentBox {
  left: number;
  top: number;
  width: number;
  height: number;
}
interface ThumbnailViewport {
  left: number;
  top: number;
  scale: number;
}
interface ThumbnailMapView {
  zoom: number;
  viewport: ThumbnailViewport;
}

type Tone = "green" | "cyan" | "amber" | "red" | "blue";
type CategoryStat = ResourceVisualizationSummary["categoryStats"][number];
type NumericStat = ResourceVisualizationSummary["numericStats"][number];
type QualityIssue = ResourceVisualizationSummary["qualityIssues"][number];
type MonitorItem =
  ResourceVisualizationSummary["monitorPreview"]["items"][number];
type RasterDatasetProfile = NonNullable<DataResourceProfile["raster"]>;
type RasterBandMetadata = RasterDatasetProfile["metadata"]["bands"][number];

const domainLabels: Partial<Record<DataDomainType, string>> = {
  germplasm: "种质数据",
  individual: "个体数据",
  population: "种群数据",
  community: "群落数据",
  field_survey: "野外调查",
  remote_sensing: "遥感影像",
  molecular: "分子数据",
  genome: "基因组数据",
  vector: "矢量数据",
};

const englishDomainLabels: Partial<Record<DataDomainType, string>> = {
  germplasm: "Germplasm data",
  individual: "Individual data",
  population: "Population data",
  community: "Community data",
  field_survey: "Field survey",
  remote_sensing: "Remote-sensing imagery",
  molecular: "Molecular data",
  genome: "Genome data",
  vector: "Vector data",
};

const domainFeaturePlans: Partial<
  Record<
    DataDomainType,
    {
      title: string;
      categoryHints: string[];
      numericHints: string[];
      radarTitle: string;
      matrixTitle: string;
    }
  >
> = {
  germplasm: {
    title: "种质来源与采集特征",
    categoryHints: ["性别", "地点", "采集", "种源", "来源", "保存"],
    numericHints: ["海拔", "经度", "纬度", "年龄", "高度", "胸径"],
    radarTitle: "种质连续指标画像",
    matrixTitle: "采集字段热力矩阵",
  },
  individual: {
    title: "个体分类与生长属性",
    categoryHints: ["科", "属", "种", "物种", "生活型", "状态"],
    numericHints: ["胸径", "树高", "冠幅", "年龄", "海拔", "盖度"],
    radarTitle: "个体生长指标画像",
    matrixTitle: "分类字段热力矩阵",
  },
  population: {
    title: "种群结构与优势度",
    categoryHints: ["物种", "样方", "栖息地", "龄级", "状态", "区域"],
    numericHints: ["重要值", "密度", "盖度", "株数", "频度", "高度"],
    radarTitle: "种群指标画像",
    matrixTitle: "种群字段热力矩阵",
  },
  community: {
    title: "群落多样性与环境梯度",
    categoryHints: ["群落", "样方", "样地", "生境", "生活型", "区域"],
    numericHints: [
      "Shannon",
      "Simpson",
      "Pielou",
      "SR",
      "FRic",
      "FDis",
      "RaoQ",
      "PD",
    ],
    radarTitle: "多样性指标画像",
    matrixTitle: "性状环境热力矩阵",
  },
  field_survey: {
    title: "调查任务与样方质量",
    categoryHints: ["调查", "样线", "样方", "人员", "生境", "天气", "地点"],
    numericHints: ["海拔", "样方面积", "株数", "盖度", "坡度", "土壤"],
    radarTitle: "调查量化指标画像",
    matrixTitle: "调查字段热力矩阵",
  },
  remote_sensing: {
    title: "影像波段与栅格元数据",
    categoryHints: ["bands", "波段", "传感器", "产品", "时相"],
    numericHints: ["Band", "NDVI", "min", "max", "像元", "分辨率"],
    radarTitle: "波段范围画像",
    matrixTitle: "波段范围热力矩阵",
  },
};

const fallbackFeaturePlan = {
  title: "数据字段与要素洞察",
  categoryHints: ["类型", "状态", "地点", "类别", "名称"],
  numericHints: ["值", "数量", "面积", "长度", "高度", "海拔"],
  radarTitle: "数值指标画像",
  matrixTitle: "字段结构热力矩阵",
};

const featurePlanEnglishText: Record<string, string> = {
  种质来源与采集特征: "Germplasm origin and collection traits",
  种质连续指标画像: "Germplasm numeric profile",
  采集字段热力矩阵: "Collection-field heat matrix",
  个体分类与生长属性: "Individual classification and growth traits",
  个体生长指标画像: "Individual growth profile",
  分类字段热力矩阵: "Classification-field heat matrix",
  种群结构与优势度: "Population structure and dominance",
  种群指标画像: "Population indicator profile",
  种群字段热力矩阵: "Population-field heat matrix",
  群落多样性与环境梯度: "Community diversity and environmental gradient",
  多样性指标画像: "Diversity indicator profile",
  性状环境热力矩阵: "Trait-environment heat matrix",
  调查任务与样方质量: "Survey tasks and plot quality",
  调查量化指标画像: "Survey indicator profile",
  调查字段热力矩阵: "Survey-field heat matrix",
  影像波段与栅格元数据: "Image bands and raster metadata",
  波段范围画像: "Band-range profile",
  波段范围热力矩阵: "Band-range heat matrix",
  数据字段与要素洞察: "Data fields and feature insights",
  数值指标画像: "Numeric indicator profile",
  字段结构热力矩阵: "Field-structure heat matrix",
};

const insightUiEnglishText: Record<string, string> = {
  刷新中: "Refreshing",
  接口异常: "API error",
  字段体检: "Field health",
  字段适配: "Field suitability",
  种质样本: "Germplasm samples",
  样本采集画像: "Sample collection profile",
  性别结构: "Sex structure",
  海拔梯度: "Elevation gradient",
  字段健康与图表适配: "Field health and chart suitability",
  采集地点待统计: "Collection sites pending",
  暂无性别字段统计: "No sex-field statistics",
  雌株: "Female",
  雄株: "Male",
  均衡度: "Balance",
  待标准化: "Needs standardization",
  可识别: "Recognized",
  存在性别标签标准化风险: "Sex labels require standardization",
  暂无海拔字段统计: "No elevation-field statistics",
  海拔字段缺少有效梯度范围: "No valid elevation gradient",
  低值: "Low",
  中位: "Median",
  高值: "High",
  缺失: "Missing",
  个体记录: "Individual records",
  分类谱系画像: "Taxonomic profile",
  "科排序 TopN": "Family-order Top N",
  科排序序列分布: "Family-order sequence",
  分类字段适配矩阵: "Classification-field suitability matrix",
  物种字段待统计: "Species field pending",
  暂无科排序或科类字段统计: "No family-order or family statistics",
  暂无科排序字段统计: "No family-order statistics",
  科排序字段缺少可用序列范围: "No usable family-order range",
  最小: "Minimum",
  最大: "Maximum",
  类别: "Categories",
  生态梯度画像: "Ecological-gradient profile",
  样方分组格局: "Plot grouping pattern",
  多样性指数梯度: "Diversity-index gradient",
  性状环境适配矩阵: "Trait-environment suitability matrix",
  种群调查画像: "Population-survey profile",
  优势种结构: "Dominant-species structure",
  调查梯度: "Survey gradient",
  调查字段适配矩阵: "Survey-field suitability matrix",
  完整度: "Completeness",
  多样度: "Diversity",
  丰富度: "Richness",
  均衡性: "Balance",
  标准化: "Standardization",
  区分度: "Discrimination",
  空间度: "Spatial coverage",
  梯度性: "Gradient",
  稳定性: "Stability",
  跨度: "Range",
  可视化: "Visualization",
  待统计: "Pending",
  索引稳定: "Stable index",
  有重复风险: "Duplicate risk",
  标签清晰: "Clear labels",
  空间采集: "Spatial collection",
  梯度连续: "Continuous gradient",
  科类覆盖: "Family coverage",
  属级覆盖: "Genus coverage",
  物种覆盖: "Species coverage",
  海拔记录: "Elevation records",
  采集来源: "Collection source",
  空间位置: "Spatial location",
  分类谱系: "Taxonomic lineage",
  科排序: "Family order",
  DNA编号: "DNA ID",
  采集地点: "Collection site",
  性别: "Sex",
  经纬度: "Coordinates",
  海拔: "Elevation",
  空间: "Spatial",
  字段: "Fields",
  质量: "Quality",
  像元估算: "Estimated pixels",
  要素记录: "Feature records",
  统计记录: "Statistical records",
  字段数量: "Field count",
  数据规模: "Data scale",
  字段结构: "Field structure",
  校验状态: "Validation status",
};

function insightUiText(value: string, english: boolean) {
  if (!english) return value;
  const exact = insightUiEnglishText[value];
  if (exact) return exact;
  return value
    .replace(/(\d+) 个采集地点/g, "$1 collection sites")
    .replace(/(\d+) 个物种/g, "$1 species")
    .replace(/(\d+) 个地点/g, "$1 sites")
    .replace(/(\d+) 类单位/g, "$1 source types")
    .replace(/(\d+) 类地点/g, "$1 site types")
    .replace(/(\d+) 条待清洗/g, "$1 records need cleaning")
    .replace(/(\d+) 条缺失/g, "$1 missing")
    .replace(/(\d+) 科/g, "$1 families")
    .replace(/(\d+) 属/g, "$1 genera")
    .replace(/(\d+) 种/g, "$1 species");
}

function localizedFeaturePlan(
  plan: typeof fallbackFeaturePlan,
  english: boolean,
) {
  if (!english) return plan;
  return {
    ...plan,
    title: featurePlanEnglishText[plan.title] ?? plan.title,
    radarTitle: featurePlanEnglishText[plan.radarTitle] ?? plan.radarTitle,
    matrixTitle: featurePlanEnglishText[plan.matrixTitle] ?? plan.matrixTitle,
  };
}

function usePanelEnglish() {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
}

interface Props {
  selectedFeature: FeatureInfo | null;
  selectedResource: ResourceListItem | null;
  selectedResourceProfile: DataResourceProfile | null;
  selectedLayer: LoadedLayer | null;
  visualizationSummary: ResourceVisualizationSummary | null;
  visualizationSummaryLoading: boolean;
  visualizationSummaryError: string | null;
  currentView: MapViewState | null;
  mapConfig: MapBasemapConfig;
}

type EcoTabKey = "overview" | "feature" | "monitor";

export default function RightSidePanel({
  selectedFeature,
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  visualizationSummary,
  visualizationSummaryLoading,
  visualizationSummaryError,
  currentView,
  mapConfig,
}: Props) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const rasterSelected = isRasterInsightSelection(
    selectedResource,
    selectedResourceProfile,
    selectedLayer,
  );
  const [activeEcoTab, setActiveEcoTab] = useState<EcoTabKey>(() =>
    nextEcoTabForSelectedFeature(
      "overview",
      selectedFeature,
      selectedLayer?.layerType === "vector" ? selectedLayer.id : null,
    ),
  );

  useEffect(() => {
    setActiveEcoTab((currentTab) =>
      nextEcoTabForSelectedFeature(
        currentTab,
        selectedFeature,
        selectedLayer?.layerType === "vector" ? selectedLayer.id : null,
      ),
    );
  }, [selectedFeature, selectedLayer?.id, selectedLayer?.layerType]);

  const handleEcoTabChange = useCallback((key: string) => {
    if (isEcoTabKey(key)) {
      setActiveEcoTab(key);
    }
  }, []);

  const domainType =
    visualizationSummary?.domainType ?? selectedResource?.domainType ?? null;
  const domainLabel = domainType
    ? ((english ? englishDomainLabels : domainLabels)[domainType] ??
      (english ? "Geographic data" : "地理数据"))
    : english
      ? "Waiting for resource"
      : "等待资源";
  const sourceLabel =
    selectedLayer?.name ??
    selectedResource?.name ??
    (english ? "No resource selected" : "未选择资源");

  return (
    <div className="right-panel-stack">
      <section
        className="right-map-overview-panel"
        aria-label={
          english ? "Current-view map thumbnail" : "当前视角平面缩略图"
        }
      >
        <FlatMapThumbnail currentView={currentView} mapConfig={mapConfig} />
      </section>

      <section
        className="right-eco-panel"
        aria-label={english ? "Geographic data insights" : "地理数据洞察面板"}
      >
        <div className="right-panel-heading right-panel-heading-main">
          <span>
            <RadarChartOutlined style={{ fontSize: 15 }} />
            <Typography.Text strong>
              {english ? "Geographic data insights" : "地理数据洞察"}
            </Typography.Text>
          </span>
          <Tag color={selectedResource ? "green" : "default"}>
            {domainLabel}
          </Tag>
        </div>
        <Typography.Text className="right-insight-source" type="secondary">
          {sourceLabel}
        </Typography.Text>
        <Tabs
          className="right-side-tabs"
          activeKey={activeEcoTab}
          onChange={handleEcoTabChange}
          size="small"
          items={[
            {
              key: "overview",
              label: (
                <span className="tab-label">
                  <AreaChartOutlined style={{ fontSize: 14 }} />
                  {english ? "Overview" : "概览"}
                </span>
              ),
              children: (
                <EcologyOverviewPanel
                  selectedResource={selectedResource}
                  selectedResourceProfile={selectedResourceProfile}
                  selectedLayer={selectedLayer}
                  summary={visualizationSummary}
                  loading={visualizationSummaryLoading}
                  error={visualizationSummaryError}
                />
              ),
            },
            {
              key: "feature",
              label: (
                <span className="tab-label">
                  {rasterSelected ? (
                    <BgColorsOutlined style={{ fontSize: 14 }} />
                  ) : (
                    <AimOutlined style={{ fontSize: 14 }} />
                  )}
                  {rasterSelected
                    ? english
                      ? "Bands"
                      : "波段"
                    : english
                      ? "Features"
                      : "要素"}
                </span>
              ),
              children: (
                <EcologyFactorPanel
                  feature={selectedFeature}
                  selectedResource={selectedResource}
                  selectedResourceProfile={selectedResourceProfile}
                  selectedLayer={selectedLayer}
                  summary={visualizationSummary}
                  loading={visualizationSummaryLoading}
                  error={visualizationSummaryError}
                />
              ),
            },
            {
              key: "monitor",
              label: (
                <span className="tab-label">
                  <RadarChartOutlined style={{ fontSize: 14 }} />
                  {rasterSelected
                    ? english
                      ? "Quality"
                      : "质量"
                    : english
                      ? "Monitoring"
                      : "监测"}
                </span>
              ),
              children: (
                <EcologyMonitorPanel
                  selectedResource={selectedResource}
                  selectedResourceProfile={selectedResourceProfile}
                  selectedLayer={selectedLayer}
                  summary={visualizationSummary}
                  loading={visualizationSummaryLoading}
                  error={visualizationSummaryError}
                />
              ),
            },
          ]}
        />
      </section>
    </div>
  );
}

export function nextEcoTabForSelectedFeature(
  currentTab: EcoTabKey,
  selectedFeature: FeatureInfo | null,
  selectedLayerId: string | null = null,
): EcoTabKey {
  return selectedFeature || selectedLayerId ? "feature" : currentTab;
}

function isEcoTabKey(key: string): key is EcoTabKey {
  return key === "overview" || key === "feature" || key === "monitor";
}

export function isRasterInsightSelection(
  resource: ResourceListItem | null,
  profile: DataResourceProfile | null,
  layer: LoadedLayer | null,
) {
  return Boolean(
    layer?.layerType === "raster" ||
    profile?.raster ||
    profile?.resource.dataType === "raster" ||
    resource?.dataType === "raster",
  );
}

function FlatMapThumbnail({
  currentView,
  mapConfig,
}: {
  currentView: MapViewState | null;
  mapConfig: MapBasemapConfig;
}) {
  const english = usePanelEnglish();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [tileRetryNonce, setTileRetryNonce] = useState(0);
  const mapTile = useMemo(
    () => thumbnailMapTileForBasemap(mapConfig),
    [mapConfig],
  );
  const tileFilter = shouldUseMapboxBasemap(mapConfig)
    ? satelliteBasemapThumbnailFilter
    : undefined;
  const retryingMapTile = useMemo(
    () => ({
      ...mapTile,
      tileUrlTemplate: thumbnailUrlTemplateWithRetry(
        mapTile.tileUrlTemplate,
        tileRetryNonce,
      ),
    }),
    [mapTile, tileRetryNonce],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateSize = () => {
      const rect = container.getBoundingClientRect();
      setContainerSize({
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      });
    };
    updateSize();
    const resizeObserver = new ResizeObserver(updateSize);
    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, []);

  useEffect(
    () => () => {
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
      }
    },
    [],
  );

  const scheduleTileRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      return;
    }
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      setTileRetryNonce(Date.now());
    }, thumbnailTileRetryDelayMs);
  }, []);

  const handleTileError = useCallback(
    (event: SyntheticEvent<HTMLImageElement>) => {
      const shouldRetry = isPlatformThumbnailTileUrl(event.currentTarget.src);
      handleThumbnailTileError(event);
      if (shouldRetry) {
        scheduleTileRetry();
      }
    },
    [scheduleTileRetry],
  );

  const thumbnail = useMemo(
    () =>
      buildThumbnail(
        currentView,
        containerSize.width,
        containerSize.height,
        retryingMapTile,
      ),
    [containerSize.height, containerSize.width, currentView, retryingMapTile],
  );

  return (
    <div className="right-map-mini">
      <div
        ref={containerRef}
        className="right-map-mini-canvas"
        aria-label={
          english
            ? "2D map thumbnail of the current extent"
            : "当前范围二维地图缩略图"
        }
        role="img"
      >
        {thumbnail.tiles.map((tile) => (
          <img
            key={tile.key}
            className="right-map-mini-tile"
            src={tile.url}
            alt=""
            style={{
              left: tile.left,
              top: tile.top,
              width: tile.width,
              height: tile.height,
              filter: tileFilter,
            }}
            onError={handleTileError}
            draggable={false}
          />
        ))}
        {thumbnail.extent ? (
          <span
            className="right-map-mini-extent"
            style={{
              left: thumbnail.extent.left,
              top: thumbnail.extent.top,
              width: thumbnail.extent.width,
              height: thumbnail.extent.height,
            }}
          />
        ) : null}
      </div>
      {!currentView ? (
        <div className="right-map-mini-empty">
          <Typography.Text type="secondary">
            {english ? "Waiting for map view" : "等待地图视角"}
          </Typography.Text>
        </div>
      ) : null}
    </div>
  );
}

function handleThumbnailTileError(event: SyntheticEvent<HTMLImageElement>) {
  const image = event.currentTarget;
  const fallback = thumbnailFallbackUrlForFailedTile(
    image.src,
    image.dataset.triedSubdomains ?? "",
  );
  image.dataset.triedSubdomains = fallback.triedSubdomains;
  image.src = fallback.url;
}

export function isPlatformThumbnailTileUrl(currentUrl: string) {
  try {
    return new URL(currentUrl, "http://localhost").pathname.startsWith(
      "/api/map/thumbnail-tiles/",
    );
  } catch {
    return currentUrl.startsWith("/api/map/thumbnail-tiles/");
  }
}

export function thumbnailUrlTemplateWithRetry(
  tileUrlTemplate: string,
  retryNonce: number,
) {
  if (retryNonce <= 0) {
    return tileUrlTemplate;
  }
  const separator = tileUrlTemplate.includes("?") ? "&" : "?";
  return `${tileUrlTemplate}${separator}retry=${retryNonce}`;
}

export function thumbnailFallbackUrlForFailedTile(
  currentUrl: string,
  triedSubdomains: string,
) {
  const match = osmThumbnailTileUrlPattern.exec(currentUrl);
  if (!match) {
    return {
      url: thumbnailFallbackTileUrl,
      triedSubdomains,
    };
  }
  const currentSubdomain = match[1]?.toLowerCase();
  const tried = new Set(triedSubdomains.split(",").filter(Boolean));
  if (currentSubdomain) {
    tried.add(currentSubdomain);
  }
  const nextSubdomain = osmTileSubdomains.find(
    (subdomain) => !tried.has(subdomain),
  );
  return {
    url: nextSubdomain
      ? currentUrl.replace(
          `://${currentSubdomain}.tile.openstreetmap.org/`,
          `://${nextSubdomain}.tile.openstreetmap.org/`,
        )
      : thumbnailFallbackTileUrl,
    triedSubdomains: [...tried].join(","),
  };
}

export function buildThumbnail(
  currentView: MapViewState | null,
  width: number,
  height: number,
  mapTile: ThumbnailMapTile = thumbnailMapTile,
) {
  if (width <= 0 || height <= 0) {
    return {
      tiles: [] as ThumbnailTile[],
      extent: null as ThumbnailExtentBox | null,
    };
  }
  const overview = currentView
    ? thumbnailViewportForMapView(currentView, width, height)
    : {
        zoom: mapTile.tileZoom,
        viewport: thumbnailViewportForMapTile(mapTile, width, height),
      };
  return {
    tiles: thumbnailTiles(
      overview.zoom,
      overview.viewport,
      width,
      height,
      mapTile.tileUrlTemplate,
    ),
    extent: currentView
      ? thumbnailExtentBox(
          currentView.bounds,
          overview.zoom,
          overview.viewport,
          width,
          height,
        )
      : null,
  };
}

export function thumbnailViewportForMapTile(
  mapTile: ThumbnailMapTile,
  width: number,
  height: number,
): ThumbnailViewport {
  const center = lngLatToWorldPixel(mapTile.center, mapTile.tileZoom);
  const scale = Math.max(
    0.05,
    mapTile.scale,
    thumbnailMinScaleForWorldHeight(mapTile.tileZoom, height),
  );
  return {
    left: center.x - width / (2 * scale),
    top: constrainThumbnailViewportTop(
      center.y - height / (2 * scale),
      mapTile.tileZoom,
      height,
      scale,
    ),
    scale,
  };
}

export function thumbnailViewportForMapView(
  currentView: MapViewState,
  width: number,
  height: number,
): ThumbnailMapView {
  const targetZoom = clamp(
    Math.floor(currentView.zoom) - thumbnailZoomOffset,
    thumbnailMinZoom,
    thumbnailMaxZoom,
  );
  const normalizedBounds = normalizeThumbnailBounds(currentView);
  let selectedZoom = targetZoom;
  let selectedMetrics = thumbnailFitMetrics(
    normalizedBounds,
    selectedZoom,
    width,
    height,
  );

  while (
    selectedZoom > thumbnailMinZoom &&
    selectedMetrics.fitScale < thumbnailMinTileScale
  ) {
    selectedZoom -= 1;
    selectedMetrics = thumbnailFitMetrics(
      normalizedBounds,
      selectedZoom,
      width,
      height,
    );
  }

  const scale = Math.max(
    clamp(
      selectedMetrics.fitScale,
      thumbnailMinTileScale,
      thumbnailMaxTileScale,
    ),
    thumbnailMinScaleForWorldHeight(selectedZoom, height),
  );
  const center = lngLatToWorldPixel(normalizedBounds.center, selectedZoom);
  return {
    zoom: selectedZoom,
    viewport: {
      left: center.x - width / (2 * scale),
      top: constrainThumbnailViewportTop(
        center.y - height / (2 * scale),
        selectedZoom,
        height,
        scale,
      ),
      scale,
    },
  };
}

export function thumbnailTiles(
  zoom: number,
  viewport: ThumbnailViewport,
  width: number,
  height: number,
  tileUrlTemplate = thumbnailMapTile.tileUrlTemplate,
) {
  const tileCount = 2 ** zoom;
  const minTileX = Math.floor(viewport.left / thumbnailTileSize);
  const maxTileX = Math.floor(
    (viewport.left + width / viewport.scale) / thumbnailTileSize,
  );
  const minTileY = Math.max(0, Math.floor(viewport.top / thumbnailTileSize));
  const maxTileY = Math.min(
    tileCount - 1,
    Math.floor((viewport.top + height / viewport.scale) / thumbnailTileSize),
  );
  const displayTileSize = thumbnailTileSize * viewport.scale;
  const tiles: ThumbnailTile[] = [];
  for (let tileY = minTileY; tileY <= maxTileY; tileY += 1) {
    for (let tileX = minTileX; tileX <= maxTileX; tileX += 1) {
      const wrappedX = wrapTileX(tileX, tileCount);
      const subdomain =
        osmTileSubdomains[Math.abs(tileX + tileY) % osmTileSubdomains.length] ??
        "a";
      const rawLeft =
        (tileX * thumbnailTileSize - viewport.left) * viewport.scale;
      const rawTop =
        (tileY * thumbnailTileSize - viewport.top) * viewport.scale;
      const left = Math.floor(rawLeft);
      const top = Math.floor(rawTop);
      const right = Math.ceil(rawLeft + displayTileSize) + 1;
      const bottom = Math.ceil(rawTop + displayTileSize) + 1;
      tiles.push({
        key: `${zoom}-${tileX}-${tileY}`,
        url: tileUrlTemplate
          .replace("{s}", subdomain)
          .replace("{z}", String(zoom))
          .replace("{x}", String(wrappedX))
          .replace("{y}", String(tileY)),
        left,
        top,
        width: right - left,
        height: bottom - top,
      });
    }
  }
  return tiles;
}

export function thumbnailExtentBox(
  bounds: MapViewState["bounds"],
  zoom: number,
  viewport: ThumbnailViewport,
  canvasWidth: number,
  canvasHeight: number,
): ThumbnailExtentBox {
  const [west, south, east, north] = bounds;
  const extent = ensureMinimumThumbnailExtent(
    zoom,
    {
      west,
      east,
      south,
      north,
    },
    viewport.scale,
  );
  const northwest = lngLatToWorldPixel([extent.west, extent.north], zoom);
  const southeast = lngLatToWorldPixel([extent.east, extent.south], zoom);
  const rawBox = {
    left: Math.round((northwest.x - viewport.left) * viewport.scale),
    top: Math.round((northwest.y - viewport.top) * viewport.scale),
    width: Math.round(
      Math.max(1, (southeast.x - northwest.x) * viewport.scale),
    ),
    height: Math.round(
      Math.max(1, (southeast.y - northwest.y) * viewport.scale),
    ),
  };
  return constrainThumbnailExtentBox(rawBox, canvasWidth, canvasHeight);
}

function constrainThumbnailExtentBox(
  box: ThumbnailExtentBox,
  canvasWidth: number,
  canvasHeight: number,
): ThumbnailExtentBox {
  const right = box.left + box.width;
  const bottom = box.top + box.height;
  const visibleLeft = Math.max(0, box.left);
  const visibleTop = Math.max(0, box.top);
  const visibleRight = Math.min(canvasWidth, right);
  const visibleBottom = Math.min(canvasHeight, bottom);
  const intersects = visibleRight > visibleLeft && visibleBottom > visibleTop;

  if (intersects) {
    const centerX = (visibleLeft + visibleRight) / 2;
    const centerY = (visibleTop + visibleBottom) / 2;
    const width = Math.min(
      canvasWidth,
      Math.max(thumbnailMinIndicatorSizePx, visibleRight - visibleLeft),
    );
    const height = Math.min(
      canvasHeight,
      Math.max(thumbnailMinIndicatorSizePx, visibleBottom - visibleTop),
    );
    return {
      left: clamp(centerX - width / 2, 0, canvasWidth - width),
      top: clamp(centerY - height / 2, 0, canvasHeight - height),
      width,
      height,
    };
  }

  return {
    left: clamp(
      box.left + box.width / 2 - thumbnailMinIndicatorSizePx / 2,
      0,
      canvasWidth - thumbnailMinIndicatorSizePx,
    ),
    top: clamp(
      box.top + box.height / 2 - thumbnailMinIndicatorSizePx / 2,
      0,
      canvasHeight - thumbnailMinIndicatorSizePx,
    ),
    width: thumbnailMinIndicatorSizePx,
    height: thumbnailMinIndicatorSizePx,
  };
}

function ensureMinimumThumbnailExtent(
  zoom: number,
  extent: { west: number; east: number; south: number; north: number },
  viewportScale: number,
) {
  const centerLng = (extent.west + extent.east) / 2;
  const centerLat = (extent.south + extent.north) / 2;
  const westPoint = lngLatToWorldPixel([extent.west, centerLat], zoom);
  const eastPoint = lngLatToWorldPixel([extent.east, centerLat], zoom);
  const southPoint = lngLatToWorldPixel([centerLng, extent.south], zoom);
  const northPoint = lngLatToWorldPixel([centerLng, extent.north], zoom);
  const widthPx = Math.abs(eastPoint.x - westPoint.x);
  const heightPx = Math.abs(southPoint.y - northPoint.y);
  const minIndicatorWorldPx = thumbnailMinIndicatorSizePx / viewportScale;
  if (widthPx >= minIndicatorWorldPx && heightPx >= minIndicatorWorldPx) {
    return extent;
  }

  const centerPoint = lngLatToWorldPixel([centerLng, centerLat], zoom);
  const halfWidthPx = Math.max(widthPx, minIndicatorWorldPx) / 2;
  const halfHeightPx = Math.max(heightPx, minIndicatorWorldPx) / 2;
  const southwest = worldPixelToLngLat(
    centerPoint.x - halfWidthPx,
    centerPoint.y + halfHeightPx,
    zoom,
  );
  const northeast = worldPixelToLngLat(
    centerPoint.x + halfWidthPx,
    centerPoint.y - halfHeightPx,
    zoom,
  );
  return {
    west: Math.max(-180, southwest[0]),
    east: Math.min(180, northeast[0]),
    south: Math.max(-85, southwest[1]),
    north: Math.min(85, northeast[1]),
  };
}

function normalizeThumbnailBounds(currentView: MapViewState) {
  const [rawWest, rawSouth, rawEast, rawNorth] = currentView.bounds;
  const west = clamp(rawWest, -180, 180);
  const east = clamp(rawEast, -180, 180);
  const south = clamp(
    rawSouth,
    -thumbnailMaxMercatorLat,
    thumbnailMaxMercatorLat,
  );
  const north = clamp(
    rawNorth,
    -thumbnailMaxMercatorLat,
    thumbnailMaxMercatorLat,
  );
  const center: [number, number] = [
    clamp(currentView.center[0], -180, 180),
    clamp(
      currentView.center[1],
      -thumbnailMaxMercatorLat,
      thumbnailMaxMercatorLat,
    ),
  ];

  return {
    west: Math.min(west, east),
    east: Math.max(west, east),
    south: Math.min(south, north),
    north: Math.max(south, north),
    center,
  };
}

function thumbnailFitMetrics(
  bounds: ReturnType<typeof normalizeThumbnailBounds>,
  zoom: number,
  width: number,
  height: number,
) {
  const westPoint = lngLatToWorldPixel([bounds.west, bounds.center[1]], zoom);
  const eastPoint = lngLatToWorldPixel([bounds.east, bounds.center[1]], zoom);
  const southPoint = lngLatToWorldPixel([bounds.center[0], bounds.south], zoom);
  const northPoint = lngLatToWorldPixel([bounds.center[0], bounds.north], zoom);
  const boundsWidth = Math.max(1, Math.abs(eastPoint.x - westPoint.x));
  const boundsHeight = Math.max(1, Math.abs(southPoint.y - northPoint.y));
  return {
    fitScale: Math.min(
      width / (boundsWidth * thumbnailContextPaddingRatio),
      height / (boundsHeight * thumbnailContextPaddingRatio),
    ),
  };
}

function thumbnailMinScaleForWorldHeight(zoom: number, height: number) {
  return height / thumbnailWorldSize(zoom);
}

function constrainThumbnailViewportTop(
  top: number,
  zoom: number,
  height: number,
  scale: number,
) {
  const worldSize = thumbnailWorldSize(zoom);
  const visibleWorldHeight = height / scale;
  if (visibleWorldHeight >= worldSize) {
    return 0;
  }
  return clamp(top, 0, worldSize - visibleWorldHeight);
}

function lngLatToWorldPixel([lng, lat]: [number, number], zoom: number) {
  const worldSize = thumbnailWorldSize(zoom);
  const clampedLat = Math.max(
    -thumbnailMaxMercatorLat,
    Math.min(thumbnailMaxMercatorLat, lat),
  );
  const sinLat = Math.sin((clampedLat * Math.PI) / 180);
  return {
    x: ((lng + 180) / 360) * worldSize,
    y:
      (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * worldSize,
  };
}

function worldPixelToLngLat(
  x: number,
  y: number,
  zoom: number,
): [number, number] {
  const worldSize = thumbnailWorldSize(zoom);
  const lng = (x / worldSize) * 360 - 180;
  const mercatorY = Math.PI * (1 - (2 * y) / worldSize);
  const lat = (Math.atan(Math.sinh(mercatorY)) * 180) / Math.PI;
  return [lng, lat];
}

function thumbnailWorldSize(zoom: number) {
  return thumbnailTileSize * 2 ** zoom;
}

function wrapTileX(tileX: number, tileCount: number) {
  return ((tileX % tileCount) + tileCount) % tileCount;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

interface InsightPanelProps {
  selectedResource?: ResourceListItem | null;
  selectedResourceProfile?: DataResourceProfile | null;
  selectedLayer?: LoadedLayer | null;
  summary: ResourceVisualizationSummary | null;
  loading: boolean;
  error: string | null;
}

function EcologyOverviewPanel({
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  summary,
  loading,
  error,
}: InsightPanelProps) {
  if (
    isRasterInsightSelection(
      selectedResource ?? null,
      selectedResourceProfile ?? null,
      selectedLayer ?? null,
    )
  ) {
    return (
      <RasterOverviewPanel
        error={error}
        layer={selectedLayer?.layerType === "raster" ? selectedLayer : null}
        loading={loading}
        profile={selectedResourceProfile ?? null}
        resource={selectedResource ?? null}
        summary={summary}
      />
    );
  }

  return (
    <VectorEcologyOverviewPanel
      error={error}
      loading={loading}
      selectedLayer={selectedLayer}
      selectedResource={selectedResource}
      selectedResourceProfile={selectedResourceProfile}
      summary={summary}
    />
  );
}

function VectorEcologyOverviewPanel({
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  summary,
  loading,
  error,
}: InsightPanelProps) {
  const english = usePanelEnglish();
  const insight = useMemo(
    () =>
      createInsightStats(
        summary,
        selectedLayer ?? null,
        selectedResourceProfile ?? null,
        selectedResource ?? null,
      ),
    [selectedLayer, selectedResource, selectedResourceProfile, summary],
  );
  const [selectedNumericField, setSelectedNumericField] = useState<
    string | null
  >(null);
  const [selectedCategoryField, setSelectedCategoryField] = useState<
    string | null
  >(null);
  const numericOptions = useMemo(
    () =>
      insight.numericStats.map((stat) => ({
        value: stat.field,
        label: stat.label,
      })),
    [insight.numericStats],
  );
  const categoryOptions = useMemo(
    () =>
      insight.categoryStats.map((stat) => ({
        value: stat.field,
        label: stat.label,
      })),
    [insight.categoryStats],
  );
  useEffect(() => {
    setSelectedNumericField((current) => {
      if (
        current &&
        insight.numericStats.some((stat) => stat.field === current)
      ) {
        return current;
      }
      return insight.numericStats[0]?.field ?? null;
    });
  }, [insight.numericStats]);
  useEffect(() => {
    setSelectedCategoryField((current) => {
      if (
        current &&
        insight.categoryStats.some((stat) => stat.field === current)
      ) {
        return current;
      }
      return insight.categoryStats[0]?.field ?? null;
    });
  }, [insight.categoryStats]);
  const primaryNumeric =
    (selectedNumericField
      ? insight.numericStats.find((stat) => stat.field === selectedNumericField)
      : null) ??
    insight.numericStats[0] ??
    null;
  const primaryCategory =
    (selectedCategoryField
      ? insight.categoryStats.find(
          (stat) => stat.field === selectedCategoryField,
        )
      : null) ??
    insight.categoryStats[0] ??
    null;
  const qualityScore = qualityReadinessScore(insight.qualityIssues, insight);

  if (!insight.hasData && loading) {
    return (
      <InsightState
        loading
        text={
          english ? "Generating visualization summary" : "正在生成可视化摘要"
        }
      />
    );
  }
  if (!insight.hasData) {
    return (
      <InsightState
        error={error}
        text={
          english
            ? "Select or load a geographic data resource to view insights"
            : "请选择或加载一个地理数据资源后查看可视化洞察"
        }
      />
    );
  }

  return (
    <div className="eco-tab-panel eco-overview-panel">
      <DataAssetOverview insight={insight} qualityScore={qualityScore} />
      <div className="eco-trend-card">
        <div className="right-panel-heading eco-chart-heading">
          <Typography.Text strong>
            {english ? "Numeric field distribution" : "数值字段分布"}
          </Typography.Text>
          <FieldStatSelect
            options={numericOptions}
            placeholder={english ? "Select field" : "选择字段"}
            value={primaryNumeric?.field ?? null}
            onChange={setSelectedNumericField}
          />
        </div>
        {primaryNumeric ? (
          <HistogramChart stat={primaryNumeric} />
        ) : (
          <ChartEmpty
            text={
              english
                ? "No continuous numeric fields could be parsed"
                : "暂无可解析的连续数值字段"
            }
          />
        )}
      </div>
      <div className="eco-distribution-card">
        <div className="right-panel-heading eco-chart-heading">
          <Typography.Text strong>
            {english ? "Categorical field composition" : "分类字段构成"}
          </Typography.Text>
          <FieldStatSelect
            options={categoryOptions}
            placeholder={english ? "Select field" : "选择字段"}
            value={primaryCategory?.field ?? null}
            onChange={setSelectedCategoryField}
          />
        </div>
        {primaryCategory ? (
          <DonutDistribution stat={primaryCategory} />
        ) : (
          <ChartEmpty
            text={
              english
                ? "No fields are suitable for categorical composition"
                : "暂无适合做分类构成的字段"
            }
          />
        )}
      </div>
      <div className="eco-spatial-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Spatial status and validation risks"
              : "空间状态与校验风险"}
          </Typography.Text>
          {loading ? (
            <Tag color="processing">{english ? "Refreshing" : "刷新中"}</Tag>
          ) : null}
        </div>
        <SpatialQualityStrip insight={insight} error={error} />
      </div>
    </div>
  );
}

function EcologyFactorPanel({
  feature,
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  summary,
  loading,
  error,
}: {
  feature: FeatureInfo | null;
  selectedResource: ResourceListItem | null;
  selectedResourceProfile: DataResourceProfile | null;
  selectedLayer: LoadedLayer | null;
  summary: ResourceVisualizationSummary | null;
  loading: boolean;
  error: string | null;
}) {
  const english = usePanelEnglish();
  const insight = useMemo(
    () => createInsightStats(summary, selectedLayer, null, null),
    [selectedLayer, summary],
  );
  const plan = localizedFeaturePlan(
    featurePlanFor(insight.domainType),
    english,
  );
  const categoryForDomain = bestCategoryStat(
    insight.categoryStats,
    plan.categoryHints,
  );
  const numericForDomain = bestNumericStats(
    insight.numericStats,
    plan.numericHints,
  );
  const primaryNumeric = numericForDomain[0] ?? insight.numericStats[0] ?? null;

  if (!insight.hasData && loading) {
    return (
      <InsightState
        loading
        text={english ? "Loading feature-chart layout" : "正在加载要素图表方案"}
      />
    );
  }

  if (
    isRasterInsightSelection(
      selectedResource,
      selectedResourceProfile,
      selectedLayer,
    )
  ) {
    return (
      <RasterBandPanel
        error={error}
        layer={selectedLayer?.layerType === "raster" ? selectedLayer : null}
        loading={loading}
        profile={selectedResourceProfile}
        resource={selectedResource}
        summary={summary}
      />
    );
  }

  if (insight.domainType === "germplasm") {
    return (
      <GermplasmFactorPanel
        error={error}
        feature={feature}
        insight={insight}
        loading={loading}
      />
    );
  }

  if (insight.domainType === "individual") {
    return (
      <IndividualFactorPanel
        error={error}
        feature={feature}
        insight={insight}
        loading={loading}
      />
    );
  }

  if (insight.domainType === "community") {
    return (
      <CommunityFactorPanel
        error={error}
        feature={feature}
        insight={insight}
        loading={loading}
      />
    );
  }

  if (
    insight.domainType === "population" ||
    insight.domainType === "field_survey"
  ) {
    return (
      <PopulationSurveyFactorPanel
        error={error}
        feature={feature}
        insight={insight}
        loading={loading}
      />
    );
  }

  return (
    <div className="eco-tab-panel eco-factor-panel">
      <div className="eco-factor-card">
        <div className="right-panel-heading">
          <Typography.Text strong>{plan.title}</Typography.Text>
          <Typography.Text type="secondary">
            {summary
              ? english
                ? "Driven by aggregated fields"
                : "聚合字段驱动"
              : english
                ? "Driven by local fields"
                : "本地字段驱动"}
          </Typography.Text>
        </div>
        <div className="eco-factor-layout">
          {numericForDomain.length > 2 ? (
            <RadarProfile
              stats={numericForDomain.slice(0, 6)}
              title={plan.radarTitle}
            />
          ) : (
            <ChartEmpty
              compact
              text={
                english
                  ? "Not enough numeric fields for a radar profile"
                  : "数值字段不足，暂不绘制雷达画像"
              }
            />
          )}
          <RecommendationList insight={insight} />
        </div>
      </div>
      <div className="eco-domain-chart-grid">
        <div className="eco-rose-card">
          <div className="right-panel-heading">
            <Typography.Text strong>
              {categoryForDomain
                ? `${categoryForDomain.label} TopN`
                : english
                  ? "Category ranking"
                  : "分类排行"}
            </Typography.Text>
            <BarChartOutlined style={{ fontSize: 14 }} />
          </div>
          {categoryForDomain ? (
            <HorizontalBars stat={categoryForDomain} />
          ) : (
            <ChartEmpty
              text={
                english
                  ? "No categorical fields are available for ranking"
                  : "暂无可用于排行的分类字段"
              }
            />
          )}
        </div>
        <div className="eco-rose-card">
          <div className="right-panel-heading">
            <Typography.Text strong>
              {primaryNumeric
                ? english
                  ? `${primaryNumeric.label} quantiles`
                  : `${primaryNumeric.label} 分位`
                : english
                  ? "Numeric quantiles"
                  : "数值分位"}
            </Typography.Text>
            <SlidersOutlined style={{ fontSize: 14 }} />
          </div>
          {primaryNumeric ? (
            <BoxRangeChart stat={primaryNumeric} />
          ) : (
            <ChartEmpty
              text={
                english
                  ? "No numeric fields are available for quantile display"
                  : "暂无可用于分位展示的数值字段"
              }
            />
          )}
        </div>
      </div>
      <div className="eco-risk-card">
        <div className="right-panel-heading">
          <Typography.Text strong>{plan.matrixTitle}</Typography.Text>
          <Tag color={error ? "warning" : "processing"}>
            {error
              ? english
                ? "API issue"
                : "接口异常"
              : english
                ? "Derived from fields"
                : "字段衍生"}
          </Tag>
        </div>
        <FieldDensityMatrix insight={insight} />
      </div>
      {selectedLayer?.layerType === "raster" ? (
        <RasterMetadataPanel insight={insight} layer={selectedLayer} />
      ) : null}
      <div className="eco-field-profile-card">
        <FieldProfileList insight={insight} />
      </div>
      <div className="eco-feature-detail-shell">
        <FeatureDetailPanel feature={feature} />
      </div>
    </div>
  );
}

function EcologyMonitorPanel({
  selectedResource,
  selectedResourceProfile,
  selectedLayer,
  summary,
  loading,
  error,
}: InsightPanelProps) {
  const english = usePanelEnglish();
  const insight = useMemo(
    () =>
      createInsightStats(
        summary,
        selectedLayer ?? null,
        null,
        selectedResource ?? null,
      ),
    [selectedLayer, selectedResource, summary],
  );

  if (
    isRasterInsightSelection(
      selectedResource ?? null,
      selectedResourceProfile ?? null,
      selectedLayer ?? null,
    )
  ) {
    return (
      <RasterQualityPanel
        error={error}
        insight={insight}
        layer={selectedLayer?.layerType === "raster" ? selectedLayer : null}
        loading={loading}
        profile={selectedResourceProfile ?? null}
        resource={selectedResource ?? null}
        summary={summary}
      />
    );
  }
  const monitorItems = insight.monitorItems;
  const issueCounts = issueCountsBySeverity(insight.qualityIssues);

  return (
    <div className="eco-tab-panel eco-monitor-panel">
      <div className="monitor-grid">
        <span className="eco-tone-green">
          <strong>{issueCounts.info}</strong>
          <small>{english ? "Information" : "信息提示"}</small>
          <em>
            {loading
              ? english
                ? "Refreshing"
                : "刷新中"
              : english
                ? "Quality checklist"
                : "质量清单"}
          </em>
        </span>
        <span className="eco-tone-amber">
          <strong>{issueCounts.warning}</strong>
          <small>{english ? "Attention needed" : "需关注项"}</small>
          <em>
            {english ? "Can become monitoring rules" : "后续可转监测规则"}
          </em>
        </span>
        <span className="eco-tone-red">
          <strong>{issueCounts.error}</strong>
          <small>{english ? "Blocking issues" : "阻断异常"}</small>
          <em>
            {error
              ? english
                ? "API recovery pending"
                : "接口待恢复"
              : english
                ? "Current summary"
                : "当前摘要"}
          </em>
        </span>
      </div>
      <div className="eco-risk-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Data-quality monitoring preview" : "数据质量监测预览"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {english ? "Reserved for Phase 3" : "第三阶段占位"}
          </Typography.Text>
        </div>
        <QualityList issues={insight.qualityIssues} />
      </div>
      <div className="monitor-placeholder">
        <div className="right-panel-heading">
          <Typography.Text strong>{insight.monitorTitle}</Typography.Text>
          <Tag color="processing">
            {english ? "UI placeholder" : "前端预留"}
          </Tag>
        </div>
        <MonitorFlow items={monitorItems} />
      </div>
      <div className="monitor-placeholder">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Future closed-loop tasks" : "后续闭环任务"}
          </Typography.Text>
          <Tag color="default">{english ? "Disabled" : "未启用"}</Tag>
        </div>
        <div className="eco-monitor-brief">
          <span>
            {english
              ? "Thresholds will be bound to resource fields, spatial extents, and business types."
              : "阈值配置将绑定资源字段、空间范围和业务类型。"}
          </span>
          <span>
            {english
              ? "Scheduled scans will generate issue lists from Phase 2 aggregation results."
              : "定时扫描将基于第二阶段聚合结果生成异常清单。"}
          </span>
          <span>
            {english
              ? "Notifications, review, and response records will form a future monitoring loop."
              : "通知、复核、处置记录将在后续形成监测任务闭环。"}
          </span>
        </div>
      </div>
    </div>
  );
}

interface RasterBandInsight {
  band: number;
  label: string;
  type: string;
  colorInterpretation: string;
  min: number | null;
  max: number | null;
  isInteger: boolean;
}

interface RasterInsightModel {
  bands: RasterBandInsight[];
  size: [number, number] | null;
  pixelCount: number | null;
  bounds: number[];
  coordinateSystem: string;
  driver: string;
  rasterKind: RasterDatasetProfile["rasterKind"] | "unknown";
  datasetStatus: RasterDatasetProfile["status"] | "metadata";
  renderStatus: string;
  renderProgress: number | null;
  renderMessages: string[];
  symbolization: RasterSymbolization;
  sourceFileSize: number;
  processedFileSize: number;
  sourceFileName: string;
}

function RasterOverviewPanel({
  error,
  layer,
  loading,
  profile,
  resource,
  summary,
}: {
  error: string | null;
  layer: LoadedRasterLayer | null;
  loading: boolean;
  profile: DataResourceProfile | null;
  resource: ResourceListItem | null;
  summary: ResourceVisualizationSummary | null;
}) {
  const english = usePanelEnglish();
  const raster = useMemo(
    () => createRasterInsightModel(profile, layer, summary, resource),
    [layer, profile, resource, summary],
  );
  const hasRasterMetadata = Boolean(
    raster.bands.length || raster.size || profile?.raster || layer,
  );

  if (!hasRasterMetadata && loading) {
    return (
      <InsightState
        loading
        text={english ? "Reading raster metadata" : "正在读取栅格元数据"}
      />
    );
  }
  if (!hasRasterMetadata) {
    return (
      <InsightState
        error={error}
        text={
          english
            ? "This raster does not yet have usable band, size, or spatial-extent metadata"
            : "当前栅格尚未生成可用的波段、尺寸和空间范围元数据"
        }
      />
    );
  }

  return (
    <div className="eco-tab-panel raster-overview-panel">
      <div className="eco-status-card raster-overview-hero">
        <div className="right-panel-heading raster-heading">
          <span>
            <FileImageOutlined style={{ fontSize: 16 }} />
            <Typography.Text strong>
              {english ? "Raster dataset overview" : "栅格数据集概览"}
            </Typography.Text>
          </span>
          <Tag color={rasterStatusColor(raster.datasetStatus)}>
            {rasterDatasetStatusLabel(raster.datasetStatus, english)}
          </Tag>
        </div>
        <div className="raster-kind-line">
          <strong>{rasterKindLabel(raster.rasterKind, english)}</strong>
          <span>
            {raster.driver || (english ? "Unknown format" : "未知格式")}
          </span>
          {loading ? (
            <em>{english ? "Refreshing metadata" : "元数据刷新中"}</em>
          ) : null}
        </div>
        <div className="raster-metric-grid">
          <span>
            <b>
              {raster.size
                ? `${formatCompactNumber(raster.size[0])} × ${formatCompactNumber(raster.size[1])}`
                : "-"}
            </b>
            {english ? "Pixel dimensions" : "像素尺寸"}
          </span>
          <span>
            <b>{formatRasterPixelCount(raster.pixelCount, english)}</b>
            {english ? "Total pixels" : "总像元"}
          </span>
          <span>
            <b>{raster.bands.length || "-"}</b>
            {english ? "Bands" : "波段"}
          </span>
          <span title={raster.coordinateSystem}>
            <b>{raster.coordinateSystem || "-"}</b>
            {english ? "Coordinate system" : "坐标系统"}
          </span>
        </div>
      </div>

      <div className="eco-trend-card raster-range-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Pixel value range (metadata)" : "像元值域（元数据）"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {english
              ? `${raster.bands.length} bands`
              : `${raster.bands.length} 个波段`}
          </Typography.Text>
        </div>
        <RasterBandRangeChart bands={raster.bands} />
        <Typography.Text className="raster-chart-note" type="secondary">
          {english
            ? "Only backend-extracted minimum and maximum values are shown; value ranges are not misrepresented as pixel distributions."
            : "当前仅展示后端提取的最小值与最大值，不将值域误绘制为像元分布。"}
        </Typography.Text>
      </div>

      <RasterRenderingSummary raster={raster} />

      <div className="eco-spatial-card raster-spatial-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Spatial coverage and data volume"
              : "空间覆盖与数据体量"}
          </Typography.Text>
          <Tag color={raster.bounds.length === 4 ? "green" : "warning"}>
            {raster.bounds.length === 4
              ? english
                ? "Extent registered"
                : "范围已登记"
              : english
                ? "Extent missing"
                : "缺少范围"}
          </Tag>
        </div>
        <RasterFootprint raster={raster} />
        {error ? (
          <Typography.Text type="warning">{error}</Typography.Text>
        ) : null}
      </div>
    </div>
  );
}

function RasterBandPanel({
  error,
  layer,
  loading,
  profile,
  resource,
  summary,
}: {
  error: string | null;
  layer: LoadedRasterLayer | null;
  loading: boolean;
  profile: DataResourceProfile | null;
  resource: ResourceListItem | null;
  summary: ResourceVisualizationSummary | null;
}) {
  const english = usePanelEnglish();
  const raster = useMemo(
    () => createRasterInsightModel(profile, layer, summary, resource),
    [layer, profile, resource, summary],
  );
  const [selectedBandNumber, setSelectedBandNumber] = useState<number | null>(
    null,
  );

  useEffect(() => {
    setSelectedBandNumber((current) => {
      if (current && raster.bands.some((band) => band.band === current)) {
        return current;
      }
      return raster.bands[0]?.band ?? null;
    });
  }, [raster.bands]);

  const selectedBand =
    raster.bands.find((band) => band.band === selectedBandNumber) ??
    raster.bands[0] ??
    null;

  if (!raster.bands.length && loading) {
    return (
      <InsightState
        loading
        text={english ? "Reading band information" : "正在读取波段信息"}
      />
    );
  }

  return (
    <div className="eco-tab-panel raster-band-panel">
      <div className="eco-factor-card raster-band-focus-card">
        <div className="right-panel-heading eco-chart-heading">
          <span>
            <BgColorsOutlined style={{ fontSize: 15 }} />
            <Typography.Text strong>
              {english ? "Band ranges and data types" : "波段值域与数据类型"}
            </Typography.Text>
          </span>
          <Select
            aria-label={english ? "Select raster band" : "选择栅格波段"}
            className="eco-field-select"
            disabled={!raster.bands.length}
            options={raster.bands.map((band) => ({
              label: `B${band.band} · ${band.label}`,
              value: band.band,
            }))}
            size="small"
            value={selectedBandNumber ?? undefined}
            onChange={setSelectedBandNumber}
          />
        </div>
        {selectedBand ? (
          <RasterBandFocus band={selectedBand} />
        ) : (
          <ChartEmpty
            text={
              english
                ? "This raster has no band metadata to display"
                : "当前栅格没有可展示的波段元数据"
            }
          />
        )}
      </div>

      <div className="eco-field-profile-card raster-band-list-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "All bands" : "全部波段"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {english ? "Unified range comparison" : "统一值域对比"}
          </Typography.Text>
        </div>
        <RasterBandRangeChart bands={raster.bands} />
      </div>

      <RasterRenderingSummary raster={raster} />

      {error ? (
        <div className="eco-risk-card">
          <Typography.Text type="warning">{error}</Typography.Text>
        </div>
      ) : null}
    </div>
  );
}

function RasterQualityPanel({
  error,
  insight,
  layer,
  loading,
  profile,
  resource,
  summary,
}: {
  error: string | null;
  insight: InsightStats;
  layer: LoadedRasterLayer | null;
  loading: boolean;
  profile: DataResourceProfile | null;
  resource: ResourceListItem | null;
  summary: ResourceVisualizationSummary | null;
}) {
  const english = usePanelEnglish();
  const raster = useMemo(
    () => createRasterInsightModel(profile, layer, summary, resource),
    [layer, profile, resource, summary],
  );
  const metadataReady = Boolean(raster.size && raster.bands.length);
  const preprocessingReady = raster.datasetStatus === "ready";
  const tilesReady = Boolean(layer?.tileUrl && layer.renderStatus === "ready");

  return (
    <div className="eco-tab-panel raster-quality-panel">
      <div className="eco-status-card raster-quality-hero">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Raster readiness checks" : "栅格可用性检查"}
          </Typography.Text>
          {loading ? (
            <Tag color="processing">{english ? "Refreshing" : "刷新中"}</Tag>
          ) : null}
        </div>
        <div className="raster-readiness-grid">
          <RasterReadinessStep
            label={english ? "Metadata" : "元数据"}
            detail={
              metadataReady
                ? english
                  ? "Dimensions and bands available"
                  : "尺寸与波段可用"
                : english
                  ? "Information incomplete"
                  : "信息不完整"
            }
            ready={metadataReady}
          />
          <RasterReadinessStep
            label={english ? "COG preprocessing" : "COG 预处理"}
            detail={rasterDatasetStatusLabel(raster.datasetStatus, english)}
            ready={preprocessingReady}
          />
          <RasterReadinessStep
            label={english ? "XYZ layer" : "XYZ 图层"}
            detail={
              tilesReady
                ? english
                  ? "Loaded on map"
                  : "地图已加载"
                : layer
                  ? renderStatusLabel(raster.renderStatus, english)
                  : english
                    ? "Not loaded"
                    : "尚未加载"
            }
            ready={tilesReady}
          />
        </div>
      </div>

      <div className="eco-risk-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Metadata and rendering risks" : "元数据与渲染风险"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {english
              ? `${insight.qualityIssues.length} items`
              : `${insight.qualityIssues.length} 项`}
          </Typography.Text>
        </div>
        {error ? (
          <div className="eco-quality-list">
            <span className="eco-quality-warning">
              <ExclamationCircleOutlined style={{ fontSize: 14 }} />
              <b>{english ? "Summary API issue" : "摘要接口异常"}</b>
              <small>{error}</small>
            </span>
          </div>
        ) : (
          <QualityList issues={insight.qualityIssues} />
        )}
      </div>

      <div className="eco-field-profile-card raster-delivery-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Backend delivery status" : "后端交付状态"}
          </Typography.Text>
          <Tag color={tilesReady ? "green" : "default"}>XYZ</Tag>
        </div>
        <div className="raster-delivery-facts">
          <span>
            <b>{renderStatusLabel(raster.renderStatus, english)}</b>
            {english ? "Current rendering" : "当前渲染"}
          </span>
          <span>
            <b>
              {raster.renderProgress === null
                ? "-"
                : `${Math.round(raster.renderProgress)}%`}
            </b>
            {english ? "Job progress" : "任务进度"}
          </span>
          <span>
            <b>
              {raster.symbolization.nodata.enabled
                ? english
                  ? "Enabled"
                  : "已启用"
                : english
                  ? "Disabled"
                  : "未启用"}
            </b>
            {english ? "NoData transparency" : "NoData 透明"}
          </span>
        </div>
        {raster.renderMessages.length ? (
          <div className="raster-message-list">
            {raster.renderMessages
              .filter(
                (message, messageIndex, messages) =>
                  messages.indexOf(message) === messageIndex,
              )
              .slice(-3)
              .map((message) => (
                <span key={message}>{message}</span>
              ))}
          </div>
        ) : (
          <Typography.Text type="secondary">
            {layer
              ? english
                ? "No rendering-job messages"
                : "暂无渲染任务消息"
              : english
                ? "Load on the map to view tile delivery status"
                : "加载到地图后可查看瓦片交付状态"}
          </Typography.Text>
        )}
      </div>
    </div>
  );
}

function RasterReadinessStep({
  detail,
  label,
  ready,
}: {
  detail: string;
  label: string;
  ready: boolean;
}) {
  return (
    <span className={ready ? "is-ready" : "is-pending"}>
      {ready ? (
        <CheckCircleOutlined style={{ fontSize: 15 }} />
      ) : (
        <ExclamationCircleOutlined style={{ fontSize: 15 }} />
      )}
      <b>{label}</b>
      <small>{detail}</small>
    </span>
  );
}

function RasterBandFocus({ band }: { band: RasterBandInsight }) {
  const english = usePanelEnglish();
  const range =
    band.min !== null && band.max !== null
      ? Math.abs(band.max - band.min)
      : null;
  return (
    <div className="raster-band-focus">
      <div className="raster-band-focus-value">
        <span>B{band.band}</span>
        <strong>{band.label}</strong>
        <small>
          {band.colorInterpretation ||
            (english
              ? "Colour interpretation not specified"
              : "未标注颜色解释")}
        </small>
      </div>
      <div className="raster-band-focus-range">
        <i />
        <div>
          <span>
            <small>{english ? "Minimum" : "最小值"}</small>
            <b>{formatNumber(band.min)}</b>
          </span>
          <span>
            <small>{english ? "Range" : "值域跨度"}</small>
            <b>{formatNumber(range)}</b>
          </span>
          <span>
            <small>{english ? "Maximum" : "最大值"}</small>
            <b>{formatNumber(band.max)}</b>
          </span>
        </div>
      </div>
      <div className="raster-band-type-line">
        <Tag>{band.type || (english ? "Unknown type" : "未知类型")}</Tag>
        <Tag color={band.isInteger ? "blue" : "cyan"}>
          {band.isInteger
            ? english
              ? "Integer pixels"
              : "整型像元"
            : english
              ? "Continuous pixels"
              : "连续像元"}
        </Tag>
      </div>
    </div>
  );
}

function RasterBandRangeChart({ bands }: { bands: RasterBandInsight[] }) {
  const english = usePanelEnglish();
  const validValues = bands.flatMap((band) =>
    [band.min, band.max].filter((value): value is number => value !== null),
  );
  if (!bands.length) {
    return (
      <ChartEmpty
        compact
        text={english ? "No band-range metadata" : "暂无波段值域元数据"}
      />
    );
  }
  const domainMin = validValues.length ? Math.min(...validValues) : 0;
  const domainMax = validValues.length ? Math.max(...validValues) : 1;

  return (
    <div
      className="raster-band-range-chart"
      aria-label={
        english ? "Raster band-range comparison" : "栅格波段值域对比图"
      }
    >
      <div className="raster-range-axis">
        <span>{formatNumber(domainMin)}</span>
        <span>{english ? "Shared range" : "统一值域"}</span>
        <span>{formatNumber(domainMax)}</span>
      </div>
      {bands.slice(0, 12).map((band) => {
        const position = rasterBandRangePosition(
          band.min,
          band.max,
          domainMin,
          domainMax,
        );
        return (
          <div className="raster-range-row" key={band.band}>
            <span className="raster-range-label" title={band.label}>
              <b>B{band.band}</b>
              <small>{band.label}</small>
            </span>
            <div className="raster-range-track">
              {position ? (
                <i
                  style={
                    {
                      "--raster-range-left": `${position.left}%`,
                      "--raster-range-width": `${position.width}%`,
                    } as CSSProperties
                  }
                />
              ) : (
                <em>{english ? "No range" : "无值域"}</em>
              )}
            </div>
            <span className="raster-range-values">
              {band.min === null || band.max === null
                ? "-"
                : `${formatNumber(band.min)} → ${formatNumber(band.max)}`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function rasterBandRangePosition(
  minimum: number | null,
  maximum: number | null,
  domainMinimum: number,
  domainMaximum: number,
) {
  if (minimum === null || maximum === null) return null;
  const domainSpan = domainMaximum - domainMinimum;
  if (!Number.isFinite(domainSpan) || domainSpan <= 0) {
    return { left: 0, width: 100 };
  }
  const low = Math.min(minimum, maximum);
  const high = Math.max(minimum, maximum);
  const left = clamp(((low - domainMinimum) / domainSpan) * 100, 0, 100);
  const right = clamp(((high - domainMinimum) / domainSpan) * 100, 0, 100);
  const width = Math.max(2, right - left);
  return { left: Math.min(left, 100 - width), width };
}

function RasterRenderingSummary({ raster }: { raster: RasterInsightModel }) {
  const english = usePanelEnglish();
  const activeBands = raster.symbolization.bands
    .map((band) => `B${band}`)
    .join(" / ");
  return (
    <div className="eco-distribution-card raster-render-card">
      <div className="right-panel-heading">
        <Typography.Text strong>
          {english ? "Current backend rendering" : "当前后端渲染方案"}
        </Typography.Text>
        <Tag color="cyan">
          {renderModeLabel(raster.symbolization.mode, english)}
        </Tag>
      </div>
      <div
        className={`raster-palette-strip raster-palette-${raster.symbolization.mode === "pseudocolor" ? raster.symbolization.palette : raster.symbolization.mode}`}
        role="img"
        aria-label={
          english
            ? `${renderModeLabel(raster.symbolization.mode, true)} palette preview`
            : `${renderModeLabel(raster.symbolization.mode)}色带预览`
        }
      >
        <span>
          {activeBands || (english ? "No bands specified" : "未指定波段")}
        </span>
      </div>
      <div className="raster-render-facts">
        <span>
          <b>{activeBands || "-"}</b>
          {english ? "Output bands" : "输出波段"}
        </span>
        <span>
          <b>{raster.symbolization.opacity}%</b>
          {english ? "Layer opacity" : "图层透明度"}
        </span>
        <span>
          <b>
            {raster.symbolization.stretch.enabled
              ? "Min–Max"
              : english
                ? "Off"
                : "关闭"}
          </b>
          {english ? "Stretch" : "拉伸"}
        </span>
        <span>
          <b>
            {raster.symbolization.nodata.enabled
              ? english
                ? "Transparent"
                : "透明"
              : english
                ? "Retained"
                : "保留"}
          </b>
          NoData
        </span>
      </div>
    </div>
  );
}

function RasterFootprint({ raster }: { raster: RasterInsightModel }) {
  const english = usePanelEnglish();
  const bounds = raster.bounds;
  const approximateResolution = approximateRasterResolution(
    bounds,
    raster.size,
  );
  const totalSize = raster.sourceFileSize + raster.processedFileSize;
  return (
    <div className="raster-footprint-layout">
      <div
        className="raster-footprint-graphic"
        aria-label={
          english ? "Raster spatial extent diagram" : "栅格空间范围示意"
        }
      >
        <i />
        <span>Raster</span>
      </div>
      <div className="raster-footprint-facts">
        <span>
          <small>{english ? "WGS84 extent" : "WGS84 范围"}</small>
          <b title={formatBounds(bounds)}>{formatBounds(bounds)}</b>
        </span>
        <span>
          <small>
            {english ? "Approximate pixel span" : "视图像元跨度（约）"}
          </small>
          <b>{approximateResolution}</b>
        </span>
        <span>
          <small>{english ? "Source / processed" : "源文件 / 预处理"}</small>
          <b>
            {formatBytes(raster.sourceFileSize)} /{" "}
            {formatBytes(raster.processedFileSize)}
          </b>
        </span>
        <span>
          <small>{english ? "Total size" : "合计体量"}</small>
          <b>{totalSize ? formatBytes(totalSize) : "-"}</b>
        </span>
      </div>
    </div>
  );
}

function createRasterInsightModel(
  profile: DataResourceProfile | null,
  layer: LoadedRasterLayer | null,
  summary: ResourceVisualizationSummary | null,
  resource: ResourceListItem | null,
): RasterInsightModel {
  const dataset = profile?.raster ?? null;
  const metadata = dataset?.metadata ?? layer?.rasterMetadata ?? null;
  const metadataBands = metadata?.bands ?? [];
  const bands = metadataBands.length
    ? metadataBands.map(rasterBandFromMetadata)
    : (summary?.numericStats ?? []).map((stat, statIndex) => ({
        band: bandNumberFromField(stat.field) ?? statIndex + 1,
        label: stat.label || stat.field,
        type: "",
        colorInterpretation: "",
        min: finiteNumberOrNull(stat.min),
        max: finiteNumberOrNull(stat.max),
        isInteger: false,
      }));
  const rawSize = metadata?.size ?? [];
  const width = positiveIntegerOrNull(rawSize[0]);
  const height = positiveIntegerOrNull(rawSize[1]);
  const size: [number, number] | null =
    width !== null && height !== null ? [width, height] : null;
  const bounds =
    dataset?.bounds4326?.length === 4
      ? dataset.bounds4326
      : summary?.profile.bounds?.length === 4
        ? summary.profile.bounds
        : profile?.bounds?.length === 4
          ? profile.bounds
          : parseBounds(resource?.spatialExtent ?? "");
  const symbolization = layer?.symbolization
    ? layer.symbolization
    : rasterSymbolizationFromRules(dataset?.defaultRules);

  return {
    bands,
    size,
    pixelCount: size ? size[0] * size[1] : null,
    bounds,
    coordinateSystem: String(
      metadata?.coordinateSystem ?? resource?.coordinateSystem ?? "",
    ),
    driver:
      metadata?.driver || dataset?.sourceFormat || resource?.fileFormat || "",
    rasterKind: dataset?.rasterKind ?? "unknown",
    datasetStatus: dataset?.status ?? "metadata",
    renderStatus:
      layer?.renderStatus ??
      (dataset?.status === "ready"
        ? "not_loaded"
        : (dataset?.status ?? "metadata")),
    renderProgress:
      typeof layer?.renderProgress === "number" ? layer.renderProgress : null,
    renderMessages: layer?.renderMessages ?? [],
    symbolization,
    sourceFileSize: dataset?.sourceFileSize ?? 0,
    processedFileSize: dataset?.processedFileSize ?? 0,
    sourceFileName: dataset?.sourceFileName ?? "",
  };
}

function rasterBandFromMetadata(band: RasterBandMetadata): RasterBandInsight {
  return {
    band: band.band,
    label: band.description || `Band ${band.band}`,
    type: band.type,
    colorInterpretation: band.colorInterpretation,
    min: finiteNumberOrNull(band.min),
    max: finiteNumberOrNull(band.max),
    isInteger: band.isInteger,
  };
}

function finiteNumberOrNull(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveIntegerOrNull(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.round(value)
    : null;
}

function bandNumberFromField(field: string) {
  const match = field.match(/(\d+)/);
  return match ? Number(match[1]) : null;
}

export function formatRasterPixelCount(value: number | null, english = false) {
  if (value === null || !Number.isFinite(value)) return "-";
  if (value >= 1_000_000_000)
    return `${formatNumber(value / 1_000_000_000)} ${english ? "billion" : "十亿"}`;
  if (value >= 1_000_000)
    return `${formatNumber(value / 1_000_000)} ${english ? "million" : "百万"}`;
  if (value >= 10_000)
    return english
      ? formatCompactNumber(value)
      : `${formatNumber(value / 10_000)} 万`;
  return formatNumber(value);
}

function approximateRasterResolution(
  bounds: number[],
  size: [number, number] | null,
) {
  if (bounds.length !== 4 || !size) return "-";
  const [minLng, minLat, maxLng, maxLat] = bounds;
  if (
    minLng === undefined ||
    minLat === undefined ||
    maxLng === undefined ||
    maxLat === undefined
  ) {
    return "-";
  }
  const xResolution = Math.abs((maxLng - minLng) / size[0]);
  const yResolution = Math.abs((maxLat - minLat) / size[1]);
  if (!Number.isFinite(xResolution) || !Number.isFinite(yResolution))
    return "-";
  return `${formatResolutionDegrees(xResolution)} × ${formatResolutionDegrees(yResolution)}`;
}

function formatResolutionDegrees(value: number) {
  if (value >= 0.01) return `${value.toFixed(4)}°`;
  if (value >= 0.0001) return `${value.toFixed(6)}°`;
  return `${value.toExponential(2)}°`;
}

function formatBytes(value: number) {
  if (!value || !Number.isFinite(value)) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = Math.min(
    units.length - 1,
    Math.floor(Math.log(value) / Math.log(1024)),
  );
  return `${formatNumber(value / 1024 ** unitIndex)} ${units[unitIndex]}`;
}

function rasterKindLabel(
  kind: RasterInsightModel["rasterKind"],
  english = false,
) {
  return english
    ? {
        imagery: "Multiband imagery",
        continuous: "Continuous raster",
        categorical: "Categorical raster",
        unknown: "Raster data",
      }[kind]
    : {
        imagery: "多波段影像",
        continuous: "连续型栅格",
        categorical: "分类栅格",
        unknown: "栅格数据",
      }[kind];
}

function rasterDatasetStatusLabel(
  status: RasterInsightModel["datasetStatus"],
  english = false,
) {
  return english
    ? {
        pending: "Waiting for preprocessing",
        processing: "Preprocessing",
        ready: "Preprocessing ready",
        failed: "Preprocessing failed",
        metadata: "Metadata available",
      }[status]
    : {
        pending: "等待预处理",
        processing: "预处理中",
        ready: "预处理就绪",
        failed: "预处理失败",
        metadata: "元数据可用",
      }[status];
}

function rasterStatusColor(status: RasterInsightModel["datasetStatus"]) {
  if (status === "ready") return "green";
  if (status === "failed") return "error";
  if (status === "processing") return "processing";
  return "default";
}

function renderModeLabel(mode: RasterSymbolization["mode"], english = false) {
  return english
    ? {
        gray: "Single-band grayscale",
        rgb: "RGB composite",
        pseudocolor: "Pseudocolor",
        unique: "Unique-value classes",
      }[mode]
    : {
        gray: "单波段灰度",
        rgb: "RGB 合成",
        pseudocolor: "伪彩色",
        unique: "唯一值分类",
      }[mode];
}

function renderStatusLabel(status: string, english = false) {
  return (
    (english
      ? {
          ready: "Tiles ready",
          queued: "Waiting to render",
          running: "Rendering",
          processing: "Processing",
          failed: "Rendering failed",
          not_loaded: "Not loaded",
          metadata: "Metadata only",
        }
      : {
          ready: "瓦片已就绪",
          queued: "等待渲染",
          running: "渲染中",
          processing: "处理中",
          failed: "渲染失败",
          not_loaded: "尚未加载",
          metadata: "仅元数据",
        })[status] ?? status
  );
}

function GermplasmFactorPanel({
  error,
  feature,
  insight,
  loading,
}: {
  error: string | null;
  feature: FeatureInfo | null;
  insight: InsightStats;
  loading: boolean;
}) {
  const english = usePanelEnglish();
  const germplasm = germplasmStatsFor(insight);
  return (
    <div className="eco-tab-panel eco-factor-panel eco-germplasm-panel">
      <div className="eco-factor-card eco-germplasm-hero-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Germplasm origin and collection traits"
              : "种质来源与采集特征"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {insightUiText(loading ? "刷新中" : "样本采集画像", english)}
          </Typography.Text>
        </div>
        <GermplasmCollectionPortrait stats={germplasm} />
      </div>
      <div className="eco-germplasm-card eco-germplasm-sex-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("性别结构", english)}
          </Typography.Text>
          <BarChartOutlined style={{ fontSize: 14 }} />
        </div>
        <GermplasmSexMirror stats={germplasm} />
      </div>
      <div className="eco-germplasm-card eco-germplasm-altitude-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("海拔梯度", english)}
          </Typography.Text>
          <SlidersOutlined style={{ fontSize: 14 }} />
        </div>
        <GermplasmAltitudeGradient stat={germplasm.altitudeStat} />
      </div>
      <div className="eco-risk-card eco-germplasm-health-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("字段健康与图表适配", english)}
          </Typography.Text>
          <Tag color={error ? "warning" : "processing"}>
            {insightUiText(error ? "接口异常" : "字段体检", english)}
          </Tag>
        </div>
        <GermplasmFieldHealthMatrix stats={germplasm} />
      </div>
      <div className="eco-field-profile-card">
        <FieldProfileList insight={insight} />
      </div>
      <div className="eco-feature-detail-shell">
        <FeatureDetailPanel feature={feature} />
      </div>
    </div>
  );
}

function GermplasmCollectionPortrait({ stats }: { stats: GermplasmStats }) {
  const english = usePanelEnglish();
  return (
    <div className="eco-germplasm-portrait">
      <div className="eco-germplasm-sample-card">
        <div className="eco-germplasm-dna-board" aria-hidden="true">
          {stats.fingerprintMetrics.map((metric, index) => (
            <i
              className={`eco-tone-${metric.tone}`}
              key={metric.label}
              style={
                {
                  "--eco-fingerprint-offset": `${index * 11}%`,
                  "--eco-fingerprint-value": `${Math.round(metric.value * 100)}%`,
                } as CSSProperties
              }
            />
          ))}
        </div>
        <div className="eco-germplasm-sample-core">
          <small>{insightUiText("种质样本", english)}</small>
          <strong>{formatCompactNumber(stats.sampleTotal)}</strong>
          <span>
            {stats.locationStat
              ? insightUiText(
                  `${stats.locationStat.uniqueCount} 个采集地点`,
                  english,
                )
              : insightUiText("采集地点待统计", english)}
          </span>
        </div>
      </div>
      <div className="eco-germplasm-trait-stack">
        {stats.fingerprintMetrics.map((metric) => (
          <span
            className={`eco-germplasm-trait eco-tone-${metric.tone}`}
            key={metric.label}
          >
            <b>{insightUiText(metric.label, english)}</b>
            <i>
              <em style={{ width: `${Math.round(metric.value * 100)}%` }} />
            </i>
            <strong>{metric.display}</strong>
          </span>
        ))}
      </div>
    </div>
  );
}

function GermplasmSexMirror({ stats }: { stats: GermplasmStats }) {
  const english = usePanelEnglish();
  const sex = stats.sex;
  if (!sex.stat) {
    return <ChartEmpty text={insightUiText("暂无性别字段统计", english)} />;
  }
  const total = Math.max(sex.total, sex.female + sex.male + sex.pending, 1);
  const tracks = [
    {
      key: "female",
      label: "雌株",
      value: sex.female,
      ratio: ratio(sex.female, total),
    },
    {
      key: "male",
      label: "雄株",
      value: sex.male,
      ratio: ratio(sex.male, total),
    },
  ];
  return (
    <div className="eco-sex-mirror">
      <div className="eco-sex-track-list">
        {tracks.map((track) => (
          <div
            className={`eco-sex-track eco-sex-track-${track.key}`}
            key={track.key}
          >
            <span>
              <b>{insightUiText(track.label, english)}</b>
              <small>{formatPercent(track.ratio)}</small>
            </span>
            <strong>{formatCompactNumber(track.value)}</strong>
            <i>
              <em style={{ width: `${Math.max(4, track.ratio * 100)}%` }} />
            </i>
          </div>
        ))}
      </div>
      <div className="eco-sex-balance-strip">
        <span>
          <b>{formatPercent(sex.balance)}</b>
          {insightUiText("均衡度", english)}
        </span>
        <span>
          <b>{formatCompactNumber(sex.pending)}</b>
          {insightUiText("待标准化", english)}
        </span>
        <span>
          <b>{formatPercent(sex.validRatio)}</b>
          {insightUiText("可识别", english)}
        </span>
      </div>
      {sex.pending > 0 ? (
        <div className="eco-sex-warning">
          <ExclamationCircleOutlined style={{ fontSize: 13 }} />
          <span>{insightUiText("存在性别标签标准化风险", english)}</span>
        </div>
      ) : null}
    </div>
  );
}

function GermplasmAltitudeGradient({ stat }: { stat: NumericStat | null }) {
  const english = usePanelEnglish();
  if (!stat) {
    return <ChartEmpty text={insightUiText("暂无海拔字段统计", english)} />;
  }
  if (stat.min === null || stat.max === null || stat.min === stat.max) {
    return (
      <ChartEmpty text={insightUiText("海拔字段缺少有效梯度范围", english)} />
    );
  }
  const maxCount = Math.max(...stat.histogram.map((bin) => bin.count), 1);
  const ridgePoints = stat.histogram.length
    ? stat.histogram
        .map((bin, index) => {
          const x = 8 + (index / Math.max(stat.histogram.length - 1, 1)) * 104;
          const y = 80 - (bin.count / maxCount) * 48;
          return `${x},${y}`;
        })
        .join(" ")
    : "8,72 112,72";
  const range = stat.max - stat.min;
  const q1 = percentPosition(stat.q1 ?? stat.min, stat.min, range);
  const q3 = percentPosition(stat.q3 ?? stat.max, stat.min, range);
  const median = percentPosition(
    stat.median ?? stat.mean ?? stat.min,
    stat.min,
    range,
  );
  return (
    <div className="eco-altitude-gradient">
      <svg
        className="eco-altitude-ridge"
        viewBox="0 0 120 86"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient
            id="ecoAltitudeFill"
            x1="0%"
            y1="0%"
            x2="100%"
            y2="100%"
          >
            <stop offset="0%" stopColor="#38cfff" stopOpacity="0.2" />
            <stop offset="48%" stopColor="#20d6b0" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#f5b84b" stopOpacity="0.4" />
          </linearGradient>
        </defs>
        <polygon points={`8,82 ${ridgePoints} 112,82`} />
        <polyline points={ridgePoints} />
      </svg>
      <div className="eco-altitude-band">
        <i
          className="eco-altitude-iqr"
          style={{ left: `${q1}%`, width: `${Math.max(2, q3 - q1)}%` }}
        />
        <i className="eco-altitude-median" style={{ left: `${median}%` }} />
      </div>
      <div className="eco-altitude-values">
        <span>
          <b>{formatNumber(stat.min)}</b>
          {insightUiText("低值", english)}
        </span>
        <span>
          <b>{formatNumber(stat.median)}</b>
          {insightUiText("中位", english)}
        </span>
        <span>
          <b>{formatNumber(stat.max)}</b>
          {insightUiText("高值", english)}
        </span>
        <span>
          <b>{formatCompactNumber(stat.nullCount)}</b>
          {insightUiText("缺失", english)}
        </span>
      </div>
    </div>
  );
}

function GermplasmFieldHealthMatrix({ stats }: { stats: GermplasmStats }) {
  const english = usePanelEnglish();
  return (
    <div className="eco-germplasm-health-matrix">
      {stats.healthRows.map((row) => (
        <div className="eco-germplasm-health-row" key={row.label}>
          <span className="eco-germplasm-health-label">
            <b>{insightUiText(row.label, english)}</b>
            <small>{insightUiText(row.hint, english)}</small>
          </span>
          <div className="eco-germplasm-health-meters">
            {row.cells.map((cell) => (
              <span
                className={`eco-germplasm-health-cell eco-tone-${cell.tone}`}
                key={`${row.label}-${cell.label}`}
                title={`${row.label} ${cell.label} ${formatPercent(cell.value)}`}
              >
                <small>{insightUiText(cell.label, english)}</small>
                <strong>{formatPercent(cell.value)}</strong>
                <i>
                  <em style={{ width: `${Math.round(cell.value * 100)}%` }} />
                </i>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function IndividualFactorPanel({
  error,
  feature,
  insight,
  loading,
}: {
  error: string | null;
  feature: FeatureInfo | null;
  insight: InsightStats;
  loading: boolean;
}) {
  const english = usePanelEnglish();
  const individual = individualStatsFor(insight);
  return (
    <div className="eco-tab-panel eco-factor-panel eco-individual-panel">
      <div className="eco-factor-card eco-individual-hero-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Individual classification and growth traits"
              : "个体分类与生长属性"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {insightUiText(loading ? "刷新中" : "分类谱系画像", english)}
          </Typography.Text>
        </div>
        <IndividualClassificationPortrait stats={individual} />
      </div>
      <div className="eco-individual-card eco-individual-rank-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("科排序 TopN", english)}
          </Typography.Text>
          <BarChartOutlined style={{ fontSize: 14 }} />
        </div>
        <IndividualOrderRanking stats={individual} />
      </div>
      <div className="eco-individual-card eco-individual-order-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("科排序序列分布", english)}
          </Typography.Text>
          <SlidersOutlined style={{ fontSize: 14 }} />
        </div>
        <IndividualOrderSequence stats={individual} />
      </div>
      <div className="eco-risk-card eco-individual-field-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("分类字段适配矩阵", english)}
          </Typography.Text>
          <Tag color={error ? "warning" : "processing"}>
            {insightUiText(error ? "接口异常" : "字段适配", english)}
          </Tag>
        </div>
        <IndividualFieldMatrix stats={individual} />
      </div>
      <div className="eco-field-profile-card">
        <FieldProfileList insight={insight} />
      </div>
      <div className="eco-feature-detail-shell">
        <FeatureDetailPanel feature={feature} />
      </div>
    </div>
  );
}

function IndividualClassificationPortrait({
  stats,
}: {
  stats: IndividualStats;
}) {
  const english = usePanelEnglish();
  return (
    <div className="eco-individual-portrait">
      <div className="eco-individual-taxonomy-card">
        <div className="eco-individual-taxonomy-core">
          <small>{insightUiText("个体记录", english)}</small>
          <strong>{formatCompactNumber(stats.recordTotal)}</strong>
          <span>
            {stats.speciesStat
              ? insightUiText(
                  `${stats.speciesStat.uniqueCount} 个物种`,
                  english,
                )
              : insightUiText("物种字段待统计", english)}
          </span>
        </div>
        <div className="eco-individual-taxonomy-rings" aria-hidden="true">
          {stats.taxonomyMetrics.map((metric, index) => (
            <i
              className={`eco-tone-${metric.tone}`}
              key={metric.label}
              style={
                {
                  "--eco-taxonomy-offset": `${index * 13}%`,
                  "--eco-taxonomy-value": `${Math.round(metric.value * 100)}%`,
                } as CSSProperties
              }
            />
          ))}
        </div>
      </div>
      <div className="eco-individual-taxonomy-stack">
        {stats.taxonomyMetrics.map((metric) => (
          <span
            className={`eco-individual-taxonomy-metric eco-tone-${metric.tone}`}
            key={metric.label}
          >
            <b>{insightUiText(metric.label, english)}</b>
            <strong>{metric.display}</strong>
            <i>
              <em style={{ width: `${Math.round(metric.value * 100)}%` }} />
            </i>
          </span>
        ))}
      </div>
    </div>
  );
}

function IndividualOrderRanking({ stats }: { stats: IndividualStats }) {
  const english = usePanelEnglish();
  const stat = stats.orderCategoryStat ?? stats.familyStat;
  if (!stat) {
    return (
      <ChartEmpty text={insightUiText("暂无科排序或科类字段统计", english)} />
    );
  }
  const items = categoryDisplayItems(stat).slice(0, 6);
  const maxCount = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="eco-individual-rank-list">
      {items.map((item, index) => (
        <div
          className="eco-individual-rank-row"
          key={`${stat.field}-${item.label}`}
        >
          <span>
            <b>{item.label || (english ? "Not provided" : "未填写")}</b>
            <small>{formatPercent(item.ratio)}</small>
          </span>
          <i>
            <em
              style={{
                width: `${Math.max(5, (item.count / maxCount) * 100)}%`,
                opacity: 1 - index * 0.06,
              }}
            />
          </i>
          <strong>{formatCompactNumber(item.count)}</strong>
        </div>
      ))}
    </div>
  );
}

function IndividualOrderSequence({ stats }: { stats: IndividualStats }) {
  const english = usePanelEnglish();
  const numeric = stats.orderNumericStat;
  const category = stats.orderCategoryStat;
  if (!numeric && !category) {
    return <ChartEmpty text={insightUiText("暂无科排序字段统计", english)} />;
  }
  const min = numeric?.min ?? minimumCategoryNumber(category);
  const max = numeric?.max ?? maximumCategoryNumber(category);
  if (min === null || max === null || min === max) {
    return (
      <ChartEmpty text={insightUiText("科排序字段缺少可用序列范围", english)} />
    );
  }
  const range = max - min;
  const items = category ? categoryDisplayItems(category).slice(0, 8) : [];
  const q1 = numeric ? percentPosition(numeric.q1 ?? min, min, range) : 0;
  const q3 = numeric ? percentPosition(numeric.q3 ?? max, min, range) : 100;
  const median = numeric
    ? percentPosition(numeric.median ?? min, min, range)
    : 50;
  return (
    <div className="eco-individual-order-sequence">
      <div className="eco-individual-order-track">
        <i
          className="eco-individual-order-iqr"
          style={{ left: `${q1}%`, width: `${Math.max(2, q3 - q1)}%` }}
        />
        <i
          className="eco-individual-order-median"
          style={{ left: `${median}%` }}
        />
        {items.map((item, index) => {
          const value = toFiniteNumber(item.label);
          if (value === null) return null;
          return (
            <span
              key={`${item.label}-${index}`}
              style={{
                left: `${clamp(percentPosition(value, min, range), 4, 96)}%`,
              }}
              title={`${item.label}: ${formatCompactNumber(item.count)}`}
            />
          );
        })}
      </div>
      {items.length ? (
        <div className="eco-individual-order-badges">
          {items.map((item) => (
            <span key={`${item.label}-badge`}>
              <b>{item.label}</b>
              <small>{formatCompactNumber(item.count)}</small>
            </span>
          ))}
        </div>
      ) : null}
      <div className="eco-individual-order-stats">
        <span>
          <b>{formatNumber(min)}</b>
          {insightUiText("最小", english)}
        </span>
        <span>
          <b>{formatNumber(numeric?.median ?? null)}</b>
          {insightUiText("中位", english)}
        </span>
        <span>
          <b>{formatNumber(max)}</b>
          {insightUiText("最大", english)}
        </span>
        <span>
          <b>{formatCompactNumber(category?.uniqueCount ?? 0)}</b>
          {insightUiText("类别", english)}
        </span>
      </div>
    </div>
  );
}

function IndividualFieldMatrix({ stats }: { stats: IndividualStats }) {
  const english = usePanelEnglish();
  return (
    <div className="eco-individual-field-matrix">
      {stats.fieldRows.map((row) => (
        <div className="eco-individual-field-row" key={row.label}>
          <span className="eco-individual-field-label">
            <b>{insightUiText(row.label, english)}</b>
            <small>{insightUiText(row.hint, english)}</small>
          </span>
          <div className="eco-individual-field-cells">
            {row.cells.map((cell) => (
              <span
                className={`eco-individual-field-cell eco-tone-${cell.tone}`}
                key={`${row.label}-${cell.label}`}
                title={`${row.label} ${cell.label} ${formatPercent(cell.value)}`}
              >
                <small>{insightUiText(cell.label, english)}</small>
                <strong>{formatPercent(cell.value)}</strong>
                <i>
                  <em style={{ width: `${Math.round(cell.value * 100)}%` }} />
                </i>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CommunityFactorPanel({
  error,
  feature,
  insight,
  loading,
}: {
  error: string | null;
  feature: FeatureInfo | null;
  insight: InsightStats;
  loading: boolean;
}) {
  const english = usePanelEnglish();
  const community = communityStatsFor(insight);
  return (
    <div className="eco-tab-panel eco-factor-panel eco-community-panel">
      <div className="eco-factor-card eco-community-hero-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Community diversity and environmental gradient"
              : "群落多样性与环境梯度"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {insightUiText(loading ? "刷新中" : "生态梯度画像", english)}
          </Typography.Text>
        </div>
        <CommunityDiversityPortrait stats={community} />
      </div>
      <div className="eco-community-card eco-community-group-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("样方分组格局", english)}
          </Typography.Text>
          <BarChartOutlined style={{ fontSize: 14 }} />
        </div>
        <CommunityGroupBalance stats={community} />
      </div>
      <div className="eco-community-card eco-community-gradient-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("多样性指数梯度", english)}
          </Typography.Text>
          <SlidersOutlined style={{ fontSize: 14 }} />
        </div>
        <CommunityDiversityGradient stats={community} />
      </div>
      <div className="eco-risk-card eco-community-field-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {insightUiText("性状环境适配矩阵", english)}
          </Typography.Text>
          <Tag color={error ? "warning" : "processing"}>
            {insightUiText(error ? "接口异常" : "字段适配", english)}
          </Tag>
        </div>
        <CommunityFieldMatrix stats={community} />
      </div>
      <div className="eco-field-profile-card">
        <FieldProfileList insight={insight} />
      </div>
      <div className="eco-feature-detail-shell">
        <FeatureDetailPanel feature={feature} />
      </div>
    </div>
  );
}

function CommunityDiversityPortrait({ stats }: { stats: CommunityStats }) {
  const english = usePanelEnglish();
  return (
    <div className="eco-community-portrait">
      <div className="eco-community-gradient-map">
        <div className="eco-community-gradient-core">
          <small>{english ? "Community plots" : "群落样方"}</small>
          <strong>{formatCompactNumber(stats.plotTotal)}</strong>
          <span>
            {stats.groupStat
              ? english
                ? `${stats.groupStat.uniqueCount} groups`
                : `${stats.groupStat.uniqueCount} 个分组`
              : english
                ? "Groups pending"
                : "分组待统计"}
          </span>
        </div>
        <svg
          viewBox="0 0 240 118"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {stats.portraitMetrics.map((metric, index) => {
            const y = 24 + index * 22;
            const width = 182 * clamp(metric.value, 0.04, 1);
            return (
              <g className={`eco-tone-${metric.tone}`} key={metric.label}>
                <path
                  d={`M18 ${y} C 62 ${y - 20}, 92 ${y + 20}, 126 ${y} S 190 ${y - 8}, 222 ${y}`}
                />
                <rect x="28" y={y - 3} width={width} height="6" rx="3" />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="eco-community-metric-grid">
        {stats.portraitMetrics.map((metric) => (
          <span
            className={`eco-community-metric eco-tone-${metric.tone}`}
            key={metric.label}
          >
            <b>{insightUiText(metric.label, english)}</b>
            <strong>{metric.display}</strong>
            <i>
              <em style={{ width: `${Math.round(metric.value * 100)}%` }} />
            </i>
          </span>
        ))}
      </div>
    </div>
  );
}

function CommunityGroupBalance({ stats }: { stats: CommunityStats }) {
  const english = usePanelEnglish();
  const stat = stats.groupStat;
  if (!stat) {
    return (
      <ChartEmpty
        text={english ? "No plot-group statistics" : "暂无样方分组字段统计"}
      />
    );
  }
  const items = categoryDisplayItems(stat).slice(0, 6);
  const maxCount = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="eco-community-group-list">
      {items.map((item, index) => (
        <div
          className="eco-community-group-row"
          key={`${stat.field}-${item.label}`}
        >
          <span>
            <b>{item.label || (english ? "Not provided" : "未填写")}</b>
            <small>{formatPercent(item.ratio)}</small>
          </span>
          <i>
            <em
              style={{
                width: `${Math.max(5, (item.count / maxCount) * 100)}%`,
                opacity: 1 - index * 0.05,
              }}
            />
          </i>
          <strong>{formatCompactNumber(item.count)}</strong>
        </div>
      ))}
    </div>
  );
}

function CommunityDiversityGradient({ stats }: { stats: CommunityStats }) {
  const english = usePanelEnglish();
  const primary = stats.shannonStat ?? stats.richnessStat ?? stats.raoStat;
  if (
    !primary ||
    primary.min === null ||
    primary.max === null ||
    primary.min === primary.max
  ) {
    return (
      <ChartEmpty
        text={
          english ? "No usable diversity-index range" : "暂无可用多样性指数范围"
        }
      />
    );
  }
  const range = primary.max - primary.min;
  const q1 = percentPosition(primary.q1 ?? primary.min, primary.min, range);
  const q3 = percentPosition(primary.q3 ?? primary.max, primary.min, range);
  const median = percentPosition(
    primary.median ?? primary.mean ?? primary.min,
    primary.min,
    range,
  );
  return (
    <div className="eco-community-diversity-gradient">
      <div className="eco-community-ridge">
        <svg viewBox="0 0 240 96" preserveAspectRatio="none" aria-hidden="true">
          <path d={communityRidgePath(primary)} />
          <polyline points={communityRidgePolyline(primary)} />
        </svg>
      </div>
      <div className="eco-community-gradient-band">
        <i
          className="eco-community-gradient-iqr"
          style={{ left: `${q1}%`, width: `${Math.max(2, q3 - q1)}%` }}
        />
        <i
          className="eco-community-gradient-median"
          style={{ left: `${median}%` }}
        />
      </div>
      <div className="eco-community-gradient-values">
        <span>
          <b>{formatNumber(primary.min)}</b>
          {insightUiText("低值", english)}
        </span>
        <span>
          <b>{formatNumber(primary.median)}</b>
          {insightUiText("中位", english)}
        </span>
        <span>
          <b>{formatNumber(primary.max)}</b>
          {insightUiText("高值", english)}
        </span>
        <span>
          <b>{formatCompactNumber(primary.nullCount)}</b>
          {insightUiText("缺失", english)}
        </span>
      </div>
    </div>
  );
}

function CommunityFieldMatrix({ stats }: { stats: CommunityStats }) {
  const english = usePanelEnglish();
  return (
    <div className="eco-community-field-matrix">
      {stats.fieldRows.map((row) => (
        <div className="eco-community-field-row" key={row.label}>
          <span className="eco-community-field-label">
            <b>{insightUiText(row.label, english)}</b>
            <small>{insightUiText(row.hint, english)}</small>
          </span>
          <div className="eco-community-field-cells">
            {row.cells.map((cell) => (
              <span
                className={`eco-community-field-cell eco-tone-${cell.tone}`}
                key={`${row.label}-${cell.label}`}
                title={`${row.label} ${cell.label} ${formatPercent(cell.value)}`}
              >
                <small>{insightUiText(cell.label, english)}</small>
                <strong>{formatPercent(cell.value)}</strong>
                <i>
                  <em style={{ width: `${Math.round(cell.value * 100)}%` }} />
                </i>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function PopulationSurveyFactorPanel({
  error,
  feature,
  insight,
  loading,
}: {
  error: string | null;
  feature: FeatureInfo | null;
  insight: InsightStats;
  loading: boolean;
}) {
  const english = usePanelEnglish();
  const stats = populationSurveyStatsFor(insight);
  const isFieldSurvey = insight.domainType === "field_survey";
  return (
    <div className="eco-tab-panel eco-factor-panel eco-pop-survey-panel">
      <div className="eco-factor-card eco-pop-survey-hero-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {isFieldSurvey
              ? english
                ? "Survey plots and species records"
                : "调查样方与物种记录"
              : english
                ? "Population plots and dominance profile"
                : "种群样方与优势度画像"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {loading
              ? insightUiText("刷新中", english)
              : isFieldSurvey
                ? english
                  ? "Field-record profile"
                  : "野外记录画像"
                : english
                  ? "Population-structure profile"
                  : "种群结构画像"}
          </Typography.Text>
        </div>
        <PopulationSurveyStructurePortrait stats={stats} />
      </div>
      <div className="eco-pop-survey-card eco-pop-survey-dominance-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english ? "Species dominance Top N" : "物种优势 TopN"}
          </Typography.Text>
          <BarChartOutlined style={{ fontSize: 14 }} />
        </div>
        <PopulationSurveySpeciesDominance stats={stats} />
      </div>
      <div className="eco-pop-survey-card eco-pop-survey-gradient-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {english
              ? "Density and importance-value gradient"
              : "密度与重要值梯度"}
          </Typography.Text>
          <SlidersOutlined style={{ fontSize: 14 }} />
        </div>
        <PopulationSurveyGradient stats={stats} />
      </div>
      <div className="eco-risk-card eco-pop-survey-field-card">
        <div className="right-panel-heading">
          <Typography.Text strong>
            {isFieldSurvey
              ? english
                ? "Survey-field suitability matrix"
                : "调查字段适配矩阵"
              : english
                ? "Population-field suitability matrix"
                : "种群字段适配矩阵"}
          </Typography.Text>
          <Tag color={error ? "warning" : "processing"}>
            {insightUiText(error ? "接口异常" : "字段适配", english)}
          </Tag>
        </div>
        <PopulationSurveyFieldMatrix stats={stats} />
      </div>
      <div className="eco-field-profile-card">
        <FieldProfileList insight={insight} />
      </div>
      <div className="eco-feature-detail-shell">
        <FeatureDetailPanel feature={feature} />
      </div>
    </div>
  );
}

function PopulationSurveyStructurePortrait({
  stats,
}: {
  stats: PopulationSurveyStats;
}) {
  const english = usePanelEnglish();
  const isFieldSurvey = stats.domainType === "field_survey";
  const plotLabel = stats.plotStat
    ? english
      ? `${formatCompactNumber(stats.plotStat.uniqueCount)} plots`
      : `${formatCompactNumber(stats.plotStat.uniqueCount)} 个样方`
    : english
      ? "Plots pending"
      : "样方待统计";
  const lineCount = clamp(
    Math.round(
      stats.transectStat?.uniqueCount ?? stats.plotStat?.uniqueCount ?? 4,
    ),
    3,
    6,
  );
  return (
    <div className="eco-pop-survey-portrait">
      <div className="eco-pop-survey-quadrat">
        <svg
          viewBox="0 0 260 150"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {Array.from({ length: lineCount }).map((_, index) => {
            const y = 26 + index * (96 / Math.max(lineCount - 1, 1));
            return (
              <path
                className="eco-pop-survey-transect"
                d={`M22 ${y} C 68 ${y - 16}, 104 ${y + 18}, 150 ${y} S 222 ${y - 10}, 238 ${y + 4}`}
                key={`transect-${index}`}
              />
            );
          })}
          {stats.portraitMetrics.map((metric, index) => {
            const y = 32 + index * 25;
            const x = 38 + 164 * clamp(metric.value, 0.05, 1);
            return (
              <g className={`eco-tone-${metric.tone}`} key={metric.label}>
                <line x1="38" y1={y} x2={x} y2={y} />
                <rect x={x - 5} y={y - 5} width="10" height="10" rx="2" />
              </g>
            );
          })}
        </svg>
        <div className="eco-pop-survey-core">
          <small>
            {isFieldSurvey
              ? english
                ? "Survey records"
                : "调查记录"
              : english
                ? "Population records"
                : "种群记录"}
          </small>
          <strong>{formatCompactNumber(stats.recordTotal)}</strong>
          <span>{plotLabel}</span>
        </div>
      </div>
      <div className="eco-pop-survey-metric-grid">
        {stats.portraitMetrics.map((metric) => (
          <span
            className={`eco-pop-survey-metric eco-tone-${metric.tone}`}
            key={metric.label}
          >
            <b>{insightUiText(metric.label, english)}</b>
            <strong>{metric.display}</strong>
            <i>
              <em style={{ width: `${Math.round(metric.value * 100)}%` }} />
            </i>
          </span>
        ))}
      </div>
    </div>
  );
}

function PopulationSurveySpeciesDominance({
  stats,
}: {
  stats: PopulationSurveyStats;
}) {
  const english = usePanelEnglish();
  const stat = stats.speciesStat ?? stats.plotStat ?? stats.habitatStat;
  if (!stat) {
    return (
      <ChartEmpty
        text={
          english
            ? "No species, plot, or habitat statistics"
            : "暂无物种、样方或栖息地分类统计"
        }
      />
    );
  }
  const items = categoryDisplayItems(stat).slice(0, 7);
  const maxCount = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="eco-pop-survey-dominance-list">
      {items.map((item, index) => (
        <div
          className="eco-pop-survey-dominance-row"
          key={`${stat.field}-${item.label}`}
        >
          <span className="eco-pop-survey-rank">{index + 1}</span>
          <span className="eco-pop-survey-name">
            <b>{item.label || (english ? "Not provided" : "未填写")}</b>
            <small>{formatPercent(item.ratio)}</small>
          </span>
          <i>
            <em
              style={{
                width: `${Math.max(6, (item.count / maxCount) * 100)}%`,
              }}
            />
          </i>
          <strong>{formatCompactNumber(item.count)}</strong>
        </div>
      ))}
    </div>
  );
}

function PopulationSurveyGradient({ stats }: { stats: PopulationSurveyStats }) {
  const english = usePanelEnglish();
  const lanes = [
    {
      label: english ? "Density" : "密度",
      stat: stats.densityStat,
      tone: "cyan" as Tone,
    },
    {
      label: english ? "Importance value" : "重要值",
      stat: stats.importanceStat,
      tone: "amber" as Tone,
    },
  ].filter((lane): lane is { label: string; stat: NumericStat; tone: Tone } =>
    Boolean(lane.stat),
  );
  if (!lanes.length) {
    return (
      <ChartEmpty
        text={
          english
            ? "No density or importance-value statistics"
            : "暂无密度或重要值字段统计"
        }
      />
    );
  }
  return (
    <div className="eco-pop-survey-gradient">
      {lanes.map((lane) => (
        <PopulationSurveyMetricLane
          key={lane.label}
          label={lane.label}
          stat={lane.stat}
          tone={lane.tone}
        />
      ))}
      <div className="eco-pop-survey-gradient-summary">
        <span>
          <b>
            {formatNumber(
              stats.plantCountStat?.median ??
                stats.actualPlantCountStat?.median,
            )}
          </b>
          {english ? "Median plant count" : "株数中位"}
        </span>
        <span>
          <b>{formatNumber(stats.coverStat?.median)}</b>
          {english ? "Median cover" : "盖度中位"}
        </span>
        <span>
          <b>{formatNumber(stats.frequencyStat?.median)}</b>
          {english ? "Median frequency" : "频度中位"}
        </span>
        <span>
          <b>{stats.bioStats.length}</b>
          {english ? "Climate fields" : "气候字段"}
        </span>
      </div>
    </div>
  );
}

function PopulationSurveyMetricLane({
  label,
  stat,
  tone,
}: {
  label: string;
  stat: NumericStat;
  tone: Tone;
}) {
  const english = usePanelEnglish();
  const bins = stat.histogram.length
    ? stat.histogram
    : syntheticHistogram(stat);
  const maxCount = Math.max(...bins.map((bin) => bin.count), 1);
  return (
    <div className={`eco-pop-survey-lane eco-tone-${tone}`}>
      <div className="eco-pop-survey-lane-head">
        <span>
          <b>{label}</b>
          <small>{stat.label}</small>
        </span>
        <strong>{formatNumber(stat.median ?? stat.mean)}</strong>
      </div>
      <div className="eco-pop-survey-bin-board">
        {bins.map((bin, index) => (
          <span
            key={`${label}-${index}`}
            style={
              {
                "--eco-pop-bin-height": `${Math.max(8, (bin.count / maxCount) * 100)}%`,
              } as CSSProperties
            }
            title={`${formatNumber(bin.min)}-${formatNumber(bin.max)}: ${formatCompactNumber(bin.count)}`}
          />
        ))}
      </div>
      <div className="eco-pop-survey-range-row">
        <span>
          <b>{formatNumber(stat.min)}</b>
          {insightUiText("低值", english)}
        </span>
        <span>
          <b>{formatNumber(stat.q1)}</b>
          {english ? "Q1" : "下四分"}
        </span>
        <span>
          <b>{formatNumber(stat.q3)}</b>
          {english ? "Q3" : "上四分"}
        </span>
        <span>
          <b>{formatNumber(stat.max)}</b>
          {insightUiText("高值", english)}
        </span>
      </div>
    </div>
  );
}

function PopulationSurveyFieldMatrix({
  stats,
}: {
  stats: PopulationSurveyStats;
}) {
  const english = usePanelEnglish();
  return (
    <div className="eco-pop-survey-field-matrix">
      {stats.fieldRows.map((row) => (
        <div className="eco-pop-survey-field-row" key={row.label}>
          <span className="eco-pop-survey-field-label">
            <b>{insightUiText(row.label, english)}</b>
            <small>{insightUiText(row.hint, english)}</small>
          </span>
          <div className="eco-pop-survey-field-cells">
            {row.cells.map((cell) => (
              <span
                className={`eco-pop-survey-field-cell eco-tone-${cell.tone}`}
                key={`${row.label}-${cell.label}`}
                title={`${row.label} ${cell.label} ${formatPercent(cell.value)}`}
              >
                <small>{insightUiText(cell.label, english)}</small>
                <strong>{formatPercent(cell.value)}</strong>
                <i>
                  <em style={{ height: `${Math.round(cell.value * 100)}%` }} />
                </i>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

interface InsightStats {
  hasData: boolean;
  domainType: DataDomainType | null;
  source: string;
  profile: ResourceVisualizationSummary["profile"];
  spatialSummary: ResourceVisualizationSummary["spatialSummary"];
  categoryStats: CategoryStat[];
  numericStats: NumericStat[];
  qualityIssues: QualityIssue[];
  recommendedCharts: ResourceVisualizationSummary["recommendedCharts"];
  monitorTitle: string;
  monitorItems: MonitorItem[];
  fieldNames: string[];
}

function createInsightStats(
  summary: ResourceVisualizationSummary | null,
  layer: LoadedLayer | null,
  profile: DataResourceProfile | null,
  resource: ResourceListItem | null,
): InsightStats {
  const localCategories = buildLocalCategoryStats(layer);
  const localNumerics = buildLocalNumericStats(layer);
  const localProfile = buildLocalProfile(layer, profile, resource);
  const localSpatialSummary = buildLocalSpatialSummary(layer, localProfile);
  const categoryStats = summary?.categoryStats.length
    ? summary.categoryStats
    : localCategories;
  const numericStats = summary?.numericStats.length
    ? summary.numericStats
    : localNumerics;
  const baseQualityIssues = summary?.qualityIssues.length
    ? summary.qualityIssues
    : buildLocalQualityIssues(
        layer,
        profile,
        resource,
        categoryStats,
        numericStats,
      );
  const qualityIssues = withQualityNoteIssue(
    baseQualityIssues,
    summary?.resource ?? resource,
  );
  const fieldNames =
    layer?.fields.map((field) => field.description || field.name) ??
    profile?.fields.map((field) => field.description || field.name) ??
    [];

  return {
    hasData: Boolean(summary || layer || profile || resource),
    domainType:
      summary?.domainType ??
      layer?.sourceResource.domainType ??
      resource?.domainType ??
      null,
    source:
      summary?.source ?? (layer ? "frontend_loaded_layer" : "frontend_profile"),
    profile: summary?.profile ?? localProfile,
    spatialSummary: summary?.spatialSummary ?? localSpatialSummary,
    categoryStats,
    numericStats,
    qualityIssues,
    recommendedCharts: summary?.recommendedCharts ?? [],
    monitorTitle: summary?.monitorPreview.title ?? "监测能力预留",
    monitorItems: summary?.monitorPreview.items ?? defaultMonitorItems(),
    fieldNames,
  };
}

function InsightState({
  loading,
  error,
  text,
}: {
  loading?: boolean;
  error?: string | null;
  text: string;
}) {
  return (
    <div className="eco-tab-panel eco-empty-state">
      {loading ? (
        <Spin size="small" />
      ) : (
        <DatabaseOutlined style={{ fontSize: 22 }} />
      )}
      <Typography.Text type={error ? "warning" : "secondary"}>
        {error ?? text}
      </Typography.Text>
    </div>
  );
}

function ChartEmpty({
  text,
  compact = false,
}: {
  text: string;
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact ? "eco-chart-empty eco-chart-empty-compact" : "eco-chart-empty"
      }
    >
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />
    </div>
  );
}

function FieldStatSelect({
  options,
  placeholder,
  value,
  onChange,
}: {
  options: Array<{ value: string; label: string }>;
  placeholder: string;
  value: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      className="eco-field-select"
      disabled={!options.length}
      notFoundContent="暂无字段"
      optionFilterProp="label"
      options={options}
      placeholder={placeholder}
      popupMatchSelectWidth={false}
      showSearch={options.length > 6}
      size="small"
      value={value ?? undefined}
      onChange={onChange}
    />
  );
}

function DataAssetOverview({
  insight,
  qualityScore,
}: {
  insight: InsightStats;
  qualityScore: number;
}) {
  const english = usePanelEnglish();
  const assetScale = assetScaleFor(insight);
  const chartFieldCount =
    insight.categoryStats.length + insight.numericStats.length;
  const fieldTotal = Math.max(insight.profile.fieldCount, chartFieldCount);
  const fieldRatio = fieldTotal > 0 ? chartFieldCount / fieldTotal : 0;
  const coverageRatio = spatialCoverageRatio(insight);
  const issueCounts = issueCountsBySeverity(insight.qualityIssues);
  const blockingRisks = issueCounts.warning + issueCounts.error;
  const scaleValues = insight.categoryStats[0]?.items.map(
    (item) => item.count,
  ) ??
    insight.numericStats[0]?.histogram.map((bin) => bin.count) ?? [
      assetScale.raw,
    ];

  return (
    <div className="eco-status-card eco-asset-card">
      <div className="eco-asset-ring-wrap">
        <AssetScaleDial assetScale={assetScale} qualityScore={qualityScore} />
        <MetricRibbon
          metrics={[
            {
              label: insightUiText("空间", english),
              tone: "green",
              value: coverageRatio,
              text: formatPercent(coverageRatio),
            },
            {
              label: insightUiText("字段", english),
              tone: "cyan",
              value: fieldRatio,
              text: formatPercent(fieldRatio),
            },
            {
              label: insightUiText("质量", english),
              tone: blockingRisks ? "amber" : "green",
              value: qualityScore / 100,
              text: String(qualityScore),
            },
          ]}
        />
      </div>
      <div className="eco-asset-mini-grid">
        <AssetMiniCard
          caption={insightUiText(assetScale.label, english)}
          tone="green"
          title={insightUiText("数据规模", english)}
          value={assetScale.value}
        >
          <Sparkline values={sparkValuesFromCounts(scaleValues)} />
        </AssetMiniCard>
        <AssetMiniCard
          caption={
            english
              ? `Categorical ${insight.categoryStats.length} · Numeric ${insight.numericStats.length}`
              : `分类 ${insight.categoryStats.length} · 数值 ${insight.numericStats.length}`
          }
          tone={chartFieldCount > 0 ? "cyan" : "red"}
          title={insightUiText("字段结构", english)}
          value={`${chartFieldCount}/${fieldTotal || 0}`}
        >
          <SegmentMeter
            segments={fieldStructureSegments(
              insight.categoryStats.length,
              insight.numericStats.length,
              fieldTotal,
            )}
          />
        </AssetMiniCard>
        <AssetMiniCard
          caption={
            blockingRisks
              ? english
                ? `${blockingRisks} risks`
                : `风险 ${blockingRisks} 项`
              : english
                ? "No blocking risks"
                : "未见阻断风险"
          }
          tone={blockingRisks ? "amber" : "green"}
          title={insightUiText("校验状态", english)}
          value={String(qualityScore)}
        >
          <SegmentMeter segments={riskSegments(issueCounts)} />
        </AssetMiniCard>
      </div>
    </div>
  );
}

function AssetScaleDial({
  assetScale,
  qualityScore,
}: {
  assetScale: ReturnType<typeof assetScaleFor>;
  qualityScore: number;
}) {
  const english = usePanelEnglish();
  return (
    <div className="eco-asset-dial">
      <svg
        className="eco-asset-dial-svg"
        viewBox="0 0 148 126"
        aria-hidden="true"
      >
        <defs>
          <linearGradient
            id="ecoAssetDialGradient"
            x1="20%"
            y1="0%"
            x2="90%"
            y2="100%"
          >
            <stop offset="0%" stopColor="#38cfff" />
            <stop offset="55%" stopColor="#20d6b0" />
            <stop offset="100%" stopColor="#a9fff1" />
          </linearGradient>
        </defs>
        <path
          className="eco-asset-dial-rail"
          d="M 29 91 A 49 49 0 1 1 119 91"
          pathLength={100}
        />
        <path
          className="eco-asset-dial-progress"
          d="M 29 91 A 49 49 0 1 1 119 91"
          pathLength={100}
          style={{ strokeDasharray: `${qualityScore} 100` }}
        />
        <path
          className="eco-asset-dial-glow"
          d="M 42 96 A 35 35 0 1 1 106 96"
        />
        <circle className="eco-asset-dial-dot" cx="29" cy="91" r="3.2" />
        <circle
          className="eco-asset-dial-dot eco-asset-dial-dot-end"
          cx="119"
          cy="91"
          r="3.2"
        />
      </svg>
      <div className="eco-asset-dial-core">
        <small>{insightUiText("数据规模", english)}</small>
        <strong>{assetScale.value}</strong>
        <span>{insightUiText(assetScale.label, english)}</span>
      </div>
    </div>
  );
}

function MetricRibbon({
  metrics,
}: {
  metrics: Array<{ label: string; tone: Tone; value: number; text: string }>;
}) {
  return (
    <div className="eco-metric-ribbon">
      {metrics.map((metric) => (
        <span className={`eco-tone-${metric.tone}`} key={metric.label}>
          <b>{metric.label}</b>
          <i>
            <em style={{ width: `${clamp(metric.value, 0, 1) * 100}%` }} />
          </i>
          <strong>{metric.text}</strong>
        </span>
      ))}
    </div>
  );
}

function AssetMiniCard({
  caption,
  children,
  title,
  tone,
  value,
}: {
  caption: string;
  children: ReactNode;
  title: string;
  tone: Tone;
  value: string;
}) {
  return (
    <span className={`eco-metric-card eco-asset-mini-card eco-tone-${tone}`}>
      <small>{title}</small>
      <strong>{value}</strong>
      <em>{caption}</em>
      {children}
    </span>
  );
}

function SegmentMeter({
  segments,
}: {
  segments: Array<{ label: string; tone: Tone; value: number }>;
}) {
  return (
    <div className="eco-segment-meter">
      {segments.map((segment) => (
        <i
          className={`eco-tone-${segment.tone}`}
          key={segment.label}
          style={{ flexGrow: Math.max(0.04, segment.value) }}
          title={`${segment.label} ${formatPercent(segment.value)}`}
        />
      ))}
    </div>
  );
}

function Sparkline({ values }: { values: readonly number[] }) {
  return (
    <svg className="eco-sparkline" viewBox="0 0 72 24" aria-hidden="true">
      <polyline points={formatPoints(values, 72, 24)} />
    </svg>
  );
}

function HistogramChart({ stat }: { stat: NumericStat }) {
  if (!stat.histogram.length || stat.count === 0) {
    return <ChartEmpty text="该字段暂无可绘制的数值分布" />;
  }
  if (stat.count <= 8 || stat.histogram.length < 3 || stat.min === stat.max) {
    return <NumericDotDistribution stat={stat} />;
  }
  const maxCount = Math.max(...stat.histogram.map((bin) => bin.count), 1);
  const densityPoints = densityPointsFromHistogram(stat.histogram, maxCount);
  const densityPointsAttr = densityPoints
    .map((point) => `${point.x},${point.y}`)
    .join(" ");
  const densityAreaPath = densityPoints.length
    ? `M 0 96 L ${densityPoints.map((point) => `${point.x} ${point.y}`).join(" L ")} L 100 96 Z`
    : "";
  return (
    <div className="eco-histogram">
      <div className="eco-chart-subline">
        <span>有效 {formatCompactNumber(stat.count)}</span>
        <span>空值 {formatCompactNumber(stat.nullCount)}</span>
        <span>均值 {formatNumber(stat.mean)}</span>
      </div>
      <div className="eco-histogram-stage">
        <div className="eco-histogram-bars">
          {stat.histogram.map((bin, index) => (
            <span
              key={`${bin.label}-${index}`}
              title={`${bin.label}: ${bin.count}`}
            >
              <i
                style={{
                  height: `${Math.max(8, (bin.count / maxCount) * 100)}%`,
                  opacity: 0.72 + (bin.count / maxCount) * 0.28,
                }}
              />
            </span>
          ))}
        </div>
        <svg
          className="eco-density-svg"
          preserveAspectRatio="none"
          viewBox="0 0 100 100"
          aria-hidden="true"
        >
          <path d={densityAreaPath} />
          <polyline points={densityPointsAttr} />
        </svg>
      </div>
      <QuantileStrip stat={stat} />
      <div className="eco-stat-row">
        <span>
          <b>{formatNumber(stat.q1)}</b>
          Q1
        </span>
        <span>
          <b>{formatNumber(stat.median)}</b>
          中位
        </span>
        <span>
          <b>{formatNumber(stat.q3)}</b>
          Q3
        </span>
      </div>
    </div>
  );
}

function NumericDotDistribution({ stat }: { stat: NumericStat }) {
  const dots = stat.histogram.flatMap((bin, binIndex) =>
    Array.from({ length: Math.min(bin.count, 10) }, (_, dotIndex) => ({
      key: `${bin.label}-${dotIndex}`,
      x:
        stat.min !== null && stat.max !== null && stat.max !== stat.min
          ? percentPosition(
              (bin.min + bin.max) / 2,
              stat.min,
              stat.max - stat.min,
            )
          : 50,
      y: 18 + ((dotIndex * 19 + binIndex * 17) % 64),
    })),
  );
  if (!dots.length) {
    return <ChartEmpty text="该字段暂无可绘制的数值点位" />;
  }
  return (
    <div className="eco-dot-distribution">
      <div className="eco-chart-subline">
        <span>有效 {formatCompactNumber(stat.count)}</span>
        <span>空值 {formatCompactNumber(stat.nullCount)}</span>
        <span>均值 {formatNumber(stat.mean)}</span>
      </div>
      <div className="eco-dot-stage">
        {dots.map((dot) => (
          <i
            key={dot.key}
            style={{ left: `${dot.x}%`, top: `${dot.y}%` }}
            title={stat.label}
          />
        ))}
      </div>
      <div className="eco-stat-row">
        <span>
          <b>{formatNumber(stat.min)}</b>
          最小
        </span>
        <span>
          <b>{formatNumber(stat.median)}</b>
          中位
        </span>
        <span>
          <b>{formatNumber(stat.max)}</b>
          最大
        </span>
      </div>
    </div>
  );
}

function QuantileStrip({ stat }: { stat: NumericStat }) {
  const english = usePanelEnglish();
  if (stat.min === null || stat.max === null || stat.min === stat.max) {
    return null;
  }
  const range = stat.max - stat.min;
  const q1 = percentPosition(stat.q1 ?? stat.min, stat.min, range);
  const q3 = percentPosition(stat.q3 ?? stat.max, stat.min, range);
  const median = percentPosition(
    stat.median ?? stat.mean ?? stat.min,
    stat.min,
    range,
  );
  const mean = percentPosition(
    stat.mean ?? stat.median ?? stat.min,
    stat.min,
    range,
  );
  return (
    <div className="eco-quantile-strip">
      <div className="eco-quantile-track">
        <i
          className="eco-quantile-range"
          style={{ left: `${q1}%`, width: `${Math.max(2, q3 - q1)}%` }}
        />
        <i className="eco-quantile-median" style={{ left: `${median}%` }} />
        <i
          className="eco-quantile-mean"
          style={{ left: `${mean}%` }}
          title={english ? "Mean" : "均值"}
        />
      </div>
      <div className="eco-quantile-labels">
        <span>{formatNumber(stat.min)}</span>
        <span>{formatNumber(stat.max)}</span>
      </div>
    </div>
  );
}

function DonutDistribution({ stat }: { stat: CategoryStat }) {
  const colors = [
    "#20d6b0",
    "#38cfff",
    "#f5b84b",
    "#ff6b6b",
    "#8fffee",
    "#8ab4ff",
  ];
  const displayItems = categoryDisplayItems(stat);
  const maxCount = Math.max(...displayItems.map((item) => item.count), 1);
  let cursor = 0;
  const stops = displayItems.map((item, index) => {
    const start = cursor;
    cursor += Math.max(0, item.ratio * 100);
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  });
  const gradient = stops.length
    ? `conic-gradient(${stops.join(", ")}, rgba(223, 248, 238, 0.1) ${cursor}% 100%)`
    : undefined;

  return (
    <div className="eco-category-chart">
      <div className="eco-chart-subline">
        <span>总量 {formatCompactNumber(stat.total)}</span>
        <span>类别 {formatCompactNumber(stat.uniqueCount)}</span>
        <span>空值 {formatCompactNumber(stat.nullCount)}</span>
      </div>
      <div className="eco-donut-layout">
        <div className="eco-donut" style={{ background: gradient }}>
          <span>
            <b>{formatCompactNumber(stat.total)}</b>
            总量
          </span>
        </div>
        <div className="eco-donut-list eco-donut-rank-list">
          {displayItems.map((item, index) => (
            <span key={`${stat.field}-${item.label}`}>
              <i style={{ background: colors[index % colors.length] }} />
              <b title={item.label}>{item.label || "未填写"}</b>
              <div className="eco-donut-rank-bar">
                <em
                  style={{
                    width: `${Math.max(5, (item.count / maxCount) * 100)}%`,
                    background: colors[index % colors.length],
                  }}
                />
              </div>
              <strong>{formatPercent(item.ratio)}</strong>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function HorizontalBars({ stat }: { stat: CategoryStat }) {
  const maxCount = Math.max(...stat.items.map((item) => item.count), 1);
  return (
    <div className="eco-horizontal-bars">
      {stat.items.slice(0, 8).map((item, index) => (
        <div className="eco-horizontal-row" key={`${stat.field}-${item.label}`}>
          <span title={item.label}>{item.label || "未填写"}</span>
          <div>
            <i
              style={{
                width: `${Math.max(4, (item.count / maxCount) * 100)}%`,
                opacity: 1 - index * 0.055,
              }}
            />
          </div>
          <b>{formatCompactNumber(item.count)}</b>
        </div>
      ))}
    </div>
  );
}

function BoxRangeChart({ stat }: { stat: NumericStat }) {
  if (stat.min === null || stat.max === null || stat.min === stat.max) {
    return <ChartEmpty text="该字段缺少可用分位范围" />;
  }
  const range = stat.max - stat.min;
  const q1 = percentPosition(stat.q1 ?? stat.min, stat.min, range);
  const q3 = percentPosition(stat.q3 ?? stat.max, stat.min, range);
  const median = percentPosition(
    stat.median ?? stat.mean ?? stat.min,
    stat.min,
    range,
  );
  const mean = percentPosition(
    stat.mean ?? stat.median ?? stat.min,
    stat.min,
    range,
  );
  return (
    <div className="eco-boxplot">
      <div className="eco-boxplot-track">
        <i
          className="eco-boxplot-box"
          style={{ left: `${q1}%`, width: `${Math.max(2, q3 - q1)}%` }}
        />
        <i className="eco-boxplot-median" style={{ left: `${median}%` }} />
        <i className="eco-boxplot-mean" style={{ left: `${mean}%` }} />
      </div>
      <div className="eco-stat-row">
        <span>
          <b>{formatNumber(stat.q1)}</b>
          Q1
        </span>
        <span>
          <b>{formatNumber(stat.median)}</b>
          Median
        </span>
        <span>
          <b>{formatNumber(stat.q3)}</b>
          Q3
        </span>
      </div>
    </div>
  );
}

function RadarProfile({
  stats,
  title,
}: {
  stats: NumericStat[];
  title: string;
}) {
  const values = stats.slice(0, 6).map((stat) => ({
    label: shortLabel(stat.label),
    value: normalizedNumericStat(stat),
  }));
  const points = values.map((item, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / values.length;
    const radius = (item.value / 100) * 52;
    return `${70 + Math.cos(angle) * radius},${62 + Math.sin(angle) * radius}`;
  });
  const outer = values.map((_, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / values.length;
    return `${70 + Math.cos(angle) * 52},${62 + Math.sin(angle) * 52}`;
  });
  return (
    <div className="eco-radar-wrap">
      <svg
        className="eco-radar-svg"
        viewBox="0 0 140 124"
        role="img"
        aria-label={title}
      >
        <polygon className="eco-radar-grid" points={outer.join(" ")} />
        <polygon
          className="eco-radar-grid eco-radar-grid-inner"
          points={scalePolygon(outer, 70, 62, 0.58)}
        />
        {outer.map((point) => (
          <line
            className="eco-radar-axis"
            key={point}
            x1="70"
            y1="62"
            x2={point.split(",")[0]}
            y2={point.split(",")[1]}
          />
        ))}
        <polygon className="eco-radar-shape" points={points.join(" ")} />
        {points.map((point) => (
          <circle
            className="eco-radar-dot"
            key={point}
            cx={point.split(",")[0]}
            cy={point.split(",")[1]}
            r="3"
          />
        ))}
      </svg>
      <div className="eco-radar-labels">
        {values.map((item) => (
          <span key={item.label}>{item.label}</span>
        ))}
      </div>
    </div>
  );
}

function RecommendationList({ insight }: { insight: InsightStats }) {
  const recommendations = insight.recommendedCharts.slice(0, 4);
  const fallback = [
    ...insight.categoryStats.slice(0, 2).map((stat) => ({
      title: `${stat.label} 构成`,
      description: "基于分类字段 TopN 展示组成结构。",
    })),
    ...insight.numericStats.slice(0, 2).map((stat) => ({
      title: `${stat.label} 分布`,
      description: "基于连续数值字段展示分位和直方图。",
    })),
  ];
  const items = recommendations.length ? recommendations : fallback;
  if (!items.length) {
    return <ChartEmpty compact text="暂无可推荐的图表字段" />;
  }
  return (
    <div className="eco-recommend-list">
      {items.map((item) => (
        <span key={item.title}>
          <CheckCircleOutlined style={{ fontSize: 13 }} />
          <b>{item.title}</b>
          <small>{item.description}</small>
        </span>
      ))}
    </div>
  );
}

function FieldDensityMatrix({ insight }: { insight: InsightStats }) {
  const english = usePanelEnglish();
  const rows = [
    ...insight.categoryStats.slice(0, 3).map((stat) => fieldMatrixRow(stat)),
    ...insight.numericStats.slice(0, 3).map((stat) => numericMatrixRow(stat)),
  ].slice(0, 5);
  if (!rows.length) {
    return (
      <ChartEmpty
        text={
          english
            ? "No field statistics for a heat matrix"
            : "暂无字段统计可生成热力矩阵"
        }
      />
    );
  }
  return (
    <div
      className="eco-risk-matrix eco-field-matrix"
      aria-label={
        english ? "Field visualization heat matrix" : "字段可视化热力矩阵"
      }
    >
      <span className="eco-field-matrix-head" />
      {(english
        ? ["Coverage", "Structure", "Dominance", "Chart"]
        : ["覆盖", "结构", "主导", "图表"]
      ).map((label) => (
        <span className="eco-field-matrix-head" key={label}>
          {label}
        </span>
      ))}
      {rows.flatMap((row) => [
        <span
          className="eco-field-matrix-label"
          key={`${row.key}-label`}
          title={row.label}
        >
          {row.label}
        </span>,
        ...row.values.map((value, index) => (
          <i
            key={`${row.key}-${index}`}
            style={{ opacity: 0.18 + clamp(value, 0, 1) * 0.82 }}
            title={`${row.label} ${Math.round(value * 100)}%`}
          />
        )),
      ])}
    </div>
  );
}

function RasterMetadataPanel({
  insight,
  layer,
}: {
  insight: InsightStats;
  layer: LoadedRasterLayer;
}) {
  const english = usePanelEnglish();
  const metadata = layer.rasterMetadata;
  const size = metadata?.size ?? [];
  return (
    <div className="eco-field-profile-card">
      <div className="right-panel-heading">
        <Typography.Text strong>
          {english ? "Raster imagery metadata" : "栅格影像元数据"}
        </Typography.Text>
        <Tag color={layer.renderStatus === "ready" ? "green" : "processing"}>
          {layer.renderStatus ?? "metadata"}
        </Tag>
      </div>
      <div className="eco-raster-meta">
        <span>
          <b>{metadata?.bands?.length ?? insight.profile.fieldCount}</b>
          {english ? "Band count" : "波段数量"}
        </span>
        <span>
          <b>{size.length >= 2 ? `${size[0]} x ${size[1]}` : "-"}</b>
          {english ? "Pixel dimensions" : "像素尺寸"}
        </span>
        <span>
          <b>
            {String(
              metadata?.coordinateSystem ??
                layer.sourceResource.coordinateSystem ??
                "-",
            )}
          </b>
          {english ? "Coordinate system" : "坐标系统"}
        </span>
      </div>
    </div>
  );
}

function FieldProfileList({ insight }: { insight: InsightStats }) {
  const english = usePanelEnglish();
  const fields = insight.fieldNames.slice(0, 10);
  const chartFields = new Set([
    ...insight.categoryStats.map((stat) => stat.label),
    ...insight.numericStats.map((stat) => stat.label),
  ]);
  if (!fields.length) {
    return (
      <ChartEmpty
        text={
          english ? "No field profile to display" : "暂无字段 profile 可展示"
        }
      />
    );
  }
  return (
    <>
      <div className="right-panel-heading">
        <Typography.Text strong>
          {english ? "Field profile" : "字段 profile"}
        </Typography.Text>
        <Typography.Text type="secondary">
          {english
            ? `${fields.length} fields previewed`
            : `${fields.length} 项预览`}
        </Typography.Text>
      </div>
      <div className="eco-field-chip-grid">
        {fields.map((field) => (
          <span
            className={chartFields.has(field) ? "is-chart-ready" : ""}
            key={field}
          >
            {field}
          </span>
        ))}
      </div>
    </>
  );
}

function SpatialQualityStrip({
  insight,
  error,
}: {
  insight: InsightStats;
  error: string | null;
}) {
  const english = usePanelEnglish();
  const spatial = insight.spatialSummary;
  const profile = insight.profile;
  const geometryItems = spatial.geometryTypes.length
    ? spatial.geometryTypes
    : insight.categoryStats.find((stat) => stat.field === "geometryTypes")
        ?.items;
  const coverage = spatialCoverageRatio(insight);
  const issueCounts = issueCountsBySeverity(insight.qualityIssues);
  const topIssues = insight.qualityIssues.slice(0, 3);
  const spatialBounds =
    spatial.bounds.length === 4 ? spatial.bounds : profile.bounds;
  return (
    <div className="eco-spatial-quality">
      <div className="eco-spatial-status">
        <div
          className="eco-spatial-maplet"
          style={
            {
              "--eco-spatial-coverage": `${Math.round(coverage * 100)}%`,
            } as CSSProperties
          }
        >
          <div className="eco-spatial-maplet-canvas">
            <i className="eco-spatial-extent" />
            <i className="eco-spatial-river" />
            <i className="eco-spatial-centroid" />
          </div>
          <div className="eco-spatial-maplet-foot">
            <span>{english ? "Spatial coverage" : "空间覆盖"}</span>
            <strong>{formatPercent(coverage)}</strong>
            <i>
              <em />
            </i>
          </div>
        </div>
        <div className="eco-spatial-facts">
          <span>
            <b>{profile.geometryType || "-"}</b>
            {english ? "Geometry / imagery" : "几何 / 影像"}
          </span>
          <span>
            <b>
              {spatialBounds.length === 4
                ? english
                  ? "Registered"
                  : "已登记"
                : english
                  ? "Missing"
                  : "缺失"}
            </b>
            {english ? "Spatial extent" : "空间范围"}
          </span>
          <span>
            <b>{geometryItems?.[0]?.label ?? sourceText(insight.source)}</b>
            {english ? "Summary source" : "摘要来源"}
          </span>
        </div>
      </div>
      <div className="eco-spatial-bounds">
        <span title={formatBounds(spatialBounds)}>
          {formatBounds(spatialBounds)}
        </span>
        <em>{formatCentroid(spatial.centroid)}</em>
      </div>
      <div className="eco-validation-summary">
        <div className="eco-risk-pills">
          <span className="eco-tone-red">
            <b>{issueCounts.error}</b>
            {english ? "Errors" : "错误"}
          </span>
          <span className="eco-tone-amber">
            <b>{issueCounts.warning}</b>
            {english ? "Warnings" : "警告"}
          </span>
          <span className="eco-tone-green">
            <b>{issueCounts.info}</b>
            {english ? "Notices" : "提示"}
          </span>
        </div>
        <div className="eco-validation-list">
          {error ? (
            <span className="eco-quality-warning">
              <ExclamationCircleOutlined style={{ fontSize: 14 }} />
              <b>{english ? "API error" : "接口异常"}</b>
              <small>{error}</small>
            </span>
          ) : topIssues.length ? (
            topIssues.map((issue) => (
              <span
                className={`eco-quality-${issue.severity}`}
                key={`${issue.code}-${issue.field ?? ""}`}
              >
                {issue.severity === "error" ? (
                  <ExclamationCircleOutlined style={{ fontSize: 14 }} />
                ) : (
                  <CheckCircleOutlined style={{ fontSize: 14 }} />
                )}
                <b>{issue.title}</b>
                <small>{issue.message}</small>
              </span>
            ))
          ) : (
            <span className="eco-quality-info">
              <CheckCircleOutlined style={{ fontSize: 14 }} />
              <b>{english ? "Validation passed" : "校验通过"}</b>
              <small>
                {english
                  ? "No data-import or spatial-quality risks were found in the current summary."
                  : "当前摘要未发现数据导入或空间质量风险。"}
              </small>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function QualityList({ issues }: { issues: QualityIssue[] }) {
  if (!issues.length) {
    return <ChartEmpty text="暂无质量问题" />;
  }
  return (
    <div className="eco-quality-list">
      {issues.slice(0, 6).map((issue) => (
        <span
          className={`eco-quality-${issue.severity}`}
          key={`${issue.code}-${issue.field ?? ""}`}
        >
          {issue.severity === "error" ? (
            <ExclamationCircleOutlined style={{ fontSize: 14 }} />
          ) : (
            <CheckCircleOutlined style={{ fontSize: 14 }} />
          )}
          <b>{issue.title}</b>
          <small>{issue.message}</small>
        </span>
      ))}
    </div>
  );
}

function MonitorFlow({ items }: { items: MonitorItem[] }) {
  return (
    <div className="eco-timeline">
      {items.map((item, index) => (
        <div className="eco-timeline-item" key={item.label}>
          <time>{String(index + 1).padStart(2, "0")}</time>
          <span>
            <strong>{item.label}</strong>
            <small>{item.description}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

function scalePolygon(
  points: string[],
  centerX: number,
  centerY: number,
  scale: number,
) {
  return points
    .map((point) => {
      const coordinates = point.split(",").map(Number);
      const x = coordinates[0];
      const y = coordinates[1];
      if (
        x === undefined ||
        y === undefined ||
        Number.isNaN(x) ||
        Number.isNaN(y)
      ) {
        return `${centerX},${centerY}`;
      }
      return `${centerX + (x - centerX) * scale},${centerY + (y - centerY) * scale}`;
    })
    .join(" ");
}

function buildLocalCategoryStats(layer: LoadedLayer | null): CategoryStat[] {
  if (!layer || layer.layerType !== "vector") {
    return [];
  }
  const features = layer.geojson.features;
  const fields = layer.fields.length
    ? layer.fields.map((field) => field.name)
    : Object.keys((features[0]?.properties ?? {}) as Record<string, unknown>);
  const candidates: CategoryStat[] = [];
  for (const field of fields) {
    const values = features
      .map((feature) => valueForField(feature.properties, field))
      .filter((value) => value !== null);
    if (!values.length) continue;
    const uniqueValues = new Map<string, number>();
    let numericCount = 0;
    for (const value of values) {
      const label = String(value || "未填写");
      uniqueValues.set(label, (uniqueValues.get(label) ?? 0) + 1);
      if (toFiniteNumber(value) !== null) {
        numericCount += 1;
      }
    }
    const uniqueCount = uniqueValues.size;
    if (numericCount / values.length > 0.85 && uniqueCount > 12) {
      continue;
    }
    if (uniqueCount > Math.max(20, features.length * 0.65)) {
      continue;
    }
    const items = [...uniqueValues.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([label, count]) => ({
        label,
        count,
        ratio: ratio(count, features.length),
      }));
    candidates.push({
      field,
      label: fieldLabel(layer, field),
      total: features.length,
      nullCount: features.length - values.length,
      uniqueCount,
      truncated: uniqueCount > items.length,
      items,
    });
  }
  return candidates.slice(0, 6);
}

function buildLocalNumericStats(layer: LoadedLayer | null): NumericStat[] {
  if (!layer || layer.layerType !== "vector") {
    return [];
  }
  const features = layer.geojson.features;
  const fields = layer.fields.length
    ? layer.fields.map((field) => field.name)
    : Object.keys((features[0]?.properties ?? {}) as Record<string, unknown>);
  const stats: NumericStat[] = [];
  for (const field of fields) {
    const rawValues = features
      .map((feature) => valueForField(feature.properties, field))
      .filter((value) => value !== null);
    const values = rawValues
      .map((value) => toFiniteNumber(value))
      .filter((value): value is number => value !== null);
    if (
      !values.length ||
      values.length / Math.max(1, rawValues.length) < 0.85
    ) {
      continue;
    }
    const sorted = [...values].sort((a, b) => a - b);
    stats.push({
      field,
      label: fieldLabel(layer, field),
      count: values.length,
      nullCount: features.length - values.length,
      min: roundNumber(sorted[0]),
      max: roundNumber(sorted[sorted.length - 1]),
      mean: roundNumber(
        values.reduce((sum, value) => sum + value, 0) / values.length,
      ),
      median: roundNumber(quantile(sorted, 0.5)),
      q1: roundNumber(quantile(sorted, 0.25)),
      q3: roundNumber(quantile(sorted, 0.75)),
      histogram: histogramBins(values, 8),
    });
  }
  return stats.slice(0, 8);
}

function buildLocalProfile(
  layer: LoadedLayer | null,
  profile: DataResourceProfile | null,
  resource: ResourceListItem | null,
): ResourceVisualizationSummary["profile"] {
  if (profile) {
    return {
      featureCount: profile.featureCount,
      fieldCount: profile.fields.length,
      geometryType: profile.geometryType,
      bounds: profile.bounds,
    };
  }
  if (layer?.layerType === "vector") {
    return {
      featureCount: layer.geojson.features.length,
      fieldCount: layer.fields.length,
      geometryType: layer.geometryType,
      bounds: parseBounds(layer.sourceResource.spatialExtent),
    };
  }
  if (layer?.layerType === "raster") {
    return {
      featureCount: null,
      fieldCount: layer.rasterMetadata?.bands?.length ?? layer.fields.length,
      geometryType: "Raster",
      bounds: parseBounds(layer.sourceResource.spatialExtent),
    };
  }
  return {
    featureCount: resource?.itemCount ?? null,
    fieldCount: 0,
    geometryType: resource?.dataType ?? "",
    bounds: parseBounds(resource?.spatialExtent ?? ""),
  };
}

function buildLocalSpatialSummary(
  layer: LoadedLayer | null,
  profile: ResourceVisualizationSummary["profile"],
): ResourceVisualizationSummary["spatialSummary"] {
  if (layer?.layerType === "vector") {
    const total = layer.geojson.features.length;
    const geometryCounts = new Map<string, number>();
    let validGeometryCount = 0;
    for (const feature of layer.geojson.features) {
      const type = feature.geometry?.type;
      if (!type) continue;
      validGeometryCount += 1;
      geometryCounts.set(type, (geometryCounts.get(type) ?? 0) + 1);
    }
    const geometryTypes = [...geometryCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => ({
        label,
        count,
        ratio: ratio(count, total),
      }));
    return {
      featureCount: total,
      validGeometryCount,
      nullGeometryCount: Math.max(0, total - validGeometryCount),
      coordinateCoverageRatio: ratio(validGeometryCount, total),
      bounds: profile.bounds,
      geometryTypes,
      centroid: boundsCentroid(profile.bounds),
    };
  }
  return {
    featureCount: profile.featureCount,
    validGeometryCount: null,
    nullGeometryCount: null,
    coordinateCoverageRatio: profile.bounds.length === 4 ? 1 : null,
    bounds: profile.bounds,
    geometryTypes: [],
    centroid: boundsCentroid(profile.bounds),
  };
}

function withQualityNoteIssue(
  issues: QualityIssue[],
  resource: ResourceListItem | null,
): QualityIssue[] {
  const qualityNote = resource?.qualityNote?.trim();
  if (
    !qualityNote ||
    issues.some((issue) => issue.code === "resource_quality_note")
  ) {
    return issues;
  }
  return [
    ...issues,
    {
      code: "resource_quality_note",
      severity: "info",
      title: "数据质量备注",
      message: qualityNote,
      count: 0,
      ratio: 0,
      field: null,
    },
  ];
}

function buildLocalQualityIssues(
  layer: LoadedLayer | null,
  profile: DataResourceProfile | null,
  resource: ResourceListItem | null,
  categories: CategoryStat[],
  numerics: NumericStat[],
): QualityIssue[] {
  const issues: QualityIssue[] = [];
  if (!layer && !profile && !resource) {
    return [];
  }
  if (layer?.layerType === "vector") {
    const total = layer.geojson.features.length;
    const nullGeometry = layer.geojson.features.filter(
      (feature) => !feature.geometry,
    ).length;
    if (nullGeometry > 0) {
      issues.push({
        code: "local_null_geometry",
        severity: "warning",
        title: "空几何记录",
        message: `已加载 GeoJSON 中有 ${nullGeometry} 条记录缺少几何。`,
        count: nullGeometry,
        ratio: ratio(nullGeometry, total),
        field: null,
      });
    }
  }
  if (!categories.length && !numerics.length) {
    issues.push({
      code: "local_limited_fields",
      severity: "info",
      title: "可视化字段较少",
      message: "当前本地数据缺少适合做分类或数值图表的字段。",
      count: 0,
      ratio: 0,
      field: null,
    });
  }
  if (!issues.length) {
    issues.push({
      code: "local_visual_ready",
      severity: "info",
      title: "本地数据可用",
      message: "已基于前端可获得数据生成可视化摘要。",
      count: 0,
      ratio: 0,
      field: null,
    });
  }
  return issues;
}

function defaultMonitorItems(): MonitorItem[] {
  return [
    {
      label: "阈值配置",
      status: "planned",
      description: "按字段、专题和空间范围配置异常阈值。",
    },
    {
      label: "定时扫描",
      status: "planned",
      description: "周期性扫描聚合指标、数据质量和处理状态。",
    },
    {
      label: "异常复核",
      status: "planned",
      description: "对异常记录进行定位、确认、忽略和闭环处置。",
    },
  ];
}

function featurePlanFor(domainType: DataDomainType | null) {
  if (domainType && domainFeaturePlans[domainType]) {
    return domainFeaturePlans[domainType];
  }
  return fallbackFeaturePlan;
}

function bestCategoryStat(stats: CategoryStat[], hints: string[]) {
  return (
    [...stats].sort(
      (a, b) => hintScore(a.label, hints) - hintScore(b.label, hints),
    )[0] ?? null
  );
}

function bestNumericStats(stats: NumericStat[], hints: string[]) {
  return [...stats]
    .sort((a, b) => hintScore(a.label, hints) - hintScore(b.label, hints))
    .slice(0, 6);
}

function hintScore(label: string, hints: string[]) {
  const normalized = label.toLowerCase();
  const index = hints.findIndex((hint) =>
    normalized.includes(hint.toLowerCase()),
  );
  return index === -1 ? 1000 : index;
}

interface PopulationSurveyStats {
  domainType: DataDomainType | null;
  recordTotal: number;
  regionStat: CategoryStat | null;
  countyStat: CategoryStat | null;
  townshipStat: CategoryStat | null;
  plotStat: CategoryStat | null;
  habitatStat: CategoryStat | null;
  transectStat: CategoryStat | null;
  speciesStat: CategoryStat | null;
  distributionStat: CategoryStat | null;
  altitudeStat: NumericStat | null;
  plantCountStat: NumericStat | null;
  actualPlantCountStat: NumericStat | null;
  densityStat: NumericStat | null;
  areaStat: NumericStat | null;
  coverStat: NumericStat | null;
  occurrenceStat: NumericStat | null;
  frequencyStat: NumericStat | null;
  relativeAbundanceStat: NumericStat | null;
  relativeFrequencyStat: NumericStat | null;
  relativeCoverStat: NumericStat | null;
  importanceStat: NumericStat | null;
  bioStats: NumericStat[];
  coordinateCoverage: number;
  portraitMetrics: Array<{
    label: string;
    value: number;
    display: string;
    tone: Tone;
  }>;
  fieldRows: Array<{
    label: string;
    hint: string;
    cells: Array<{
      label: string;
      value: number;
      tone: Tone;
    }>;
  }>;
}

function populationSurveyStatsFor(
  insight: InsightStats,
): PopulationSurveyStats {
  const regionStat = findPreferredCategoryStat(insight.categoryStats, [
    "地区",
    "地州",
    "region",
  ]);
  const countyStat = findPreferredCategoryStat(insight.categoryStats, [
    "市县",
    "县",
    "county",
  ]);
  const townshipStat = findPreferredCategoryStat(insight.categoryStats, [
    "乡镇",
    "town",
  ]);
  const plotStat = findPreferredCategoryStat(insight.categoryStats, [
    "地点（样方）",
    "地点(样方)",
    "样方",
    "地点",
    "plot",
    "site",
  ]);
  const habitatStat = findPreferredCategoryStat(insight.categoryStats, [
    "栖息地类型",
    "栖息地",
    "生境",
    "habitat",
  ]);
  const transectStat = findPreferredCategoryStat(insight.categoryStats, [
    "样线",
    "transect",
  ]);
  const speciesStat = findPreferredCategoryStat(insight.categoryStats, [
    "种",
    "物种",
    "species",
  ]);
  const distributionStat = findPreferredCategoryStat(insight.categoryStats, [
    "分布方式",
    "分布",
    "distribution",
  ]);
  const altitudeStat = findPreferredNumericStat(insight.numericStats, [
    "海拔",
    "altitude",
    "elevation",
  ]);
  const plantCountStat = findPreferredNumericStat(insight.numericStats, [
    "株数（数量）",
    "株数(数量)",
    "株数",
    "数量",
  ]);
  const actualPlantCountStat = findPreferredNumericStat(insight.numericStats, [
    "实际株数",
    "草本按50m2",
  ]);
  const densityStat = findPreferredNumericStat(insight.numericStats, [
    "密度（某物种个体数/样方面积）",
    "密度",
    "density",
  ]);
  const areaStat = findPreferredNumericStat(insight.numericStats, [
    "样方面积",
    "面积",
    "area",
  ]);
  const coverStat = findPreferredNumericStat(insight.numericStats, [
    "盖度（草、灌）/100",
    "盖度",
    "cover",
  ]);
  const occurrenceStat = findPreferredNumericStat(insight.numericStats, [
    "物种出现样方次数",
    "出现样方次数",
  ]);
  const frequencyStat = findPreferredNumericStat(insight.numericStats, [
    "频度(物种出现次数/样方总个数)",
    "频度",
    "frequency",
  ]);
  const relativeAbundanceStat = findPreferredNumericStat(insight.numericStats, [
    "相对多度",
    "相对密度",
    "relative abundance",
  ]);
  const relativeFrequencyStat = findPreferredNumericStat(insight.numericStats, [
    "相对频度",
    "relative frequency",
  ]);
  const relativeCoverStat = findPreferredNumericStat(insight.numericStats, [
    "相对盖度",
    "relative cover",
  ]);
  const importanceStat = findPreferredNumericStat(insight.numericStats, [
    "重要值",
    "importance",
  ]);
  const bioStats = statsByHints(insight.numericStats, [
    "bio",
    "最冷季度",
    "最暖季",
    "年均温",
    "降水",
  ]);
  const recordTotal =
    insight.profile.featureCount ??
    speciesStat?.total ??
    plotStat?.total ??
    densityStat?.count ??
    importanceStat?.count ??
    0;
  const coordinateCoverage = spatialCoverageRatio(insight);
  const speciesRichness = categoryRichness(speciesStat, 40);
  const plotCoverage = averageScore([
    categoryCompleteness(plotStat),
    categoryCompleteness(transectStat),
    coordinateCoverage,
  ]);
  const abundanceStats = [
    plantCountStat,
    actualPlantCountStat,
    densityStat,
    areaStat,
  ].filter((stat): stat is NumericStat => Boolean(stat));
  const abundanceCompleteness = numericGroupCompleteness(abundanceStats);
  const importanceScore = normalizedStatScore(importanceStat);
  const fieldRows = populationSurveyFieldRows({
    actualPlantCountStat,
    altitudeStat,
    areaStat,
    bioStats,
    coordinateCoverage,
    countyStat,
    coverStat,
    densityStat,
    distributionStat,
    frequencyStat,
    habitatStat,
    importanceStat,
    occurrenceStat,
    plantCountStat,
    plotStat,
    regionStat,
    relativeAbundanceStat,
    relativeCoverStat,
    relativeFrequencyStat,
    speciesStat,
    townshipStat,
    transectStat,
  });

  return {
    domainType: insight.domainType,
    recordTotal,
    regionStat,
    countyStat,
    townshipStat,
    plotStat,
    habitatStat,
    transectStat,
    speciesStat,
    distributionStat,
    altitudeStat,
    plantCountStat,
    actualPlantCountStat,
    densityStat,
    areaStat,
    coverStat,
    occurrenceStat,
    frequencyStat,
    relativeAbundanceStat,
    relativeFrequencyStat,
    relativeCoverStat,
    importanceStat,
    bioStats,
    coordinateCoverage,
    portraitMetrics: [
      {
        label: "物种记录",
        value: speciesRichness,
        display: speciesStat
          ? `${formatCompactNumber(speciesStat.uniqueCount)} 种`
          : "-",
        tone: "green",
      },
      {
        label: "样方覆盖",
        value: plotCoverage,
        display: plotStat
          ? `${formatCompactNumber(plotStat.uniqueCount)} 样方`
          : formatPercent(coordinateCoverage),
        tone: "cyan",
      },
      {
        label: "数量密度",
        value: abundanceCompleteness,
        display: densityStat ? formatNumber(densityStat.median) : "-",
        tone: "amber",
      },
      {
        label: "重要值",
        value: importanceScore,
        display: importanceStat ? formatNumber(importanceStat.median) : "-",
        tone: "blue",
      },
    ],
    fieldRows,
  };
}

function populationSurveyFieldRows({
  actualPlantCountStat,
  altitudeStat,
  areaStat,
  bioStats,
  coordinateCoverage,
  countyStat,
  coverStat,
  densityStat,
  distributionStat,
  frequencyStat,
  habitatStat,
  importanceStat,
  occurrenceStat,
  plantCountStat,
  plotStat,
  regionStat,
  relativeAbundanceStat,
  relativeCoverStat,
  relativeFrequencyStat,
  speciesStat,
  townshipStat,
  transectStat,
}: {
  actualPlantCountStat: NumericStat | null;
  altitudeStat: NumericStat | null;
  areaStat: NumericStat | null;
  bioStats: NumericStat[];
  coordinateCoverage: number;
  countyStat: CategoryStat | null;
  coverStat: NumericStat | null;
  densityStat: NumericStat | null;
  distributionStat: CategoryStat | null;
  frequencyStat: NumericStat | null;
  habitatStat: CategoryStat | null;
  importanceStat: NumericStat | null;
  occurrenceStat: NumericStat | null;
  plantCountStat: NumericStat | null;
  plotStat: CategoryStat | null;
  regionStat: CategoryStat | null;
  relativeAbundanceStat: NumericStat | null;
  relativeCoverStat: NumericStat | null;
  relativeFrequencyStat: NumericStat | null;
  speciesStat: CategoryStat | null;
  townshipStat: CategoryStat | null;
  transectStat: CategoryStat | null;
}): PopulationSurveyStats["fieldRows"] {
  const spatialCategories = [
    regionStat,
    countyStat,
    townshipStat,
    plotStat,
    transectStat,
  ].filter((stat): stat is CategoryStat => Boolean(stat));
  const speciesCategories = [speciesStat, habitatStat, distributionStat].filter(
    (stat): stat is CategoryStat => Boolean(stat),
  );
  const abundanceStats = [
    plantCountStat,
    actualPlantCountStat,
    densityStat,
    areaStat,
  ].filter((stat): stat is NumericStat => Boolean(stat));
  const coverFrequencyStats = [
    coverStat,
    occurrenceStat,
    frequencyStat,
    relativeAbundanceStat,
    relativeFrequencyStat,
    relativeCoverStat,
  ].filter((stat): stat is NumericStat => Boolean(stat));
  const climateImportanceStats = [
    importanceStat,
    altitudeStat,
    ...bioStats,
  ].filter((stat): stat is NumericStat => Boolean(stat));
  const spatialCompleteness = Math.max(
    coordinateCoverage,
    averageScore(spatialCategories.map((stat) => categoryCompleteness(stat))),
  );
  const spatialRichness = averageScore(
    spatialCategories.map((stat) => categoryRichness(stat, 12)),
  );
  const spatialBalance = averageScore(
    spatialCategories.map((stat) => categoryBalance(stat)),
  );
  const speciesCompleteness = averageScore(
    speciesCategories.map((stat) => categoryCompleteness(stat)),
  );
  const speciesRichness = averageScore([
    categoryRichness(speciesStat, 40),
    categoryRichness(habitatStat, 8),
    categoryRichness(distributionStat, 8),
  ]);
  const speciesBalance = averageScore(
    speciesCategories.map((stat) => categoryBalance(stat)),
  );
  return [
    {
      label: "空间样方",
      hint: plotStat ? `${plotStat.uniqueCount} 个样方` : "地区层级与坐标",
      cells: [
        populationSurveyCell(
          "完整度",
          spatialCompleteness,
          spatialCompleteness > 0.75 ? "green" : "amber",
        ),
        populationSurveyCell("层级性", spatialRichness, "cyan"),
        populationSurveyCell(
          "均衡度",
          spatialBalance,
          spatialBalance > 0.45 ? "cyan" : "amber",
        ),
        populationSurveyCell(
          "可视化",
          coordinateCoverage > 0 ? 0.95 : 0.58,
          coordinateCoverage > 0 ? "green" : "amber",
        ),
      ],
    },
    {
      label: "生境物种",
      hint: speciesStat ? `${speciesStat.uniqueCount} 个物种` : "物种与生境",
      cells: [
        populationSurveyCell("完整度", speciesCompleteness, "green"),
        populationSurveyCell("丰富度", speciesRichness, "cyan"),
        populationSurveyCell(
          "均衡度",
          speciesBalance,
          speciesBalance > 0.45 ? "cyan" : "amber",
        ),
        populationSurveyCell(
          "可视化",
          speciesStat || habitatStat ? 0.96 : 0,
          speciesStat || habitatStat ? "green" : "red",
        ),
      ],
    },
    {
      label: "数量密度",
      hint: `${abundanceStats.length} 项数量字段`,
      cells: [
        populationSurveyCell(
          "完整度",
          numericGroupCompleteness(abundanceStats),
          "green",
        ),
        populationSurveyCell(
          "梯度性",
          numericGroupRange(abundanceStats),
          "cyan",
        ),
        populationSurveyCell(
          "变异度",
          numericGroupVariation(abundanceStats),
          "amber",
        ),
        populationSurveyCell(
          "可视化",
          abundanceStats.length ? 0.94 : 0,
          abundanceStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "盖度频度",
      hint: `${coverFrequencyStats.length} 项盖度频度`,
      cells: [
        populationSurveyCell(
          "完整度",
          numericGroupCompleteness(coverFrequencyStats),
          "green",
        ),
        populationSurveyCell(
          "梯度性",
          numericGroupRange(coverFrequencyStats),
          "cyan",
        ),
        populationSurveyCell(
          "变异度",
          numericGroupVariation(coverFrequencyStats),
          "amber",
        ),
        populationSurveyCell(
          "可视化",
          coverFrequencyStats.length ? 0.92 : 0,
          coverFrequencyStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "重要值气候",
      hint: importanceStat
        ? `${bioStats.length} 项气候字段`
        : "重要值与bio字段",
      cells: [
        populationSurveyCell(
          "完整度",
          numericGroupCompleteness(climateImportanceStats),
          "green",
        ),
        populationSurveyCell(
          "梯度性",
          numericGroupRange(climateImportanceStats),
          "cyan",
        ),
        populationSurveyCell(
          "变异度",
          numericGroupVariation(climateImportanceStats),
          "amber",
        ),
        populationSurveyCell(
          "可视化",
          importanceStat || bioStats.length ? 0.9 : 0,
          importanceStat || bioStats.length ? "green" : "red",
        ),
      ],
    },
  ];
}

function populationSurveyCell(
  label: string,
  value: number,
  tone: Tone,
): PopulationSurveyStats["fieldRows"][number]["cells"][number] {
  return {
    label,
    value: clamp(value, 0, 1),
    tone,
  };
}

interface CommunityStats {
  plotTotal: number;
  groupStat: CategoryStat | null;
  shannonStat: NumericStat | null;
  simpsonStat: NumericStat | null;
  pielouStat: NumericStat | null;
  richnessStat: NumericStat | null;
  phyloStat: NumericStat | null;
  raoStat: NumericStat | null;
  functionalStats: NumericStat[];
  traitStats: NumericStat[];
  soilStats: NumericStat[];
  climateStats: NumericStat[];
  coverStats: NumericStat[];
  coordinateCoverage: number;
  portraitMetrics: Array<{
    label: string;
    value: number;
    display: string;
    tone: Tone;
  }>;
  fieldRows: Array<{
    label: string;
    hint: string;
    cells: Array<{
      label: string;
      value: number;
      tone: Tone;
    }>;
  }>;
}

function communityStatsFor(insight: InsightStats): CommunityStats {
  const groupStat = findCategoryStat(insight.categoryStats, [
    "样方分组",
    "分组",
    "group",
  ]);
  const shannonStat = findNumericStat(insight.numericStats, [
    "Shannon",
    "香农",
  ]);
  const simpsonStat = findNumericStat(insight.numericStats, ["Simpson"]);
  const pielouStat = findNumericStat(insight.numericStats, [
    "Pielou",
    "均匀度指数",
  ]);
  const richnessStat = findNumericStat(insight.numericStats, [
    "物种丰富度",
    "丰富度",
    "species richness",
  ]);
  const phyloStat = findNumericStat(insight.numericStats, [
    "系统发育多样性",
    "系统发育",
    "phylo",
  ]);
  const raoStat = findNumericStat(insight.numericStats, ["Rao", "二次熵"]);
  const functionalStats = statsByHints(insight.numericStats, [
    "功能丰富度",
    "功能均匀度",
    "功能离散度",
    "功能离散指数",
    "Rao",
  ]);
  const traitStats = statsByHints(insight.numericStats, [
    "群落加权平均",
    "叶片",
    "比叶面积",
    "叶厚",
    "干物质",
  ]);
  const soilStats = statsByHints(insight.numericStats, [
    "土壤",
    "电导率",
    "总盐",
    "酸碱度",
    "含水量",
  ]);
  const climateStats = statsByHints(insight.numericStats, [
    "温度",
    "降水",
    "太阳辐射",
    "蒸散量",
  ]);
  const coverStats = statsByHints(insight.numericStats, [
    "盖度",
    "净初级生产力",
    "生物量",
    "碳储量",
  ]);
  const plotTotal =
    insight.profile.featureCount ??
    groupStat?.total ??
    shannonStat?.count ??
    richnessStat?.count ??
    0;
  const coordinateCoverage = spatialCoverageRatio(insight);
  const alphaDiversity = averageScore([
    normalizedStatScore(shannonStat),
    normalizedStatScore(simpsonStat),
    normalizedStatScore(pielouStat),
    normalizedStatScore(richnessStat),
  ]);
  const functionalStrength = averageScore(
    functionalStats.slice(0, 5).map((stat) => normalizedStatScore(stat)),
  );
  const environmentGradient = averageScore([
    ...soilStats
      .slice(0, 4)
      .map((stat) =>
        numericRangeScore(
          stat,
          Math.max(1, Math.abs((stat.max ?? 0) - (stat.min ?? 0))),
        ),
      ),
    ...climateStats
      .slice(0, 4)
      .map((stat) =>
        numericRangeScore(
          stat,
          Math.max(1, Math.abs((stat.max ?? 0) - (stat.min ?? 0))),
        ),
      ),
  ]);
  const fieldRows = communityFieldRows({
    climateStats,
    coordinateCoverage,
    coverStats,
    functionalStats,
    groupStat,
    phyloStat,
    richnessStat,
    raoStat,
    shannonStat,
    simpsonStat,
    soilStats,
    traitStats,
  });

  return {
    plotTotal,
    groupStat,
    shannonStat,
    simpsonStat,
    pielouStat,
    richnessStat,
    phyloStat,
    raoStat,
    functionalStats,
    traitStats,
    soilStats,
    climateStats,
    coverStats,
    coordinateCoverage,
    portraitMetrics: [
      {
        label: "α多样性",
        value: alphaDiversity,
        display: shannonStat ? formatNumber(shannonStat.median) : "-",
        tone: "green",
      },
      {
        label: "功能性状",
        value: functionalStrength,
        display: `${functionalStats.length} 项`,
        tone: "cyan",
      },
      {
        label: "环境梯度",
        value: environmentGradient,
        display: `${soilStats.length + climateStats.length} 项`,
        tone: "amber",
      },
      {
        label: "空间覆盖",
        value: coordinateCoverage,
        display: formatPercent(coordinateCoverage),
        tone: "green",
      },
    ],
    fieldRows,
  };
}

function communityFieldRows({
  climateStats,
  coordinateCoverage,
  coverStats,
  functionalStats,
  groupStat,
  phyloStat,
  richnessStat,
  raoStat,
  shannonStat,
  simpsonStat,
  soilStats,
  traitStats,
}: {
  climateStats: NumericStat[];
  coordinateCoverage: number;
  coverStats: NumericStat[];
  functionalStats: NumericStat[];
  groupStat: CategoryStat | null;
  phyloStat: NumericStat | null;
  richnessStat: NumericStat | null;
  raoStat: NumericStat | null;
  shannonStat: NumericStat | null;
  simpsonStat: NumericStat | null;
  soilStats: NumericStat[];
  traitStats: NumericStat[];
}): CommunityStats["fieldRows"] {
  const diversityStats = [
    shannonStat,
    simpsonStat,
    richnessStat,
    phyloStat,
    raoStat,
  ].filter((stat): stat is NumericStat => Boolean(stat));
  return [
    {
      label: "多样性指数",
      hint: `${diversityStats.length} 项指数`,
      cells: [
        communityCell(
          "完整度",
          numericGroupCompleteness(diversityStats),
          "green",
        ),
        communityCell("梯度性", numericGroupRange(diversityStats), "cyan"),
        communityCell("变异度", numericGroupVariation(diversityStats), "amber"),
        communityCell(
          "可视化",
          diversityStats.length ? 0.96 : 0,
          diversityStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "功能性状",
      hint: `${functionalStats.length + traitStats.length} 项字段`,
      cells: [
        communityCell(
          "完整度",
          numericGroupCompleteness([...functionalStats, ...traitStats]),
          "green",
        ),
        communityCell("梯度性", numericGroupRange(functionalStats), "cyan"),
        communityCell("变异度", numericGroupVariation(traitStats), "amber"),
        communityCell(
          "可视化",
          functionalStats.length || traitStats.length ? 0.92 : 0,
          functionalStats.length || traitStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "土壤水盐",
      hint: `${soilStats.length} 项环境因子`,
      cells: [
        communityCell("完整度", numericGroupCompleteness(soilStats), "green"),
        communityCell("梯度性", numericGroupRange(soilStats), "cyan"),
        communityCell("变异度", numericGroupVariation(soilStats), "amber"),
        communityCell(
          "可视化",
          soilStats.length ? 0.9 : 0,
          soilStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "气候水分",
      hint: `${climateStats.length} 项气候因子`,
      cells: [
        communityCell(
          "完整度",
          numericGroupCompleteness(climateStats),
          "green",
        ),
        communityCell("梯度性", numericGroupRange(climateStats), "cyan"),
        communityCell("变异度", numericGroupVariation(climateStats), "amber"),
        communityCell(
          "可视化",
          climateStats.length ? 0.9 : 0,
          climateStats.length ? "green" : "red",
        ),
      ],
    },
    {
      label: "样方与生产",
      hint: groupStat ? `${groupStat.uniqueCount} 个分组` : "空间样方",
      cells: [
        communityCell(
          "完整度",
          Math.max(categoryCompleteness(groupStat), coordinateCoverage),
          "green",
        ),
        communityCell(
          "均衡度",
          categoryBalance(groupStat),
          categoryBalance(groupStat) > 0.55 ? "cyan" : "amber",
        ),
        communityCell("生产力", numericGroupRange(coverStats), "cyan"),
        communityCell(
          "可视化",
          groupStat || coverStats.length ? 0.92 : 0,
          groupStat || coverStats.length ? "green" : "red",
        ),
      ],
    },
  ];
}

function communityCell(
  label: string,
  value: number,
  tone: Tone,
): CommunityStats["fieldRows"][number]["cells"][number] {
  return {
    label,
    value: clamp(value, 0, 1),
    tone,
  };
}

function statsByHints(stats: NumericStat[], hints: string[]) {
  return stats.filter((stat) =>
    hints.some((hint) =>
      `${stat.field} ${stat.label}`.toLowerCase().includes(hint.toLowerCase()),
    ),
  );
}

function normalizedStatScore(stat: NumericStat | null) {
  if (!stat) {
    return 0;
  }
  return clamp(normalizedNumericStat(stat) / 100, 0, 1);
}

function numericGroupCompleteness(stats: NumericStat[]) {
  if (!stats.length) {
    return 0;
  }
  return averageScore(stats.map((stat) => numericCompleteness(stat)));
}

function numericGroupRange(stats: NumericStat[]) {
  if (!stats.length) {
    return 0;
  }
  return averageScore(
    stats.map((stat) => {
      if (stat.min === null || stat.max === null || stat.max === stat.min) {
        return 0;
      }
      const center = Math.max(
        Math.abs(stat.mean ?? stat.median ?? stat.max),
        1,
      );
      return clamp(Math.abs(stat.max - stat.min) / center, 0, 1);
    }),
  );
}

function numericGroupVariation(stats: NumericStat[]) {
  if (!stats.length) {
    return 0;
  }
  return averageScore(
    stats.map((stat) => {
      if (
        stat.q1 === null ||
        stat.q3 === null ||
        stat.q1 === undefined ||
        stat.q3 === undefined
      ) {
        return 0;
      }
      const center = Math.max(Math.abs(stat.median ?? stat.mean ?? stat.q3), 1);
      return clamp(Math.abs(stat.q3 - stat.q1) / center, 0, 1);
    }),
  );
}

function communityRidgePolyline(stat: NumericStat) {
  const bins = stat.histogram.length
    ? stat.histogram
    : syntheticHistogram(stat);
  const maxCount = Math.max(...bins.map((bin) => bin.count), 1);
  return bins
    .map((bin, index) => {
      const x = 12 + (index / Math.max(bins.length - 1, 1)) * 216;
      const y = 78 - (bin.count / maxCount) * 48;
      return `${roundNumber(x)},${roundNumber(y)}`;
    })
    .join(" ");
}

function communityRidgePath(stat: NumericStat) {
  const line = communityRidgePolyline(stat);
  return `M12 84 L ${line} L228 84 Z`;
}

function syntheticHistogram(stat: NumericStat) {
  const q1 = stat.q1 ?? stat.min ?? 0;
  const median = stat.median ?? stat.mean ?? q1;
  const q3 = stat.q3 ?? stat.max ?? median;
  return [
    {
      min: stat.min ?? q1,
      max: q1,
      count: Math.max(1, Math.round(stat.count * 0.18)),
    },
    { min: q1, max: median, count: Math.max(1, Math.round(stat.count * 0.32)) },
    { min: median, max: q3, count: Math.max(1, Math.round(stat.count * 0.3)) },
    {
      min: q3,
      max: stat.max ?? q3,
      count: Math.max(1, Math.round(stat.count * 0.2)),
    },
  ];
}

interface IndividualStats {
  recordTotal: number;
  collectorStat: CategoryStat | null;
  regionStat: CategoryStat | null;
  countyStat: CategoryStat | null;
  siteStat: CategoryStat | null;
  speciesStat: CategoryStat | null;
  familyStat: CategoryStat | null;
  genusStat: CategoryStat | null;
  orderCategoryStat: CategoryStat | null;
  orderNumericStat: NumericStat | null;
  altitudeStat: NumericStat | null;
  coordinateCoverage: number;
  taxonomyMetrics: Array<{
    label: string;
    value: number;
    display: string;
    tone: Tone;
  }>;
  fieldRows: Array<{
    label: string;
    hint: string;
    cells: Array<{
      label: string;
      value: number;
      tone: Tone;
    }>;
  }>;
}

function individualStatsFor(insight: InsightStats): IndividualStats {
  const collectorStat = findCategoryStat(insight.categoryStats, [
    "采集单位",
    "单位",
    "collector",
  ]);
  const regionStat = findCategoryStat(insight.categoryStats, [
    "地州",
    "地区",
    "region",
  ]);
  const countyStat = findCategoryStat(insight.categoryStats, [
    "unnamed: 3",
    "县",
    "county",
  ]);
  const siteStat = findCategoryStat(insight.categoryStats, [
    "地点",
    "采集地点",
    "site",
  ]);
  const speciesStat = findCategoryStat(insight.categoryStats, [
    "物种中文名",
    "物种",
    "种名",
    "species",
  ]);
  const familyStat = findCategoryStat(insight.categoryStats, [
    "科中文名",
    "科名",
    "family",
  ]);
  const genusStat = findCategoryStat(insight.categoryStats, [
    "属中文名",
    "属名",
    "genus",
  ]);
  const orderCategoryStat = findCategoryStat(insight.categoryStats, [
    "科排序",
    "family order",
  ]);
  const orderNumericStat = findNumericStat(insight.numericStats, [
    "科排序",
    "family order",
  ]);
  const altitudeStat = findNumericStat(insight.numericStats, [
    "海拔",
    "altitude",
    "elevation",
  ]);
  const recordTotal =
    insight.profile.featureCount ??
    speciesStat?.total ??
    familyStat?.total ??
    collectorStat?.total ??
    orderNumericStat?.count ??
    altitudeStat?.count ??
    0;
  const coordinateCoverage = spatialCoverageRatio(insight);
  const familyRichness = categoryRichness(familyStat, 8);
  const genusRichness = categoryRichness(genusStat, 12);
  const speciesRichness = categoryRichness(speciesStat, 12);
  const altitudeCompleteness = numericCompleteness(altitudeStat);
  const fieldRows = individualFieldRows({
    altitudeStat,
    collectorStat,
    coordinateCoverage,
    familyRichness,
    familyStat,
    genusRichness,
    genusStat,
    orderCategoryStat,
    orderNumericStat,
    regionStat,
    countyStat,
    siteStat,
    speciesRichness,
    speciesStat,
  });

  return {
    recordTotal,
    collectorStat,
    regionStat,
    countyStat,
    siteStat,
    speciesStat,
    familyStat,
    genusStat,
    orderCategoryStat,
    orderNumericStat,
    altitudeStat,
    coordinateCoverage,
    taxonomyMetrics: [
      {
        label: "科类覆盖",
        value: familyRichness,
        display: familyStat
          ? `${formatCompactNumber(familyStat.uniqueCount)} 科`
          : "-",
        tone: "green",
      },
      {
        label: "属级覆盖",
        value: genusRichness,
        display: genusStat
          ? `${formatCompactNumber(genusStat.uniqueCount)} 属`
          : "-",
        tone: "cyan",
      },
      {
        label: "物种覆盖",
        value: speciesRichness,
        display: speciesStat
          ? `${formatCompactNumber(speciesStat.uniqueCount)} 种`
          : "-",
        tone: "amber",
      },
      {
        label: "海拔记录",
        value: altitudeCompleteness,
        display: altitudeStat ? formatPercent(altitudeCompleteness) : "-",
        tone: altitudeCompleteness > 0.85 ? "green" : "amber",
      },
    ],
    fieldRows,
  };
}

function individualFieldRows({
  altitudeStat,
  collectorStat,
  coordinateCoverage,
  familyRichness,
  familyStat,
  genusRichness,
  genusStat,
  orderCategoryStat,
  orderNumericStat,
  regionStat,
  countyStat,
  siteStat,
  speciesRichness,
  speciesStat,
}: {
  altitudeStat: NumericStat | null;
  collectorStat: CategoryStat | null;
  coordinateCoverage: number;
  familyRichness: number;
  familyStat: CategoryStat | null;
  genusRichness: number;
  genusStat: CategoryStat | null;
  orderCategoryStat: CategoryStat | null;
  orderNumericStat: NumericStat | null;
  regionStat: CategoryStat | null;
  countyStat: CategoryStat | null;
  siteStat: CategoryStat | null;
  speciesRichness: number;
  speciesStat: CategoryStat | null;
}): IndividualStats["fieldRows"] {
  const taxonomyCompleteness = averageScore([
    categoryCompleteness(familyStat),
    categoryCompleteness(genusStat),
    categoryCompleteness(speciesStat),
  ]);
  const taxonomyRichness = averageScore([
    familyRichness,
    genusRichness,
    speciesRichness,
  ]);
  const taxonomyBalance = averageScore([
    categoryBalance(familyStat),
    categoryBalance(genusStat),
    categoryBalance(speciesStat),
  ]);
  const regionCompleteness = averageScore([
    categoryCompleteness(regionStat),
    categoryCompleteness(countyStat),
    categoryCompleteness(siteStat),
  ]);
  const regionRichness = averageScore([
    categoryRichness(regionStat, 8),
    categoryRichness(countyStat, 8),
    categoryRichness(siteStat, 12),
  ]);
  const regionBalance = averageScore([
    categoryBalance(regionStat),
    categoryBalance(countyStat),
    categoryBalance(siteStat),
  ]);
  const orderCompleteness =
    categoryCompleteness(orderCategoryStat) ||
    numericCompleteness(orderNumericStat);
  const orderSpread = numericRangeScore(orderNumericStat, 120);
  const altitudeCompleteness = numericCompleteness(altitudeStat);
  const altitudeSpread = numericRangeScore(altitudeStat, 3000);
  return [
    {
      label: "采集来源",
      hint: collectorStat ? `${collectorStat.uniqueCount} 类单位` : "待统计",
      cells: [
        individualCell("完整度", categoryCompleteness(collectorStat), "green"),
        individualCell("多样度", categoryRichness(collectorStat, 8), "cyan"),
        individualCell(
          "均衡度",
          categoryBalance(collectorStat),
          categoryBalance(collectorStat) > 0.45 ? "cyan" : "amber",
        ),
        individualCell(
          "可视化",
          collectorStat ? 0.86 : 0,
          collectorStat ? "green" : "red",
        ),
      ],
    },
    {
      label: "空间位置",
      hint: siteStat ? `${siteStat.uniqueCount} 个地点` : "经纬度采集",
      cells: [
        individualCell(
          "完整度",
          Math.max(regionCompleteness, coordinateCoverage),
          "green",
        ),
        individualCell("多样度", regionRichness, "cyan"),
        individualCell(
          "均衡度",
          regionBalance,
          regionBalance > 0.45 ? "cyan" : "amber",
        ),
        individualCell(
          "可视化",
          coordinateCoverage > 0 ? 0.94 : 0.42,
          coordinateCoverage > 0 ? "green" : "amber",
        ),
      ],
    },
    {
      label: "分类谱系",
      hint: speciesStat ? `${speciesStat.uniqueCount} 个物种` : "待统计",
      cells: [
        individualCell("完整度", taxonomyCompleteness, "green"),
        individualCell("多样度", taxonomyRichness, "cyan"),
        individualCell(
          "均衡度",
          taxonomyBalance,
          taxonomyBalance > 0.45 ? "cyan" : "amber",
        ),
        individualCell(
          "可视化",
          speciesStat || familyStat ? 0.96 : 0,
          speciesStat || familyStat ? "green" : "red",
        ),
      ],
    },
    {
      label: "科排序",
      hint: orderCategoryStat
        ? `${orderCategoryStat.uniqueCount} 类编码`
        : "序列字段",
      cells: [
        individualCell("完整度", orderCompleteness, "green"),
        individualCell("跨度", orderSpread, "cyan"),
        individualCell(
          "均衡度",
          categoryBalance(orderCategoryStat),
          categoryBalance(orderCategoryStat) > 0.45 ? "cyan" : "amber",
        ),
        individualCell(
          "可视化",
          orderCategoryStat || orderNumericStat ? 0.92 : 0,
          orderCategoryStat || orderNumericStat ? "green" : "red",
        ),
      ],
    },
    {
      label: "海拔记录",
      hint: altitudeStat
        ? `${formatCompactNumber(altitudeStat.nullCount)} 条缺失`
        : "待统计",
      cells: [
        individualCell(
          "完整度",
          altitudeCompleteness,
          altitudeCompleteness > 0.8 ? "green" : "amber",
        ),
        individualCell(
          "梯度性",
          altitudeSpread,
          altitudeSpread > 0.45 ? "cyan" : "amber",
        ),
        individualCell(
          "稳定性",
          clamp(
            1 -
              ratio(
                altitudeStat?.nullCount ?? 0,
                (altitudeStat?.count ?? 0) + (altitudeStat?.nullCount ?? 0),
              ),
            0,
            1,
          ),
          altitudeCompleteness > 0.8 ? "green" : "amber",
        ),
        individualCell(
          "可视化",
          altitudeStat ? 0.88 : 0,
          altitudeStat ? "green" : "red",
        ),
      ],
    },
  ];
}

function individualCell(
  label: string,
  value: number,
  tone: Tone,
): IndividualStats["fieldRows"][number]["cells"][number] {
  return {
    label,
    value: clamp(value, 0, 1),
    tone,
  };
}

function categoryRichness(stat: CategoryStat | null, reference = 10) {
  if (!stat) {
    return 0;
  }
  return clamp(
    stat.uniqueCount / Math.max(1, Math.min(stat.total, reference)),
    0,
    1,
  );
}

function categoryBalance(stat: CategoryStat | null) {
  if (!stat || !stat.total) {
    return 0;
  }
  return clamp(1 - (stat.items[0]?.ratio ?? 0), 0, 1);
}

function numericRangeScore(stat: NumericStat | null, referenceRange: number) {
  if (
    !stat ||
    stat.min === null ||
    stat.max === null ||
    stat.max === stat.min
  ) {
    return 0;
  }
  return clamp((stat.max - stat.min) / Math.max(1, referenceRange), 0, 1);
}

function averageScore(values: number[]) {
  const validValues = values.filter((value) => Number.isFinite(value));
  if (!validValues.length) {
    return 0;
  }
  return clamp(
    validValues.reduce((sum, value) => sum + value, 0) / validValues.length,
    0,
    1,
  );
}

function minimumCategoryNumber(stat: CategoryStat | null) {
  const values = categoryNumberValues(stat);
  return values.length ? Math.min(...values) : null;
}

function maximumCategoryNumber(stat: CategoryStat | null) {
  const values = categoryNumberValues(stat);
  return values.length ? Math.max(...values) : null;
}

function categoryNumberValues(stat: CategoryStat | null) {
  if (!stat) {
    return [];
  }
  return stat.items
    .map((item) => toFiniteNumber(item.label))
    .filter((value): value is number => value !== null);
}

interface GermplasmStats {
  sampleTotal: number;
  locationStat: CategoryStat | null;
  sex: {
    stat: CategoryStat | null;
    female: number;
    male: number;
    pending: number;
    total: number;
    balance: number;
    validRatio: number;
  };
  altitudeStat: NumericStat | null;
  coordinateCoverage: number;
  fingerprintMetrics: Array<{
    label: string;
    value: number;
    display: string;
    tone: Tone;
  }>;
  healthRows: Array<{
    label: string;
    hint: string;
    cells: Array<{
      label: string;
      value: number;
      tone: Tone;
    }>;
  }>;
}

function germplasmStatsFor(insight: InsightStats): GermplasmStats {
  const locationStat = findCategoryStat(insight.categoryStats, [
    "采集地点",
    "地点",
    "来源",
    "location",
    "site",
  ]);
  const sexStat = findCategoryStat(insight.categoryStats, [
    "性别",
    "雌",
    "雄",
    "sex",
  ]);
  const altitudeStat = findNumericStat(insight.numericStats, [
    "海拔",
    "altitude",
    "elevation",
  ]);
  const sampleTotal =
    insight.profile.featureCount ??
    locationStat?.total ??
    sexStat?.total ??
    altitudeStat?.count ??
    0;
  const sex = germplasmSexFor(sexStat);
  const coordinateCoverage = spatialCoverageRatio(insight);
  const altitudeCompleteness = numericCompleteness(altitudeStat);
  const duplicateIssue = insight.qualityIssues.find(
    (issue) =>
      `${issue.code} ${issue.title} ${issue.message}`
        .toLowerCase()
        .includes("duplicate") ||
      `${issue.title} ${issue.message}`.includes("重复"),
  );
  const sampleIdentityScore = duplicateIssue?.ratio
    ? clamp(1 - duplicateIssue.ratio, 0, 1)
    : sampleTotal > 0
      ? 1
      : 0;
  const locationRichness = locationStat
    ? clamp(
        locationStat.uniqueCount / Math.min(Math.max(sampleTotal, 1), 60),
        0,
        1,
      )
    : 0;
  const locationConcentration = locationStat?.items[0]?.ratio ?? 0;
  const healthRows = germplasmHealthRows({
    altitudeCompleteness,
    altitudeStat,
    coordinateCoverage,
    duplicateIssue: duplicateIssue ?? null,
    locationConcentration,
    locationRichness,
    locationStat,
    sampleIdentityScore,
    sampleTotal,
    sex,
  });

  return {
    sampleTotal,
    locationStat,
    sex,
    altitudeStat,
    coordinateCoverage,
    fingerprintMetrics: [
      {
        label: "样本编号",
        value: sampleIdentityScore,
        display: duplicateIssue ? "有重复" : "唯一",
        tone: duplicateIssue ? "amber" : "green",
      },
      {
        label: "采集地点",
        value: locationRichness,
        display: locationStat
          ? `${formatCompactNumber(locationStat.uniqueCount)} 地`
          : "-",
        tone: "cyan",
      },
      {
        label: "性别结构",
        value: sex.validRatio,
        display: formatPercent(sex.validRatio),
        tone: sex.pending > 0 ? "amber" : "green",
      },
      {
        label: "海拔记录",
        value: altitudeCompleteness,
        display: formatPercent(altitudeCompleteness),
        tone: altitudeCompleteness > 0.95 ? "green" : "amber",
      },
    ],
    healthRows,
  };
}

function findCategoryStat(stats: CategoryStat[], hints: string[]) {
  return (
    stats.find((stat) =>
      hints.some((hint) =>
        `${stat.field} ${stat.label}`
          .toLowerCase()
          .includes(hint.toLowerCase()),
      ),
    ) ?? null
  );
}

function findNumericStat(stats: NumericStat[], hints: string[]) {
  return (
    stats.find((stat) =>
      hints.some((hint) =>
        `${stat.field} ${stat.label}`
          .toLowerCase()
          .includes(hint.toLowerCase()),
      ),
    ) ?? null
  );
}

function findPreferredCategoryStat(stats: CategoryStat[], hints: string[]) {
  return findPreferredStat(stats, hints);
}

function findPreferredNumericStat(stats: NumericStat[], hints: string[]) {
  return findPreferredStat(stats, hints);
}

function findPreferredStat<T extends { field: string; label: string }>(
  stats: T[],
  hints: string[],
) {
  const normalized = stats.map((stat) => ({
    stat,
    field: normalizeStatLabel(stat.field),
    label: normalizeStatLabel(stat.label),
  }));
  const normalizedHints = hints.map((hint) => normalizeStatLabel(hint));
  for (const hint of normalizedHints) {
    const exact = normalized.find(
      (item) => item.field === hint || item.label === hint,
    );
    if (exact) {
      return exact.stat;
    }
  }
  for (const hint of normalizedHints) {
    const startsWith = normalized.find(
      (item) => item.field.startsWith(hint) || item.label.startsWith(hint),
    );
    if (startsWith) {
      return startsWith.stat;
    }
  }
  for (const hint of normalizedHints) {
    const includes = normalized.find(
      (item) => item.field.includes(hint) || item.label.includes(hint),
    );
    if (includes) {
      return includes.stat;
    }
  }
  return null;
}

function normalizeStatLabel(value: string) {
  return value
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[()（）]/g, "");
}

function germplasmSexFor(stat: CategoryStat | null): GermplasmStats["sex"] {
  if (!stat) {
    return {
      stat: null,
      female: 0,
      male: 0,
      pending: 0,
      total: 0,
      balance: 0,
      validRatio: 0,
    };
  }
  let female = 0;
  let male = 0;
  let pending = stat.nullCount;
  for (const item of stat.items) {
    const label = item.label.trim();
    if (label === "雌株" || label === "雌") {
      female += item.count;
    } else if (label === "雄株" || label === "雄") {
      male += item.count;
    } else {
      pending += item.count;
    }
  }
  pending = Math.max(pending, stat.total - female - male);
  const valid = female + male;
  return {
    stat,
    female,
    male,
    pending,
    total: stat.total,
    balance: valid > 0 ? clamp(1 - Math.abs(female - male) / valid, 0, 1) : 0,
    validRatio: ratio(valid, stat.total),
  };
}

function numericCompleteness(stat: NumericStat | null) {
  if (!stat) {
    return 0;
  }
  return ratio(stat.count, stat.count + stat.nullCount);
}

function germplasmHealthRows({
  altitudeCompleteness,
  altitudeStat,
  coordinateCoverage,
  duplicateIssue,
  locationConcentration,
  locationRichness,
  locationStat,
  sampleIdentityScore,
  sampleTotal,
  sex,
}: {
  altitudeCompleteness: number;
  altitudeStat: NumericStat | null;
  coordinateCoverage: number;
  duplicateIssue: QualityIssue | null;
  locationConcentration: number;
  locationRichness: number;
  locationStat: CategoryStat | null;
  sampleIdentityScore: number;
  sampleTotal: number;
  sex: GermplasmStats["sex"];
}): GermplasmStats["healthRows"] {
  const sampleCompleteness = sampleTotal > 0 ? 1 : 0;
  const locationCompleteness = categoryCompleteness(locationStat);
  const sexCompleteness = categoryCompleteness(sex.stat);
  const locationStructure = clamp(1 - locationConcentration, 0, 1);
  const altitudeSpread =
    altitudeStat?.min !== null &&
    altitudeStat?.min !== undefined &&
    altitudeStat?.max !== null &&
    altitudeStat?.max !== undefined &&
    altitudeStat.max !== altitudeStat.min
      ? 1
      : 0;
  return [
    {
      label: "DNA编号",
      hint: duplicateIssue ? "有重复风险" : "索引稳定",
      cells: [
        healthCell("完整度", sampleCompleteness, "green"),
        healthCell(
          "标准化",
          sampleIdentityScore,
          duplicateIssue ? "amber" : "green",
        ),
        healthCell("区分度", 0.48, "cyan"),
        healthCell("可视化", 0.62, "amber"),
      ],
    },
    {
      label: "采集地点",
      hint: locationStat ? `${locationStat.uniqueCount} 类地点` : "待统计",
      cells: [
        healthCell("完整度", locationCompleteness, "green"),
        healthCell(
          "均衡性",
          locationStructure,
          locationStructure > 0.5 ? "cyan" : "amber",
        ),
        healthCell("丰富度", locationRichness, "cyan"),
        healthCell("可视化", 0.92, "green"),
      ],
    },
    {
      label: "性别",
      hint: sex.pending > 0 ? `${sex.pending} 条待清洗` : "标签清晰",
      cells: [
        healthCell("完整度", sexCompleteness, "green"),
        healthCell(
          "标准化",
          sex.validRatio,
          sex.pending > 0 ? "amber" : "green",
        ),
        healthCell(
          "均衡性",
          sex.balance,
          sex.balance > 0.65 ? "cyan" : "amber",
        ),
        healthCell("可视化", 0.9, "green"),
      ],
    },
    {
      label: "经纬度",
      hint: "空间采集",
      cells: [
        healthCell("完整度", coordinateCoverage, "green"),
        healthCell(
          "标准化",
          coordinateCoverage,
          coordinateCoverage > 0.95 ? "green" : "amber",
        ),
        healthCell("空间度", 0.86, "cyan"),
        healthCell("可视化", 0.94, "green"),
      ],
    },
    {
      label: "海拔",
      hint: altitudeStat ? "梯度连续" : "待统计",
      cells: [
        healthCell(
          "完整度",
          altitudeCompleteness,
          altitudeCompleteness > 0.95 ? "green" : "amber",
        ),
        healthCell(
          "标准化",
          altitudeCompleteness,
          altitudeCompleteness > 0.95 ? "green" : "amber",
        ),
        healthCell(
          "梯度性",
          altitudeSpread,
          altitudeSpread > 0 ? "cyan" : "amber",
        ),
        healthCell(
          "可视化",
          altitudeStat ? 0.9 : 0,
          altitudeStat ? "green" : "red",
        ),
      ],
    },
  ];
}

function categoryCompleteness(stat: CategoryStat | null) {
  if (!stat) {
    return 0;
  }
  return ratio(stat.total - stat.nullCount, stat.total);
}

function healthCell(
  label: string,
  value: number,
  tone: Tone,
): GermplasmStats["healthRows"][number]["cells"][number] {
  return {
    label,
    value: clamp(value, 0, 1),
    tone,
  };
}

function assetScaleFor(insight: InsightStats) {
  const featureCount = insight.profile.featureCount;
  if (featureCount !== null && featureCount !== undefined) {
    return {
      raw: featureCount,
      value: formatCompactNumber(featureCount),
      label:
        insight.profile.geometryType === "Raster" ? "像元估算" : "要素记录",
    };
  }
  const numericCount = insight.numericStats.find(
    (stat) => stat.count > 0,
  )?.count;
  if (numericCount) {
    return {
      raw: numericCount,
      value: formatCompactNumber(numericCount),
      label: "像元估算",
    };
  }
  const categoryTotal = insight.categoryStats.find(
    (stat) => stat.total > 0,
  )?.total;
  if (categoryTotal) {
    return {
      raw: categoryTotal,
      value: formatCompactNumber(categoryTotal),
      label: "统计记录",
    };
  }
  return {
    raw: insight.profile.fieldCount,
    value: formatCompactNumber(insight.profile.fieldCount),
    label: "字段数量",
  };
}

function spatialCoverageRatio(insight: InsightStats) {
  const coverage = insight.spatialSummary.coordinateCoverageRatio;
  if (
    coverage !== null &&
    coverage !== undefined &&
    Number.isFinite(coverage)
  ) {
    return clamp(coverage, 0, 1);
  }
  const featureCount = insight.spatialSummary.featureCount;
  const validGeometryCount = insight.spatialSummary.validGeometryCount;
  if (
    featureCount !== null &&
    featureCount !== undefined &&
    validGeometryCount !== null &&
    validGeometryCount !== undefined
  ) {
    return ratio(validGeometryCount, featureCount);
  }
  return insight.spatialSummary.bounds.length === 4 ||
    insight.profile.bounds.length === 4
    ? 1
    : 0;
}

function fieldStructureSegments(
  categoryCount: number,
  numericCount: number,
  fieldTotal: number,
) {
  const chartFieldCount = categoryCount + numericCount;
  const denominator = Math.max(fieldTotal, chartFieldCount, 1);
  return [
    {
      label: "分类字段",
      tone: "green" as Tone,
      value: categoryCount / denominator,
    },
    {
      label: "数值字段",
      tone: "cyan" as Tone,
      value: numericCount / denominator,
    },
    {
      label: "其他字段",
      tone: "amber" as Tone,
      value: Math.max(0, fieldTotal - chartFieldCount) / denominator,
    },
  ];
}

function riskSegments(counts: ReturnType<typeof issueCountsBySeverity>) {
  const total = counts.error + counts.warning + counts.info;
  if (!total) {
    return [{ label: "可用", tone: "green" as Tone, value: 1 }];
  }
  return [
    { label: "错误", tone: "red" as Tone, value: counts.error / total },
    { label: "警告", tone: "amber" as Tone, value: counts.warning / total },
    { label: "提示", tone: "green" as Tone, value: counts.info / total },
  ];
}

function categoryDisplayItems(stat: CategoryStat) {
  const visibleItems = stat.items.slice(0, 5);
  const visibleCount = visibleItems.reduce((sum, item) => sum + item.count, 0);
  const restCount = Math.max(0, stat.total - visibleCount);
  if (
    restCount > 0 &&
    (stat.truncated ||
      stat.nullCount > 0 ||
      stat.items.length > visibleItems.length)
  ) {
    return [
      ...visibleItems,
      {
        label: "其他/未列出",
        count: restCount,
        ratio: ratio(restCount, stat.total),
      },
    ];
  }
  return visibleItems;
}

function densityPointsFromHistogram(
  histogram: NumericStat["histogram"],
  maxCount: number,
) {
  return histogram.map((bin, index) => ({
    x: (index / Math.max(histogram.length - 1, 1)) * 100,
    y: 92 - (bin.count / maxCount) * 72,
  }));
}

function qualityReadinessScore(issues: QualityIssue[], insight: InsightStats) {
  const penalty = issues.reduce((total, issue) => {
    if (issue.severity === "error") return total + 24;
    if (issue.severity === "warning") return total + 12;
    return total + 3;
  }, 0);
  const fieldBonus = Math.min(
    18,
    (insight.categoryStats.length + insight.numericStats.length) * 3,
  );
  return clamp(Math.round(76 + fieldBonus - penalty), 12, 99);
}

function issueCountsBySeverity(issues: QualityIssue[]) {
  return {
    info: issues.filter((issue) => issue.severity === "info").length,
    warning: issues.filter((issue) => issue.severity === "warning").length,
    error: issues.filter((issue) => issue.severity === "error").length,
  };
}

function fieldMatrixRow(stat: CategoryStat) {
  return {
    key: `category-${stat.field}`,
    label: shortLabel(stat.label),
    values: [
      ratio(stat.total - stat.nullCount, stat.total),
      clamp(stat.uniqueCount / Math.max(1, stat.total), 0, 1),
      stat.items[0]?.ratio ?? 0,
      clamp(stat.items.length / 8, 0, 1),
    ],
  };
}

function numericMatrixRow(stat: NumericStat) {
  const total = stat.count + stat.nullCount;
  return {
    key: `numeric-${stat.field}`,
    label: shortLabel(stat.label),
    values: [
      ratio(stat.count, total),
      stat.min !== null && stat.max !== null && stat.max !== stat.min ? 1 : 0,
      normalizedNumericStat(stat) / 100,
      clamp(stat.histogram.length / 8, 0, 1),
    ],
  };
}

function normalizedNumericStat(stat: NumericStat) {
  if (stat.min === null || stat.max === null || stat.max === stat.min) {
    return 50;
  }
  return clamp(
    Math.round(
      (((stat.mean ?? stat.median ?? stat.min) - stat.min) /
        (stat.max - stat.min)) *
        100,
    ),
    8,
    96,
  );
}

function valueForField(
  properties: Record<string, unknown> | null | undefined,
  field: string,
) {
  if (!properties || !(field in properties)) {
    return null;
  }
  const value = properties[field];
  if (value === undefined || value === null || value === "") {
    return null;
  }
  return value;
}

function fieldLabel(layer: LoadedLayer, field: string) {
  return layer.fields.find((item) => item.name === field)?.description || field;
}

function toFiniteNumber(value: unknown) {
  const number =
    typeof value === "number" ? value : Number(String(value).trim());
  return Number.isFinite(number) ? number : null;
}

function histogramBins(values: number[], bins: number) {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    return [
      {
        min: roundNumber(min) ?? min,
        max: roundNumber(max) ?? max,
        count: values.length,
        label: formatNumber(min),
      },
    ];
  }
  const step = (max - min) / bins;
  return Array.from({ length: bins }, (_, index) => {
    const low = min + step * index;
    const high = index === bins - 1 ? max : low + step;
    const count = values.filter((value) =>
      index === bins - 1
        ? value >= low && value <= high
        : value >= low && value < high,
    ).length;
    return {
      min: roundNumber(low) ?? low,
      max: roundNumber(high) ?? high,
      count,
      label: `${formatNumber(low)}-${formatNumber(high)}`,
    };
  });
}

function quantile(sortedValues: number[], q: number) {
  if (!sortedValues.length) return null;
  const position = (sortedValues.length - 1) * q;
  const base = Math.floor(position);
  const rest = position - base;
  const first = sortedValues[0];
  if (first === undefined) {
    return null;
  }
  const current = sortedValues[base] ?? first;
  const next = sortedValues[base + 1];
  return next === undefined ? current : current + rest * (next - current);
}

function percentPosition(value: number, min: number, range: number) {
  return clamp(((value - min) / range) * 100, 0, 100);
}

function ratio(count: number, total: number) {
  return total > 0 ? count / total : 0;
}

function roundNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return null;
  }
  return Math.round(value * 1000) / 1000;
}

function parseBounds(text: string) {
  const values = text
    .split(",")
    .map((item) => Number(item.trim()))
    .filter(Number.isFinite);
  return values.length === 4 ? values : [];
}

function boundsCentroid(bounds: number[]): [number, number] | null {
  if (bounds.length !== 4) {
    return null;
  }
  const minLng = bounds[0];
  const minLat = bounds[1];
  const maxLng = bounds[2];
  const maxLat = bounds[3];
  if (
    minLng === undefined ||
    minLat === undefined ||
    maxLng === undefined ||
    maxLat === undefined
  ) {
    return null;
  }
  return [
    roundNumber((minLng + maxLng) / 2) ?? 0,
    roundNumber((minLat + maxLat) / 2) ?? 0,
  ];
}

function sparkValuesFromCounts(values: number[]) {
  const usable = values.filter((value) => Number.isFinite(value));
  if (usable.length >= 3) {
    return usable.slice(0, 8);
  }
  const base = usable[0] ?? 1;
  return [base * 0.45, base * 0.65, base * 0.52, base * 0.82, base];
}

function formatPoints(
  values: readonly number[],
  width: number,
  height: number,
  fixedMin?: number,
  fixedMax?: number,
) {
  if (!values.length) {
    return "";
  }
  const min = fixedMin ?? Math.min(...values);
  const max = fixedMax ?? Math.max(...values);
  const range = Math.max(max - min, 1);
  return values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * (height - 12) - 6;
      return `${x},${y}`;
    })
    .join(" ");
}

function formatCompactNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return String(Math.round(value));
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) >= 1000) {
    return formatCompactNumber(value);
  }
  if (Math.abs(value) < 1 && value !== 0) {
    return value.toFixed(3);
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}

function formatBounds(bounds: number[]) {
  if (bounds.length !== 4) {
    return "空间范围待登记";
  }
  return `${formatNumber(bounds[0])}, ${formatNumber(bounds[1])} ~ ${formatNumber(bounds[2])}, ${formatNumber(bounds[3])}`;
}

function formatCentroid(centroid: number[] | null | undefined) {
  if (!centroid || centroid.length < 2) {
    return "中心点待计算";
  }
  return `中心 ${formatNumber(centroid[0])}, ${formatNumber(centroid[1])}`;
}

function shortLabel(label: string) {
  return label.length > 6 ? `${label.slice(0, 6)}` : label;
}

function sourceText(source: string) {
  const labels: Record<string, string> = {
    backend_aggregate: "后端聚合",
    raster_metadata: "栅格元数据",
    profile_only: "资源 profile",
    frontend_loaded_layer: "已加载图层",
    frontend_profile: "本地 profile",
  };
  return labels[source] ?? source;
}
