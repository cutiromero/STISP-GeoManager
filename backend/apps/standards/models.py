from apps.projects.scoping import ProjectScopedModel
from django.conf import settings
from django.db import models

from apps.catalog.models import DataResource


class DataDomainType(models.TextChoices):
    GERMPLASM = "germplasm", "种质数据"
    GENOME = "genome", "基因组数据"
    INDIVIDUAL = "individual", "个体数据"
    COMMUNITY = "community", "群落数据"
    POPULATION = "population", "种群数据"
    FIELD_SURVEY = "field_survey", "野外调查数据"
    REMOTE_SENSING = "remote_sensing", "遥感影像数据"
    MOLECULAR = "molecular", "分子数据"
    VECTOR = "vector", "矢量数据"
    OTHER = "other", "其他类型"


class SpatialClass(models.TextChoices):
    SPATIAL = "spatial", "地理数据"
    NON_SPATIAL = "non_spatial", "非地理数据"
    SPATIALIZED_TABLE = "spatialized_table", "可空间化表格"
    DERIVED_FROM_SPATIAL = "derived_from_spatial", "由空间对象关联"


class DataGranularity(models.TextChoices):
    REGION = "region", "区域"
    SITE = "site", "地点"
    POPULATION = "population", "种群"
    INDIVIDUAL = "individual", "个体"
    PLOT = "plot", "样方/样点"
    OBSERVATION = "observation", "观测记录"
    SAMPLE = "sample", "样品"
    MOLECULAR_ASSAY = "molecular_assay", "分子实验"
    GENOME_FILE = "genome_file", "基因组文件"
    RASTER_SCENE = "raster_scene", "遥感场景"
    RASTER_PRODUCT = "raster_product", "遥感产品"


class StandardizationStatus(models.TextChoices):
    RAW = "raw", "原始"
    PROFILED = "profiled", "已预检"
    MAPPED = "mapped", "已字段映射"
    SPATIALIZED = "spatialized", "已空间化"
    STANDARDIZED = "standardized", "已标准化"
    PUBLISHED = "published", "已发布"


class ResourceDomain(ProjectScopedModel):
    resource = models.OneToOneField(
        DataResource,
        on_delete=models.CASCADE,
        related_name="domain_profile",
        verbose_name="数据资源",
    )
    domain_type = models.CharField(
        max_length=32, choices=DataDomainType.choices, verbose_name="业务数据类型"
    )
    spatial_class = models.CharField(
        max_length=32,
        choices=SpatialClass.choices,
        default=SpatialClass.NON_SPATIAL,
        verbose_name="空间属性",
    )
    granularity = models.CharField(
        max_length=32,
        choices=DataGranularity.choices,
        default=DataGranularity.OBSERVATION,
        verbose_name="数据粒度",
    )
    standardization_status = models.CharField(
        max_length=32,
        choices=StandardizationStatus.choices,
        default=StandardizationStatus.RAW,
        verbose_name="标准化状态",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "资源业务分类"
        verbose_name_plural = "资源业务分类"

    def __str__(self) -> str:
        return f"{self.resource.name} - {self.get_domain_type_display()}"


class SourceDataset(ProjectScopedModel):
    resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_datasets",
        verbose_name="关联资源",
    )
    source_file_name = models.CharField(max_length=255, verbose_name="源文件名")
    file_hash = models.CharField(max_length=128, blank=True, verbose_name="文件哈希")
    provider = models.CharField(max_length=160, blank=True, verbose_name="提供单位")
    received_at = models.DateTimeField(null=True, blank=True, verbose_name="接收时间")
    source_type = models.CharField(max_length=64, blank=True, verbose_name="源数据类型")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "源数据集"
        verbose_name_plural = "源数据集"
        ordering = ("-created_at", "id")

    def __str__(self) -> str:
        return self.source_file_name


class SourceSheet(ProjectScopedModel):
    dataset = models.ForeignKey(
        SourceDataset,
        on_delete=models.CASCADE,
        related_name="sheets",
        verbose_name="源数据集",
    )
    sheet_name = models.CharField(max_length=160, verbose_name="小表名称")
    header_row = models.PositiveIntegerField(default=1, verbose_name="表头行")
    row_count = models.PositiveIntegerField(default=0, verbose_name="行数")
    column_count = models.PositiveIntegerField(default=0, verbose_name="列数")
    detected_granularity = models.CharField(
        max_length=32,
        choices=DataGranularity.choices,
        default=DataGranularity.OBSERVATION,
        verbose_name="识别粒度",
    )
    notes = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        verbose_name = "源数据小表"
        verbose_name_plural = "源数据小表"
        constraints = [
            models.UniqueConstraint(
                fields=("dataset", "sheet_name"), name="uniq_source_dataset_sheet"
            )
        ]

    def __str__(self) -> str:
        return f"{self.dataset.source_file_name}/{self.sheet_name}"


