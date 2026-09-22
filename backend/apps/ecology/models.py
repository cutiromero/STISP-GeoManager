from apps.projects.scoping import ProjectScopedModel
from django.db import models

from apps.catalog.models import DataResource, MapLayer
from apps.raster.models import RasterDataset


class Taxon(models.Model):
    code = models.SlugField(
        max_length=80, unique=True, null=True, blank=True, verbose_name="物种编码"
    )
    name_cn = models.CharField(max_length=120, blank=True, verbose_name="中文名")
    scientific_name = models.CharField(
        max_length=160, blank=True, verbose_name="科学名"
    )
    family = models.CharField(max_length=120, blank=True, verbose_name="科")
    genus = models.CharField(max_length=120, blank=True, verbose_name="属")
    protection_level = models.CharField(
        max_length=120, blank=True, verbose_name="保护等级"
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "物种"
        verbose_name_plural = "物种"
        ordering = ("name_cn", "scientific_name", "id")
        indexes = [
            models.Index(fields=("name_cn",)),
            models.Index(fields=("scientific_name",)),
        ]

    def __str__(self) -> str:
        return self.name_cn or self.scientific_name or self.code or str(self.pk)


class TaxonAlias(models.Model):
    taxon = models.ForeignKey(
        Taxon, on_delete=models.CASCADE, related_name="aliases", verbose_name="物种"
    )
    alias = models.CharField(max_length=160, verbose_name="别名")
    source = models.CharField(max_length=160, blank=True, verbose_name="来源")

    class Meta:
        verbose_name = "物种别名"
        verbose_name_plural = "物种别名"
        constraints = [
            models.UniqueConstraint(fields=("taxon", "alias"), name="uniq_taxon_alias")
        ]

    def __str__(self) -> str:
        return self.alias


class StudyArea(ProjectScopedModel):
    class AreaType(models.TextChoices):
        BASIN = "basin", "流域"
        REGION = "region", "区域"
        PROTECTED_AREA = "protected_area", "保护地"
        ADMINISTRATIVE = "administrative", "行政区"
        OTHER = "other", "其他"

    area_code = models.SlugField(
        max_length=80, null=True, blank=True, verbose_name="区域编码"
    )
    name = models.CharField(max_length=160, verbose_name="区域名称")
    area_type = models.CharField(
        max_length=32,
        choices=AreaType.choices,
        default=AreaType.REGION,
        verbose_name="区域类型",
    )
    admin_region = models.CharField(max_length=160, blank=True, verbose_name="行政区")
    description = models.TextField(blank=True, verbose_name="说明")
    boundary_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="study_area_boundaries",
        verbose_name="边界数据资源",
    )
    boundary_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="study_areas",
        verbose_name="边界图层",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "area_code"),
                name="ecology_studyarea_area_code_project"[:63],
            )
        ]
        verbose_name = "研究区域"
        verbose_name_plural = "研究区域"
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name


class Site(ProjectScopedModel):
    site_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="地点编码"
    )
    name = models.CharField(max_length=200, verbose_name="地点名称")
    study_area = models.ForeignKey(
        StudyArea,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sites",
        verbose_name="研究区域",
    )
    admin_region = models.CharField(max_length=200, blank=True, verbose_name="行政区")
    raw_location = models.TextField(blank=True, verbose_name="原始地点描述")
    longitude = models.FloatField(null=True, blank=True, verbose_name="经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="纬度")
    altitude = models.FloatField(null=True, blank=True, verbose_name="海拔")
    coordinate_system = models.CharField(
        max_length=80, blank=True, verbose_name="坐标系统"
    )
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ecology_sites",
        verbose_name="来源数据资源",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "site_code"),
                name="ecology_site_site_code_project"[:63],
            )
        ]
        verbose_name = "采集地点/样地"
        verbose_name_plural = "采集地点/样地"
        ordering = ("name", "id")
        indexes = [
            models.Index(fields=("longitude", "latitude")),
            models.Index(fields=("admin_region",)),
        ]

    def __str__(self) -> str:
        return self.name


class SurveyEvent(ProjectScopedModel):
    survey_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="调查编码"
    )
    name = models.CharField(max_length=180, verbose_name="调查名称")
    survey_type = models.CharField(max_length=80, blank=True, verbose_name="调查类型")
    study_area = models.ForeignKey(
        StudyArea,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_events",
        verbose_name="研究区域",
    )
    started_on = models.DateField(null=True, blank=True, verbose_name="开始日期")
    ended_on = models.DateField(null=True, blank=True, verbose_name="结束日期")
    principal = models.CharField(max_length=120, blank=True, verbose_name="负责人")
    team = models.CharField(max_length=255, blank=True, verbose_name="调查队伍")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_events",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "survey_code"),
                name="ecology_surveyevent_survey_code_project"[:63],
            )
        ]
        verbose_name = "野外调查事件"
        verbose_name_plural = "野外调查事件"
        ordering = ("-started_on", "name", "id")

    def __str__(self) -> str:
        return self.name


