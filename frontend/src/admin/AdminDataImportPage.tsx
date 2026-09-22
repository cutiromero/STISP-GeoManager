import { UploadProjectField } from "../projects/UploadProjectField";
import { useProjectContext } from "../projects/ProjectContext";
import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { ProCard } from "@ant-design/pro-components";
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Descriptions,
  Form,
  Input,
  Modal,
  Progress,
  Radio,
  Result,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAppContext } from "../contexts/AppContext";
import { localText, useEnglishLanguage } from "../i18n/useEnglishLanguage";
import { applyPlatformDocumentTitle } from "../config/platformBrand";
import type {
  AdminDataResourceAccessGroup,
  DataDomainType,
  DataSchemaSummary,
  ImportCommitPayload,
  ImportCommitResult,
  ImportCoordinateStats,
  ImportDuplicateTarget,
  ImportPreview,
  RasterImportCommitPayload,
  RasterImportPreview,
  RasterJob,
  ImportValidatePayload,
  ImportValidationIssue,
  VectorImportCommitResult,
} from "../types";
import {
  normalizeImportValues,
  type ImportAccessScopeId,
  type ImportFormValues,
} from "./importValues";
import { startSequentialPolling } from "../utils/sequentialPolling";
import VectorImportWorkflow from "./VectorImportWorkflow";
import ResultImportWorkflow from "./ResultImportWorkflow";
import { taxonomyLeafOptions } from "../utils/taxonomy";

type IssueAction = "continue" | "import";
type ImportTarget = "resource" | "result";
type ImportKind = "tabular" | "raster" | "vector" | "unsupported";
type ImportStorageMode = ImportFormValues["importMode"] | "raster";
type DomainDefinition = DataSchemaSummary["domains"][number];
type RasterDimensions = { width: number; height: number };
const selfAccessScopeId = "__self__";
const unfinishedImportWarning =
  "当前导入尚未完成，离开页面会丢失已选择的文件、配置和校验结果。";
const TABLE_UPLOAD_MAX_MB = 16;
const VECTOR_UPLOAD_MAX_MB = 120;
type AccessScopeId = ImportAccessScopeId;

export function effectiveTableUploadMaxMb(platformUploadMaxMb: number) {
  return Math.min(platformUploadMaxMb, TABLE_UPLOAD_MAX_MB);
}

export function effectiveVectorUploadMaxMb(platformUploadMaxMb: number) {
  return Math.min(platformUploadMaxMb, VECTOR_UPLOAD_MAX_MB);
}

const resourceTypeLabels: Record<string, string> = {
  vector: "矢量",
  raster: "栅格",
  gene: "组学/基因",
  table: "表格",
  document: "文档",
  image: "影像/照片",
};

const fallbackDomainDefinitions: DomainDefinition[] = [
  {
    code: "germplasm",
    name: "种质数据",
    spatialClass: "spatialized_table",
    description:
      "胡杨、灰杨及伴生植物种质资源，重点管理采集来源、样品编号、核心资源标记和后续分子/基因组数据关联。",
    recommendedResourceTypes: ["vector", "gene", "table"],
    coreEntities: ["GermplasmAccession", "BiologicalSample", "Site", "Taxon"],
  },
  {
    code: "genome",
    name: "基因组数据",
    spatialClass: "non_spatial",
    description:
      "测序、组装、变异、注释等非地理组学成果；通过生物样品追溯采集地、个体或种群空间来源。",
    recommendedResourceTypes: ["gene", "table"],
    coreEntities: ["GenomeDataset", "GenomeSequenceFile", "BiologicalSample"],
  },
  {
    code: "individual",
    name: "个体数据",
    spatialClass: "spatial",
    description: "单株或单个植株个体的位置、性别、健康状态和观测指标。",
    recommendedResourceTypes: ["vector", "table"],
    coreEntities: [
      "IndividualOrganism",
      "TraitObservation",
      "BiologicalSample",
    ],
  },
  {
    code: "community",
    name: "群落数据",
    spatialClass: "spatialized_table",
    description: "样方、群落组成、多样性指标和功能性状等数据。",
    recommendedResourceTypes: ["vector", "table"],
    coreEntities: [
      "SamplePlot",
      "CommunitySurvey",
      "SpeciesComposition",
      "CommunityMetricValue",
    ],
  },
  {
    code: "population",
    name: "种群数据",
    spatialClass: "spatial",
    description: "某区域内某物种种群的空间范围、调查事件和种群指标。",
    recommendedResourceTypes: ["vector", "table"],
    coreEntities: ["PopulationUnit", "SamplePlot", "RasterSampleValue"],
  },
  {
    code: "field_survey",
    name: "野外调查数据",
    spatialClass: "spatialized_table",
    description: "调查任务、路线、样点、采集记录、野外照片和观察记录。",
    recommendedResourceTypes: ["vector", "table", "image"],
    coreEntities: [
      "SurveyEvent",
      "FieldObservation",
      "SurveyRoute",
      "SpecimenRecord",
    ],
  },
  {
    code: "remote_sensing",
    name: "遥感影像数据",
    spatialClass: "spatial",
    description:
      "原始遥感影像、无人机影像、NDVI/NPP、生物量、分类和变化检测产品。",
    recommendedResourceTypes: ["raster", "vector"],
    coreEntities: [
      "RasterDataset",
      "RemoteSensingProduct",
      "RasterSampleValue",
    ],
  },
  {
    code: "molecular",
    name: "分子数据",
    spatialClass: "non_spatial",
    description:
      "DNA/RNA 提取、PCR、分子标记、实验批次和实验结果文件；通过生物样品关联空间来源。",
    recommendedResourceTypes: ["gene", "table", "document"],
    coreEntities: [
      "MolecularSample",
      "MolecularAssay",
      "MolecularResult",
      "MolecularFile",
    ],
  },
  {
    code: "vector",
    name: "矢量数据",
    spatialClass: "spatial",
    description:
      "以点、线、面几何为主体的 Shapefile、GeoJSON、GeoPackage 等空间矢量资源，支持统一入库、查询、符号化和地图展示。",
    recommendedResourceTypes: ["vector"],
    coreEntities: ["DataResource", "VectorDataset", "MapLayer"],
  },
  {
    code: "other",
    name: "其他类型",
    spatialClass: "spatialized_table",
    description:
      "暂未归入专门专题的数据资源，可先按空间点表、普通表、文档或图片统一登记，后续再补充字段映射和标准化归类。",
    recommendedResourceTypes: ["vector", "table", "document", "image"],
    coreEntities: ["DataResource", "SourceDataset", "SourceSheet"],
  },
];

const englishDomainDefinitions: Partial<
  Record<DataDomainType, { name: string; description: string }>
> = {
  germplasm: {
    name: "Germplasm data",
    description:
      "Poplar and associated-plant germplasm, including provenance, sample IDs, core-resource markers, and links to molecular or genomic data.",
  },
  genome: {
    name: "Genome data",
    description:
      "Non-geographic omics outputs such as sequencing, assembly, variants, and annotations, traceable to collection sites, individuals, or populations through biological samples.",
  },
  individual: {
    name: "Individual data",
    description:
      "Locations, sex, health status, and observations for individual plants.",
  },
  community: {
    name: "Community data",
    description:
      "Plots, community composition, diversity indices, and functional traits.",
  },
  population: {
    name: "Population data",
    description:
      "Spatial extents, survey events, and indicators for species populations in a region.",
  },
  field_survey: {
    name: "Field-survey data",
    description:
      "Survey tasks, routes, sites, collection records, field photographs, and observations.",
  },
  remote_sensing: {
    name: "Remote-sensing imagery",
    description:
      "Source satellite or UAV imagery and NDVI, NPP, biomass, classification, or change-detection products.",
  },
  molecular: {
    name: "Molecular data",
    description:
      "DNA/RNA extraction, PCR, molecular markers, experiment batches, and result files linked to spatial provenance through biological samples.",
  },
  vector: {
    name: "Vector data",
    description:
      "Point, line, and polygon resources such as Shapefile, GeoJSON, and GeoPackage, with standardized import, querying, symbolization, and map display.",
  },
  other: {
    name: "Other data",
    description:
      "Resources not yet assigned to a specialist topic; register them as point tables, attribute tables, documents, or images and add field mapping and standardization later.",
  },
};

const domainFieldHints: Record<DataDomainType, string[]> = {
  germplasm: [
    "样品编号",
    "采集地点",
    "物种",
    "经度",
    "纬度",
    "海拔",
    "核心资源标记",
  ],
  genome: [
    "样品编号",
    "测序平台",
    "数据集类型",
    "文件角色",
    "参考组装",
    "质控状态",
  ],
  individual: [
    "个体编号",
    "物种",
    "性别",
    "经度",
    "纬度",
    "健康状态",
    "功能性状",
  ],
  community: [
    "样方编号",
    "群落类型",
    "物种组成",
    "盖度",
    "多样性指数",
    "调查时间",
  ],
  population: [
    "种群编号",
    "物种",
    "调查区域",
    "样方编号",
    "种群指标",
    "遥感采样值",
  ],
  field_survey: [
    "调查编号",
    "样点/路线",
    "采集日期",
    "调查人员",
    "经度",
    "纬度",
    "观测记录",
  ],
  remote_sensing: [
    "产品编号",
    "产品类型",
    "传感器",
    "时间范围",
    "空间分辨率",
    "坐标系",
  ],
  molecular: [
    "分子样品编号",
    "核酸类型",
    "实验类型",
    "批次编号",
    "位点/标记",
    "结果文件",
  ],
  vector: ["源图层", "几何类型", "坐标系", "空间范围", "属性字段", "几何质量"],
  other: [
    "资源编号",
    "来源文件",
    "工作表",
    "字段说明",
    "数据格式",
    "后续归类建议",
  ],
};

