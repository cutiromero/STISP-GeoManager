import { useAppContext } from "../contexts/AppContext";
import CardCover from "../components/CardCover";
import { canReadHelp, downloadHelp } from "../about/helpAccess";
import {
  BookOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  DownloadOutlined,
  FilePdfOutlined,
  GlobalOutlined,
  LinkOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Button, Input, Tag, Typography } from "antd";
import { useState } from "react";
import {
  aboutAssets,
  helpAudienceCards,
  helpArticles,
  helpCategories,
  helpFaq,
  helpQuickLinks,
  type HelpArticle,
  type HelpArticleBlock,
  knowledgeGraphNodes,
  knowledgeGraphLegend,
  knowledgeMechanisms,
  knowledgePapers,
  knowledgeThemes,
  knowledgeValueCards,
  type AboutSection,
} from "../about/aboutSections";

export function KnowledgeSection({
  section,
  embedded = false,
}: {
  section: AboutSection;
  embedded?: boolean;
}) {
  const [hoveredGraphNodeId, setHoveredGraphNodeId] = useState<string | null>(
    null,
  );
  const graphNodeById = new Map(
    knowledgeGraphNodes.map((node) => [node.id, node]),
  );
  const graphDomains = [
    {
      group: "genome",
      index: "01",
      title: "基因组机制",
      summary: "雌雄基因组、性别决定区域与鉴定标记构成分子识别链条。",
      nodeIds: ["genome", "slr", "arr17", "marker"],
    },
    {
      group: "leaf",
      index: "02",
      title: "异形叶调控",
      summary: "从异形叶发育进入甲基化调控与转录组响应，解释叶形适应。",
      nodeIds: ["leaf", "methyl", "transcriptome"],
    },
    {
      group: "stress",
      index: "03",
      title: "抗逆适应",
      summary: "围绕盐旱胁迫、WOX 基因家族和灰杨比较研究形成抗逆证据链。",
      nodeIds: ["stress", "wox", "pruinosa"],
    },
    {
      group: "conservation",
      index: "04",
      title: "保护应用",
      summary: "将遥感监测、种质保育和生态修复连接到平台的数据服务场景。",
      nodeIds: ["monitoring", "germplasm", "restoration"],
    },
  ];
  const featuredPapers = knowledgePapers.slice(0, 2);
  const supportingPapers = knowledgePapers.slice(2);
  const defaultGraphNode =
    knowledgeGraphNodes.find((node) => node.id === "hub") ??
    knowledgeGraphNodes[0]!;
  const activeGraphNode =
    (hoveredGraphNodeId ? graphNodeById.get(hoveredGraphNodeId) : undefined) ??
    defaultGraphNode;
  const activeGraphNodeGroup =
    knowledgeGraphLegend.find((item) => item.group === activeGraphNode.group)
      ?.label ?? "知识节点";
  const activeGraphDomain =
    graphDomains.find((domain) => domain.group === activeGraphNode.group) ??
    graphDomains[0]!;
  const activeGraphDomainTitle =
    activeGraphNode.group === "hub" ? "联合知识体系" : activeGraphDomain.title;

  return (
    <>
      {!embedded ? (
        <section className="about-page-knowledge-hero">
          <div className="about-page-knowledge-hero-copy">
            <span className="about-page-kicker">{section.eyebrow}</span>
            <Typography.Title level={2}>
              胡杨知识（Populus euphratica）
            </Typography.Title>
            <Typography.Paragraph>
              面向胡杨林生态保护、种质资源保育和荒漠适应机制研究，本页将胡杨与灰杨相关科研成果重组为论文脉络、知识图谱、机制图解和生态价值四类内容，帮助用户从宏观生态屏障快速进入基因组、异形叶、抗逆响应等关键科学问题。
            </Typography.Paragraph>
            <div className="about-page-highlight-row">
              {section.tags.map((item) => (
                <span key={item}>
                  <CheckCircleOutlined />
                  {item}
                </span>
              ))}
            </div>
          </div>
          <figure>
            <CardCover
              alt="河畔古胡杨林景观"
              thumbnailUrl={aboutAssets.knowledgePopulusForestImage}
            />
            <figcaption>河畔古胡杨林与荒漠绿洲生态屏障</figcaption>
          </figure>
        </section>
      ) : null}

      <section className="about-page-card-grid about-page-knowledge-theme-grid">
        {knowledgeThemes.map((item, themeIndex) => (
          <article
            className="about-page-feature-card about-page-knowledge-theme-card"
            id={`knowledge-theme-${themeIndex + 1}`}
            key={item.title}
          >
            <strong>{item.title}</strong>
            <p>{item.description}</p>
          </article>
        ))}
      </section>

      <section className="about-page-knowledge-paper-wall">
        <div className="about-page-block-title">
          <ReadOutlined />
          <Typography.Title level={3}>
            从学术前沿到分子密码的科研路径全景
          </Typography.Title>
        </div>
        <div className="about-page-paper-wall-layout">
          <div className="about-page-paper-feature-column">
            {featuredPapers.map((paper) => (
              <article
                className="about-page-paper-cover-card about-page-paper-cover-feature"
                key={paper.doi}
              >
                <div className="about-page-paper-cover-head">
                  <span>{paper.mark}</span>
                  <small>
                    {paper.volume} / {paper.impact}
                  </small>
                </div>
                <strong>{paper.title}</strong>
                <p>{paper.authors}</p>
                <em>{paper.summary}</em>
                <div>
                  <Tag color="green">{paper.year}</Tag>
                  <Tag>{paper.theme}</Tag>
                  <Tag>{paper.group}</Tag>
                </div>
                <a href={paper.url} rel="noreferrer" target="_blank">
                  DOI: {paper.doi}
                  <LinkOutlined />
                </a>
              </article>
            ))}
          </div>
          <div className="about-page-paper-support-grid">
            {supportingPapers.map((paper) => (
              <article className="about-page-paper-cover-card" key={paper.doi}>
                <div className="about-page-paper-cover-head">
                  <span>{paper.mark}</span>
                  <small>{paper.volume}</small>
                </div>
                <strong>{paper.title}</strong>
                <p>{paper.authors}</p>
                <em>{paper.summary}</em>
                <div>
                  <Tag color="green">{paper.year}</Tag>
                  <Tag>{paper.theme}</Tag>
                </div>
                <a href={paper.url} rel="noreferrer" target="_blank">
                  DOI: {paper.doi}
                  <LinkOutlined />
                </a>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="about-page-split about-page-graph-section about-page-knowledge-map-section">
        <div className="about-page-knowledge-map-copy">
          <div className="about-page-block-title">
            <BranchesOutlined />
            <Typography.Title level={3}>
              胡杨知识互联网联合交互图谱
            </Typography.Title>
          </div>
          <Typography.Paragraph>
            知识图谱把论文中的基因组、性别决定、异形叶发育、抗逆适应、种质保育和遥感监测等知识点连接起来。节点之间的关系用于呈现研究主题的延展方向，鼠标悬停可查看简要说明，便于从单篇论文进入更完整的科研知识网络。
          </Typography.Paragraph>
          <div className="about-page-legend about-page-knowledge-legend">
            {knowledgeGraphLegend.map((item) => (
              <span data-group={item.group} key={item.group}>
                {item.label}
              </span>
            ))}
          </div>
        </div>
        <div className="about-page-knowledge-graph">
          <div className="about-page-graph-board">
            {graphDomains.map((domain) => {
              const isActiveDomain = activeGraphNode.group === domain.group;
              return (
                <article
                  className={`about-page-graph-domain about-page-graph-domain-${domain.group}${
                    isActiveDomain ? " about-page-graph-domain-active" : ""
                  }`}
                  key={domain.group}
                >
                  <header>
                    <span>{domain.index}</span>
                    <div>
                      <strong>{domain.title}</strong>
                      <small>{domain.summary}</small>
                    </div>
                  </header>
                  <div className="about-page-graph-chain">
                    {domain.nodeIds.map((nodeId) => {
                      const node = graphNodeById.get(nodeId);
                      if (!node) {
                        return null;
                      }
                      return (
                        <button
                          aria-label={`${node.label}：${node.detail}`}
                          className={`about-page-graph-chip about-page-graph-chip-${node.group}${
                            activeGraphNode.id === node.id
                              ? " about-page-graph-chip-active"
                              : ""
                          }`}
                          key={node.id}
                          title={node.detail}
                          type="button"
                          onClick={() => setHoveredGraphNodeId(node.id)}
                          onFocus={() => setHoveredGraphNodeId(node.id)}
                          onMouseEnter={() => setHoveredGraphNodeId(node.id)}
                        >
                          {node.label}
                        </button>
                      );
                    })}
                  </div>
                </article>
              );
            })}
            <button
              aria-label={`${defaultGraphNode.label}：${defaultGraphNode.detail}`}
              className={`about-page-graph-hub-card${
                activeGraphNode.id === defaultGraphNode.id
                  ? " about-page-graph-hub-card-active"
                  : ""
              }`}
              type="button"
              onClick={() => setHoveredGraphNodeId(defaultGraphNode.id)}
              onFocus={() => setHoveredGraphNodeId(defaultGraphNode.id)}
              onMouseEnter={() => setHoveredGraphNodeId(defaultGraphNode.id)}
            >
              <span>知识枢纽</span>
              <strong>{defaultGraphNode.label}</strong>
              <small>整合论文证据、平台数据与应用场景</small>
            </button>
          </div>
          <aside
            className={`about-page-graph-detail about-page-graph-detail-${activeGraphNode.group}`}
          >
            <div>
              <span>{activeGraphNodeGroup}</span>
              <small>{activeGraphDomainTitle}</small>
            </div>
            <strong>{activeGraphNode.label}</strong>
            <p>{activeGraphNode.detail}</p>
          </aside>
        </div>
      </section>

      <section className="about-page-knowledge-mechanism-section">
        <div className="about-page-block-title">
          <SafetyCertificateOutlined />
          <Typography.Title level={3}>核心机制图解</Typography.Title>
        </div>
        <div className="about-page-knowledge-mechanism-grid">
          {knowledgeMechanisms.map((item) => (
            <article
              className={`about-page-mechanism-card about-page-mechanism-card-${item.tone}`}
              key={item.title}
            >
              <div>
                <span className="about-page-feature-icon">
                  <SafetyCertificateOutlined />
                </span>
                <small>{item.source}</small>
              </div>
              <strong>{item.title}</strong>
              <p>{item.description}</p>
              <div className="about-page-mechanism-diagram">
                {item.steps.map((step) => (
                  <span key={step}>{step}</span>
                ))}
              </div>
              <div className="about-page-chip-list">
                {item.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="about-page-knowledge-value-band">
        <div>
          <div className="about-page-block-title">
            <GlobalOutlined />
            <Typography.Title level={3}>沙漠卫士与绿色屏障</Typography.Title>
          </div>
          <Typography.Paragraph>
            胡杨以强大的耐旱、耐盐碱和河岸固沙能力守护干旱区绿洲，被誉为“沙漠卫士”。在塔里木河流域，沿河岸延展的天然胡杨林构成抵御风沙侵袭的绿色屏障，也为种质资源保育、气候变化响应和区域生态修复研究提供不可替代的天然样本。
          </Typography.Paragraph>
        </div>
        <div className="about-page-knowledge-value-grid">
          {knowledgeValueCards.map((item) => (
            <article key={item.label}>
              <strong>{item.value}</strong>
              <span>{item.label}</span>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

export function DocsSection({ section }: { section: AboutSection }) {
  const { user } = useAppContext();
  const articles = helpArticles.filter((article) =>
    canReadHelp(article.id, user),
  );
  const faq = helpFaq.filter(
    (item) =>
      !!user?.permissions.canAccessAdmin || !/管理员|PDF/.test(item.question),
  );
  const saveHelp = () =>
    downloadHelp(
      articles
        .map(
          (a) =>
            `# ${a.title}\n\n${a.summary}\n\n${a.blocks.flatMap(helpBlockText).join("\n\n")}`,
        )
        .join("\n\n"),
      false,
    );
  const [activeArticleId, setActiveArticleId] = useState("platform-guide");
  const [searchKeyword, setSearchKeyword] = useState("");
  const activeArticle =
    articles.find((article) => article.id === activeArticleId) ?? articles[0]!;
  const normalizedKeyword = searchKeyword.trim().toLowerCase();
  const filteredCategories = helpCategories
    .map((category) => ({
      ...category,
      items: category.items.filter((item) => {
        const article = articles.find(
          (candidate) => candidate.id === item.articleId,
        );
        return article ? helpArticleMatches(article, normalizedKeyword) : false;
      }),
    }))
    .filter((category) => category.items.length > 0);
  const filteredFaq = faq.filter((item) => {
    if (!normalizedKeyword) {
      return true;
    }
    return `${item.question} ${item.answer}`
      .toLowerCase()
      .includes(normalizedKeyword);
  });

  return (
    <>
      <section className="about-page-help-hero">
        <div className="about-page-help-hero-copy">
          <span className="about-page-kicker">{section.eyebrow}</span>
          <Typography.Title level={2}>{section.title}</Typography.Title>
          <Typography.Paragraph>
            帮助文档按当前账号可用功能显示。登录后可在个人设置查看工具操作和智能体权限。
          </Typography.Paragraph>
          <div
            className="about-page-help-audience-grid"
            aria-label="帮助文档适用对象"
          >
            {helpAudienceCards
              .filter(
                (card) =>
                  user?.permissions.canAccessAdmin ||
                  !card.title.includes("管理员"),
              )
              .map((card) => (
                <article key={card.title}>
                  <strong>{card.title}</strong>
                  <span>{card.description}</span>
                </article>
              ))}
          </div>
          <div className="about-page-help-actions">
            {helpQuickLinks
              .filter((link) => canReadHelp(link.articleId, user))
              .map((quickLink) => (
                <button
                  aria-pressed={activeArticle.id === quickLink.articleId}
                  key={quickLink.articleId}
                  type="button"
                  onClick={() => setActiveArticleId(quickLink.articleId)}
                >
                  <CheckCircleOutlined />
                  {quickLink.label}
                </button>
              ))}
          </div>
        </div>
        <div className="about-page-help-download">
          <FilePdfOutlined />
          <strong>离线帮助文档</strong>
          <small>当前账号适用的操作指南</small>
          <Button onClick={saveHelp} icon={<DownloadOutlined />} type="primary">
            下载当前帮助文档
          </Button>
        </div>
      </section>

      <section className="about-page-help-shell">
        <aside className="about-page-help-index">
          <Input
            allowClear
            aria-label="搜索帮助文章"
            placeholder="搜索帮助文章"
            prefix={<SearchOutlined />}
            value={searchKeyword}
            onChange={(event) => setSearchKeyword(event.target.value)}
          />
          <div className="about-page-help-index-groups">
            {filteredCategories.length > 0 ? (
              filteredCategories.map((category) => (
                <div key={category.title}>
                  <strong>{category.title}</strong>
                  {category.items.map((item) => (
                    <button
                      aria-current={
                        activeArticle.id === item.articleId ? "page" : undefined
                      }
                      className={
                        activeArticle.id === item.articleId
                          ? "about-page-help-index-active"
                          : ""
                      }
                      key={item.articleId}
                      type="button"
                      onClick={() => setActiveArticleId(item.articleId)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ))
            ) : (
              <p className="about-page-help-empty">没有匹配的帮助文章。</p>
            )}
          </div>
        </aside>

        <article className="about-page-help-reader">
          <span className="about-page-kicker">
            帮助 / {activeArticle.category} / {activeArticle.title}
          </span>
          <Typography.Title level={3}>{activeArticle.title}</Typography.Title>
          <Typography.Paragraph>{activeArticle.summary}</Typography.Paragraph>
          <div className="about-page-help-meta">
            {activeArticle.audiences.map((audience) => (
              <Tag color="green" key={audience}>
                {audience}
              </Tag>
            ))}
            {activeArticle.tags.map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </div>
          <div className="about-page-help-content">
            {activeArticle.blocks.map((block) => (
              <HelpArticleBlockView block={block} key={block.title} />
            ))}
          </div>
        </article>

        <aside className="about-page-help-side">
          <section className="about-page-help-side-panel about-page-help-download-panel">
            <FilePdfOutlined />
            <strong>我的帮助文档</strong>
            <p>当前账号适用的操作指南</p>
            <Button
              onClick={saveHelp}
              icon={<DownloadOutlined />}
              block
              type="primary"
            >
              下载当前帮助文档
            </Button>
          </section>
          <section className="about-page-help-side-panel">
            <div className="about-page-block-title">
              <BookOutlined />
              <Typography.Title level={4}>常见问题</Typography.Title>
            </div>
            <div className="about-page-help-faq-list">
              {(filteredFaq.length > 0 ? filteredFaq : faq).map((item) => (
                <details key={item.question}>
                  <summary>{item.question}</summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </section>
          <section className="about-page-pro-tip">
            反馈问题时请附上账号角色、页面路径、资源名称、截图和复现步骤；导入或栅格任务请同时提供任务
            ID。
          </section>
        </aside>
      </section>
    </>
  );
}

function HelpArticleBlockView({ block }: { block: HelpArticleBlock }) {
  if (block.type === "steps") {
    return (
      <section className="about-page-help-block">
        <Typography.Title level={4}>{block.title}</Typography.Title>
        <div className="about-page-help-steps">
          {block.items.map((item, index) => (
            <div key={item.title}>
              <span>{index + 1}</span>
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (block.type === "note") {
    return (
      <section className="about-page-help-note">
        <strong>{block.title}</strong>
        <p>{block.body}</p>
      </section>
    );
  }

  if (block.type === "table") {
    return (
      <section className="about-page-help-block">
        <Typography.Title level={4}>{block.title}</Typography.Title>
        <div className="about-page-help-table-wrap">
          <table className="about-page-help-table">
            <thead>
              <tr>
                {block.columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row) => (
                <tr key={row.join("|")}>
                  {row.map((cell, index) => (
                    <td key={`${index}-${cell}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  return (
    <section className="about-page-help-block">
      <Typography.Title level={4}>{block.title}</Typography.Title>
      <ul
        className={
          block.type === "checklist"
            ? "about-page-help-checklist"
            : "about-page-help-bullets"
        }
      >
        {block.items.map((item) => (
          <li key={item}>
            {block.type === "checklist" ? <CheckCircleOutlined /> : null}
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function helpArticleMatches(article: HelpArticle, normalizedKeyword: string) {
  if (!normalizedKeyword) {
    return true;
  }
  return [
    article.category,
    article.title,
    article.summary,
    ...article.audiences,
    ...article.tags,
    ...article.blocks.flatMap(helpBlockText),
  ]
    .join(" ")
    .toLowerCase()
    .includes(normalizedKeyword);
}

function helpBlockText(block: HelpArticleBlock) {
  if (block.type === "steps") {
    return [
      block.title,
      ...block.items.flatMap((item) => [item.title, item.description]),
    ];
  }
  if (block.type === "note") {
    return [block.title, block.body];
  }
  if (block.type === "table") {
    return [block.title, ...block.columns, ...block.rows.flat()];
  }
  return [block.title, ...block.items];
}
