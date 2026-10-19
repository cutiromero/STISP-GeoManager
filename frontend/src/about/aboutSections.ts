import helpContent from "./helpContent.json";
import helpGuidePreview from "../assets/about/help-guide-preview.png";
import knowledgePopulusForestImage from "../assets/about/knowledge-populus-forest.png";

export type AboutSectionKey =
  | "system"
  | "team"
  | "knowledge"
  | "contact"
  | "docs";

export type AboutSource = {
  label: string;
  url?: string;
  note?: string;
};

export type AboutSection = {
  key: AboutSectionKey;
  title: string;
  badge: string;
  path: string;
  eyebrow: string;
  summary: string;
  navSummary: string;
  tags: string[];
  sources: AboutSource[];
};

export const aboutAssets = {
  helpGuidePreview,
  knowledgePopulusForestImage,
};

export const aboutSections: AboutSection[] = [
  {
    key: "system",
    title: "系统简介",
    badge: "平台定位",
    path: "/about/system",
    eyebrow: "平台概览",
    summary:
      "平台面向胡杨林生态系统保护、空间数据管理、数据查询和专题展示，提供统一的数据底座与可视化工作台，服务遥感影像、野外调查、长期监测和科研成果沉淀。",
    navSummary: "平台定位",
    tags: ["多源数据汇聚", "三维地理可视化", "专题组织", "智能检索"],
    sources: [
      {
        label: "软件设计文档",
        note: "本地项目设计边界与建设目标",
      },
    ],
  },
  {
    key: "team",
    title: "团队介绍",
    badge: "科研团队",
    path: "/about/team",
    eyebrow: "TEAM / AIR CAS",
    summary: "中国科学院空天信息创新研究院团队的研究方向、成员介绍与论文成果。",
    navSummary: "研究方向与成员",
    tags: ["遥感解译", "时空计算", "地质资源", "生态环境"],
    sources: [
      {
        label: "中国科学院空天信息创新研究院",
        url: "https://www.aircas.ac.cn/",
      },
    ],
  },
  {
    key: "knowledge",
    title: "胡杨知识",
    badge: "科研知识",
    path: "/about/knowledge",
    eyebrow: "Populus euphratica",
    summary:
      "本栏目聚合胡杨物种知识、代表论文、分子机制和保护监测主题，把平台的数据资源与科研背景连接起来。",
    navSummary: "科研知识",
    tags: ["雌雄基因组", "性别决定", "灰杨适应演化", "生态保护"],
    sources: [
      {
        label: "Communications Biology 论文",
        url: "https://www.nature.com/articles/s42003-022-04145-7",
        note: "胡杨雌雄基因组与性别决定机制",
      },
      {
        label: "Horticulture Research 论文",
        url: "https://academic.oup.com/hr/article/11/3/uhae034/7601711",
        note: "灰杨染色体级基因组与荒漠化适应演化",
      },
    ],
  },
  {
    key: "contact",
    title: "联系我们",
    badge: "服务支持",
    path: "/about/contact",
    eyebrow: "Contact & Support",
    summary:
      "按数据权限与平台技术两类场景分流受理咨询，帮助用户快速找到准确联系人并准备完整的问题信息。",
    navSummary: "咨询与反馈",
    tags: ["数据权限", "资料提交", "平台建设", "故障反馈"],
    sources: [],
  },
  {
    key: "docs",
    title: "帮助文档",
    badge: "使用支持",
    path: "/about/docs",
    eyebrow: "Help Center",
    summary:
      "帮助中心面向普通用户、科研用户、数据管理员和系统管理员，集中提供平台导览、空间查询、数据与成果导入、成果管理和后台管理说明。",
    navSummary: "使用支持",
    tags: ["快速入门", "空间查询", "数据导入", "常见问题"],
    sources: [
      {
        label: "开发者指南",
        note: "接口与功能说明",
      },
      {
        label: "软件设计文档",
        note: "平台功能边界",
      },
    ],
  },
];

/** “胡杨科普”已经升级为一级模块；关于我们保留平台、团队、联系与帮助内容。 */
export const aboutNavigationSections = aboutSections.filter(
  (section) => section.key !== "knowledge",
);

