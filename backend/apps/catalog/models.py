from apps.projects.scoping import ProjectScopedModel
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


DATA_DOMAIN_TYPE_CHOICES = [
    ("germplasm", "种质数据"),
    ("genome", "基因组数据"),
    ("individual", "个体数据"),
    ("community", "群落数据"),
    ("population", "种群数据"),
    ("field_survey", "野外调查数据"),
    ("remote_sensing", "遥感影像数据"),
    ("molecular", "分子数据"),
    ("vector", "矢量数据"),
    ("other", "其他类型"),
]


class DictionaryItem(models.Model):
    class DictType(models.TextChoices):
        DATA_CATEGORY = "data_category", "数据分类"
        LAYER_CATEGORY = "layer_category", "图层分类"
        DATA_SOURCE = "data_source", "数据来源"
        REGION = "region", "空间范围"
        PUBLIC_SCOPE = "public_scope", "公开范围"

    dict_type = models.CharField(
        max_length=32, choices=DictType.choices, verbose_name="字典类型"
    )
    code = models.SlugField(max_length=64, verbose_name="编码")
    name = models.CharField(max_length=128, verbose_name="名称")
    description = models.TextField(blank=True, verbose_name="说明")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="上级字典项",
    )
    is_selectable = models.BooleanField(default=True, verbose_name="允许选择")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="排序")
    is_active = models.BooleanField(default=True, verbose_name="启用")

    class Meta:
        verbose_name = "字典项"
        verbose_name_plural = "字典项"
        ordering = ("dict_type", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("dict_type", "code"), name="uniq_dictionary_type_code"
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("parent_id")),
                name="dictionary_parent_not_self",
            ),
        ]
        indexes = [
            models.Index(
                fields=("dict_type", "parent", "is_active", "sort_order"),
                name="catalog_dic_type_parent_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class DataResourceGroup(ProjectScopedModel):
    name = models.CharField(max_length=120, verbose_name="组别名称")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="排序")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "name"),
                name="catalog_dataresourcegroup_name_project"[:63],
            )
        ]
        verbose_name = "数据资源组别"
        verbose_name_plural = "数据资源组别"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.name


# MH-workflow task uploads and their working copies belong to one task only.
TASK_RESOURCE_SOURCES = ("workflow-upload:", "workflow-working:")
INTERNAL_SOURCE_PREFIXES = (
    "geology-archived:",
    *TASK_RESOURCE_SOURCES,
    "geology-multi-frozen-rules:",
    "geology-multi-approved:",
    "demo-changes:",
    "geology-reference:",
    "geology-case-reference-20261012:",
    "geology-multi-reference:",
    "geology-multi-evaluation:",
    "geology-review-reference:",
    "geology-review-acceptance:",
)
RESERVED_RULE_CODES = (
    "demo-geology-rules",
    "real-geology-age-rules",
    "geology-review-rules",
    "geology-review-expanded-20261025-rules",
    "geology-multi-rules",
    "geology-multi-rules-complete-20261025",
)


def task_resource_q(relation: str = ""):
    """Explicit internal packets hidden from catalogs, preserving bound ID reads."""
    related = f"{relation}__" if relation else ""
    query = models.Q(**{f"{related}code__in": RESERVED_RULE_CODES})
    query |= models.Q(**{f"{related}code__startswith": "geology-multi-rules"})
    query |= models.Q(
        **{
            f"{related}code__startswith": "geology-review-",
            f"{related}code__endswith": "-rules",
        }
    )
    for prefix in INTERNAL_SOURCE_PREFIXES:
        query |= models.Q(**{f"{related}source__startswith": prefix})
    return query


