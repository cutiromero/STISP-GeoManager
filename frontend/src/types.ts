import type {
  AdminDashboardResponse,
  AdminDashboardServerResponse,
  AdminBackupOverviewResponse,
  AdminBackupRunCreateRequest,
  AdminBackupRunListResponse,
  AdminBackupSettingsResponse,
  AdminBackupSettingsUpdateRequest,
  AdminBackupTargetTestRequest,
  AdminBackupTargetTestResponse,
  AdminDataResourceListResponse,
  AdminDataResourceGroupUpdateRequest,
  AdminDataResourceUpdateRequest,
  AdminProfilePasswordRequest,
  AdminProfilePermissionsRequest,
  AdminProfileResponse,
  AdminProfileUpdateRequest,
  AdminSettingsResponse,
  AdminSettingsUpdateRequest,
  AdminSystemLogResponse,
  AsyncJobResponse,
  BaseUserInfo,
  BootstrapResponse,
  CoordinateStats,
  DataDomainType,
  DataSchemaSummaryResponse,
  DataResource,
  Directory,
  ExportAdminDataResourcesData,
  ExportItem,
  ExportRequest,
  GermplasmAccessionListResponse,
  FieldInfo,
  AttributeFilter as GeneratedAttributeFilter,
  GeoJsonFeatureCollection as GeneratedGeoJsonFeatureCollection,
  SpatialFilter as GeneratedSpatialFilter,
  WorkspaceSceneSnapshot as GeneratedWorkspaceSceneSnapshot,
  GeoJsonGeometry,
  ImportCommitResponse,
  ImportPreviewResponse,
  ImportValidateResponse,
  LayerListResponse,
  ListAdminBackupRunsData,
  ListAdminDataResourcesData,
  ListGermplasmAccessionsData,
  ListAdminOperationLogsData,
  ListAdminSystemLogsData,
  ListAdminWorkspacesData,
  QueryRequest,
  QueryResponse,
  RasterBandInfo,
  RasterDataset,
  RasterImportCommitRequest,
  RasterImportPreviewResponse,
  RasterRenderResult,
  RegisterRequest,
  ResourceListItem,
  ResourceProfileResponse,
  ResourceVisualizationSummaryResponse,
  SearchResponse,
  UniqueValuesResponse,
  UserInfo,
  ValidationIssue,
  ValidationWarning,
  VectorImportCommitRequest,
  VectorImportCommitResponse,
  VectorImportPreviewResponse,
  VectorImportValidateRequest,
  VectorImportValidateResponse,
  AdminWorkspaceSceneListResponse,
  AdminWorkspaceSceneUpdateRequest,
  WorkspaceScene,
  WorkspaceSceneListResponse,
} from "./api/generated";

export type {
  AdminDataResourceAccessGroup,
  AdminDataResource,
  AdminDataResourceGroup,
  AdminOperationLog,
  AdminPermissionItem,
  AdminBackupRun,
  BackupPlanType,
  BackupRunStatus,
  BackupTargetType,
  AdminSystemLogFile,
  AdminWorkspaceScene,
  AdminWorkspaceSceneListResponse,
  AdminWorkspaceSceneUpdateRequest,
  DataDomainDefinition,
  DataResource,
  DataDomainType,
  DataSchemaCatalogNode,
  GeoJsonGeometry,
  Group,
  GroupCreateRequest,
  GroupListResponse,
  GroupUpdateRequest,
  ImportDuplicateTarget,
  LoginOverviewResponse,
  LoginOverviewStatus,
  RasterRenderResult,
  RegisterRequest,
  RegisterResponse,
  RoleApplicationListItem,
  RoleApplicationListResponse,
  RoleApplicationReviewRequest,
  RoleApplicationStatus,
  ResourceListItem,
  ResultArtifact,
  ResultArtifactCreatePayload,
  ResultArtifactDeleteResponse,
  ResultArtifactListResponse,
  ResultArtifactSourceType,
  ResultArtifactStatus,
  ResultArtifactType,
  ResultArtifactUpdateRequest,
  UserCreateRequest,
  UserCreateResponse,
  UserGroupUpdateRequest,
  UserListResponse,
  UserPasswordResetResponse,
  UserPermissionUpdateRequest,
  UserUpdateRequest,
  WorkspaceScene,
  WorkspaceSceneSummary,
  WorkspaceSceneCreateRequest,
  WorkspaceSceneListResponse,
  WorkspaceSceneUpdateRequest,
  MapComposition,
  MapCompositionCreateRequest,
  MapCompositionDeleteResponse,
  MapCompositionUpdateRequest,
  MapCompositionVersion,
  MapCompositionVersionCreatePayload,
  MapCompositionListResponse,
  MapCompositionPublishRequest,
  MapCompositionRestoreProjectRequest,
  MapCompositionRestoreProjectResponse,
  MapCompositionRestoreWarning,
} from "./api/generated";