export const knowledgePapers = [
  {
    journal: "Communications Biology",
    mark: "Comms Bio",
    volume: "2022",
    impact: "Nature Portfolio",
    title:
      "Chromosome-scale assemblies of the male and female Populus euphratica genomes reveal the molecular basis of sex determination and sexual dimorphism",
    authors:
      "Shanhe Zhang, Zhihua Wu, De Ma, Juntuan Zhai, Xiaoli Han, Peipei Jiao, Zhijun Li",
    year: "2022",
    doi: "10.1038/s42003-022-04145-7",
    url: "https://www.nature.com/articles/s42003-022-04145-7",
    theme: "性别决定",
    group: "雌雄基因组",
    summary:
      "完成胡杨雌雄染色体级基因组组装，揭示性别决定与性二态分子基础，为性别鉴定分子标记开发奠定基础。",
  },
  {
    journal: "Horticulture Research",
    mark: "Hortic Res",
    volume: "2024",
    impact: "Genome",
    title:
      "The chromosome-scale genome and population genomics reveal the adaptative evolution of Populus pruinosa to desertification environment",
    authors:
      "Jianhao Sun, Jindong Xu, Chen Qiu, Juntuan Zhai, Shanhe Zhang, Zhihua Wu, Zhijun Li",
    year: "2024",
    doi: "10.1093/hr/uhae034",
    url: "https://academic.oup.com/hr/article/11/3/uhae034/7601711",
    theme: "适应演化",
    group: "灰杨抗逆",
    summary:
      "构建灰杨染色体级基因组并结合群体基因组分析，解释灰杨适应荒漠化环境的遗传基础。",
  },
  {
    journal: "Industrial Crops and Products",
    mark: "Ind Crops",
    volume: "2024",
    impact: "Epigenetics",
    title:
      "DNA methylation profile revealed the dynamically epigenetic regulation of the distinct heteromorphic leaf development in Populus euphratica",
    authors:
      "Chen Qiu, Shuo Liu, Jianhao Sun, Zhongshuai Gai, Xiaoli Han, Peipei Jiao, Juntuan Zhai, Zhijun Li",
    year: "2024",
    doi: "10.1016/j.indcrop.2024.118688",
    url: "https://doi.org/10.1016/j.indcrop.2024.118688",
    theme: "异形叶发育",
    group: "表观遗传",
    summary:
      "从 DNA 甲基化视角解析胡杨异形叶发育的动态表观调控，为理解叶片形态适应提供证据链。",
  },
  {
    journal: "International Journal of Molecular Sciences",
    mark: "IJMS",
    volume: "2026",
    impact: "Gene Family",
    title:
      "Genome-Wide Identification of the WOX Gene Family in Three Populus Species and Expression Profiling of Populus euphratica and Populus pruinosa Under Abiotic Stresses",
    authors:
      "Chen Qiu, Xinyue Long, Zhongshuai Gai, Xiaoli Han, Jia Song, Yuqi Yang, Jianhao Sun, Zhijun Li",
    year: "2026",
    doi: "10.3390/ijms27135999",
    url: "https://doi.org/10.3390/ijms27135999",
    theme: "抗逆机制",
    group: "WOX 基因家族",
    summary:
      "系统鉴定胡杨、灰杨等杨属植物 WOX 基因家族，分析其在非生物胁迫下的表达响应。",
  },
  {
    journal: "Journal of Forestry Research",
    mark: "J Forestry",
    volume: "2020",
    impact: "Transcriptome",
    title:
      "Short-term transcriptomic responses of Populus euphratica roots and leaves to drought stress",
    authors:
      "Peipei Jiao, Zhihua Wu, Xu Wang, Zhenbo Jiang, Yanqin Wang, Hong Liu, Rui Qin, Zhijun Li",
    year: "2020",
    doi: "10.1007/s11676-020-01123-9",
    url: "https://doi.org/10.1007/s11676-020-01123-9",
    theme: "干旱响应",
    group: "转录组",
    summary:
      "比较胡杨根和叶在短期干旱胁迫下的转录响应，为抗旱机制研究和保护育种提供分子线索。",
  },
  {
    journal: "Frontiers in Genetics",
    mark: "Frontiers",
    volume: "2019",
    impact: "Salt Stress",
    title:
      "Transcriptomic Analysis of Seed Germination Under Salt Stress in Two Desert Sister Species (Populus euphratica and P. pruinosa)",
    authors:
      "Caihua Zhang, Wenchun Luo, Yanda Li, Xu Zhang, Xiaotao Bai, Zhimin Niu, Xiao Zhang, Zhijun Li",
    year: "2019",
    doi: "10.3389/fgene.2019.00231",
    url: "https://doi.org/10.3389/fgene.2019.00231",
    theme: "盐胁迫",
    group: "种子萌发",
    summary:
      "比较胡杨和灰杨种子萌发阶段对盐胁迫的转录组响应，支撑干旱区姐妹种抗逆差异研究。",
  },
];

