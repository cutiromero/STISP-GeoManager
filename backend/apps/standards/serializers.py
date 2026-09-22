from __future__ import annotations

from apps.standards.models import (
    DataDomainType,
    SpatialClass,
)
from apps.catalog.taxonomy import taxonomy_tree


def domain_definitions() -> list[dict]:
    return [
        {
            "code": DataDomainType.GERMPLASM,
            "name": "种质数据",
            "spatialClass": SpatialClass.SPATIALIZED_TABLE,
            "description": "胡杨、灰杨及伴生植物种质资源，管理采集来源、样品编号、核心资源标记和后续分子/基因组数据关联。",
            "recommendedResourceTypes": ["vector", "gene", "table"],
            "coreEntities": ["GermplasmAccession", "BiologicalSample", "Site", "Taxon"],
        },
        {
            "code": DataDomainType.GENOME,
            "name": "基因组数据",
            "spatialClass": SpatialClass.NON_SPATIAL,
            "description": "测序、组装、变异、注释等非地理组学成果；通过生物样品追溯采集地、个体或种群空间来源。",
            "recommendedResourceTypes": ["gene", "table"],
            "coreEntities": ["GenomeDataset", "GenomeSequenceFile", "BiologicalSample"],
        },
        {
            "code": DataDomainType.INDIVIDUAL,
            "name": "个体数据",
            "spatialClass": SpatialClass.SPATIAL,
            "description": "单株或单个植株个体的位置、性别、健康状态和观测指标。",
            "recommendedResourceTypes": ["vector", "table"],
            "coreEntities": ["IndividualOrganism", "TraitObservation", "BiologicalSample"],
        },
        {
            "code": DataDomainType.COMMUNITY,
            "name": "群落数据",
            "spatialClass": SpatialClass.SPATIALIZED_TABLE,
            "description": "样方、群落组成、多样性指标和功能性状等数据。",
            "recommendedResourceTypes": ["vector", "table"],
            "coreEntities": [
                "SamplePlot",
                "CommunitySurvey",
                "SpeciesComposition",
                "CommunityMetricValue",
            ],
        },
        {
            "code": DataDomainType.POPULATION,
            "name": "种群数据",
            "spatialClass": SpatialClass.SPATIAL,
            "description": "某区域内某物种种群的空间范围、调查事件和种群指标。",
            "recommendedResourceTypes": ["vector", "table"],
            "coreEntities": ["PopulationUnit", "SamplePlot", "RasterSampleValue"],
        },
        {
            "code": DataDomainType.FIELD_SURVEY,
            "name": "野外调查数据",
            "spatialClass": SpatialClass.SPATIALIZED_TABLE,
            "description": "调查任务、路线、样点、采集记录、野外照片和观察记录。",
            "recommendedResourceTypes": ["vector", "table", "image"],
            "coreEntities": ["SurveyEvent", "FieldObservation", "SurveyRoute", "SpecimenRecord"],
        },
        {
            "code": DataDomainType.REMOTE_SENSING,
            "name": "遥感影像数据",
            "spatialClass": SpatialClass.SPATIAL,
            "description": "原始遥感影像、无人机影像、NDVI/NPP、生物量、分类和变化检测产品。",
            "recommendedResourceTypes": ["raster", "vector"],
            "coreEntities": ["RasterDataset", "RemoteSensingProduct", "RasterSampleValue"],
        },
        {
            "code": DataDomainType.MOLECULAR,
            "name": "分子数据",
            "spatialClass": SpatialClass.NON_SPATIAL,
            "description": "DNA/RNA 提取、PCR、分子标记、实验批次和实验结果文件；通过生物样品关联空间来源。",
            "recommendedResourceTypes": ["gene", "table", "document"],
            "coreEntities": ["MolecularSample", "MolecularAssay", "MolecularResult", "MolecularFile"],
        },
        {
            "code": DataDomainType.VECTOR,
            "name": "矢量数据",
            "spatialClass": SpatialClass.SPATIAL,
            "description": "以点、线、面几何为主体的 Shapefile、GeoJSON、GeoPackage 等空间矢量资源，支持统一入库、查询、符号化和地图展示。",
            "recommendedResourceTypes": ["vector"],
            "coreEntities": ["DataResource", "VectorDataset", "MapLayer"],
        },
        {
            "code": DataDomainType.OTHER,
            "name": "其他类型",
            "spatialClass": SpatialClass.SPATIALIZED_TABLE,
            "description": "暂未归入专门专题的数据资源，可先按空间点表、普通表、文档或图片统一登记，后续再补充字段映射和标准化归类。",
            "recommendedResourceTypes": ["vector", "table", "document", "image"],
            "coreEntities": ["DataResource", "SourceDataset", "SourceSheet"],
        },
    ]