import type {
  GroupSymbolization,
  RasterSymbolization,
  VectorSymbolization,
} from "./symbolization";

export type Bootstrap = BootstrapResponse;
export type BaseUser = BaseUserInfo;
export type User = UserInfo;
export type AdminProfile = AdminProfileResponse;
export type AdminProfileUpdate = AdminProfileUpdateRequest;
export type AdminProfilePermissionsUpdate = AdminProfilePermissionsRequest;
export type AdminProfilePasswordUpdate = AdminProfilePasswordRequest;
export type AdminOperationLogQuery = NonNullable<
  ListAdminOperationLogsData["query"]
>;
export type AdminSystemLog = AdminSystemLogResponse;
export type AdminSystemLogQuery = NonNullable<ListAdminSystemLogsData["query"]>;
export type AdminBackupOverview = AdminBackupOverviewResponse;
export type AdminBackupSettings = AdminBackupSettingsResponse;
export type AdminBackupSettingsUpdate = AdminBackupSettingsUpdateRequest;
export type AdminBackupTargetTestPayload = AdminBackupTargetTestRequest;
export type AdminBackupTargetTestResult = AdminBackupTargetTestResponse;
export type AdminBackupRunCreate = AdminBackupRunCreateRequest;
export type AdminBackupRunList = AdminBackupRunListResponse;
export type AdminBackupRunFilters = NonNullable<
  ListAdminBackupRunsData["query"]
>;
export type AdminDashboard = AdminDashboardResponse;
export type AdminDashboardServer = AdminDashboardServerResponse;
export type AdminSettings = AdminSettingsResponse;
export type AdminSettingsUpdate = AdminSettingsUpdateRequest;
export type AdminDataResourceList = AdminDataResourceListResponse;
export type AdminDataResourceUpdate = AdminDataResourceUpdateRequest;
export type AdminDataResourceGroupUpdate = AdminDataResourceGroupUpdateRequest;
export type AdminDataResourceFilters = NonNullable<
  ListAdminDataResourcesData["query"]
>;
export type AdminDataResourceExportFilters = NonNullable<
  ExportAdminDataResourcesData["query"]
>;
export type DataSchemaSummary = DataSchemaSummaryResponse;
export type GermplasmAccessionList = GermplasmAccessionListResponse;
export type GermplasmAccessionItem =
  GermplasmAccessionListResponse["items"][number];
export type GermplasmAccessionFilters = NonNullable<
  ListGermplasmAccessionsData["query"]
>;
export type AdminWorkspaceList = AdminWorkspaceSceneListResponse;
export type AdminWorkspaceUpdate = AdminWorkspaceSceneUpdateRequest;
export type AdminWorkspaceFilters = NonNullable<
  ListAdminWorkspacesData["query"]
>;
export type WorkspaceAccessGroup =
  WorkspaceSceneListResponse["availableAccessGroups"][number];
export type ResourceField = FieldInfo;
export type ImportCoordinateStats = CoordinateStats;
export type ImportValidationIssue = ValidationIssue;
export interface ImportWorkbookSheet {
  name: string;
  rowCount: number;
  columnCount: number;
  isGeographic: boolean;
  longitudeColumn?: string | null;
  latitudeColumn?: string | null;
  suggestedName?: string;
}