export const knowledgeThemes = [
  {
    title: "异形叶发育",
    description:
      "围绕窄叶、阔叶及不同冠层叶片形态，串联转录组、表观遗传和生态功能证据，解释胡杨如何在强光、干旱、盐碱和水分梯度中形成兼顾抗逆与光合效率的叶形策略。",
  },
  {
    title: "雌雄基因组",
    description:
      "以胡杨雌雄染色体级基因组为基础，聚焦 Y 染色体性别连锁区、ARR17 相关调控线索和性别鉴定分子标记，呈现从基础研究到精准造林应用的转化路径。",
  },
  {
    title: "群体遗传",
    description:
      "连接种质资源采集、核心保护单元、区域群体分化和遗传多样性评估，支撑天然胡杨林保护、退化群落修复与优异种质筛选。",
  },
  {
    title: "灰杨抗逆",
    description:
      "从灰杨基因组、盐旱胁迫响应和种间比较入手，补充胡杨林生态系统中近缘种荒漠适应研究，为抗逆机制解析提供参照。",
  },
];

export const knowledgeValueCards = [
  {
    value: "61%",
    label: "我国胡杨林面积约占全球比例",
    detail: "胡杨是全球干旱区河岸林生态系统中极具代表性的建群树种。",
  },
  {
    value: "89%",
    label: "新疆塔里木河流域分布占比",
    detail: "塔里木河流域是我国胡杨林集中分布和保护修复的关键区域。",
  },
  {
    value: "4000+",
    label: "胡杨种质资源积累",
    detail:
      "长期野外调查、样本采集和资源保存工作为种质资源保护和精准利用提供基础。",
  },
  {
    value: "43",
    label: "遗传多样性保护单元",
    detail: "保护单元划定有助于支撑天然胡杨林资源的精细化保育。",
  },
];

export const knowledgeGraphLegend = [
  { group: "hub", label: "知识枢纽" },
  { group: "genome", label: "基因组与性别决定" },
  { group: "stress", label: "抗逆与适应演化" },
  { group: "leaf", label: "异形叶与表观调控" },
  { group: "conservation", label: "保护利用与监测" },
];

export const knowledgeGraphClusters = [
  { group: "genome", label: "基因组机制" },
  { group: "leaf", label: "异形叶调控" },
  { group: "stress", label: "抗逆适应" },
  { group: "conservation", label: "保护应用" },
];

export const knowledgeGraphNodes = [
  {
    id: "hub",
    label: "胡杨知识体系",
    group: "hub",
    x: 50,
    y: 50,
    detail:
      "以科研论文和平台数据为入口，汇聚基因组机制、异形叶调控、抗逆适应和保护应用四类知识。",
  },
  {
    id: "genome",
    label: "胡杨雌雄基因组",
    group: "genome",
    x: 50,
    y: 13,
    detail: "染色体级组装连接性别决定和性二态研究。",
  },
  {
    id: "slr",
    label: "性别连锁区 SLR",
    group: "genome",
    x: 31,
    y: 24,
    detail: "定位 Y 染色体关键区域，支撑性别鉴定标记开发。",
  },
  {
    id: "arr17",
    label: "ARR17 相关机制",
    group: "genome",
    x: 69,
    y: 24,
    detail: "关注甲基化与性别表达调控线索。",
  },
  {
    id: "marker",
    label: "性别鉴定标记",
    group: "genome",
    x: 50,
    y: 36,
    detail: "服务苗期雌雄识别和精准造林配置。",
  },
  {
    id: "leaf",
    label: "异形叶发育",
    group: "leaf",
    x: 18,
    y: 38,
    detail: "解释下层窄叶和上层阔叶的功能分化。",
  },
  {
    id: "methyl",
    label: "DNA 甲基化",
    group: "leaf",
    x: 30,
    y: 53,
    detail: "表观调控连接叶形变化与逆境适应。",
  },
  {
    id: "transcriptome",
    label: "转录组响应",
    group: "leaf",
    x: 18,
    y: 68,
    detail: "连接叶片形态变化、根叶响应和逆境下的表达调控。",
  },
  {
    id: "stress",
    label: "盐旱胁迫响应",
    group: "stress",
    x: 82,
    y: 38,
    detail: "组织转录组、基因家族和生理响应证据。",
  },
  {
    id: "wox",
    label: "WOX 基因家族",
    group: "stress",
    x: 70,
    y: 53,
    detail: "补充胡杨和灰杨在非生物胁迫下的基因家族表达线索。",
  },
  {
    id: "pruinosa",
    label: "灰杨荒漠适应",
    group: "stress",
    x: 82,
    y: 68,
    detail: "通过灰杨基因组补充姐妹种荒漠适应研究。",
  },
  {
    id: "germplasm",
    label: "种质资源保育",
    group: "conservation",
    x: 50,
    y: 84,
    detail: "连接样本采集、保护单元和资源评价。",
  },
  {
    id: "monitoring",
    label: "遥感与样地监测",
    group: "conservation",
    x: 31,
    y: 82,
    detail: "支撑宏观分布、退化识别和恢复成效跟踪。",
  },
  {
    id: "restoration",
    label: "生态修复应用",
    group: "conservation",
    x: 69,
    y: 82,
    detail: "将性别鉴定、种质选择和监测评估转化为恢复配置策略。",
  },
];