export default function AdminDataImportPage() {
  const { message } = AntApp.useApp();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const { bootstrap, setBootstrap, user } = useAppContext();
  const location = useLocation();
  const navigate = useNavigate();
  const allowNavigationRef = useRef(false);
  const currentPathRef = useRef("");
  const rasterPreviewRequestRef = useRef(0);
  const [form] = Form.useForm<ImportFormValues>();
  const projectContext = useProjectContext();
  const [uploadProjectId, setUploadProjectId] = useState(1);
  const canImportResources = Boolean(user?.permissions.canUploadData);
  const canImportResults = Boolean(
    user?.permissions.canViewResultArtifacts &&
    user.permissions.canImportResultArtifacts &&
    user.permissions.canPublishResultArtifacts,
  );
  const [importTarget, setImportTarget] = useState<ImportTarget>(() =>
    (new URLSearchParams(location.search).get("target") === "result" &&
      canImportResults) ||
    !canImportResources
      ? "result"
      : "resource",
  );
  const [resultImportDirty, setResultImportDirty] = useState(false);
  const [schema, setSchema] = useState<DataSchemaSummary | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [importKind, setImportKind] = useState<ImportKind | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [fieldMetadata, setFieldMetadata] = useState<Record<string, string>>(
    {},
  );
  const [includedColumns, setIncludedColumns] = useState<string[]>([]);
  const [importConfig, setImportConfig] = useState<Partial<ImportFormValues>>(
    {},
  );
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportCommitResult | null>(null);
  const [validationIssues, setValidationIssues] = useState<
    ImportValidationIssue[]
  >([]);
  const [duplicateTarget, setDuplicateTarget] =
    useState<ImportDuplicateTarget | null>(null);
  const [duplicateNameConfirmed, setDuplicateNameConfirmed] = useState(false);
  const [duplicateConfirmOpen, setDuplicateConfirmOpen] = useState(false);
  const [validationStats, setValidationStats] =
    useState<ImportCoordinateStats | null>(null);
  const [validating, setValidating] = useState(false);
  const [hasValidated, setHasValidated] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [pendingIssueAction, setPendingIssueAction] =
    useState<IssueAction | null>(null);
  const [ignoreCoordinateUncertainty, setIgnoreCoordinateUncertainty] =
    useState(false);
  const [availableAccessGroups, setAvailableAccessGroups] = useState<
    ImportAccessGroup[]
  >([]);
  const [pendingNavigationPath, setPendingNavigationPath] = useState<
    string | null
  >(null);
  const [rasterFile, setRasterFile] = useState<File | null>(null);
  const [rasterFiles, setRasterFiles] = useState<File[]>([]);
  const [rasterPreview, setRasterPreview] =
    useState<RasterImportPreview | null>(null);
  const [rasterPreviewError, setRasterPreviewError] = useState<string | null>(
    null,
  );
  const [rasterName, setRasterName] = useState("");
  const [rasterDimensions, setRasterDimensions] =
    useState<RasterDimensions | null>(null);
  const [rasterInspecting, setRasterInspecting] = useState(false);
  const [rasterUploading, setRasterUploading] = useState(false);
  const [rasterUploadProgress, setRasterUploadProgress] = useState(0);
  const [completedRasterUploadProgress, setCompletedRasterUploadProgress] =
    useState(0);
  const [rasterJob, setRasterJob] = useState<RasterJob | null>(null);
  const [rasterKind, setRasterKind] =
    useState<RasterImportCommitPayload["rasterKind"]>("imagery");
  const [rasterResampling, setRasterResampling] =
    useState<RasterImportCommitPayload["resampling"]>("bilinear");
  const [rasterDefaultRules, setRasterDefaultRules] = useState<
    Record<string, unknown>
  >({});
  const [rasterAccessGroupIds, setRasterAccessGroupIds] = useState<number[]>(
    [],
  );
  const [rasterCategoryCode, setRasterCategoryCode] = useState("spatial");
  const [vectorFile, setVectorFile] = useState<File | null>(null);
  const [vectorResult, setVectorResult] =
    useState<VectorImportCommitResult | null>(null);
  const [unsupportedFile, setUnsupportedFile] = useState<File | null>(null);
  const hasUnfinishedImport = Boolean(
    (file && !result) ||
    (rasterFile && !rasterJob) ||
    (rasterJob && isActiveRasterJob(rasterJob)) ||
    (vectorFile && !vectorResult),
  );
  const hasPendingImport = hasUnfinishedImport || resultImportDirty;

  const domainDefinitions = useMemo(() => {
    const definitions = schema?.domains.length
      ? schema.domains
      : fallbackDomainDefinitions;
    if (!english) return definitions;
    return definitions.map((domain) => ({
      ...domain,
      name: englishDomainDefinitions[domain.code]?.name ?? domain.name,
      description:
        englishDomainDefinitions[domain.code]?.description ??
        domain.description,
    }));
  }, [english, schema?.domains]);
  const categoryOptions = useMemo(() => taxonomyLeafOptions(schema), [schema]);
  const selectedDomainType =
    Form.useWatch("domainType", form) ?? importConfig.domainType;
  const selectedDomain = useMemo(
    () =>
      domainDefinitions.find((domain) => domain.code === selectedDomainType) ??
      domainDefinitions[0],
    [domainDefinitions, selectedDomainType],
  );
  const remoteSensingDomain = useMemo(
    () =>
      domainDefinitions.find((domain) => domain.code === "remote_sensing") ??
      fallbackDomainDefinitions.find(
        (domain) => domain.code === "remote_sensing",
      ),
    [domainDefinitions],
  );

  const columnOptions = useMemo(
    () =>
      preview?.columns.map((column) => ({ label: column, value: column })) ??
      [],
    [preview],
  );

  const previewColumns = useMemo(
    () =>
      preview?.columns.map((column) => ({
        title: column,
        dataIndex: column,
        key: column,
        width: 180,
        ellipsis: true,
      })) ?? [],
    [preview],
  );

  const previewRows = useMemo(
    () =>
      preview?.rows.map((row) => ({
        ...row,
        previewRowKey: preview.columns
          .map((column) => row[column] ?? "")
          .join("\u001f"),
      })) ?? [],
    [preview],
  );

  const stats = validationStats;
  const hasBlockingIssues = validationIssues.some((issue) => issue.blocking);
  const hasIgnorableUncertainty = validationIssues.some(
    (issue) => issue.code === "coordinate_uncertainty",
  );
  const stepItems = useMemo(() => {
    if (importKind === "raster") {
      return [
        { title: l("选择文件", "Select file"), icon: <CloudUploadOutlined /> },
        { title: l("栅格配置", "Raster settings"), icon: <DatabaseOutlined /> },
        {
          title: l("预处理进度", "Preprocessing"),
          icon: <CheckCircleOutlined />,
        },
      ];
    }
    if (importKind === "unsupported") {
      return [
        { title: l("选择文件", "Select file"), icon: <CloudUploadOutlined /> },
        { title: l("类型识别", "Identify type"), icon: <FileSearchOutlined /> },
      ];
    }
    if (importKind === "vector") {
      return [
        { title: l("选择文件", "Select file"), icon: <CloudUploadOutlined /> },
        {
          title: l("预检与入库", "Preflight and import"),
          icon: <DatabaseOutlined />,
        },
      ];
    }
    return [
      { title: l("选择文件", "Select file"), icon: <CloudUploadOutlined /> },
      { title: l("导入配置", "Import settings"), icon: <DatabaseOutlined /> },
      {
        title: l("预览提交", "Preview and submit"),
        icon: <CheckCircleOutlined />,
      },
    ];
  }, [english, importKind]);

  useEffect(() => {
    currentPathRef.current = `${location.pathname}${location.search}${location.hash}`;
  }, [location.hash, location.pathname, location.search]);

  useEffect(() => {
    if (!canImportResources && !canImportResults) {
      return;
    }
    let ignore = false;
    const request = canImportResources
      ? api
          .adminDataResources({ current: 1, pageSize: 1 })
          .then((result) => result.availableAccessGroups)
      : api.resultArtifacts().then((result) => result.availableAccessGroups);
    request
      .then((result) => {
        if (!ignore) {
          setAvailableAccessGroups(result);
        }
      })
      .catch(() => {
        if (!ignore) {
          setAvailableAccessGroups([]);
        }
      });
    return () => {
      ignore = true;
    };
  }, [canImportResources, canImportResults]);

  useEffect(() => {
    if (!user?.permissions.canUploadData || !user.permissions.canBrowseData) {
      setSchema(null);
      return;
    }
    let ignore = false;
    api
      .dataSchemaSummary()
      .then((result) => {
        if (!ignore) {
          setSchema(result);
        }
      })
      .catch(() => {
        if (!ignore) {
          setSchema(null);
        }
      });
    return () => {
      ignore = true;
    };
  }, [user?.permissions.canBrowseData, user?.permissions.canUploadData]);

  useEffect(() => {
    let ignore = false;
    api
      .bootstrap()
      .then((nextBootstrap) => {
        if (!ignore) {
          setBootstrap(nextBootstrap);
          applyPlatformDocumentTitle(nextBootstrap.systemName);
        }
      })
      .catch(() => {
        // 导入页可继续使用启动时配置；后端仍会按当前 TOML 做最终校验。
      });
    return () => {
      ignore = true;
    };
  }, [setBootstrap]);

  useEffect(() => {
    if (!hasPendingImport) {
      return;
    }
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = unfinishedImportWarning;
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasPendingImport]);

  useEffect(() => {
    if (!hasPendingImport) {
      return;
    }
    const originalPushState = window.history.pushState;
    const originalReplaceState = window.history.replaceState;

    function shouldBlockUrl(url?: string | URL | null) {
      if (allowNavigationRef.current || url == null) {
        return false;
      }
      const nextUrl = new URL(String(url), window.location.href);
      if (nextUrl.origin !== window.location.origin) {
        return false;
      }
      const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
      const currentPath = currentPathRef.current;
      if (nextPath === currentPath) {
        return false;
      }
      setPendingNavigationPath(nextPath);
      return true;
    }

    window.history.pushState = function pushState(data, unused, url) {
      if (shouldBlockUrl(url)) {
        return;
      }
      return originalPushState.call(this, data, unused, url);
    };

    window.history.replaceState = function replaceState(data, unused, url) {
      if (shouldBlockUrl(url)) {
        return;
      }
      return originalReplaceState.call(this, data, unused, url);
    };

    const handlePopState = (event: PopStateEvent) => {
      if (allowNavigationRef.current) {
        return;
      }
      const nextPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      const currentPath = currentPathRef.current;
      if (nextPath === currentPath) {
        return;
      }
      event.stopImmediatePropagation();
      setPendingNavigationPath(nextPath);
      originalPushState.call(
        window.history,
        window.history.state,
        "",
        currentPath,
      );
    };

    const handleDocumentClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.altKey ||
        event.ctrlKey ||
        event.shiftKey
      ) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }
      const link = target.closest("a[href]");
      if (!(link instanceof HTMLAnchorElement)) {
        return;
      }
      if (link.target && link.target !== "_self") {
        return;
      }
      const nextUrl = new URL(link.href, window.location.href);
      if (nextUrl.origin !== window.location.origin) {
        return;
      }
      const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
      const currentPath = `${location.pathname}${location.search}${location.hash}`;
      if (nextPath === currentPath) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      setPendingNavigationPath(nextPath);
    };
    window.addEventListener("popstate", handlePopState, { capture: true });
    document.addEventListener("click", handleDocumentClick, true);
    return () => {
      window.history.pushState = originalPushState;
      window.history.replaceState = originalReplaceState;
      window.removeEventListener("popstate", handlePopState, { capture: true });
      document.removeEventListener("click", handleDocumentClick, true);
    };
  }, [hasPendingImport, location.hash, location.pathname, location.search]);

  const activeRasterJobId =
    rasterJob && isActiveRasterJob(rasterJob) ? rasterJob.id : null;

  useEffect(() => {
    if (!activeRasterJobId) {
      return;
    }
    return startSequentialPolling(
      async (signal) => {
        try {
          const nextJob = await api.rasterJob(activeRasterJobId, {
            signal,
            projectTagId: uploadProjectId,
          });
          if (!signal.aborted) {
            setRasterJob(nextJob);
          }
          return !signal.aborted && isActiveRasterJob(nextJob);
        } catch (error) {
          if (signal.aborted) return false;
          const text =
            error instanceof Error ? error.message : "栅格任务查询失败";
          setRasterJob((current) =>
            current?.id === activeRasterJobId
              ? { ...current, status: "failed", error: text }
              : current,
          );
          message.error(text);
          return false;
        }
      },
      { intervalMs: 1000 },
    );
  }, [activeRasterJobId, message, uploadProjectId]);

  if (!canImportResources && !canImportResults) {
    return <Navigate to="/admin/profile" replace />;
  }

  function handleImportTargetChange(nextTarget: ImportTarget) {
    if (nextTarget === importTarget) return;
    if (hasPendingImport) {
      message.warning(
        l(
          "请先完成当前导入或点击重新选择清空内容，再切换导入目标",
          "Finish the current import or clear it with Choose another file before switching import targets",
        ),
      );
      return;
    }
    setImportTarget(nextTarget);
  }

  const importTargetSelector = (
    <ProCard className="admin-section-card import-target-card">
      <div className="import-target-heading">
        <div>
          <Typography.Title level={4}>
            {l("选择导入目标", "Choose an import target")}
          </Typography.Title>
          <Typography.Text type="secondary">
            {l(
              "数据资源用于后续地图加载、查询和分析；成果文件用于集中展示已经完成的图件、报告、图表和表格。",
              "Data resources support subsequent map loading, queries, and analysis. Result files present completed maps, reports, charts, and tables.",
            )}
          </Typography.Text>
        </div>
        <Radio.Group
          optionType="button"
          buttonStyle="solid"
          value={importTarget}
          onChange={(event) =>
            handleImportTargetChange(event.target.value as ImportTarget)
          }
          options={[
            ...(canImportResources
              ? [
                  {
                    label: l("导入为数据资源", "Import as data resource"),
                    value: "resource" as const,
                  },
                ]
              : []),
            ...(canImportResults
              ? [
                  {
                    label: l("导入并发布成果", "Import and publish result"),
                    value: "result" as const,
                  },
                ]
              : []),
          ]}
        />
      </div>
    </ProCard>
  );

  const projectField = (
    <UploadProjectField
      value={uploadProjectId}
      onChange={setUploadProjectId}
      locked={Boolean(
        file ||
        rasterFile ||
        vectorFile ||
        unsupportedFile ||
        resultImportDirty ||
        previewing ||
        rasterInspecting,
      )}
    />
  );

  if (importTarget === "result") {
    return (
      <div className="admin-page-stack admin-import-page">
        {projectField}
        {importTargetSelector}
        <ResultImportWorkflow
          projectTagId={uploadProjectId}
          categoryOptions={categoryOptions}
          accessGroups={availableAccessGroups}
          uploadMaxMb={bootstrap.limits.uploadMaxMb}
          onDirtyChange={setResultImportDirty}
        />
      </div>
    );
  }

  function resetImportState() {
    rasterPreviewRequestRef.current += 1;
    setImportKind(null);
    setFile(null);
    setPreview(null);
    setFieldMetadata({});
    setIncludedColumns([]);
    setValidationIssues([]);
    setDuplicateTarget(null);
    setDuplicateNameConfirmed(false);
    setDuplicateConfirmOpen(false);
    setValidationStats(null);
    setHasValidated(false);
    setIgnoreCoordinateUncertainty(false);
    setPendingIssueAction(null);
    setIssuesOpen(false);
    setResult(null);
    setImportConfig({});
    setRasterFile(null);
    setRasterFiles([]);
    setRasterPreview(null);
    setRasterPreviewError(null);
    setRasterName("");
    setRasterDimensions(null);
    setRasterInspecting(false);
    setRasterJob(null);
    setRasterUploading(false);
    setRasterUploadProgress(0);
    setCompletedRasterUploadProgress(0);
    setRasterKind("imagery");
    setRasterResampling("bilinear");
    setRasterDefaultRules({});
    setRasterAccessGroupIds([]);
    setRasterCategoryCode("spatial");
    setVectorFile(null);
    setVectorResult(null);
    setUnsupportedFile(null);
    setCurrentStep(0);
    form.resetFields();
  }

  async function previewRasterFiles(
    selectedFiles: File[],
    primaryFileName?: string,
  ) {
    const requestId = rasterPreviewRequestRef.current + 1;
    rasterPreviewRequestRef.current = requestId;
    setRasterInspecting(true);
    setRasterPreview(null);
    setRasterPreviewError(null);
    try {
      const inspected = await api.previewRasterImport(
        selectedFiles,
        primaryFileName,
        uploadProjectId,
      );
      if (requestId !== rasterPreviewRequestRef.current) {
        return;
      }
      setRasterPreview(inspected);
      setRasterName((current) => current || inspected.suggestedName);
      setRasterDimensions({
        width: inspected.metadata.size[0] ?? 0,
        height: inspected.metadata.size[1] ?? 0,
      });
      setRasterKind(inspected.rasterKind);
      setRasterResampling(inspected.resampling);
      setRasterDefaultRules(inspected.defaultRules);
      setRasterCategoryCode("spatial");
      message.success("栅格数据包预检完成，请确认导入与显示配置");
    } catch (error) {
      if (requestId !== rasterPreviewRequestRef.current) {
        return;
      }
      setRasterDimensions(null);
      const errorText =
        error instanceof Error ? error.message : "栅格数据包预检失败";
      setRasterPreviewError(errorText);
      message.error(errorText);
    } finally {
      if (requestId === rasterPreviewRequestRef.current) {
        setRasterInspecting(false);
      }
    }
  }

  async function handleFileSelected(selectedFile: File) {
    if (
      projectContext &&
      !projectContext.projects.some((project) => project.id === uploadProjectId)
    ) {
      message.error("请选择有访问权限的所属项目标签");
      return;
    }
    const kind = detectImportKind(selectedFile);
    resetImportState();
    if (kind === "raster") {
      if (selectedFile.size > bootstrap.limits.uploadMaxMb * 1024 * 1024) {
        message.error(
          `栅格数据包总大小不能超过 ${bootstrap.limits.uploadMaxMb} MB`,
        );
        return;
      }
      setImportKind("raster");
      setRasterFile(selectedFile);
      setRasterFiles([selectedFile]);
      setRasterName(fileStem(selectedFile.name));
      setCurrentStep(1);
      void previewRasterFiles([selectedFile], selectedFile.name);
      return;
    }
    if (kind === "tabular") {
      const tableUploadMaxMb = effectiveTableUploadMaxMb(
        bootstrap.limits.uploadMaxMb,
      );
      if (selectedFile.size > tableUploadMaxMb * 1024 * 1024) {
        message.error(
          `表格文件不能超过 ${tableUploadMaxMb} MB（内存安全限制）`,
        );
        return;
      }
      setImportKind("tabular");
      void handlePreview(selectedFile);
      return;
    }
    if (kind === "vector") {
      const vectorUploadMaxMb = effectiveVectorUploadMaxMb(
        bootstrap.limits.uploadMaxMb,
      );
      if (selectedFile.size > vectorUploadMaxMb * 1024 * 1024) {
        message.error(
          `矢量文件不能超过 ${vectorUploadMaxMb} MB（内存安全限制）`,
        );
        return;
      }
      setImportKind("vector");
      setVectorFile(selectedFile);
      setCurrentStep(1);
      message.success(
        "已识别为矢量数据，正在执行图层、编码、坐标系和几何质量预检",
      );
      return;
    }
    setImportKind("unsupported");
    setUnsupportedFile(selectedFile);
    setCurrentStep(1);
    message.warning("暂不支持该文件类型的自动导入");
  }

  async function handlePreview(selectedFile: File, sheetName?: string | null) {
    setFile(selectedFile);
    setPreviewing(true);
    setResult(null);
    setValidationIssues([]);
    setValidationStats(null);
    setHasValidated(false);
    setIgnoreCoordinateUncertainty(false);
    try {
      const data = await api.importPreview(
        selectedFile,
        sheetName,
        uploadProjectId,
      );
      setPreview(data);
      setDuplicateTarget(data.duplicateTarget ?? null);
      setFieldMetadata(
        Object.fromEntries(data.columns.map((column) => [column, ""])),
      );
      setIncludedColumns(data.columns);
      const inferredDomainType = inferDomainTypeFromFile(
        selectedFile.name,
        data,
      );
      const nextConfig: ImportFormValues = {
        name: data.suggestedName,
        domainType: inferredDomainType,
        importMode: data.detected.isGeographic ? "geographic" : "table",
        longitudeColumn: data.detected.longitudeColumn ?? undefined,
        latitudeColumn: data.detected.latitudeColumn ?? undefined,
        accessGroupIds: [],
      };
      setImportConfig(nextConfig);
      form.setFieldsValue({
        ...nextConfig,
        accessGroupIds: withFixedAccessScopes(nextConfig.accessGroupIds),
      });
      setCurrentStep(1);
      message.success(
        data.activeSheetName
          ? `工作表 ${data.activeSheetName} 预检完成，请配置导入信息`
          : "文件预检完成，请配置导入信息",
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : "预检失败");
    } finally {
      setPreviewing(false);
    }
  }

  function handleSheetSelected(sheetName: string) {
    if (!file || preview?.activeSheetName === sheetName) {
      return;
    }
    void handlePreview(file, sheetName);
  }

  async function handleValidateAndContinue() {
    if (!file || !preview) {
      message.warning("请先选择并预检文件");
      return;
    }
    try {
      const values = await form.validateFields();
      setImportConfig((current) => ({ ...current, ...values }));
      const payload: ImportValidatePayload = {
        name: values.name,
        sheetName: preview.activeSheetName ?? undefined,
        importMode: values.importMode,
        tableName: preview.suggestedTableName,
        longitudeColumn: values.longitudeColumn,
        latitudeColumn: values.latitudeColumn,
      };
      setValidating(true);
      const validated = await api.importValidate(
        file,
        payload,
        uploadProjectId,
      );
      setValidationStats(validated.coordinateStats);
      setValidationIssues(validated.validationIssues);
      setDuplicateTarget(validated.duplicateTarget ?? null);
      setDuplicateNameConfirmed(false);
      setHasValidated(true);
      setIgnoreCoordinateUncertainty(false);
      if (validated.duplicateTarget) {
        setDuplicateConfirmOpen(true);
        return;
      }
      if (validated.validationIssues.length) {
        setPendingIssueAction("continue");
        setIssuesOpen(true);
        return;
      }
      message.success("数据校验通过");
      setCurrentStep(2);
    } catch (error) {
      const issues = importIssuesFromError(error);
      if (issues.length) {
        setValidationIssues(issues);
        setPendingIssueAction("continue");
        setIssuesOpen(true);
      } else {
        message.error(error instanceof Error ? error.message : "数据校验失败");
      }
    } finally {
      setValidating(false);
    }
  }

  async function handleImport() {
    await submitImport(ignoreCoordinateUncertainty);
  }

  function addRasterCompanionFiles(selectedFiles: File[]) {
    const merged = new Map(
      rasterFiles.map((file) => [file.name.toLowerCase(), file] as const),
    );
    selectedFiles.forEach((file) => merged.set(file.name.toLowerCase(), file));
    const nextFiles = Array.from(merged.values());
    const totalBytes = nextFiles.reduce((sum, file) => sum + file.size, 0);
    if (totalBytes > bootstrap.limits.uploadMaxMb * 1024 * 1024) {
      message.error(
        `栅格数据包总大小不能超过 ${bootstrap.limits.uploadMaxMb} MB`,
      );
      return;
    }
    setRasterFiles(nextFiles);
    const primaryName = rasterPreview?.primaryFileName ?? rasterFile?.name;
    void previewRasterFiles(nextFiles, primaryName);
  }

  function updateRasterRgbBand(index: number, band: number) {
    const current = Array.isArray(rasterDefaultRules.bands)
      ? [...(rasterDefaultRules.bands as number[])]
      : [1, 2, 3];
    while (current.length < 3) current.push(current[current.length - 1] ?? 1);
    current[index] = band;
    setRasterDefaultRules((rules) => ({
      ...rules,
      mode: "rgb",
      bands: current.slice(0, 3),
    }));
  }

  async function handleRasterImport() {
    if (!rasterFile || rasterFiles.length === 0) {
      message.warning("请先选择栅格文件");
      return;
    }
    if (!rasterPreview) {
      message.warning("请先通过栅格数据包预检");
      return;
    }
    if (!rasterName.trim()) {
      message.warning("请输入栅格数据名称");
      return;
    }
    setRasterUploading(true);
    setRasterUploadProgress(0);
    setCompletedRasterUploadProgress(0);
    setRasterJob(null);
    try {
      const payload: RasterImportCommitPayload = {
        primaryFileName: rasterPreview.primaryFileName,
        name: rasterName.trim(),
        rasterKind,
        resampling: rasterResampling,
        defaultRules: rasterDefaultRules,
        accessGroupIds: rasterAccessGroupIds,
        categoryCode: rasterCategoryCode,
      };
      const job = await api.importRaster(
        rasterFiles,
        payload,
        (percent) => {
          setRasterUploadProgress(percent);
        },
        uploadProjectId,
      );
      setCompletedRasterUploadProgress(100);
      setRasterJob(job);
      setCurrentStep(2);
      message.success(
        l(
          "栅格导入任务已提交，后台正在预处理",
          "Raster import submitted; preprocessing is running in the background",
        ),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : l("栅格导入失败", "Raster import failed"),
      );
    } finally {
      setRasterUploading(false);
    }
  }

  function resetRasterImportState() {
    resetImportState();
  }

  async function submitImport(ignoreUncertainty: boolean) {
    if (!file || !preview) {
      message.warning(
        l("请先选择并预检文件", "Select and preflight a file first"),
      );
      return;
    }
    try {
      if (!hasValidated) {
        message.warning(l("请先进行数据校验", "Validate the data first"));
        setCurrentStep(1);
        return;
      }
      if (shouldBlockImport(validationIssues, ignoreUncertainty)) {
        setPendingIssueAction("import");
        setIssuesOpen(true);
        return;
      }
      const values = normalizeImportValues({
        ...importConfig,
        ...form.getFieldsValue(true),
      });
      if (!values.name) {
        message.warning(l("请输入数据名称", "Enter a data name"));
        setCurrentStep(1);
        return;
      }
      if (!values.importMode) {
        message.warning(l("请选择入库方式", "Select a storage mode"));
        setCurrentStep(1);
        return;
      }

      if (duplicateTarget && !duplicateNameConfirmed) {
        message.warning(
          l(
            "请先在数据校验阶段确认重复数据名称",
            "Confirm the duplicate data name during validation first",
          ),
        );
        setCurrentStep(1);
        return;
      }
      const selectedMetadata = Object.fromEntries(
        includedColumns.map((column) => [column, fieldMetadata[column] ?? ""]),
      );
      const payload: ImportCommitPayload = {
        name: values.name,
        domainType: "other",
        categoryCode:
          values.importMode === "geographic" ? "spatial" : "non_spatial",
        sheetName: preview.activeSheetName ?? undefined,
        importMode: values.importMode,
        longitudeColumn: values.longitudeColumn,
        latitudeColumn: values.latitudeColumn,
        tableName: preview.suggestedTableName,
        ignoreCoordinateUncertainty: ignoreUncertainty,
        duplicateConfirmed: Boolean(duplicateTarget && duplicateNameConfirmed),
        includedColumns,
        fieldMetadata: selectedMetadata,
        accessGroupIds: realAccessGroupIds(values.accessGroupIds),
      };
      setImporting(true);
      const imported = await api.importCommit(file, payload, uploadProjectId);
      setResult(imported);
      setValidationIssues(imported.validationIssues);
      message.success(l("导入完成", "Import completed"));
    } catch (error) {
      const issues = importIssuesFromError(error);
      if (issues.length) {
        setValidationIssues(issues);
        setPendingIssueAction("import");
        setIssuesOpen(true);
      } else {
        message.error(
          error instanceof Error
            ? error.message
            : l("导入失败", "Import failed"),
        );
      }
    } finally {
      setImporting(false);
    }
  }

  function handleIssueConfirm() {
    if (hasBlockingIssues || !hasIgnorableUncertainty) {
      setIssuesOpen(false);
      return;
    }
    setIgnoreCoordinateUncertainty(true);
    setIssuesOpen(false);
    if (pendingIssueAction === "continue") {
      setCurrentStep(2);
      return;
    }
    void submitImport(true);
  }

  return (
    <div className="admin-page-stack admin-import-page">
      {projectField}
      {importTargetSelector}
      <ProCard className="admin-section-card">
        <Steps current={currentStep} items={stepItems} />
      </ProCard>

      <ProCard className="admin-section-card">
        <Form
          form={form}
          layout="vertical"
          component={false}
          onValuesChange={(changed) => {
            setImportConfig((current) => ({ ...current, ...changed }));
            if (
              "importMode" in changed ||
              "name" in changed ||
              "longitudeColumn" in changed ||
              "latitudeColumn" in changed
            ) {
              setValidationIssues([]);
              setValidationStats(null);
              setHasValidated(false);
              setIgnoreCoordinateUncertainty(false);
              setDuplicateNameConfirmed(false);
              if ("importMode" in changed || "name" in changed) {
                setDuplicateTarget(null);
              }
            }
          }}
        >
          {currentStep === 0 && (
            <section className="import-step-pane">
              <Upload.Dragger
                disabled={previewing || rasterInspecting}
                beforeUpload={(selectedFile) => {
                  void handleFileSelected(selectedFile);
                  return false;
                }}
                maxCount={1}
                showUploadList={false}
              >
                <CloudUploadOutlined style={{ fontSize: 34 }} />
                <Typography.Title level={4}>
                  {l("选择或拖拽数据文件", "Select or drop a data file")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {l(
                    "支持 CSV、Excel、矢量文件，以及 GeoTIFF/COG、IMG、VRT、 ENVI DAT/BSQ/BIL/BIP + HDR 栅格数据包；系统会根据文件类型自动进入后续流程。表格和矢量文件分别受 16 MB、120 MB 内存安全上限保护。",
                    "Supports CSV, Excel, vector files, and GeoTIFF/COG, IMG, VRT, and ENVI DAT/BSQ/BIL/BIP + HDR raster packages. The next workflow is selected automatically by file type. Tabular and vector files have 16 MB and 120 MB in-memory safety limits, respectively.",
                  )}
                </Typography.Text>
                <div className="import-selected-file">
                  {previewing ? (
                    <Tag color="processing">
                      {l("正在预检文件...", "Preflighting file...")}
                    </Tag>
                  ) : rasterInspecting ? (
                    <Tag color="processing">
                      {l("正在读取栅格尺寸...", "Reading raster dimensions...")}
                    </Tag>
                  ) : file ? (
                    <Tag color="green">{file.name}</Tag>
                  ) : (
                    <Tag>{l("尚未选择文件", "No file selected")}</Tag>
                  )}
                </div>
              </Upload.Dragger>
            </section>
          )}

          {currentStep === 1 && importKind === "tabular" && preview && (
            <div className="import-config-form">
              <Space className="import-actions import-actions-top">
                <Button onClick={resetImportState}>
                  {l("重新选择文件", "Choose another file")}
                </Button>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined style={{ fontSize: 16 }} />}
                  loading={validating}
                  onClick={handleValidateAndContinue}
                >
                  {l("数据校验并继续", "Validate and continue")}
                </Button>
              </Space>

              <section className="import-section import-recognition-panel">
                <Typography.Title level={5}>
                  {l("文件识别结果", "File identification")}
                </Typography.Title>
                <Descriptions
                  size="small"
                  bordered
                  column={4}
                  className="import-stats"
                >
                  <Descriptions.Item label={l("文件名", "File name")}>
                    {file?.name ?? "-"}
                  </Descriptions.Item>
                  <Descriptions.Item label={l("总行数", "Total rows")}>
                    {preview.rowCount}
                  </Descriptions.Item>
                  {preview.activeSheetName && (
                    <Descriptions.Item
                      label={l("当前工作表", "Current worksheet")}
                    >
                      {preview.activeSheetName}
                    </Descriptions.Item>
                  )}
                  <Descriptions.Item label={l("字段数", "Fields")}>
                    {preview.columns.length}
                  </Descriptions.Item>
                  <Descriptions.Item label={l("自动识别", "Detected type")}>
                    {preview.detected.isGeographic
                      ? l(
                          "地理数据（经纬度表格）",
                          "Geographic data (longitude/latitude table)",
                        )
                      : l(
                          "非地理数据（普通表格）",
                          "Non-geographic data (attribute table)",
                        )}
                  </Descriptions.Item>
                  <Descriptions.Item
                    label={l("建议存储标识", "Suggested storage identifier")}
                    span={2}
                  >
                    {preview.suggestedTableName}
                  </Descriptions.Item>
                  <Descriptions.Item
                    label={l("识别坐标列", "Detected coordinate columns")}
                    span={2}
                  >
                    {preview.detected.longitudeColumn &&
                    preview.detected.latitudeColumn
                      ? `${preview.detected.longitudeColumn} / ${preview.detected.latitudeColumn}`
                      : l("未识别", "Not detected")}
                  </Descriptions.Item>
                </Descriptions>
                {(preview.sheets?.length ?? 0) > 1 && (
                  <section className="import-section import-sheet-section">
                    <Typography.Title level={5}>
                      {l("工作表拆分结果", "Worksheet split results")}
                    </Typography.Title>
                    <Alert
                      type="info"
                      showIcon
                      title={l(
                        `已识别 ${preview.sheets?.length ?? 0} 张工作表`,
                        `${preview.sheets?.length ?? 0} worksheets detected`,
                      )}
                      description={l(
                        "每张工作表会按独立表格预检、校验和导入；请选择当前要导入的工作表，平台会重新推断字段、坐标列和建议入库名称。",
                        "Each worksheet is preflighted, validated, and imported independently. Select the worksheet to import and the platform will infer fields, coordinate columns, and a suggested storage name again.",
                      )}
                    />
                    <Table
                      size="small"
                      rowKey="name"
                      pagination={false}
                      dataSource={preview.sheets ?? []}
                      columns={[
                        {
                          title: l("工作表", "Worksheet"),
                          dataIndex: "name",
                          ellipsis: true,
                        },
                        {
                          title: l("行数", "Rows"),
                          dataIndex: "rowCount",
                          width: 96,
                        },
                        {
                          title: l("字段", "Fields"),
                          dataIndex: "columnCount",
                          width: 96,
                        },
                        {
                          title: l("识别类型", "Detected type"),
                          dataIndex: "isGeographic",
                          width: 140,
                          render: (_, record) =>
                            record.isGeographic ? (
                              <Tag color="cyan">
                                {l("经纬度表格", "Longitude/latitude table")}
                              </Tag>
                            ) : (
                              <Tag>{l("普通表格", "Attribute table")}</Tag>
                            ),
                        },
                        {
                          title: l("坐标列", "Coordinate columns"),
                          width: 180,
                          render: (_, record) =>
                            record.longitudeColumn && record.latitudeColumn
                              ? `${record.longitudeColumn} / ${record.latitudeColumn}`
                              : "-",
                        },
                        {
                          title: l("操作", "Actions"),
                          width: 120,
                          render: (_, record) =>
                            record.name === preview.activeSheetName ? (
                              <Tag color="green">
                                {l("当前导入", "Selected")}
                              </Tag>
                            ) : (
                              <Button
                                size="small"
                                loading={previewing}
                                onClick={() => handleSheetSelected(record.name)}
                              >
                                {l("切换", "Select")}
                              </Button>
                            ),
                        },
                      ]}
                    />
                  </section>
                )}
                {preview.limitations.length > 0 && (
                  <Alert
                    type="info"
                    showIcon
                    title={l("本次导入边界", "Import limitations")}
                    description={
                      <ul className="import-limit-list">
                        {preview.limitations.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("数据名称", "Data name")}
                </Typography.Title>
                <div className="import-config-grid import-name-grid">
                  <Form.Item
                    name="name"
                    label={l(
                      "存量数据中显示的资源名称",
                      "Resource name shown in inventory",
                    )}
                    rules={[
                      {
                        required: true,
                        message: l("请输入数据名称", "Enter a data name"),
                      },
                    ]}
                  >
                    <Input
                      placeholder={l(
                        "例如：2024 塔里木胡杨 DNA 样品清单",
                        "Example: 2024 Tarim poplar DNA sample inventory",
                      )}
                    />
                  </Form.Item>
                </div>
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("数据分类", "Data category")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {l(
                    "有坐标的数据归入地理数据，无坐标的数据归入非地理数据；系统依据入库方式和坐标解析结果自动归类。",
                    "Resources are classified automatically from their parsed geographic coordinates.",
                  )}
                </Typography.Text>
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("入库方式", "Storage mode")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {l(
                    "选择地理数据时须指定经纬度列，通过校验后生成点图层；无坐标的数据以普通表格入库。",
                    "The storage mode determines whether the file becomes a mappable point layer or an attribute table. The business type determines its later standard-entity mapping.",
                  )}
                </Typography.Text>
                <Form.Item
                  name="importMode"
                  rules={[
                    {
                      required: true,
                      message: l("请选择入库方式", "Select a storage mode"),
                    },
                  ]}
                >
                  <Radio.Group className="import-mode-grid">
                    <Radio value="geographic" className="import-mode-card">
                      <span className="import-mode-title">
                        {l(
                          "空间点表（有经纬度列）",
                          "Spatial point table (with longitude/latitude)",
                        )}
                      </span>
                      <span className="import-mode-desc">
                        {l(
                          "适合样点、样方、采集地、个体位置等数据，会生成可上图的点图层。",
                          "For sample sites, plots, collection locations, and individual positions; creates a mappable point layer.",
                        )}
                      </span>
                    </Radio>
                    <Radio value="table" className="import-mode-card">
                      <span className="import-mode-title">
                        {l(
                          "普通属性表（无坐标）",
                          "Attribute table (no coordinates)",
                        )}
                      </span>
                      <span className="import-mode-desc">
                        {l(
                          "适合实验记录、统计指标、文件清单等数据，先作为表格资源管理。",
                          "For experiment records, statistical indicators, and file inventories; managed initially as a table resource.",
                        )}
                      </span>
                    </Radio>
                  </Radio.Group>
                </Form.Item>
                <Form.Item
                  noStyle
                  shouldUpdate={(prev, current) =>
                    prev.importMode !== current.importMode ||
                    prev.domainType !== current.domainType
                  }
                >
                  {({ getFieldValue }) => {
                    const mode = getFieldValue("importMode") as
                      | ImportFormValues["importMode"]
                      | undefined;
                    const domainType = getFieldValue("domainType") as
                      | DataDomainType
                      | undefined;
                    const domain =
                      domainDefinitions.find(
                        (item) => item.code === domainType,
                      ) ?? selectedDomain;
                    return <ImportStorageSummary mode={mode} domain={domain} />;
                  }}
                </Form.Item>
              </section>

              <Form.Item
                noStyle
                shouldUpdate={(prev, current) =>
                  prev.importMode !== current.importMode
                }
              >
                {({ getFieldValue }) =>
                  getFieldValue("importMode") === "geographic" ? (
                    <div className="import-coordinate-grid">
                      <Form.Item
                        name="longitudeColumn"
                        label={l("经度列", "Longitude column")}
                        rules={[
                          {
                            required: true,
                            message: l(
                              "请选择经度列",
                              "Select a longitude column",
                            ),
                          },
                        ]}
                      >
                        <Select
                          options={columnOptions}
                          placeholder={l(
                            "选择经度列",
                            "Select longitude column",
                          )}
                          showSearch
                        />
                      </Form.Item>
                      <Form.Item
                        name="latitudeColumn"
                        label={l("纬度列", "Latitude column")}
                        rules={[
                          {
                            required: true,
                            message: l(
                              "请选择纬度列",
                              "Select a latitude column",
                            ),
                          },
                        ]}
                      >
                        <Select
                          options={columnOptions}
                          placeholder={l(
                            "选择纬度列",
                            "Select latitude column",
                          )}
                          showSearch
                        />
                      </Form.Item>
                      <Space className="import-validation-actions">
                        {hasValidated && validationIssues.length === 0 && (
                          <Tag color="green">
                            {l("校验通过", "Validation passed")}
                          </Tag>
                        )}
                        {hasValidated && validationIssues.length > 0 && (
                          <Tag color={hasBlockingIssues ? "red" : "gold"}>
                            {hasBlockingIssues
                              ? l("存在阻断问题", "Blocking issues")
                              : l("存在可忽略问题", "Ignorable issues")}
                          </Tag>
                        )}
                      </Space>
                    </div>
                  ) : null
                }
              </Form.Item>

              {stats && (
                <Descriptions
                  size="small"
                  bordered
                  column={4}
                  className="import-stats"
                >
                  <Descriptions.Item label={l("总行数", "Total rows")}>
                    {stats.totalRows}
                  </Descriptions.Item>
                  <Descriptions.Item label={l("有效坐标", "Valid coordinates")}>
                    {stats.validRows}
                  </Descriptions.Item>
                  <Descriptions.Item
                    label={l("空或非法坐标", "Missing or invalid coordinates")}
                  >
                    {stats.missingRows}
                  </Descriptions.Item>
                  <Descriptions.Item
                    label={l("量化误差范围", "Quantization-error range")}
                  >
                    {stats.quantizationErrorMeters.min ?? "-"} -{" "}
                    {stats.quantizationErrorMeters.max ?? "-"} {l("米", "m")}
                  </Descriptions.Item>
                </Descriptions>
              )}

              {!preview.detected.isGeographic && (
                <Alert
                  type="info"
                  showIcon
                  title={l(
                    "已自动归类为非地理数据",
                    "Automatically classified as non-geographic data",
                  )}
                  description={l(
                    "当前工作表未识别到可用的经纬度列，系统已默认按普通属性表入库；提交后只会显示在非地理数据资源列表中。若文件实际使用非标准坐标列名，可手动切换为空间点表并明确选择经度列和纬度列。",
                    "No usable longitude/latitude columns were detected, so this worksheet defaults to an attribute table and will appear only in non-geographic resources. If the file uses non-standard coordinate column names, switch to Spatial point table and select the longitude and latitude columns explicitly.",
                  )}
                />
              )}

              {duplicateTarget && (
                <DuplicateTargetAlert
                  target={duplicateTarget}
                  confirmed={duplicateNameConfirmed}
                />
              )}
            </div>
          )}

          {currentStep === 1 && importKind === "raster" && rasterFile && (
            <div className="import-config-form">
              <Space className="import-actions import-actions-top">
                <Button onClick={resetRasterImportState}>
                  {l("重新选择文件", "Choose another file")}
                </Button>
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined style={{ fontSize: 16 }} />}
                  loading={rasterUploading}
                  disabled={!rasterPreview || rasterInspecting}
                  onClick={handleRasterImport}
                >
                  {l("上传并预处理", "Upload and preprocess")}
                </Button>
              </Space>

              <Alert
                type="info"
                showIcon
                title={
                  rasterInspecting
                    ? l("正在预检栅格数据包", "Preflighting raster package")
                    : rasterPreview
                      ? l(
                          "栅格数据包预检通过",
                          "Raster package preflight passed",
                        )
                      : rasterPreviewError
                        ? l("栅格预检未通过", "Raster preflight failed")
                        : l(
                            "尚未完成栅格预检",
                            "Raster preflight not completed",
                          )
                }
                description={
                  rasterInspecting
                    ? l(
                        "正在使用 GDAL 读取文件格式、坐标系、尺寸和波段信息，请稍候。",
                        "GDAL is reading the format, CRS, dimensions, and band information. Please wait.",
                      )
                    : rasterPreviewError
                      ? rasterPreviewError
                      : rasterFileNeedsCompanions(rasterFile.name)
                        ? l(
                            "该文件类型需要配套文件：DAT/BSQ/BIL/BIP 需同名 HDR；VRT 需同时上传全部引用文件。",
                            "This file type needs companion files: DAT/BSQ/BIL/BIP requires a same-name HDR, and VRT requires every referenced file.",
                          )
                        : l(
                            `单个 GeoTIFF/COG 或 IMG 可直接导入，无需辅助文件。后端会使用 GDAL 校验文件大小不超过 ${bootstrap.limits.uploadMaxMb} MB、单边长度不超过 ${bootstrap.limits.maxRasterSidePixels} 像素。`,
                            `A single GeoTIFF/COG or IMG can be imported without companion files. GDAL verifies a maximum file size of ${bootstrap.limits.uploadMaxMb} MB and maximum side length of ${bootstrap.limits.maxRasterSidePixels} pixels.`,
                          )
                }
              />

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("栅格数据包", "Raster package")}
                </Typography.Title>
                <Space size={[6, 6]} wrap>
                  {rasterFiles.map((file) => (
                    <Tag key={`${file.name}-${file.size}`}>{file.name}</Tag>
                  ))}
                </Space>
                <div style={{ marginTop: 12 }}>
                  <Upload
                    multiple
                    showUploadList={false}
                    beforeUpload={(selectedFile, selectedBatch) => {
                      if (selectedFile === selectedBatch[0]) {
                        addRasterCompanionFiles(selectedBatch);
                      }
                      return false;
                    }}
                  >
                    <Button
                      icon={<CloudUploadOutlined />}
                      loading={rasterInspecting}
                    >
                      {l(
                        "补充 HDR、VRT 引用或可选辅助文件",
                        "Add HDR, VRT references, or optional companion files",
                      )}
                    </Button>
                  </Upload>
                </div>
                {rasterPreview?.warnings.map((warning) => (
                  <Alert
                    key={warning}
                    type="warning"
                    showIcon
                    title={warning}
                    style={{ marginTop: 10 }}
                  />
                ))}
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l(
                    "业务数据类型与入库去向",
                    "Business data type and storage destination",
                  )}
                </Typography.Title>
                {remoteSensingDomain && (
                  <DomainDetail domain={remoteSensingDomain} />
                )}
                <ImportStorageSummary
                  mode="raster"
                  domain={remoteSensingDomain}
                />
                <Alert
                  type="info"
                  showIcon
                  title={l(
                    "栅格数据导入后可在存量数据中继续管理",
                    "Imported rasters remain manageable in Data Inventory",
                  )}
                  description={l(
                    "当前流程会先完成文件登记、预处理和地图图层创建；可见权限、默认样式和后续遥感产品标准化关系可在存量数据和后续业务治理模块中维护。",
                    "This workflow registers the file, preprocesses it, and creates a map layer. Visibility, default style, and later remote-sensing product standardization can be maintained in Data Inventory and downstream governance modules.",
                  )}
                />
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("数据分类", "Data category")}
                </Typography.Title>
                <Select
                  showSearch
                  optionFilterProp="label"
                  disabled
                  value={rasterCategoryCode}
                  options={categoryOptions}
                  onChange={setRasterCategoryCode}
                  style={{ width: "100%" }}
                />
                <Alert
                  type="info"
                  showIcon
                  title={l(
                    "具有坐标信息的影像自动归入地理数据",
                    "Georeferenced imagery is classified as geographic data",
                  )}
                  description={l(
                    "栅格导入会验证坐标参考系统，并创建可在地理工作台加载的图层。",
                    "Raster import validates the coordinate reference system and creates a map layer.",
                  )}
                  style={{ marginTop: 10 }}
                />
              </section>

              <Descriptions
                size="small"
                bordered
                column={2}
                className="import-stats"
              >
                <Descriptions.Item label={l("文件名", "File name")}>
                  {rasterFile.name}
                </Descriptions.Item>
                <Descriptions.Item label={l("文件类型", "File type")}>
                  {rasterPreview?.sourceFormat ??
                    rasterFileExtensionLabel(rasterFile.name)}
                </Descriptions.Item>
                <Descriptions.Item label={l("像素尺寸", "Pixel dimensions")}>
                  {rasterDimensions
                    ? `${rasterDimensions.width} x ${rasterDimensions.height}`
                    : "-"}
                </Descriptions.Item>
                <Descriptions.Item label={l("大小上限", "Size limit")}>
                  {bootstrap.limits.uploadMaxMb} MB
                </Descriptions.Item>
                <Descriptions.Item label={l("坐标系", "CRS")}>
                  {rasterPreview?.metadata.coordinateSystem ||
                    l("未识别", "Not detected")}
                </Descriptions.Item>
                <Descriptions.Item label={l("波段数", "Band count")}>
                  {rasterPreview?.metadata.bands.length ?? "-"}
                </Descriptions.Item>
              </Descriptions>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("栅格数据名称", "Raster data name")}
                </Typography.Title>
                <Input
                  aria-label={l("栅格数据名称", "Raster data name")}
                  value={rasterName}
                  onChange={(event) => setRasterName(event.target.value)}
                  placeholder={l(
                    "栅格数据名称，默认取文件名",
                    "Raster data name; defaults to the file name",
                  )}
                  disabled={rasterUploading}
                />
              </section>

              <section className="import-section">
                <Typography.Title level={5}>
                  {l("预处理与默认显示", "Preprocessing and default display")}
                </Typography.Title>
                <div className="import-config-grid">
                  <div>
                    <Typography.Text>
                      {l("栅格类型", "Raster type")}
                    </Typography.Text>
                    <Select
                      value={rasterKind}
                      style={{ width: "100%", marginTop: 6 }}
                      options={[
                        {
                          value: "imagery",
                          label: l(
                            "多波段遥感影像",
                            "Multiband remote-sensing imagery",
                          ),
                        },
                        {
                          value: "continuous",
                          label: l(
                            "连续型指标/高程",
                            "Continuous indicator / elevation",
                          ),
                        },
                        {
                          value: "categorical",
                          label: l("分类栅格", "Categorical raster"),
                        },
                      ]}
                      onChange={(value) => {
                        setRasterKind(value);
                        setRasterResampling(
                          value === "categorical" ? "nearest" : "bilinear",
                        );
                      }}
                    />
                  </div>
                  <div>
                    <Typography.Text>
                      {l("重采样方式", "Resampling")}
                    </Typography.Text>
                    <Select
                      value={rasterResampling}
                      style={{ width: "100%", marginTop: 6 }}
                      options={[
                        {
                          value: "nearest",
                          label: l(
                            "最近邻（分类数据）",
                            "Nearest neighbour (categorical data)",
                          ),
                        },
                        {
                          value: "bilinear",
                          label: l(
                            "双线性（连续影像）",
                            "Bilinear (continuous imagery)",
                          ),
                        },
                        {
                          value: "cubic",
                          label: l(
                            "三次卷积（高质量影像）",
                            "Cubic convolution (high-quality imagery)",
                          ),
                        },
                      ]}
                      onChange={setRasterResampling}
                      disabled={rasterKind === "categorical"}
                    />
                    {rasterKind === "categorical" ? (
                      <Typography.Text type="secondary">
                        {l(
                          "分类栅格固定使用最近邻，避免缩放时产生不存在的类别值。",
                          "Categorical rasters always use nearest-neighbour resampling to avoid creating nonexistent classes during scaling.",
                        )}
                      </Typography.Text>
                    ) : null}
                  </div>
                </div>

                {(rasterPreview?.metadata.bands.length ?? 0) >= 3 && (
                  <div style={{ marginTop: 14 }}>
                    <Space wrap>
                      <Typography.Text>
                        {l("RGB 波段：", "RGB bands: ")}
                      </Typography.Text>
                      {[0, 1, 2].map((index) => (
                        <Select
                          key={index}
                          aria-label={`RGB 波段 ${index + 1}`}
                          value={
                            (
                              rasterDefaultRules.bands as number[] | undefined
                            )?.[index] ?? index + 1
                          }
                          style={{ width: 110 }}
                          options={(rasterPreview?.metadata.bands ?? []).map(
                            (band) => ({
                              value: band.band,
                              label: `Band ${band.band}`,
                            }),
                          )}
                          onChange={(band) => updateRasterRgbBand(index, band)}
                        />
                      ))}
                      {(rasterPreview?.metadata.bands.length ?? 0) >= 8 && (
                        <Button
                          onClick={() =>
                            setRasterDefaultRules((rules) => ({
                              ...rules,
                              mode: "rgb",
                              bands: [5, 3, 2],
                            }))
                          }
                        >
                          {l(
                            "WorldView 8 波段自然色",
                            "WorldView 8-band natural colour",
                          )}
                        </Button>
                      )}
                    </Space>
                  </div>
                )}
              </section>

              {rasterUploading && (
                <section className="import-section raster-upload-progress">
                  <Space>
                    <Tag color="processing">{l("正在上传", "Uploading")}</Tag>
                    <Typography.Text type="secondary">
                      {l(
                        `已上传 ${rasterUploadProgress}%`,
                        `${rasterUploadProgress}% uploaded`,
                      )}
                    </Typography.Text>
                  </Space>
                  <Progress
                    percent={rasterUploadProgress}
                    status="active"
                    showInfo
                  />
                </section>
              )}
            </div>
          )}

          {currentStep === 1 && importKind === "vector" && vectorFile && (
            <VectorImportWorkflow
              projectTagId={uploadProjectId}
              key={`${vectorFile.name}-${vectorFile.lastModified}`}
              file={vectorFile}
              domainDefinitions={domainDefinitions}
              categoryOptions={categoryOptions}
              availableAccessGroups={availableAccessGroups}
              onReset={resetImportState}
              onCompleted={setVectorResult}
            />
          )}

          {currentStep === 1 && importKind === "unsupported" && (
            <section className="import-step-pane">
              <Result
                status="warning"
                title={l(
                  "暂不支持自动导入该文件类型",
                  "Automatic import is not supported for this file type",
                )}
                subTitle={
                  unsupportedFile
                    ? l(
                        `${unsupportedFile.name} 未匹配到当前可用的表格、栅格或矢量导入流程。`,
                        `${unsupportedFile.name} did not match any available tabular, raster, or vector import workflow.`,
                      )
                    : l(
                        "未匹配到当前可用的导入流程。",
                        "No available import workflow matched this file.",
                      )
                }
                extra={[
                  <Button
                    key="again"
                    type="primary"
                    icon={<ReloadOutlined />}
                    onClick={resetImportState}
                  >
                    {l("重新选择文件", "Choose another file")}
                  </Button>,
                ]}
              />
            </section>
          )}

          {currentStep === 2 && importKind === "tabular" && preview && (
            <section className="import-step-pane">
              {result ? (
                <Result
                  status="success"
                  title={l("数据导入完成", "Data import completed")}
                  subTitle={l(
                    `已导入 ${result.resourceName}，共 ${result.importedRows} 行。`,
                    `${result.resourceName} imported with ${result.importedRows} rows.`,
                  )}
                  extra={[
                    <Button
                      key="view"
                      onClick={() => {
                        const open = () =>
                          navigate(
                            result.mode === "table" ? "/nongeo" : "/map",
                          );
                        if (projectContext)
                          projectContext.choose(String(uploadProjectId), open);
                        else open();
                      }}
                    >
                      {result.mode === "table"
                        ? l("查看非地理数据", "View non-geographic data")
                        : l("查看地理数据", "View geographic data")}
                    </Button>,
                    <Button
                      key="again"
                      type="primary"
                      icon={<ReloadOutlined />}
                      onClick={resetImportState}
                    >
                      {l("继续导入", "Import another file")}
                    </Button>,
                  ]}
                />
              ) : (
                <>
                  <Space className="import-actions import-actions-top">
                    <Button onClick={() => setCurrentStep(1)}>
                      {l("上一步", "Previous")}
                    </Button>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined style={{ fontSize: 16 }} />}
                      loading={importing}
                      onClick={handleImport}
                    >
                      {l("提交导入", "Submit import")}
                    </Button>
                  </Space>

                  <section className="import-section">
                    <Typography.Title level={5}>
                      {l("数据预览", "Data preview")}
                    </Typography.Title>
                    {duplicateTarget && (
                      <DuplicateTargetAlert
                        target={duplicateTarget}
                        confirmed={duplicateNameConfirmed}
                      />
                    )}
                    <div className="import-preview-scroll">
                      <Table
                        size="small"
                        rowKey="previewRowKey"
                        pagination={false}
                        scroll={{ x: "max-content" }}
                        dataSource={previewRows}
                        columns={previewColumns}
                      />
                    </div>
                  </section>

                  <section className="import-section">
                    <Typography.Title level={5}>
                      {l("字段元数据", "Field metadata")}
                    </Typography.Title>
                    {selectedDomain && (
                      <Alert
                        type="info"
                        showIcon
                        title={`${selectedDomain.name}字段整理建议`}
                        description={
                          <Space size={[4, 4]} wrap>
                            {domainFieldHints[selectedDomain.code].map(
                              (field) => (
                                <Tag key={field}>{field}</Tag>
                              ),
                            )}
                          </Space>
                        }
                      />
                    )}
                    <Table
                      size="small"
                      rowKey="column"
                      pagination={false}
                      dataSource={preview.columns.map((column) => ({
                        column,
                        description: fieldMetadata[column] ?? "",
                        included: includedColumns.includes(column),
                      }))}
                      columns={[
                        {
                          title: l("上传", "Include"),
                          dataIndex: "included",
                          width: 64,
                          render: (_, record) => (
                            <Checkbox
                              checked={includedColumns.includes(record.column)}
                              onChange={(event) => {
                                setIncludedColumns((current) =>
                                  event.target.checked
                                    ? [...current, record.column]
                                    : current.filter(
                                        (column) => column !== record.column,
                                      ),
                                );
                              }}
                            />
                          ),
                        },
                        {
                          title: l("字段", "Field"),
                          dataIndex: "column",
                          width: 150,
                        },
                        {
                          title: l("描述", "Description"),
                          dataIndex: "description",
                          render: (_, record) => (
                            <Input.TextArea
                              autoSize={{ minRows: 1, maxRows: 4 }}
                              placeholder={l(
                                "中文名称、单位、计算方式、数据来源等，可留空",
                                "Name, unit, calculation, source, etc.; optional",
                              )}
                              value={fieldMetadata[record.column] ?? ""}
                              onChange={(event) =>
                                setFieldMetadata((current) => ({
                                  ...current,
                                  [record.column]: event.target.value,
                                }))
                              }
                            />
                          ),
                        },
                      ]}
                    />
                  </section>
                </>
              )}
            </section>
          )}

          {currentStep === 2 && importKind === "raster" && (
            <section className="import-step-pane">
              {rasterJob ? (
                <section className="raster-import-progress">
                  <Space>
                    <Tag color={rasterJobTagColor(rasterJob)}>
                      {rasterJobStatusText(rasterJob, english)}
                    </Tag>
                    <Typography.Text type="secondary">
                      {l("任务 ID：", "Task ID: ")}
                      {rasterJob.id}
                    </Typography.Text>
                  </Space>
                  <section className="import-section raster-upload-progress">
                    <Typography.Text strong>
                      {l("上传进度", "Upload progress")}
                    </Typography.Text>
                    <Progress
                      percent={completedRasterUploadProgress}
                      status="success"
                    />
                  </section>
                  <section className="import-section raster-gdal-progress">
                    <Typography.Text strong>
                      {l("GDAL 预处理进度", "GDAL preprocessing progress")}
                    </Typography.Text>
                    <Progress
                      percent={rasterJob.progressPercent}
                      status={rasterJobProgressStatus(rasterJob)}
                    />
                  </section>
                  {rasterJob.status === "ready" && (
                    <Alert
                      type="success"
                      showIcon
                      title={l(
                        "栅格预处理完成",
                        "Raster preprocessing completed",
                      )}
                      description={l(
                        "数据资源和地图图层已在后台登记，可在存量数据或地图数据目录中查看。",
                        "The data resource and map layer have been registered and can be viewed in Data Inventory or the map data catalog.",
                      )}
                    />
                  )}
                  {rasterJob.status === "failed" && (
                    <Alert
                      type="error"
                      showIcon
                      title={l("栅格预处理失败", "Raster preprocessing failed")}
                      description={
                        rasterJob.error ||
                        l("后台任务执行失败", "Background task failed")
                      }
                    />
                  )}
                  {rasterJob.messages.length > 0 && (
                    <pre className="raster-import-log">
                      {rasterJob.messages.slice(-12).join("\n")}
                    </pre>
                  )}
                  {!isActiveRasterJob(rasterJob) && (
                    <Space className="import-actions import-actions-top">
                      <Button
                        type="primary"
                        icon={<ReloadOutlined />}
                        onClick={resetImportState}
                      >
                        {l("继续导入", "Import another file")}
                      </Button>
                    </Space>
                  )}
                </section>
              ) : (
                <Result
                  status="info"
                  title={l(
                    "尚未提交栅格预处理任务",
                    "Raster preprocessing task has not been submitted",
                  )}
                  extra={[
                    <Button key="back" onClick={() => setCurrentStep(1)}>
                      {l("返回配置", "Back to settings")}
                    </Button>,
                  ]}
                />
              )}
            </section>
          )}
        </Form>
      </ProCard>

      <Modal
        title={l("上传数据校验结果", "Upload validation results")}
        open={issuesOpen}
        onCancel={() => setIssuesOpen(false)}
        cancelButtonProps={{ style: { display: "none" } }}
        okText={
          hasBlockingIssues
            ? ""
            : hasIgnorableUncertainty
              ? pendingIssueAction === "continue"
                ? l("忽略并进入预览", "Ignore and preview")
                : l("忽略并继续导入", "Ignore and continue import")
              : ""
        }
        confirmLoading={importing}
        okButtonProps={{
          style:
            hasBlockingIssues || !hasIgnorableUncertainty
              ? { display: "none" }
              : undefined,
          disabled: hasIgnorableUncertainty && !ignoreCoordinateUncertainty,
        }}
        onOk={handleIssueConfirm}
      >
        <Alert
          type={hasBlockingIssues ? "error" : "warning"}
          showIcon
          title={
            hasBlockingIssues
              ? l(
                  "检测到阻止上传的问题",
                  "Issues blocking upload were detected",
                )
              : l("检测到可确认忽略的问题", "Ignorable issues were detected")
          }
          description={
            hasBlockingIssues
              ? l(
                  "请修正以下问题后重新预检或提交。",
                  "Fix the issues below before preflighting or submitting again.",
                )
              : l(
                  "坐标不确定性差距可能影响空间分析精度，确认后可继续。",
                  "Coordinate uncertainty differences may affect spatial-analysis accuracy. Confirm to continue.",
                )
          }
        />
        <Table
          className="import-issue-table"
          size="small"
          rowKey={(record) => `${record.code}-${record.message}`}
          pagination={false}
          dataSource={validationIssues}
          columns={[
            {
              title: l("问题项", "Issue"),
              dataIndex: "message",
              render: (value, record) => (
                <Space orientation="vertical" size={2}>
                  <Typography.Text>{value}</Typography.Text>
                  <Space size={4} align="center">
                    <Tag color={record.blocking ? "red" : "gold"}>
                      {record.blocking
                        ? l("必须修正", "Must fix")
                        : l("可忽略", "Ignorable")}
                    </Tag>
                    {record.code === "coordinate_uncertainty" && (
                      <Tooltip
                        title={l(
                          "系统会根据经纬度小数位数估算坐标量化误差；该项表示最大误差与最小误差的比值过大，可能说明同一批数据的坐标精度不一致。",
                          "The system estimates coordinate quantization error from longitude/latitude decimal places. A large maximum-to-minimum ratio may indicate inconsistent coordinate precision within the dataset.",
                        )}
                      >
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <QuestionCircleOutlined style={{ fontSize: 14 }} />
                          }
                          aria-label={l(
                            "坐标不确定性差距说明",
                            "Coordinate uncertainty explanation",
                          )}
                        />
                      </Tooltip>
                    )}
                  </Space>
                </Space>
              ),
            },
          ]}
        />
        {hasIgnorableUncertainty && !hasBlockingIssues && (
          <Checkbox
            checked={ignoreCoordinateUncertainty}
            onChange={(event) =>
              setIgnoreCoordinateUncertainty(event.target.checked)
            }
          >
            {l(
              "我已了解坐标不确定性差距，并继续",
              "I understand the coordinate uncertainty difference and want to continue",
            )}
          </Checkbox>
        )}
      </Modal>
      <Modal
        title={l("确认重复数据名称", "Confirm duplicate data name")}
        open={duplicateConfirmOpen}
        okText={l("确认继续导入", "Confirm and continue")}
        cancelText={l("返回修改", "Back to edit")}
        onCancel={() => setDuplicateConfirmOpen(false)}
        onOk={() => {
          setDuplicateNameConfirmed(true);
          setDuplicateConfirmOpen(false);
          if (validationIssues.length) {
            setPendingIssueAction("continue");
            setIssuesOpen(true);
            return;
          }
          message.success(
            l(
              "已确认重复数据名称，后端将新建数据记录",
              "Duplicate name confirmed; a new data record will be created",
            ),
          );
          setCurrentStep(2);
        }}
      >
        {duplicateTarget && (
          <Alert
            type="warning"
            showIcon
            title={l("数据名重复", "Duplicate data name")}
            description={
              <Space orientation="vertical" size={4}>
                <Typography.Text>{duplicateTarget.message}</Typography.Text>
                <Typography.Text type="secondary">
                  {l(
                    "继续导入会创建新的数据记录，不会覆盖已有数据。",
                    "Continuing creates a new data record and does not overwrite existing data.",
                  )}
                </Typography.Text>
              </Space>
            }
          />
        )}
      </Modal>
      <Modal
        title={l("离开数据导入页面？", "Leave the data-import page?")}
        open={pendingNavigationPath !== null}
        okText={l("确认离开", "Leave")}
        cancelText={l("继续导入", "Continue importing")}
        okType="danger"
        onOk={() => {
          const nextPath = pendingNavigationPath;
          setPendingNavigationPath(null);
          if (nextPath) {
            allowNavigationRef.current = true;
            navigate(nextPath);
          }
        }}
        onCancel={() => setPendingNavigationPath(null)}
      >
        <Alert
          type="warning"
          showIcon
          title={l("当前导入尚未完成", "The current import is not complete")}
          description={l(
            unfinishedImportWarning,
            "Leaving now will discard the current import progress.",
          )}
        />
      </Modal>
    </div>
  );
}