export type ImportPreview = ImportPreviewResponse & {
  activeSheetName?: string | null;
  sheets?: ImportWorkbookSheet[];
};
export type ImportValidateResult = ImportValidateResponse;
export type ImportCommitResult = ImportCommitResponse;
export type VectorImportPreview = VectorImportPreviewResponse;
export type VectorImportValidatePayload = VectorImportValidateRequest;
export type VectorImportValidateResult = VectorImportValidateResponse;
export type VectorImportCommitPayload = VectorImportCommitRequest;
export type VectorImportCommitResult = VectorImportCommitResponse;
export type RasterBandMetadata = RasterBandInfo;
type RasterDatasetProfile = RasterDataset;
export type GeoJsonValidationWarning = ValidationWarning;
export type ResourceQueryResult = QueryResponse;
export type ExportLayerItem = ExportItem;
export type ExportLayersPayload = ExportRequest;
export type DataCatalog = Directory;
export type MapLayerListItem = LayerListResponse["items"][number];
export type RasterUniqueValuesResult = UniqueValuesResponse;
export type RasterJob = AsyncJobResponse;
export type RasterImportPreview = RasterImportPreviewResponse;
export type RasterImportCommitPayload = RasterImportCommitRequest;
export type SearchResult = SearchResponse;
export type WorkspaceSceneKind = WorkspaceScene["kind"];
export type SavedWorkspaceLayer = {
  id: string;
  name: string;
  layerType: LoadedLayer["layerType"];
  sourceResource: ResourceListItem;
  geometryType: string;
  visible: boolean;
  summary: string;
  metadata: Record<string, string | number | boolean | null | undefined>;
  symbolization: LoadedLayer["symbolization"];
  fields: ResourceField[];
  query?: {
    attributeFilters: AttributeFilter[];
    spatialFilter: SpatialFilter | null;
  };
  tileUrl?: string;
  tileMinZoom?: number;
  tileMaxZoom?: number;
  tileSampling?: RasterRenderResult["tileSampling"];
  imageCoordinates?: RasterRenderResult["imageCoordinates"];
  rasterDatasetId?: number;
  rasterLayerId?: number | null;
  rasterKind?: RasterDatasetProfile["rasterKind"];
  rasterMetadata?: RasterDatasetProfile["metadata"];
  renderStatus?: string;
  renderProgress?: number;
  renderMessages?: string[];
};
export type SavedWorkspaceLayerGroup = Omit<LoadedLayerGroup, "children"> & {
  children: SavedWorkspaceLayer[];
};
export type WorkspaceSceneSnapshot = GeneratedWorkspaceSceneSnapshot & {
  version?: number;
  groups?: SavedWorkspaceLayerGroup[] | LoadedLayerGroup[];
  selectedLayerId?: string | null;
  mapView?: MapViewState | null;
  savedAt?: string;
  basemapId?: string;
};

export type DataResourceProfile = ResourceProfileResponse;
export type ResourceVisualizationSummary = ResourceVisualizationSummaryResponse;

export type NonGeoScalar = string | number | boolean | null;
export type NonGeoFieldRole =
  | "identifier"
  | "category"
  | "measure"
  | "date"
  | "text"
  | "coordinate"
  | "unknown";
export type NonGeoTableRow = Record<string, NonGeoScalar>;

export interface NonGeoFieldProfile {
  name: string;
  type: string;
  label: string;
  description: string;
  unit: string;
  role: NonGeoFieldRole;
  nullable: boolean;
  nonNullCount: number;
  nullCount: number;
  completeness: number;
  uniqueCount: number;
  sampleValues: NonGeoScalar[];
  min?: number | null;
  max?: number | null;
  mean?: number | null;
}

export interface NonGeoTableQueryResult {
  resourceId: number;
  resourceName: string;
  totalCount: number;
  returnedCount: number;
  limit: number;
  offset: number;
  fields: Array<{
    name: string;
    type: string;
    nullable: boolean;
    sampleValues: NonGeoScalar[];
    description: string;
  }>;
  rows: NonGeoTableRow[];
}

export interface NonGeoAnalytics {
  resource: ResourceListItem;
  summary: {
    rowCount: number;
    analyzedRowCount: number;
    sampled: boolean;
    fieldCount: number;
    numericFieldCount: number;
    textFieldCount: number;
    categoricalFieldCount: number;
    completeness: number;
    updatedAt: string;
    suggestedView:
      | "species"
      | "community"
      | "traits"
      | "environment"
      | "generic";
  };
  fields: NonGeoFieldProfile[];
  categoricalDistributions: Array<{
    field: string;
    label: string;
    total: number;
    items: Array<{ value: NonGeoScalar; count: number; ratio: number }>;
  }>;
  numericDistributions: Array<{
    field: string;
    label: string;
    min: number;
    max: number;
    mean: number;
    median: number;
    q1: number;
    q3: number;
    bins: Array<{
      label: string;
      min: number;
      max: number;
      count: number;
      ratio: number;
    }>;
  }>;
  correlation: { fields: string[]; values: number[][] } | null;
  tablePreview: NonGeoTableQueryResult;
  insights: string[];
}