export const knowledgeGraphEdges = [
  { from: "genome", to: "slr", tone: "genome", label: "定位", bend: -2 },
  { from: "genome", to: "arr17", tone: "genome", label: "调控", bend: 2 },
  { from: "slr", to: "marker", tone: "genome", label: "标记", bend: 1 },
  { from: "arr17", to: "marker", tone: "genome", label: "表达", bend: -1 },
  { from: "marker", to: "hub", tone: "genome", label: "转化", bend: 0 },
  { from: "leaf", to: "methyl", tone: "leaf", label: "表观调控", bend: -1 },
  {
    from: "methyl",
    to: "transcriptome",
    tone: "leaf",
    label: "表达响应",
    bend: 1,
  },
  { from: "methyl", to: "hub", tone: "leaf", label: "叶形机制", bend: 3 },
  { from: "hub", to: "wox", tone: "stress", label: "抗逆机制", bend: -3 },
  { from: "stress", to: "wox", tone: "stress", label: "基因响应", bend: 1 },
  { from: "wox", to: "pruinosa", tone: "stress", label: "适应演化", bend: -1 },
  {
    from: "hub",
    to: "germplasm",
    tone: "conservation",
    label: "资源沉淀",
    bend: 0,
  },
  {
    from: "monitoring",
    to: "germplasm",
    tone: "conservation",
    label: "监测评估",
    bend: -2,
  },
  {
    from: "germplasm",
    to: "restoration",
    tone: "conservation",
    label: "修复应用",
    bend: 2,
  },
];

export const knowledgeMechanisms = [
  {
    title: "胡杨性别决定机制图解",
    description:
      "基于雌雄染色体级基因组研究，页面将性别决定过程拆解为基因组组装、Y 染色体性别连锁区定位、ARR17 相关甲基化线索和性别鉴定分子标记四个层级，帮助用户理解科研成果如何转化为苗期识别能力。",
    source: "Communications Biology, 2022",
    tone: "genome",
    tags: ["Y 染色体", "SLR", "ARR17", "DNA 分子标记"],
    steps: [
      "雌雄基因组组装",
      "定位性别连锁区",
      "解析甲基化线索",
      "开发鉴定标记",
    ],
  },
  {
    title: "异形叶发育调控网络",
    description:
      "围绕胡杨下层窄叶、上层阔叶以及不同冠层梯度下的形态分化，页面以转录组、DNA 甲基化和生态功能为线索，说明异形叶如何在抗逆、防失水和光合效率之间形成适应性平衡。",
    source: "Industrial Crops and Products, 2024",
    tone: "leaf",
    tags: ["异形叶", "转录组", "DNA 甲基化", "冠层梯度"],
    steps: ["环境梯度", "叶形分化", "多组学调控", "生态适应"],
  },
  {
    title: "灰杨荒漠适应与抗逆响应",
    description:
      "灰杨作为胡杨林生态系统中的重要近缘种，其基因组和群体遗传研究揭示了荒漠化环境适应路径；结合盐旱胁迫响应研究，可为抗逆新种质培育和区域生态修复提供比较视角。",
    source: "Horticulture Research, 2024 / IJMS, 2026",
    tone: "stress",
    tags: ["灰杨基因组", "WOX 基因", "盐旱胁迫", "荒漠适应"],
    steps: ["灰杨基因组", "群体分化", "胁迫表达", "抗逆利用"],
  },
];