class PopulationUnit(ProjectScopedModel):
    population_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="种群编码"
    )
    name = models.CharField(max_length=180, blank=True, verbose_name="种群名称")
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="populations",
        verbose_name="物种",
    )
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="populations",
        verbose_name="地点",
    )
    study_area = models.ForeignKey(
        StudyArea,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="populations",
        verbose_name="研究区域",
    )
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="populations",
        verbose_name="调查事件",
    )
    geometry_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="population_geometries",
        verbose_name="种群空间资源",
    )
    map_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="population_units",
        verbose_name="种群图层",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "population_code"),
                name="ecology_populationunit_population_code_project"[:63],
            )
        ]
        verbose_name = "种群单元"
        verbose_name_plural = "种群单元"
        ordering = ("population_code", "id")

    def __str__(self) -> str:
        return self.name or self.population_code or str(self.pk)


class SamplePlot(ProjectScopedModel):
    plot_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="样方编码"
    )
    name = models.CharField(max_length=180, blank=True, verbose_name="样方名称")
    plot_type = models.CharField(max_length=80, blank=True, verbose_name="样方类型")
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_plots",
        verbose_name="地点",
    )
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_plots",
        verbose_name="调查事件",
    )
    population = models.ForeignKey(
        PopulationUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_plots",
        verbose_name="种群",
    )
    raw_longitude = models.CharField(
        max_length=120, blank=True, verbose_name="原始经度"
    )
    raw_latitude = models.CharField(max_length=120, blank=True, verbose_name="原始纬度")
    longitude = models.FloatField(null=True, blank=True, verbose_name="经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="纬度")
    altitude = models.FloatField(null=True, blank=True, verbose_name="海拔")
    area_square_meters = models.FloatField(
        null=True, blank=True, verbose_name="样方面积平方米"
    )
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_plots",
        verbose_name="来源数据资源",
    )
    map_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_plots",
        verbose_name="样方图层",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "plot_code"),
                name="ecology_sampleplot_plot_code_project"[:63],
            )
        ]
        verbose_name = "样方/样点"
        verbose_name_plural = "样方/样点"
        ordering = ("plot_code", "id")
        indexes = [models.Index(fields=("longitude", "latitude"))]

    def __str__(self) -> str:
        return self.name or self.plot_code or str(self.pk)


class IndividualOrganism(ProjectScopedModel):
    individual_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="个体编码"
    )
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="individuals",
        verbose_name="物种",
    )
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="individuals",
        verbose_name="地点",
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="individuals",
        verbose_name="样方",
    )
    population = models.ForeignKey(
        PopulationUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="individuals",
        verbose_name="种群",
    )
    sex = models.CharField(max_length=40, blank=True, verbose_name="性别")
    growth_stage = models.CharField(max_length=80, blank=True, verbose_name="生长阶段")
    health_status = models.CharField(max_length=80, blank=True, verbose_name="健康状态")
    raw_longitude = models.CharField(
        max_length=120, blank=True, verbose_name="原始经度"
    )
    raw_latitude = models.CharField(max_length=120, blank=True, verbose_name="原始纬度")
    longitude = models.FloatField(null=True, blank=True, verbose_name="经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="纬度")
    altitude = models.FloatField(null=True, blank=True, verbose_name="海拔")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="individuals",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "individual_code"),
                name="ecology_individualorganism_individual_code_project"[:63],
            )
        ]
        verbose_name = "植物个体"
        verbose_name_plural = "植物个体"
        ordering = ("individual_code", "id")
        indexes = [models.Index(fields=("longitude", "latitude"))]

    def __str__(self) -> str:
        return self.individual_code or str(self.pk)


