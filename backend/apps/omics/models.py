from apps.projects.scoping import ProjectScopedModel
from django.db import models

from apps.catalog.models import DataResource
from apps.ecology.models import (
    IndividualOrganism,
    PopulationUnit,
    SamplePlot,
    Site,
    Taxon,
)
from apps.standards.models import SourceSheet


class BiologicalSample(ProjectScopedModel):
    sample_code = models.CharField(max_length=120, verbose_name="样品编号")
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="物种",
    )
    source_site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="采集地点",
    )
    individual = models.ForeignKey(
        IndividualOrganism,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="个体",
    )
    population = models.ForeignKey(
        PopulationUnit,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="种群",
    )
    sample_plot = models.ForeignKey(
        SamplePlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="样方",
    )
    material_type = models.CharField(max_length=80, blank=True, verbose_name="材料类型")
    sex = models.CharField(max_length=40, blank=True, verbose_name="性别")
    collected_at = models.DateTimeField(null=True, blank=True, verbose_name="采集时间")
    collector = models.CharField(max_length=120, blank=True, verbose_name="采集人")
    raw_location = models.TextField(blank=True, verbose_name="原始地点")
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
        related_name="biological_samples",
        verbose_name="来源数据资源",
    )
    source_sheet = models.ForeignKey(
        SourceSheet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="biological_samples",
        verbose_name="来源小表",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "sample_code"),
                name="omics_biologicalsample_sample_code_project"[:63],
            )
        ]
        verbose_name = "生物样品"
        verbose_name_plural = "生物样品"
        ordering = ("sample_code", "id")
        indexes = [
            models.Index(fields=("longitude", "latitude")),
            models.Index(fields=("material_type",)),
        ]

    def __str__(self) -> str:
        return self.sample_code


class GermplasmAccession(ProjectScopedModel):
    accession_code = models.CharField(max_length=120, verbose_name="种质资源编号")
    biological_sample = models.OneToOneField(
        BiologicalSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="germplasm_accession",
        verbose_name="生物样品",
    )
    sample_code = models.CharField(max_length=120, blank=True, verbose_name="样品编号")
    taxon = models.ForeignKey(
        Taxon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="germplasm_accessions",
        verbose_name="物种",
    )
    source_site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="germplasm_accessions",
        verbose_name="采集地点",
    )
    material_type = models.CharField(max_length=80, blank=True, verbose_name="材料类型")
    resource_type = models.CharField(
        max_length=120, blank=True, verbose_name="资源类型"
    )
    sex = models.CharField(max_length=40, blank=True, verbose_name="性别")
    is_core = models.BooleanField(default=False, verbose_name="核心种质资源")
    storage_status = models.CharField(
        max_length=120, blank=True, verbose_name="保存状态"
    )
    raw_location = models.TextField(blank=True, verbose_name="原始地点")
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
        related_name="germplasm_accessions",
        verbose_name="来源数据资源",
    )
    source_sheet = models.ForeignKey(
        SourceSheet,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="germplasm_accessions",
        verbose_name="来源小表",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "accession_code"),
                name="omics_germplasmaccession_accession_code_project"[:63],
            )
        ]
        verbose_name = "种质资源"
        verbose_name_plural = "种质资源"
        ordering = ("accession_code", "id")
        indexes = [
            models.Index(fields=("sample_code",)),
            models.Index(fields=("resource_type",)),
            models.Index(fields=("is_core",)),
            models.Index(fields=("longitude", "latitude")),
        ]

    def __str__(self) -> str:
        return self.accession_code


class MolecularSample(ProjectScopedModel):
    molecular_sample_code = models.CharField(
        max_length=120, verbose_name="分子样品编号"
    )
    biological_sample = models.ForeignKey(
        BiologicalSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_samples",
        verbose_name="生物样品",
    )
    nucleic_acid_type = models.CharField(
        max_length=40, blank=True, verbose_name="核酸类型"
    )
    extraction_method = models.CharField(
        max_length=160, blank=True, verbose_name="提取方法"
    )
    concentration = models.FloatField(null=True, blank=True, verbose_name="浓度")
    purity_260_280 = models.FloatField(null=True, blank=True, verbose_name="260/280")
    storage_condition = models.CharField(
        max_length=120, blank=True, verbose_name="保存条件"
    )
    extracted_at = models.DateTimeField(null=True, blank=True, verbose_name="提取时间")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_samples",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "molecular_sample_code"),
                name="omics_molecularsample_molecular_sample_code_project"[:63],
            )
        ]
        verbose_name = "分子样品"
        verbose_name_plural = "分子样品"
        ordering = ("molecular_sample_code", "id")

    def __str__(self) -> str:
        return self.molecular_sample_code