def schema_layers() -> list[dict]:
    return [
        {
            "name": "平台管理元数据层",
            "storage": "app_data/database/metadata.sqlite3",
            "description": "保存用户、权限、资源、目录、图层、工程和日志。",
        },
        {
            "name": "科研数据物理存储层",
            "storage": "vector.gpkg + table/data.sqlite + raster/ + gene/",
            "description": "保存几何、原始表格、栅格文件和组学大文件。",
        },
        {
            "name": "生态业务语义层",
            "storage": "Django 主库新增模型",
            "description": "保存样方、个体、种群、群落、种质、样品和物种等标准实体。",
        },
        {
            "name": "质量治理与追溯层",
            "storage": "Django 主库新增模型",
            "description": "保存源文件、字段映射、坐标解析、质量问题和源记录关联。",
        },
    ]


def schema_entities() -> list[dict]:
    return [
        {
            "name": "GermplasmAccession",
            "label": "种质资源",
            "domainTypes": [DataDomainType.GERMPLASM],
            "description": "连接样品、物种、采集地、核心资源标记和后续分子/基因组数据。",
            "keyFields": ["accession_code", "sample_code", "taxon_id", "source_site_id", "is_core"],
        },
        {
            "name": "Taxon",
            "label": "物种",
            "domainTypes": [
                DataDomainType.GERMPLASM,
                DataDomainType.INDIVIDUAL,
                DataDomainType.COMMUNITY,
                DataDomainType.POPULATION,
                DataDomainType.FIELD_SURVEY,
            ],
            "description": "胡杨、灰杨及伴生植物的标准物种主表，承接原始物种名和后续别名治理。",
            "keyFields": ["code", "name_cn", "scientific_name"],
        },
        {
            "name": "Site",
            "label": "采集地点/样地",
            "domainTypes": [
                DataDomainType.GERMPLASM,
                DataDomainType.INDIVIDUAL,
                DataDomainType.POPULATION,
                DataDomainType.FIELD_SURVEY,
                DataDomainType.GENOME,
                DataDomainType.MOLECULAR,
            ],
            "description": "统一保存采集地点、经纬度、海拔和行政区，是表格数据空间化后的地点锚点。",
            "keyFields": ["site_code", "name", "longitude", "latitude", "altitude"],
        },
        {
            "name": "BiologicalSample",
            "label": "生物样品",
            "domainTypes": [
                DataDomainType.GERMPLASM,
                DataDomainType.GENOME,
                DataDomainType.MOLECULAR,
            ],
            "description": "连接地理来源与分子/基因组数据的样品主表。",
            "keyFields": ["sample_code", "taxon_id", "individual_id", "population_id", "site_id"],
        },
        {
            "name": "SurveyEvent",
            "label": "野外调查事件",
            "domainTypes": [DataDomainType.FIELD_SURVEY, DataDomainType.COMMUNITY, DataDomainType.POPULATION],
            "description": "记录调查任务、时间、负责人和来源资源，用于串联路线、样方、群落和观测记录。",
            "keyFields": ["survey_code", "study_area_id", "started_on", "ended_on"],
        },
        {
            "name": "SamplePlot",
            "label": "样方/样点",
            "domainTypes": [DataDomainType.COMMUNITY, DataDomainType.FIELD_SURVEY],
            "description": "群落调查和野外调查的空间锚点。",
            "keyFields": ["plot_code", "site_id", "longitude", "latitude"],
        },
        {
            "name": "IndividualOrganism",
            "label": "植物个体",
            "domainTypes": [DataDomainType.INDIVIDUAL, DataDomainType.GERMPLASM, DataDomainType.FIELD_SURVEY],
            "description": "保存单株植物位置、性别、生长阶段和健康状态，可关联种质样品和功能性状观测。",
            "keyFields": ["individual_code", "taxon_id", "site_id", "population_id", "longitude", "latitude"],
        },
        {
            "name": "PopulationUnit",
            "label": "种群单元",
            "domainTypes": [DataDomainType.POPULATION, DataDomainType.INDIVIDUAL],
            "description": "描述某区域内某物种种群，可关联空间范围、样方、个体和遥感采样值。",
            "keyFields": ["population_code", "taxon_id", "site_id", "study_area_id"],
        },
        {
            "name": "CommunitySurvey",
            "label": "群落调查",
            "domainTypes": [DataDomainType.COMMUNITY],
            "description": "保存样方群落类型、盖度、物种数和多样性指数等群落层级信息。",
            "keyFields": ["community_code", "sample_plot_id", "survey_event_id"],
        },
        {
            "name": "SpeciesComposition",
            "label": "群落物种组成",
            "domainTypes": [DataDomainType.COMMUNITY],
            "description": "保存群落调查中的物种、多度、盖度、频度和重要值。",
            "keyFields": ["community_survey_id", "taxon_id", "raw_taxon_name"],
        },
        {
            "name": "TraitObservation",
            "label": "功能性状观测",
            "domainTypes": [DataDomainType.COMMUNITY, DataDomainType.INDIVIDUAL, DataDomainType.FIELD_SURVEY],
            "description": "按个体、样方或物种记录功能性状指标，兼容文本值和数值。",
            "keyFields": ["trait_code", "individual_id", "sample_plot_id", "value_numeric"],
        },
        {
            "name": "FieldObservation",
            "label": "野外观测记录",
            "domainTypes": [DataDomainType.FIELD_SURVEY],
            "description": "保存野外调查过程中的点位观测、描述、物种和个体关联。",
            "keyFields": ["survey_event_id", "site_id", "observation_type", "observed_at"],
        },
        {
            "name": "RemoteSensingProduct",
            "label": "遥感产品",
            "domainTypes": [DataDomainType.REMOTE_SENSING],
            "description": "登记遥感影像、指数产品、栅格数据集和地图图层之间的业务关系。",
            "keyFields": ["product_code", "product_type", "raster_dataset_id", "data_resource_id"],
        },
        {
            "name": "RasterSampleValue",
            "label": "遥感采样值",
            "domainTypes": [DataDomainType.REMOTE_SENSING, DataDomainType.POPULATION, DataDomainType.COMMUNITY],
            "description": "把遥感产品在地点、样方、个体或种群上的采样值标准化入库。",
            "keyFields": ["product_id", "site_id", "sample_plot_id", "metric_code", "value"],
        },
        {
            "name": "GenomeDataset",
            "label": "基因组数据集",
            "domainTypes": [DataDomainType.GENOME],
            "description": "测序、组装、变异、注释等基因组数据的统一登记实体。",
            "keyFields": ["genome_dataset_code", "bio_sample_id", "dataset_type", "data_resource_id"],
        },
        {
            "name": "SequencingRun",
            "label": "测序批次",
            "domainTypes": [DataDomainType.GENOME],
            "description": "记录测序平台、文库策略、读长、读数和测序日期。",
            "keyFields": ["run_code", "genome_dataset_id", "biological_sample_id", "platform"],
        },
        {
            "name": "GenomeSequenceFile",
            "label": "基因组序列文件",
            "domainTypes": [DataDomainType.GENOME],
            "description": "登记原始 reads、清洗 reads、组装输入输出等基因组文件与 DataResource 的关系。",
            "keyFields": ["file_code", "genome_dataset_id", "file_role", "data_resource_id"],
        },
        {
            "name": "GenomeAssembly",
            "label": "基因组组装",
            "domainTypes": [DataDomainType.GENOME],
            "description": "保存组装版本、级别、基因组大小、N50 等组装指标。",
            "keyFields": ["assembly_code", "genome_dataset_id", "version", "data_resource_id"],
        },
        {
            "name": "VariantDataset",
            "label": "变异数据集",
            "domainTypes": [DataDomainType.GENOME],
            "description": "保存 SNP、InDel 等变异集与参考组装、文件资源之间的关系。",
            "keyFields": ["variant_code", "genome_dataset_id", "variant_type", "data_resource_id"],
        },
        {
            "name": "GenomeAnnotation",
            "label": "基因组注释",
            "domainTypes": [DataDomainType.GENOME],
            "description": "保存基因、功能、结构等注释结果和对应文件资源。",
            "keyFields": ["annotation_code", "genome_dataset_id", "annotation_type", "data_resource_id"],
        },
        {
            "name": "MolecularSample",
            "label": "分子样品",
            "domainTypes": [DataDomainType.MOLECULAR],
            "description": "记录 DNA/RNA 提取、浓度、纯度、保存条件等分子样品信息。",
            "keyFields": ["molecular_sample_code", "biological_sample_id", "nucleic_acid_type"],
        },
        {
            "name": "MolecularAssay",
            "label": "分子实验",
            "domainTypes": [DataDomainType.MOLECULAR],
            "description": "记录 PCR、分子标记、实验批次、实验室和结果状态。",
            "keyFields": ["assay_code", "molecular_sample_id", "assay_type", "batch_code"],
        },
        {
            "name": "MolecularResult",
            "label": "分子实验结果",
            "domainTypes": [DataDomainType.MOLECULAR],
            "description": "按实验记录位点、等位基因、数值或文本结果和质控标记。",
            "keyFields": ["assay_id", "result_code", "locus", "value_numeric"],
        },
        {
            "name": "MolecularFile",
            "label": "分子数据文件",
            "domainTypes": [DataDomainType.MOLECULAR],
            "description": "登记分子实验产生的图谱、结果表和文档文件。",
            "keyFields": ["file_code", "assay_id", "file_type", "data_resource_id"],
        },
        {
            "name": "GenericImportedDataset",
            "label": "其他导入数据",
            "domainTypes": [DataDomainType.OTHER],
            "description": "承接暂未归入专门业务专题的数据资源，保留源文件、工作表、字段说明和后续归类线索。",
            "keyFields": ["data_resource_id", "source_file_name", "sheet_name", "file_format"],
        },
        {
            "name": "VectorDataset",
            "label": "矢量数据集",
            "domainTypes": [DataDomainType.VECTOR],
            "description": "记录矢量源文件、源图层、编码、坐标系、几何质量、标准化 GeoPackage 图层和渲染策略。",
            "keyFields": ["data_resource_id", "source_format", "source_layer_name", "geometry_type", "feature_count"],
        },
    ]


def catalog_tree() -> list[dict]:
    return taxonomy_tree()