class CommunitySurvey(ProjectScopedModel):
    community_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="群落调查编码"
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="community_surveys",
        verbose_name="样方",
    )
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="community_surveys",
        verbose_name="调查事件",
    )
    vegetation_type = models.CharField(
        max_length=120, blank=True, verbose_name="植被类型"
    )
    layer_name = models.CharField(max_length=80, blank=True, verbose_name="群落层片")
    total_coverage_percent = models.FloatField(
        null=True, blank=True, verbose_name="总盖度百分比"
    )
    species_count = models.PositiveIntegerField(default=0, verbose_name="物种数")
    diversity_index = models.FloatField(
        null=True, blank=True, verbose_name="多样性指数"
    )
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="community_surveys",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "community_code"),
                name="ecology_communitysurvey_community_code_project"[:63],
            )
        ]
        verbose_name = "群落调查"
        verbose_name_plural = "群落调查"
        ordering = ("community_code", "id")

    def __str__(self) -> str:
        return self.community_code or str(self.pk)


class SpeciesComposition(ProjectScopedModel):
    community_survey = models.ForeignKey(
        CommunitySurvey,
        on_delete=models.CASCADE,
        related_name="species_compositions",
        verbose_name="群落调查",
    )
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="community_compositions",
        verbose_name="物种",
    )
    raw_taxon_name = models.CharField(
        max_length=160, blank=True, verbose_name="原始物种名"
    )
    abundance = models.FloatField(null=True, blank=True, verbose_name="多度")
    coverage_percent = models.FloatField(
        null=True, blank=True, verbose_name="盖度百分比"
    )
    frequency = models.FloatField(null=True, blank=True, verbose_name="频度")
    importance_value = models.FloatField(null=True, blank=True, verbose_name="重要值")
    life_form = models.CharField(max_length=80, blank=True, verbose_name="生活型")
    notes = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        verbose_name = "群落物种组成"
        verbose_name_plural = "群落物种组成"
        ordering = ("community_survey_id", "id")

    def __str__(self) -> str:
        return self.raw_taxon_name or str(self.taxon_id)


class CommunityMetricValue(ProjectScopedModel):
    community_survey = models.ForeignKey(
        CommunitySurvey,
        on_delete=models.CASCADE,
        related_name="metric_values",
        verbose_name="群落调查",
    )
    metric_code = models.SlugField(max_length=100, verbose_name="指标编码")
    metric_name = models.CharField(max_length=160, verbose_name="指标名称")
    value = models.FloatField(null=True, blank=True, verbose_name="指标值")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")
    method = models.CharField(max_length=160, blank=True, verbose_name="计算方法")

    class Meta:
        verbose_name = "群落指标值"
        verbose_name_plural = "群落指标值"
        ordering = ("community_survey_id", "metric_code")
        constraints = [
            models.UniqueConstraint(
                fields=("community_survey", "metric_code"),
                name="uniq_community_metric",
            )
        ]

    def __str__(self) -> str:
        return self.metric_name


class TraitObservation(ProjectScopedModel):
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trait_observations",
        verbose_name="物种",
    )
    individual = models.ForeignKey(
        IndividualOrganism,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trait_observations",
        verbose_name="个体",
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trait_observations",
        verbose_name="样方",
    )
    observed_at = models.DateTimeField(null=True, blank=True, verbose_name="观测时间")
    trait_code = models.SlugField(max_length=100, verbose_name="性状编码")
    trait_name = models.CharField(max_length=160, verbose_name="性状名称")
    value_text = models.CharField(max_length=255, blank=True, verbose_name="文本值")
    value_numeric = models.FloatField(null=True, blank=True, verbose_name="数值")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trait_observations",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "功能性状观测"
        verbose_name_plural = "功能性状观测"
        ordering = ("-observed_at", "id")
        indexes = [models.Index(fields=("trait_code",))]

    def __str__(self) -> str:
        return self.trait_name


class FieldObservation(ProjectScopedModel):
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="调查事件",
    )
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="地点",
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="样方",
    )
    individual = models.ForeignKey(
        IndividualOrganism,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="个体",
    )
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="物种",
    )
    observation_type = models.CharField(
        max_length=80, blank=True, verbose_name="观测类型"
    )
    observed_at = models.DateTimeField(null=True, blank=True, verbose_name="观测时间")
    longitude = models.FloatField(null=True, blank=True, verbose_name="经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="纬度")
    description = models.TextField(blank=True, verbose_name="观测描述")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_observations",
        verbose_name="来源数据资源",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "野外观测记录"
        verbose_name_plural = "野外观测记录"
        ordering = ("-observed_at", "id")
        indexes = [models.Index(fields=("longitude", "latitude"))]

    def __str__(self) -> str:
        return self.observation_type or str(self.pk)


class SurveyRoute(ProjectScopedModel):
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_routes",
        verbose_name="调查事件",
    )
    route_code = models.SlugField(
        max_length=100, null=True, blank=True, verbose_name="路线编码"
    )
    name = models.CharField(max_length=180, blank=True, verbose_name="路线名称")
    line_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_routes",
        verbose_name="路线空间资源",
    )
    map_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="survey_routes",
        verbose_name="路线图层",
    )
    notes = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "route_code"),
                name="ecology_surveyroute_route_code_project"[:63],
            )
        ]
        verbose_name = "调查路线"
        verbose_name_plural = "调查路线"
        ordering = ("route_code", "id")

    def __str__(self) -> str:
        return self.name or self.route_code or str(self.pk)