class DataResource(ProjectScopedModel):
    class SpatialClass(models.TextChoices):
        SPATIAL = "spatial", "地理数据"
        NON_SPATIAL = "non_spatial", "非地理数据"

    class DataType(models.TextChoices):
        VECTOR = "vector", "矢量空间数据"
        RASTER = "raster", "栅格空间数据"
        GENE = "gene", "基因非地理数据"
        TABLE = "table", "表格属性数据"
        DOCUMENT = "document", "文档资料"
        IMAGE = "image", "图片资料"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    name = models.CharField(max_length=160, verbose_name="数据名称")
    code = models.SlugField(max_length=80, verbose_name="数据编号")
    data_type = models.CharField(
        max_length=24, choices=DataType.choices, verbose_name="数据类型"
    )
    domain_type = models.CharField(
        max_length=32,
        choices=DATA_DOMAIN_TYPE_CHOICES,
        blank=True,
        verbose_name="业务数据类型",
    )
    category = models.ForeignKey(
        DictionaryItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="data_resources",
        verbose_name="数据分类",
    )
    source = models.CharField(max_length=160, blank=True, verbose_name="数据来源")
    provider = models.CharField(max_length=160, blank=True, verbose_name="提供单位")
    data_date = models.DateField(null=True, blank=True, verbose_name="数据时间")
    spatial_extent = models.CharField(
        max_length=255, blank=True, verbose_name="空间范围"
    )
    coordinate_system = models.CharField(
        max_length=120, blank=True, verbose_name="坐标信息"
    )
    file_format = models.CharField(max_length=40, blank=True, verbose_name="数据格式")
    storage_path = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="存储相对路径",
        help_text="矢量填写 GeoPackage 图层名；栅格相对于地理数据 raster/；基因和表格相对于非地理数据根目录。",
    )
    description = models.TextField(blank=True, verbose_name="数据说明")
    quality_note = models.TextField(blank=True, verbose_name="数据质量说明")
    default_visualization = models.JSONField(
        default=dict, blank=True, verbose_name="默认可视化方案"
    )
    size_bytes = models.PositiveBigIntegerField(default=0, verbose_name="数据大小")
    item_count = models.PositiveBigIntegerField(default=0, verbose_name="数据条目数")
    access_groups = models.ManyToManyField(
        Group, blank=True, related_name="data_resources", verbose_name="访问角色"
    )
    owner_only = models.BooleanField(
        default=False,
        verbose_name="仅上传者可见",
        help_text="启用后仅上传者和超级管理员可访问；默认项目成员可见。",
    )
    is_compute_result = models.BooleanField(
        default=False,
        db_default=False,
        editable=False,
        verbose_name="计算结果",
        help_text="由计算结果入库流程登记；用户上传保留地理/非地理分类。",
    )
    inventory_group = models.ForeignKey(
        DataResourceGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resources",
        verbose_name="存量数据组别",
    )
    maintainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintained_resources",
        verbose_name="维护人员",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="状态",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "code"),
                name="catalog_dataresource_code_project"[:63],
            )
        ]
        verbose_name = "数据资源"
        verbose_name_plural = "数据资源"
        ordering = ("name",)
        permissions = [
            ("export_dataresource", "可导出数据资源"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def spatial_class(self) -> str:
        if (
            self.data_type in {self.DataType.VECTOR, self.DataType.RASTER}
            and self.coordinate_system.strip()
        ):
            return self.SpatialClass.SPATIAL
        return self.SpatialClass.NON_SPATIAL

    @property
    def classification_category_code(self) -> str:
        return "compute_results" if self.is_compute_result else self.spatial_class

    def save(self, *args, **kwargs):
        # All import/scan paths use this same classification after coordinates are parsed.
        category = DictionaryItem.objects.filter(
            dict_type=DictionaryItem.DictType.DATA_CATEGORY,
            code=self.classification_category_code,
            is_active=True,
        ).first()
        if category is not None:
            self.category = category
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"category"}
        return super().save(*args, **kwargs)


class WorkspaceScene(ProjectScopedModel):
    class Kind(models.TextChoices):
        PROJECT = "project", "工程"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_scenes",
        verbose_name="所属用户",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="类型")
    name = models.CharField(max_length=160, verbose_name="名称")
    description = models.TextField(blank=True, verbose_name="说明")
    snapshot = models.JSONField(default=dict, blank=True, verbose_name="工作台快照")
    access_groups = models.ManyToManyField(
        Group, blank=True, related_name="workspace_scenes", verbose_name="访问角色"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="状态",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "工作台场景"
        verbose_name_plural = "工作台场景"
        ordering = ("kind", "-updated_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "owner", "kind", "name"),
                name="uniq_workspace_scene_owner_kind_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}：{self.name}"


class ShareInvitation(ProjectScopedModel):
    """A personal invitation, never a project membership or resource ACL."""

    class Kind(models.TextChoices):
        WORKSPACE = "workspace", "工程"
        COMPOSITION = "composition", "专题图"
        COMPUTE_OUTPUT = "compute_output", "计算结果"

    class Status(models.TextChoices):
        PENDING = "pending", "等待接受"
        ACCEPTED = "accepted", "已接受"
        REJECTED = "rejected", "已拒绝"
        UNAVAILABLE = "unavailable", "已失效"

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_shares"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_shares",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    object_id = models.PositiveBigIntegerField()
    object_name = models.CharField(max_length=160)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    request_key = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    response_key = models.CharField(max_length=80, blank=True)
    response_decision = models.CharField(max_length=8, blank=True)
    detail = models.CharField(max_length=500, default="邀请已发出，等待对方接受")
    recipient_read_at = models.DateTimeField(null=True, blank=True)
    sender_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("sender", "request_key"), name="share_sender_key"
            ),
            models.UniqueConstraint(
                fields=("sender", "recipient", "project_tag", "kind", "object_id"),
                condition=models.Q(status__in=("pending", "accepted")),
                name="share_one_live_invitation",
            ),
            models.CheckConstraint(
                condition=~models.Q(sender=models.F("recipient")), name="share_no_self"
            ),
        ]