class MolecularAssay(ProjectScopedModel):
    assay_code = models.CharField(max_length=120, verbose_name="实验编号")
    molecular_sample = models.ForeignKey(
        MolecularSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assays",
        verbose_name="分子样品",
    )
    biological_sample = models.ForeignKey(
        BiologicalSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_assays",
        verbose_name="生物样品",
    )
    assay_type = models.CharField(max_length=80, blank=True, verbose_name="实验类型")
    marker_name = models.CharField(max_length=120, blank=True, verbose_name="标记名称")
    batch_code = models.CharField(max_length=120, blank=True, verbose_name="批次编号")
    laboratory = models.CharField(max_length=160, blank=True, verbose_name="实验室")
    assayed_on = models.DateField(null=True, blank=True, verbose_name="实验日期")
    result_status = models.CharField(max_length=80, blank=True, verbose_name="结果状态")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_assays",
        verbose_name="来源数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "assay_code"),
                name="omics_molecularassay_assay_code_project"[:63],
            )
        ]
        verbose_name = "分子实验"
        verbose_name_plural = "分子实验"
        ordering = ("assay_code", "id")

    def __str__(self) -> str:
        return self.assay_code


class MolecularResult(ProjectScopedModel):
    assay = models.ForeignKey(
        MolecularAssay,
        on_delete=models.CASCADE,
        related_name="results",
        verbose_name="分子实验",
    )
    result_code = models.CharField(max_length=120, blank=True, verbose_name="结果编号")
    locus = models.CharField(max_length=120, blank=True, verbose_name="位点")
    allele = models.CharField(max_length=120, blank=True, verbose_name="等位基因")
    value_text = models.CharField(max_length=255, blank=True, verbose_name="文本值")
    value_numeric = models.FloatField(null=True, blank=True, verbose_name="数值")
    unit = models.CharField(max_length=64, blank=True, verbose_name="单位")
    quality_flag = models.CharField(max_length=80, blank=True, verbose_name="质控标记")
    source_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_results",
        verbose_name="来源数据资源",
    )

    class Meta:
        verbose_name = "分子实验结果"
        verbose_name_plural = "分子实验结果"
        ordering = ("assay_id", "id")

    def __str__(self) -> str:
        return self.result_code or str(self.pk)


class MolecularFile(ProjectScopedModel):
    file_code = models.CharField(max_length=120, verbose_name="文件编号")
    assay = models.ForeignKey(
        MolecularAssay,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="files",
        verbose_name="分子实验",
    )
    file_type = models.CharField(max_length=80, blank=True, verbose_name="文件类型")
    file_format = models.CharField(max_length=40, blank=True, verbose_name="文件格式")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="molecular_files",
        verbose_name="数据资源",
    )
    storage_path = models.CharField(max_length=500, blank=True, verbose_name="存储路径")
    checksum = models.CharField(max_length=128, blank=True, verbose_name="校验值")
    size_bytes = models.PositiveBigIntegerField(default=0, verbose_name="文件大小")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "file_code"),
                name="omics_molecularfile_file_code_project"[:63],
            )
        ]
        verbose_name = "分子数据文件"
        verbose_name_plural = "分子数据文件"
        ordering = ("file_code", "id")

    def __str__(self) -> str:
        return self.file_code


class GenomeDataset(ProjectScopedModel):
    genome_dataset_code = models.CharField(
        max_length=120, verbose_name="基因组数据集编号"
    )
    name = models.CharField(max_length=180, verbose_name="数据集名称")
    biological_sample = models.ForeignKey(
        BiologicalSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_datasets",
        verbose_name="生物样品",
    )
    dataset_type = models.CharField(
        max_length=80, blank=True, verbose_name="数据集类型"
    )
    platform = models.CharField(max_length=120, blank=True, verbose_name="测序平台")
    source_site = models.ForeignKey(
        Site,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_datasets",
        verbose_name="空间来源",
    )
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_datasets",
        verbose_name="数据资源",
    )
    status = models.CharField(max_length=80, blank=True, verbose_name="状态")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "genome_dataset_code"),
                name="omics_genomedataset_genome_dataset_code_project"[:63],
            )
        ]
        verbose_name = "基因组数据集"
        verbose_name_plural = "基因组数据集"
        ordering = ("genome_dataset_code", "id")
        indexes = [models.Index(fields=("dataset_type",))]

    def __str__(self) -> str:
        return self.name