function DomainDetail({ domain }: { domain: DomainDefinition }) {
  const english = useEnglishLanguage();
  return (
    <div className="import-domain-detail">
      <div>
        <Typography.Text strong>
          {english ? "Recommended resource forms" : "推荐资源形态"}
        </Typography.Text>
        <Space size={[4, 4]} wrap>
          {domain.recommendedResourceTypes.map((type) => (
            <Tag key={type}>
              {english
                ? ((
                    {
                      vector: "Vector",
                      raster: "Raster",
                      table: "Table",
                      document: "Document",
                      image: "Image",
                      gene: "Gene",
                    } as Record<string, string>
                  )[type] ?? type)
                : (resourceTypeLabels[type] ?? type)}
            </Tag>
          ))}
        </Space>
      </div>
      <div>
        <Typography.Text strong>
          {english ? "Downstream standardized entities" : "后续标准化实体"}
        </Typography.Text>
        <Typography.Text type="secondary">
          {domain.coreEntities.join(english ? ", " : "、")}
        </Typography.Text>
      </div>
    </div>
  );
}

function ImportStorageSummary({
  mode,
  domain,
}: {
  mode?: ImportStorageMode;
  domain?: DomainDefinition;
}) {
  const english = useEnglishLanguage();
  const steps = storageSteps(mode, domain, english);
  return (
    <div className="import-storage-summary">
      {steps.map((step) => (
        <article key={step.title} className="import-storage-item">
          <Tag color={step.color}>{step.label}</Tag>
          <Typography.Text strong>{step.title}</Typography.Text>
          <Typography.Text type="secondary">{step.description}</Typography.Text>
        </article>
      ))}
    </div>
  );
}