class SpecimenRecord(ProjectScopedModel):
    specimen_code = models.SlugField(
        max_length=120, null=True, blank=True, verbose_name="标本编码"
    )
    survey_event = models.ForeignKey(
        SurveyEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specimens",
        verbose_name="调查事件",
    )
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specimens",
        verbose_name="物种",
    )
    individual = models.ForeignKey(
        IndividualOrganism,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specimens",
        verbose_name="个体",
    )
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specimens",
        verbose_name="地点",
    )
    sample_code = models.CharField(max_length=120, blank=True, verbose_name="样品编号")
    material_type = models.CharField(max_length=80, blank=True, verbose_name="材料类型")
    collector = models.CharField(max_length=120, blank=True, verbose_name="采集人")
    collected_at = models.DateTimeField(null=True, blank=True, verbose_name="采集时间")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specimens",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "specimen_code"),
                name="ecology_specimenrecord_specimen_code_project"[:63],
            )
        ]
        verbose_name = "标本/采样记录"
        verbose_name_plural = "标本/采样记录"
        ordering = ("specimen_code", "id")

    def __str__(self) -> str:
        return self.specimen_code or self.sample_code or str(self.pk)


class RemoteSensingProduct(ProjectScopedModel):
    product_code = models.SlugField(
        max_length=120, null=True, blank=True, verbose_name="产品编码"
    )
    name = models.CharField(max_length=180, verbose_name="产品名称")
    product_type = models.CharField(max_length=80, blank=True, verbose_name="产品类型")
    sensor = models.CharField(max_length=120, blank=True, verbose_name="传感器")
    acquired_on = models.DateField(null=True, blank=True, verbose_name="获取日期")
    period_start = models.DateField(null=True, blank=True, verbose_name="周期开始")
    period_end = models.DateField(null=True, blank=True, verbose_name="周期结束")
    resolution = models.CharField(max_length=80, blank=True, verbose_name="分辨率")
    index_name = models.CharField(max_length=80, blank=True, verbose_name="指数名称")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="remote_sensing_products",
        verbose_name="数据资源",
    )
    raster_dataset = models.ForeignKey(
        RasterDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="remote_sensing_products",
        verbose_name="栅格数据集",
    )
    map_layer = models.ForeignKey(
        MapLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="remote_sensing_products",
        verbose_name="地图图层",
    )
    bounds_4326 = models.JSONField(default=list, blank=True, verbose_name="经纬度范围")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="产品元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "product_code"),
                name="ecology_remotesensingproduct_product_code_project"[:63],
            )
        ]
        verbose_name = "遥感产品"
        verbose_name_plural = "遥感产品"
        ordering = ("-acquired_on", "name", "id")

    def __str__(self) -> str:
        return self.name


class RasterSampleValue(ProjectScopedModel):
    product = models.ForeignKey(
        RemoteSensingProduct,
        on_delete=models.CASCADE,
        related_name="sample_values",
        verbose_name="遥感产品",
    )
    site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_sample_values",
        verbose_name="地点",
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_sample_values",
        verbose_name="样方",
    )
    individual = models.ForeignKey(
        IndividualOrganism,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_sample_values",
        verbose_name="个体",
    )
    population = models.ForeignKey(
        PopulationUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="raster_sample_values",
        verbose_name="种群",
    )
    longitude = models.FloatField(null=True, blank=True, verbose_name="经度")
    latitude = models.FloatField(null=True, blank=True, verbose_name="纬度")
    sampled_at = models.DateTimeField(null=True, blank=True, verbose_name="采样时间")
    band_name = models.CharField(max_length=80, blank=True, verbose_name="波段")
    metric_code = models.SlugField(max_length=100, blank=True, verbose_name="指标编码")
    value = models.FloatField(null=True, blank=True, verbose_name="采样值")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")

    class Meta:
        verbose_name = "遥感采样值"
        verbose_name_plural = "遥感采样值"
        ordering = ("product_id", "id")
        indexes = [models.Index(fields=("longitude", "latitude"))]

    def __str__(self) -> str:
        return self.metric_code or self.band_name or str(self.pk)