class MapComposition(ProjectScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        COMPLETED = "completed", "已生成成果"
        PUBLISHED = "published", "已发布"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="map_compositions",
        verbose_name="所属用户",
    )
    project = models.ForeignKey(
        WorkspaceScene,
        on_delete=models.PROTECT,
        related_name="map_compositions",
        verbose_name="来源工程",
    )
    name = models.CharField(max_length=160, verbose_name="专题图名称")
    description = models.TextField(blank=True, verbose_name="专题图说明")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="状态",
    )
    layout = models.JSONField(default=dict, blank=True, verbose_name="版式配置")
    source_workspace_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name="来源工程快照"
    )
    audience_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="map_compositions",
        verbose_name="发布可见角色",
    )
    published_version = models.ForeignKey(
        "MapCompositionVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_compositions",
        verbose_name="正式发布版本",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_map_compositions",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="发布时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "专题出图稿"
        verbose_name_plural = "专题出图稿"
        ordering = ("-updated_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "project", "name"),
                name="uniq_map_composition_owner_project_name",
            ),
        ]
        permissions = [
            ("export_mapcomposition", "导出专题图成果"),
            ("publish_mapcomposition", "发布专题图成果"),
            ("restore_mapcomposition", "还原专题图为工程"),
        ]

    def __str__(self) -> str:
        return f"{self.project.name}：{self.name}"