function storageSteps(
  mode?: ImportStorageMode,
  _domain?: DomainDefinition,
  english = false,
) {
  const l = (zh: string, en: string) => localText(english, zh, en);
  const spatial = mode === "geographic" || mode === "raster";
  return [
    {
      label: l("数据分类", "Data category"),
      color: spatial ? "blue" : "cyan",
      title: spatial
        ? l("地理数据", "Geographic data")
        : l("非地理数据", "Non-geographic data"),
      description: spatial
        ? l(
            "验证坐标信息后创建地图图层，可进入地理工作台。",
            "Validate coordinates and create a layer for the map workspace.",
          )
        : l(
            "保留原始字段与记录，支持表格查阅、查询和分析。",
            "Preserve fields and records for table queries and analysis.",
          ),
    },
  ];
}

function shouldBlockImport(
  issues: ImportValidationIssue[],
  ignoreCoordinateUncertainty: boolean,
) {
  return issues.some(
    (issue) =>
      issue.blocking ||
      (issue.code === "coordinate_uncertainty" && !ignoreCoordinateUncertainty),
  );
}

function isActiveRasterJob(job: RasterJob) {
  return job.status === "queued" || job.status === "running";
}

function rasterJobStatusText(job: RasterJob, english = false) {
  switch (job.status) {
    case "queued":
      return english ? "Queued" : "等待处理";
    case "running":
      return english ? "Preprocessing" : "正在预处理";
    case "ready":
      return english ? "Completed" : "处理完成";
    case "failed":
      return english ? "Failed" : "处理失败";
    default:
      return job.status;
  }
}