export interface NonGeoTableQueryPayload {
  limit?: number;
  offset?: number;
  sortField?: string | null;
  sortDirection?: "asc" | "desc";
}

export interface ImportCommitPayload {
  name: string;
  domainType: DataDomainType;
  categoryCode: string;
  sheetName?: string | null;
  tableName: string;
  importMode: "geographic" | "table";
  longitudeColumn?: string;
  latitudeColumn?: string;
  ignoreCoordinateUncertainty: boolean;
  duplicateConfirmed: boolean;
  includedColumns: string[];
  fieldMetadata: Record<string, string>;
  accessGroupIds: number[];
}

export interface ImportValidatePayload {
  name?: string;
  sheetName?: string | null;
  importMode: "geographic" | "table";
  tableName?: string;
  longitudeColumn?: string;
  latitudeColumn?: string;
}

export type AttributeFilter = GeneratedAttributeFilter & {
  id: string;
};

export type SpatialFilter = GeneratedSpatialFilter & {
  geometry: GeoJsonGeometry;
};

export type ResourceQueryPayload = Omit<
  QueryRequest,
  "attributeFilters" | "spatialFilter"
> & {
  attributeFilters: AttributeFilter[];
  spatialFilter: SpatialFilter | null;
};

export type GeoJsonFeatureCollection = GeneratedGeoJsonFeatureCollection & {
  warnings?: GeoJsonValidationWarning[];
};

export interface FeatureInfo {
  layerId: string;
  layerName: string;
  properties: Record<string, unknown>;
}

export interface MapViewState {
  center: [number, number];
  bounds: [number, number, number, number];
  zoom: number;
  bearing: number;
  pitch: number;
}

export interface LoadedVectorLayer {
  viewportOnly?: boolean;
  id: string;
  name: string;
  layerType: "vector";
  sourceResource: ResourceListItem;
  geojson: GeoJsonFeatureCollection;
  geometryType: string;
  visible: boolean;
  summary: string;
  metadata: Record<string, string | number | boolean | null | undefined>;
  symbolization: VectorSymbolization;
  fields: ResourceField[];
  query?: {
    attributeFilters: AttributeFilter[];
    spatialFilter: SpatialFilter | null;
  };
}

export interface LoadedRasterLayer {
  id: string;
  name: string;
  layerType: "raster";
  sourceResource: DataResource;
  tileUrl?: string;
  tileMinZoom?: number;
  tileMaxZoom?: number;
  tileSampling?: RasterRenderResult["tileSampling"];
  imageCoordinates?: RasterRenderResult["imageCoordinates"];
  rasterDatasetId?: number;
  rasterLayerId?: number | null;
  rasterKind?: RasterDatasetProfile["rasterKind"];
  rasterMetadata?: RasterDatasetProfile["metadata"];
  renderJobId?: string;
  renderStatus?: string;
  renderProgress?: number;
  renderMessages?: string[];
  geometryType: string;
  visible: boolean;
  summary: string;
  metadata: Record<string, string | number | boolean | null | undefined>;
  symbolization: RasterSymbolization;
  fields: ResourceField[];
}

export type LoadedLayer = LoadedVectorLayer | LoadedRasterLayer;

export interface LoadedLayerGroup {
  id: string;
  name: string;
  sourceResource: ResourceListItem;
  isManual?: boolean;
  visible: boolean;
  summary: string;
  createdAt: string;
  metadata: Record<string, string | number | boolean | null | undefined>;
  symbolization: GroupSymbolization;
  children: LoadedLayer[];
}

export type ResourceFilters = NonNullable<
  import("./api/generated").GetResourcesData["query"]
>;

export interface LoginFormValues {
  username: string;
  password: string;
  remember?: boolean;
}

export interface RegisterFormValues {
  username: string;
  email: string;
  password: string;
  passwordConfirm: string;
  accountPurpose: RegisterRequest["accountPurpose"];
  displayName?: string;
  department?: string;
  applicationReason?: string;
}