class MapCompositionVersion(ProjectScopedModel):
    class Format(models.TextChoices):
        PNG = "png", "PNG"
        JPG = "jpg", "JPG"
        PDF = "pdf", "PDF"

    composition = models.ForeignKey(
        MapComposition,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="出图稿",
    )
    version_number = models.PositiveIntegerField(verbose_name="版本号")
    format = models.CharField(max_length=8, choices=Format.choices, verbose_name="格式")
    dpi = models.PositiveSmallIntegerField(default=300, verbose_name="DPI")
    width_px = models.PositiveIntegerField(verbose_name="宽度像素")
    height_px = models.PositiveIntegerField(verbose_name="高度像素")
    note = models.CharField(max_length=500, blank=True, verbose_name="版本说明")
    preview_path = models.CharField(max_length=500, verbose_name="预览文件路径")
    artifact_path = models.CharField(max_length=500, verbose_name="成果文件路径")
    layout_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name="版式快照"
    )
    workspace_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name="工程快照"
    )
    snapshot_schema_version = models.PositiveSmallIntegerField(
        default=1, verbose_name="快照结构版本"
    )
    snapshot_checksum = models.CharField(
        max_length=64, blank=True, verbose_name="快照校验值"
    )
    resource_manifest = models.JSONField(
        default=list, blank=True, verbose_name="资源引用清单"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_map_composition_versions",
        verbose_name="生成人",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="生成时间")

    class Meta:
        verbose_name = "专题图成果版本"
        verbose_name_plural = "专题图成果版本"
        ordering = ("-version_number", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("composition", "version_number"),
                name="uniq_map_composition_version_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.composition.name} V{self.version_number}"


class ResultArtifact(ProjectScopedModel):
    class SourceType(models.TextChoices):
        ANALYSIS = "analysis", "平台分析成果"
        DIRECT_IMPORT = "direct_import", "直接导入成果"

    class ResultType(models.TextChoices):
        MAP = "map", "地图"
        CHART = "chart", "图表"
        REPORT = "report", "报告"
        TABLE = "table", "表格"
        IMAGE = "image", "图片"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="result_artifacts",
        verbose_name="创建者",
    )
    related_resources = models.ManyToManyField(
        DataResource,
        blank=True,
        related_name="result_artifacts",
        verbose_name="关联数据",
    )
    name = models.CharField(max_length=160, verbose_name="成果名称")
    description = models.TextField(blank=True, verbose_name="成果说明")
    source_type = models.CharField(
        max_length=24,
        choices=SourceType.choices,
        default=SourceType.DIRECT_IMPORT,
        verbose_name="成果来源",
    )
    result_type = models.CharField(
        max_length=16,
        choices=ResultType.choices,
        default=ResultType.OTHER,
        verbose_name="成果类型",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="状态",
    )
    category = models.ForeignKey(
        DictionaryItem,
        on_delete=models.PROTECT,
        related_name="result_artifacts",
        verbose_name="权威业务分类",
    )
    provider = models.CharField(max_length=200, blank=True, verbose_name="提供单位")
    file_path = models.CharField(max_length=500, verbose_name="成果文件路径")
    file_name = models.CharField(max_length=255, verbose_name="原始文件名")
    mime_type = models.CharField(max_length=120, blank=True, verbose_name="媒体类型")
    size_bytes = models.PositiveBigIntegerField(default=0, verbose_name="文件大小")
    access_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="result_artifacts",
        verbose_name="可访问角色",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_result_artifacts",
        verbose_name="发布人",
    )
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="发布时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "成果文件"
        verbose_name_plural = "成果文件"
        ordering = ("-published_at", "-updated_at", "id")
        permissions = [
            ("download_resultartifact", "下载成果文件"),
            ("publish_resultartifact", "发布成果文件"),
        ]
        indexes = [
            models.Index(fields=("status", "source_type")),
            models.Index(fields=("category", "status")),
        ]

    def __str__(self) -> str:
        return self.name


class DataCatalog(ProjectScopedModel):
    name = models.CharField(max_length=120, verbose_name="目录名称")
    code = models.SlugField(max_length=80, verbose_name="目录编码")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        verbose_name="上级目录",
    )
    description = models.TextField(blank=True, verbose_name="说明")
    resources = models.ManyToManyField(
        DataResource, blank=True, related_name="catalogs", verbose_name="数据资源"
    )
    access_groups = models.ManyToManyField(
        Group, blank=True, related_name="data_catalogs", verbose_name="访问角色"
    )
    sort_order = models.PositiveIntegerField(default=100, verbose_name="排序")
    is_active = models.BooleanField(default=True, verbose_name="启用")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "code"),
                name="catalog_datacatalog_code_project"[:63],
            )
        ]
        verbose_name = "数据目录"
        verbose_name_plural = "数据目录"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.name