function rasterJobTagColor(job: RasterJob) {
  if (job.status === "ready") {
    return "green";
  }
  if (job.status === "failed") {
    return "red";
  }
  return "processing";
}

function rasterJobProgressStatus(job: RasterJob) {
  if (job.status === "ready") {
    return "success";
  }
  if (job.status === "failed") {
    return "exception";
  }
  return "active";
}

function fileStem(name: string) {
  return name.replace(/\.[^.]+$/, "");
}

function inferDomainTypeFromFile(
  fileName: string,
  preview?: ImportPreview,
): DataDomainType {
  if (/\.(tif|tiff|img|vrt|dat|bsq|bil|bip)$/i.test(fileName)) {
    return "remote_sensing";
  }
  const text = `${fileName} ${preview?.columns.join(" ") ?? ""}`.toLowerCase();
  const rules: Array<{ type: DataDomainType; keywords: string[] }> = [
    {
      type: "remote_sensing",
      keywords: [
        "遥感",
        "影像",
        "ndvi",
        "npp",
        "landsat",
        "sentinel",
        "无人机",
      ],
    },
    {
      type: "genome",
      keywords: [
        "基因组",
        "genome",
        "sequencing",
        "sequence",
        "snp",
        "vcf",
        "assembly",
      ],
    },
    {
      type: "molecular",
      keywords: ["分子", "pcr", "ssr", "rna", "marker", "引物", "实验"],
    },
    {
      type: "germplasm",
      keywords: ["种质", "dna样品", "dna", "样品清单", "核心资源", "保存材料"],
    },
    {
      type: "community",
      keywords: ["群落", "样方", "多样性", "盖度", "重要值", "功能性状"],
    },
    {
      type: "population",
      keywords: ["种群", "population", "群体", "分布区"],
    },
    {
      type: "individual",
      keywords: ["个体", "单株", "植株", "性别", "胸径", "树高"],
    },
    {
      type: "field_survey",
      keywords: ["野外", "调查", "样点", "路线", "采集", "观测"],
    },
  ];
  const matched = rules.find((rule) =>
    rule.keywords.some((keyword) => text.includes(keyword.toLowerCase())),
  );
  if (matched) {
    return matched.type;
  }
  return "other";
}