class FieldDefinition(models.Model):
    field_code = models.SlugField(max_length=80, unique=True, verbose_name="字段编码")
    name_cn = models.CharField(max_length=120, verbose_name="中文名")
    name_en = models.CharField(max_length=120, blank=True, verbose_name="英文名")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")
    data_type = models.CharField(max_length=40, blank=True, verbose_name="数据类型")
    category = models.CharField(max_length=64, blank=True, verbose_name="字段类别")
    description = models.TextField(blank=True, verbose_name="说明")
    is_active = models.BooleanField(default=True, verbose_name="启用")

    class Meta:
        verbose_name = "字段定义"
        verbose_name_plural = "字段定义"
        ordering = ("category", "field_code")

    def __str__(self) -> str:
        return self.name_cn


class SourceFieldMapping(ProjectScopedModel):
    source_sheet = models.ForeignKey(
        SourceSheet,
        on_delete=models.CASCADE,
        related_name="field_mappings",
        verbose_name="源数据小表",
    )
    source_column = models.CharField(max_length=160, verbose_name="源字段名")
    field_definition = models.ForeignKey(
        FieldDefinition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_mappings",
        verbose_name="标准字段",
    )
    mapping_confidence = models.FloatField(default=0, verbose_name="映射置信度")
    notes = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        verbose_name = "源字段映射"
        verbose_name_plural = "源字段映射"
        constraints = [
            models.UniqueConstraint(
                fields=("source_sheet", "source_column"),
                name="uniq_source_sheet_column_mapping",
            )
        ]

    def __str__(self) -> str:
        return self.source_column


class CoordinateParseRecord(ProjectScopedModel):
    class Status(models.TextChoices):
        VALID = "valid", "有效"
        EMPTY = "empty", "空值"
        INVALID = "invalid", "无效"
        OUT_OF_RANGE = "out_of_range", "超出范围"

    source_sheet = models.ForeignKey(
        SourceSheet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="coordinate_records",
        verbose_name="源数据小表",
    )
    row_key = models.CharField(max_length=120, verbose_name="源记录键")
    raw_longitude = models.CharField(
        max_length=120, blank=True, verbose_name="原始经度"
    )
    raw_latitude = models.CharField(max_length=120, blank=True, verbose_name="原始纬度")
    parser = models.CharField(max_length=40, blank=True, verbose_name="解析器")
    longitude = models.FloatField(null=True, blank=True, verbose_name="标准经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="标准纬度")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.VALID, verbose_name="状态"
    )
    message = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        verbose_name = "坐标解析记录"
        verbose_name_plural = "坐标解析记录"
        indexes = [models.Index(fields=("source_sheet", "row_key"))]

    def __str__(self) -> str:
        return self.row_key


class DataQualityIssue(ProjectScopedModel):
    class Severity(models.TextChoices):
        INFO = "info", "提示"
        WARNING = "warning", "警告"
        ERROR = "error", "错误"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        CONFIRMED = "confirmed", "已确认"
        RESOLVED = "resolved", "已解决"
        IGNORED = "ignored", "已忽略"

    resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quality_issues",
        verbose_name="数据资源",
    )
    source_sheet = models.ForeignKey(
        SourceSheet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quality_issues",
        verbose_name="源数据小表",
    )
    row_key = models.CharField(max_length=120, blank=True, verbose_name="源记录键")
    issue_type = models.CharField(max_length=64, verbose_name="问题类型")
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.WARNING,
        verbose_name="严重程度",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="处理状态",
    )
    message = models.TextField(verbose_name="问题说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_quality_issues",
        verbose_name="处理人",
    )

    class Meta:
        verbose_name = "数据质量问题"
        verbose_name_plural = "数据质量问题"
        ordering = ("-created_at", "id")

    def __str__(self) -> str:
        return self.issue_type


class SourceRecordLink(ProjectScopedModel):
    source_sheet = models.ForeignKey(
        SourceSheet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="record_links",
        verbose_name="源数据小表",
    )
    resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_record_links",
        verbose_name="数据资源",
    )
    table_name = models.CharField(max_length=120, blank=True, verbose_name="表名")
    row_key = models.CharField(max_length=120, verbose_name="源记录键")
    entity_type = models.CharField(max_length=80, verbose_name="实体类型")
    entity_id = models.PositiveBigIntegerField(verbose_name="实体 ID")

    class Meta:
        verbose_name = "源记录关联"
        verbose_name_plural = "源记录关联"
        indexes = [
            models.Index(fields=("entity_type", "entity_id")),
            models.Index(fields=("source_sheet", "row_key")),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"