class SequencingRun(ProjectScopedModel):
    run_code = models.CharField(max_length=120, verbose_name="测序批次编号")
    genome_dataset = models.ForeignKey(
        GenomeDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sequencing_runs",
        verbose_name="基因组数据集",
    )
    biological_sample = models.ForeignKey(
        BiologicalSample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sequencing_runs",
        verbose_name="生物样品",
    )
    platform = models.CharField(max_length=120, blank=True, verbose_name="测序平台")
    library_strategy = models.CharField(
        max_length=80, blank=True, verbose_name="文库策略"
    )
    read_length = models.PositiveIntegerField(default=0, verbose_name="读长")
    read_count = models.PositiveBigIntegerField(default=0, verbose_name="读数")
    run_date = models.DateField(null=True, blank=True, verbose_name="测序日期")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sequencing_runs",
        verbose_name="数据资源",
    )
    notes = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "run_code"),
                name="omics_sequencingrun_run_code_project"[:63],
            )
        ]
        verbose_name = "测序批次"
        verbose_name_plural = "测序批次"
        ordering = ("run_code", "id")

    def __str__(self) -> str:
        return self.run_code


class GenomeSequenceFile(ProjectScopedModel):
    file_code = models.CharField(max_length=120, verbose_name="基因组文件编号")
    genome_dataset = models.ForeignKey(
        GenomeDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sequence_files",
        verbose_name="基因组数据集",
    )
    sequencing_run = models.ForeignKey(
        SequencingRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sequence_files",
        verbose_name="测序批次",
    )
    file_role = models.CharField(max_length=80, blank=True, verbose_name="文件角色")
    file_format = models.CharField(max_length=40, blank=True, verbose_name="文件格式")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_sequence_files",
        verbose_name="数据资源",
    )
    storage_path = models.CharField(max_length=500, blank=True, verbose_name="存储路径")
    checksum = models.CharField(max_length=128, blank=True, verbose_name="校验值")
    size_bytes = models.PositiveBigIntegerField(default=0, verbose_name="文件大小")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "file_code"),
                name="omics_genomesequencefile_file_code_project"[:63],
            )
        ]
        verbose_name = "基因组序列文件"
        verbose_name_plural = "基因组序列文件"
        ordering = ("file_code", "id")

    def __str__(self) -> str:
        return self.file_code


class GenomeAssembly(ProjectScopedModel):
    assembly_code = models.CharField(max_length=120, verbose_name="组装编号")
    genome_dataset = models.ForeignKey(
        GenomeDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assemblies",
        verbose_name="基因组数据集",
    )
    version = models.CharField(max_length=80, blank=True, verbose_name="版本")
    assembly_level = models.CharField(
        max_length=80, blank=True, verbose_name="组装级别"
    )
    genome_size = models.PositiveBigIntegerField(default=0, verbose_name="基因组大小")
    contig_n50 = models.PositiveBigIntegerField(default=0, verbose_name="Contig N50")
    scaffold_n50 = models.PositiveBigIntegerField(
        default=0, verbose_name="Scaffold N50"
    )
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_assemblies",
        verbose_name="数据资源",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "assembly_code"),
                name="omics_genomeassembly_assembly_code_project"[:63],
            )
        ]
        verbose_name = "基因组组装"
        verbose_name_plural = "基因组组装"
        ordering = ("assembly_code", "id")

    def __str__(self) -> str:
        return self.assembly_code


class VariantDataset(ProjectScopedModel):
    variant_code = models.CharField(max_length=120, verbose_name="变异集编号")
    genome_dataset = models.ForeignKey(
        GenomeDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variant_datasets",
        verbose_name="基因组数据集",
    )
    variant_type = models.CharField(max_length=80, blank=True, verbose_name="变异类型")
    reference_assembly = models.CharField(
        max_length=120, blank=True, verbose_name="参考组装"
    )
    variant_count = models.PositiveBigIntegerField(default=0, verbose_name="变异数量")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variant_datasets",
        verbose_name="数据资源",
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "variant_code"),
                name="omics_variantdataset_variant_code_project"[:63],
            )
        ]
        verbose_name = "变异数据集"
        verbose_name_plural = "变异数据集"
        ordering = ("variant_code", "id")

    def __str__(self) -> str:
        return self.variant_code


class GenomeAnnotation(ProjectScopedModel):
    annotation_code = models.CharField(max_length=120, verbose_name="注释编号")
    genome_dataset = models.ForeignKey(
        GenomeDataset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="annotations",
        verbose_name="基因组数据集",
    )
    annotation_type = models.CharField(
        max_length=80, blank=True, verbose_name="注释类型"
    )
    reference_version = models.CharField(
        max_length=120, blank=True, verbose_name="参考版本"
    )
    gene_count = models.PositiveIntegerField(default=0, verbose_name="基因数量")
    data_resource = models.ForeignKey(
        DataResource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genome_annotations",
        verbose_name="数据资源",
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project_tag", "annotation_code"),
                name="omics_genomeannotation_annotation_code_project"[:63],
            )
        ]
        verbose_name = "基因组注释"
        verbose_name_plural = "基因组注释"
        ordering = ("annotation_code", "id")

    def __str__(self) -> str:
        return self.annotation_code