function fileExtension(name: string) {
  const dotIndex = name.lastIndexOf(".");
  return dotIndex >= 0 ? name.slice(dotIndex).toLowerCase() : "";
}

function detectImportKind(file: File): ImportKind {
  const extension = fileExtension(file.name);
  if ([".csv", ".xls", ".xlsx"].includes(extension)) {
    return "tabular";
  }
  if (
    [".tif", ".tiff", ".img", ".vrt", ".dat", ".bsq", ".bil", ".bip"].includes(
      extension,
    )
  ) {
    return "raster";
  }
  if (
    [".geojson", ".json", ".gpkg", ".kml", ".kmz", ".shp", ".zip"].includes(
      extension,
    )
  ) {
    return "vector";
  }
  return "unsupported";
}

function rasterFileExtensionLabel(name: string) {
  const extension = fileExtension(name);
  switch (extension) {
    case ".tif":
    case ".tiff":
      return "GeoTIFF";
    case ".img":
      return "IMG";
    case ".vrt":
      return "VRT";
    case ".dat":
    case ".bsq":
    case ".bil":
    case ".bip":
      return "ENVI 栅格";
    default:
      return extension || "未知";
  }
}

function rasterFileNeedsCompanions(name: string) {
  return /\.(dat|bsq|bil|bip|vrt)$/i.test(name);
}