export type HelpArticleBlock =
  | {
      type: "steps";
      title: string;
      items: { title: string; description: string }[];
    }
  | {
      type: "bullets" | "checklist";
      title: string;
      items: string[];
    }
  | {
      type: "note";
      title: string;
      body: string;
    }
  | {
      type: "table";
      title: string;
      columns: string[];
      rows: string[][];
    };

export type HelpArticle = {
  id: string;
  category: string;
  title: string;
  summary: string;
  audiences: string[];
  tags: string[];
  blocks: HelpArticleBlock[];
};

export const helpDocumentDownload = {
  label: "下载 PDF 帮助文档",
  href: `${import.meta.env.BASE_URL}docs/platform-help-center.pdf`,
  filename: "时空智能服务平台使用手册.pdf",
  meta: "2026-09-18 / 项目标签、数据上传、制图与公共内容",
};

export const helpQuickLinks = [
  { label: "快速入门", articleId: "quick-start" },
  { label: "空间查询", articleId: "spatial-query" },
  { label: "数据导入", articleId: "data-import" },
  { label: "权限日志", articleId: "permission-audit" },
];

export const helpAudienceCards = [
  {
    title: "普通用户",
    description: "浏览授权数据、加载图层、查看属性、执行基础查询。",
  },
  {
    title: "科研用户",
    description: "提交数据、导出结果、保存工程和沉淀专题成果。",
  },
  {
    title: "数据管理员",
    description: "维护所属项目的存量数据、默认样式、分组和成果。",
  },
  {
    title: "系统管理员",
    description: "管理账号、角色、日志、系统设置和数据备份。",
  },
];

export const helpCategories = [
  {
    title: "入门指南",
    items: [
      { label: "平台导览", articleId: "platform-guide" },
      { label: "快速入门", articleId: "quick-start" },
      { label: "账号、角色与权限", articleId: "account-roles" },
    ],
  },
  {
    title: "空间分析",
    items: [
      { label: "地理数据工作台", articleId: "map-workbench" },
      { label: "空间查询工作台", articleId: "spatial-query" },
      { label: "属性查询与图层", articleId: "attribute-layer" },
    ],
  },
  {
    title: "数据管理",
    items: [
      { label: "数据与成果导入", articleId: "data-import" },
      { label: "数据准备规范", articleId: "data-standards" },
      { label: "存量数据维护", articleId: "data-inventory" },
      { label: "工程、制图与成果", articleId: "project-topic" },
    ],
  },
  {
    title: "后台管理",
    items: [
      { label: "后台运行概览", articleId: "admin-management" },
      { label: "权限与日志", articleId: "permission-audit" },
      { label: "备份与安全", articleId: "backup-security" },
    ],
  },
];

export const helpArticles: HelpArticle[] =
  helpContent.articles as HelpArticle[];

export const helpFaq = [
  {
    question: "导入数据前最容易忽略什么？",
    answer:
      "最容易忽略字段含义、坐标系、采集日期和访问范围。建议在导入前先补齐字段说明、来源单位、数据日期和敏感信息判断。",
  },
  {
    question: "空间查询没有结果时应如何排查？",
    answer:
      "先确认数据已加载到图层树且为可查询矢量来源，再检查查询范围是否相交、资源是否启用及当前项目权限。空间查询按来源重新查询，原属性筛选不自动带入。",
  },
  {
    question: "同名数据继续导入会覆盖旧数据吗？",
    answer:
      "不会。系统会创建新的数据记录。为便于后续管理，建议在名称中加入区域、日期、批次或版本号。",
  },
  {
    question: "管理员如何为用户分配数据查看权限？",
    answer:
      "由超级管理员在后台项目管理中为用户分配对应项目标签；操作权限另由账号和角色管理控制。公开项目无需分配。",
  },
  {
    question: "帮助文档 PDF 可以离线使用吗？",
    answer:
      "可以。页面提供 PDF 下载按钮，适用于培训、验收附件和离线阅读。平台功能继续迭代后，应同步更新 PDF 文件。",
  },
];

export function aboutSectionByKey(key: string | undefined) {
  return (
    aboutSections.find((section) => section.key === key) ?? aboutSections[0]!
  );
}
