from apps.projects.scoping import ProjectScopedModel
from django.conf import settings
from django.db import models

from apps.catalog.models import DataResource, MapLayer


class RasterDataset(ProjectScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "等待处理"
        PROCESSING = "processing", "处理中"
        READY = "ready", "可用"
        FAILED = "failed", "失败"

    class RasterKind(models.TextChoices):
        IMAGERY = "imagery", "多波段影像"
        CONTINUOUS = "continuous", "连续型栅格"
        CATEGORICAL = "categorical", "分类栅格"

    name = models.CharField(max_length=160, verbose_name="数据名称")
    code = models.SlugField(max_length=96, verbose_name="数据编号")
    source_relative_path = models.CharField(
        max_length=500, verbose_name="源文件相对路径"
    )
    source_file_name = models.CharField(
        max_length=255, blank=True, verbose_name="源主文件原始名称"
    )
    source_format = models.CharField(
        max_length=40, blank=True, verbose_name="源栅格格式"
    )
    source_manifest = models.JSONField(
        default=list, blank=True, verbose_name="源数据包文件清单"
    )
    source_checksum_sha256 = models.CharField(
        max_length=64, blank=True, verbose_name="源主文件 SHA256"
    )
    raster_kind = models.CharField(
        max_length=20,
        choices=RasterKind.choices,
        default=RasterKind.IMAGERY,
        verbose_name="栅格数据语义",
    )
    resampling = models.CharField(
        max_length=20, default="bilinear", verbose_name="预处理重采样方式"
    )
    processed_relative_path = models.CharField(
        max_length=500, blank=True, verbose_name="预处理文件相对路径"
    )
    source_metadata_relative_path = models.CharField(
        max_length=500, blank=True, verbose_name="源文件元数据路径"
    )
    processed_metadata_relative_path = models.CharField(
        max_length=500, blank=True, verbose_name="预处理文件元数据路径"
    )
    source_gdalinfo = models.JSONField(
        default=dict, blank=True, verbose_name="源文件 GDAL 元数据"
    )
    processed_gdalinfo = models.JSONField(
        default=dict, blank=True, verbose_name="预处理文件 GDAL 元数据"
    )
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_datasets",
        verbose_name="数据资源",
    )
    map_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_datasets",
        verbose_name="地图图层",
    )
    default_rules = models.JSONField(
        default=dict, blank=True, verbose_name="默认符号化规则"
    )
    bounds_3857 = models.JSONField(
        default=list, blank=True, verbose_name="EPSG:3857 范围"
    )
    bounds_4326 = models.JSONField(default=list, blank=True, verbose_name="经纬度范围")
    image_coordinates = models.JSONField(
        default=list, blank=True, verbose_name="Mapbox 图片角点"
    )
    band_count = models.PositiveIntegerField(default=0, verbose_name="波段数")
    source_file_size = models.PositiveBigIntegerField(
        default=0, verbose_name="源文件大小"
    )
    processed_file_size = models.PositiveBigIntegerField(
        default=0, verbose_name="预处理文件大小"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="状态",
    )
    progress_log = models.TextField(blank=True, verbose_name="处理日志")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    imported_at = models.DateTimeField(auto_now_add=True, verbose_name="导入时间")
    processed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="预处理完成时间"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "code"),
                name="raster_rasterdataset_code_project"[:63],
            ),
            models.UniqueConstraint(
                fields=("project_tag", "source_relative_path"),
                name="raster_rasterdataset_source_relative_path_project"[:63],
            ),
        ]
        verbose_name = "栅格数据集"
        verbose_name_plural = "栅格数据集"
        ordering = ("-imported_at",)
        permissions = [
            ("manage_raster_dataset", "可管理栅格数据集"),
        ]

    def __str__(self) -> str:
        return self.name


class RasterBand(ProjectScopedModel):
    dataset = models.ForeignKey(
        RasterDataset,
        on_delete=models.CASCADE,
        related_name="band_records",
        verbose_name="栅格数据集",
    )
    band_index = models.PositiveIntegerField(verbose_name="波段序号")
    name = models.CharField(max_length=120, blank=True, verbose_name="波段名称")
    data_type = models.CharField(max_length=40, blank=True, verbose_name="数据类型")
    color_interpretation = models.CharField(
        max_length=40, blank=True, verbose_name="颜色解释"
    )
    nodata = models.FloatField(null=True, blank=True, verbose_name="NoData 值")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")
    minimum = models.FloatField(null=True, blank=True, verbose_name="最小值")
    maximum = models.FloatField(null=True, blank=True, verbose_name="最大值")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="波段元数据")

    class Meta:
        verbose_name = "栅格波段"
        verbose_name_plural = "栅格波段"
        ordering = ("dataset_id", "band_index")
        constraints = [
            models.UniqueConstraint(
                fields=("dataset", "band_index"), name="uniq_raster_band_index"
            )
        ]


class RasterProcessingJob(ProjectScopedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待处理"
        RUNNING = "running", "处理中"
        READY = "ready", "已完成"
        FAILED = "failed", "失败"

    id = models.CharField(max_length=32, primary_key=True, editable=False)
    kind = models.CharField(max_length=24, verbose_name="任务类型")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        verbose_name="任务状态",
    )
    stage = models.CharField(max_length=32, default="queued", verbose_name="处理阶段")
    progress_percent = models.PositiveSmallIntegerField(default=0, verbose_name="进度")
    messages = models.JSONField(default=list, blank=True, verbose_name="进度消息")
    result = models.JSONField(null=True, blank=True, verbose_name="任务结果")
    error = models.TextField(blank=True, verbose_name="错误信息")
    artifact_path = models.CharField(
        max_length=500, blank=True, verbose_name="任务产物路径"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_processing_jobs",
        verbose_name="发起用户",
    )
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "栅格处理任务"
        verbose_name_plural = "栅格处理任务"
        ordering = ("-started_at",)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "progressPercent": self.progress_percent,
            "messages": list(self.messages or []),
            "result": self.result,
            "error": self.error,
            "startedAt": self.started_at.timestamp() if self.started_at else 0,
            "finishedAt": self.finished_at.timestamp() if self.finished_at else None,
        }


class RasterStyle(ProjectScopedModel):
    dataset = models.ForeignKey(
        RasterDataset,
        on_delete=models.CASCADE,
        related_name="render_styles",
        verbose_name="栅格数据集",
    )
    style_hash = models.CharField(max_length=24, verbose_name="样式哈希")
    rules = models.JSONField(default=dict, verbose_name="符号化规则")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_styles",
        verbose_name="创建用户",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    last_used_at = models.DateTimeField(auto_now=True, verbose_name="最后使用时间")

    class Meta:
        verbose_name = "栅格渲染样式"
        verbose_name_plural = "栅格渲染样式"
        constraints = [
            models.UniqueConstraint(
                fields=("dataset", "style_hash"), name="uniq_raster_dataset_style"
            )
        ]