function DuplicateTargetAlert({
  target,
  confirmed,
}: {
  target: ImportDuplicateTarget;
  confirmed: boolean;
}) {
  const english = useEnglishLanguage();
  return (
    <Alert
      type="warning"
      showIcon
      title={
        confirmed
          ? english
            ? "Duplicate data name confirmed"
            : "已确认重复数据名称"
          : english
            ? "Duplicate data name"
            : "数据名重复"
      }
      description={
        <Space orientation="vertical" size={4}>
          <Typography.Text>{target.message}</Typography.Text>
          <Typography.Text type="secondary">
            {confirmed
              ? english
                ? "Continuing creates a new data record and does not overwrite existing data."
                : "继续导入会新建数据记录，不会覆盖已有数据。"
              : english
                ? `Data name: ${target.targetName}`
                : `数据名称：${target.targetName}`}
          </Typography.Text>
        </Space>
      }
    />
  );
}

function withFixedAccessScopes(values: AccessScopeId[] = []): AccessScopeId[] {
  const optionalValues = values.filter((value) => value !== selfAccessScopeId);
  return [selfAccessScopeId, ...optionalValues];
}

function realAccessGroupIds(values: AccessScopeId[] = []): number[] {
  return values.filter((value): value is number => typeof value === "number");
}

function importIssuesFromError(error: unknown): ImportValidationIssue[] {
  if (!(error instanceof ApiError)) {
    return [];
  }
  const data = error.data as { issues?: ImportValidationIssue[] } | null;
  return Array.isArray(data?.issues) ? data.issues : [];
}

type ImportAccessGroup = AdminDataResourceAccessGroup;