class MapLayer(ProjectScopedModel):
    class LayerType(models.TextChoices):
        VECTOR = "vector", "矢量图层"
        RASTER = "raster", "栅格图层"

    class GeometryType(models.TextChoices):
        POINT = "point", "点"
        LINE = "line", "线"
        POLYGON = "polygon", "面"
        MIXED = "mixed", "混合"

    name = models.CharField(max_length=160, verbose_name="图层名称")
    code = models.SlugField(max_length=80, verbose_name="图层编码")
    layer_type = models.CharField(
        max_length=16, choices=LayerType.choices, verbose_name="图层类型"
    )
    geometry_type = models.CharField(
        max_length=16,
        choices=GeometryType.choices,
        default=GeometryType.MIXED,
        verbose_name="几何类型",
    )
    category = models.ForeignKey(
        DictionaryItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="map_layers",
        verbose_name="图层分类",
    )
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="map_layers",
        verbose_name="数据资源",
    )
    source_path = models.CharField(
        max_length=255, blank=True, verbose_name="数据图层名或相对路径"
    )
    sort_order = models.PositiveIntegerField(default=100, verbose_name="排序")
    default_visible = models.BooleanField(default=False, verbose_name="默认显示")
    default_opacity = models.PositiveSmallIntegerField(
        default=85, verbose_name="默认透明度"
    )
    symbolization = models.JSONField(
        default=dict, blank=True, verbose_name="矢量符号化"
    )
    bounds = models.JSONField(default=list, blank=True, verbose_name="边界范围")
    legend = models.TextField(blank=True, verbose_name="图例说明")
    raster_symbolizer_script = models.CharField(
        max_length=255, blank=True, verbose_name="栅格符号化脚本"
    )
    raster_rules = models.JSONField(
        default=dict, blank=True, verbose_name="栅格符号化规则"
    )
    access_groups = models.ManyToManyField(
        Group, blank=True, related_name="map_layers", verbose_name="访问角色"
    )
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "code"),
                name="catalog_maplayer_code_project"[:63],
            )
        ]
        verbose_name = "地图图层"
        verbose_name_plural = "地图图层"
        ordering = ("sort_order", "id")
        permissions = [
            ("load_maplayer", "可加载地图图层"),
        ]

    def __str__(self) -> str:
        return self.name


class VectorDataset(ProjectScopedModel):
    class SourceFormat(models.TextChoices):
        SHAPEFILE = "SHAPEFILE", "Shapefile"
        GEOJSON = "GEOJSON", "GeoJSON"
        GPKG = "GPKG", "GeoPackage"

    class RenderStrategy(models.TextChoices):
        GEOJSON = "geojson", "GeoJSON"
        VECTOR_TILE = "vector_tile", "矢量瓦片"

    resource = models.OneToOneField(
        DataResource,
        on_delete=models.CASCADE,
        related_name="vector_dataset",
        verbose_name="数据资源",
    )
    source_file_name = models.CharField(max_length=255, verbose_name="源文件名")
    source_format = models.CharField(
        max_length=20, choices=SourceFormat.choices, verbose_name="源格式"
    )
    source_archive_path = models.CharField(
        max_length=255, blank=True, verbose_name="原始文件归档相对路径"
    )
    source_layer_name = models.CharField(
        max_length=255, blank=True, verbose_name="源图层名称"
    )
    source_encoding = models.CharField(
        max_length=40, blank=True, verbose_name="源属性编码"
    )
    source_crs = models.TextField(blank=True, verbose_name="源坐标系")
    source_epsg = models.IntegerField(null=True, blank=True, verbose_name="源 EPSG")
    normalized_epsg = models.PositiveIntegerField(
        default=4326, verbose_name="标准化 EPSG"
    )
    geometry_type = models.CharField(max_length=64, verbose_name="几何类型")
    feature_count = models.PositiveBigIntegerField(default=0, verbose_name="要素数")
    vertex_count = models.PositiveBigIntegerField(default=0, verbose_name="顶点数")
    field_count = models.PositiveIntegerField(default=0, verbose_name="字段数")
    valid_geometry_count = models.PositiveBigIntegerField(
        default=0, verbose_name="有效几何数"
    )
    invalid_geometry_count = models.PositiveBigIntegerField(
        default=0, verbose_name="无效几何数"
    )
    empty_geometry_count = models.PositiveBigIntegerField(
        default=0, verbose_name="空几何数"
    )
    null_geometry_count = models.PositiveBigIntegerField(
        default=0, verbose_name="空值几何数"
    )
    bounds = models.JSONField(default=list, blank=True, verbose_name="边界")
    checksum_sha256 = models.CharField(
        max_length=64, blank=True, verbose_name="源文件 SHA256"
    )
    render_strategy = models.CharField(
        max_length=20,
        choices=RenderStrategy.choices,
        default=RenderStrategy.GEOJSON,
        verbose_name="渲染策略",
    )
    import_summary = models.JSONField(
        default=dict, blank=True, verbose_name="导入质量摘要"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "矢量数据集"
        verbose_name_plural = "矢量数据集"
        ordering = ("-created_at", "id")

    def __str__(self) -> str:
        return self.resource.name
