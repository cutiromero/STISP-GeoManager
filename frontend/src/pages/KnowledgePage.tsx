import {
  BranchesOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Layout, Typography } from "antd";
import poplarWaterGoldenImage from "../assets/about/poplar-water-golden.jpeg";
import xjafsMonitoringTowerImage from "../assets/about/xjafs-monitoring-tower.png";
import knowledgeAncientPoplarImage from "../assets/portal/knowledge-ancient-poplar.png";
import { aboutSectionByKey } from "../about/aboutSections";
import { protectionCases, speciesArchiveSections } from "../about/contentV2";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import { KnowledgeSection } from "./KnowledgeHelpSections";
import { currentLocale } from "../i18n";
import { EnglishKnowledgePage } from "./EnglishEditorialPages";

const navigation = [
  {
    index: "01",
    title: "物种档案",
    summary: "名片、价值、文化、生存智慧与科研价值",
    href: "#species-archive",
  },
  {
    index: "02",
    title: "保护管理",
    summary: "生态输水、引洪灌溉与系统治理案例",
    href: "#protection-management",
  },
  {
    index: "03",
    title: "胡杨知识图谱",
    summary: "保留原有论文、机制与联合交互图谱",
    href: "#knowledge-graph",
  },
];

export default function KnowledgePage() {
  const { user } = useAppContext();
  const section = aboutSectionByKey("knowledge");

  if (currentLocale() === "en-US") {
    return <EnglishKnowledgePage />;
  }

  return (
    <Layout className="workspace">
      <WorkspaceHeader
        activeTab="knowledge"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="workspace-body workspace-body-about">
        <aside className="about-page-nav-panel knowledge-page-nav-panel">
          <div className="about-page-panel-head">
            <Typography.Text strong>胡杨科普</Typography.Text>
          </div>
          <nav
            className="knowledge-v2-primary-nav"
            aria-label="胡杨科普内容导航"
          >
            {navigation.map((item) => (
              <a href={item.href} key={item.index}>
                <span>{item.index}</span>
                <strong>{item.title}</strong>
                <small>{item.summary}</small>
              </a>
            ))}
          </nav>
          <div className="knowledge-v2-species-links">
            <strong>物种档案</strong>
            {speciesArchiveSections.map((item) => (
              <a href={`#species-${item.id}`} key={item.id}>
                {item.index} {item.title}
              </a>
            ))}
          </div>
          <p className="knowledge-page-nav-note">
            从物种认识进入保护实践，再沿知识图谱深入基因组、异形叶与抗逆机制。
          </p>
        </aside>

        <main className="about-page-main-panel knowledge-page-main-panel knowledge-v2-main">
          <section
            className="knowledge-v2-hero"
            style={{
              backgroundImage: `linear-gradient(90deg, rgba(5, 31, 27, 0.95), rgba(5, 31, 27, 0.54) 58%, rgba(5, 31, 27, 0.08)), url(${knowledgeAncientPoplarImage})`,
            }}
          >
            <div>
              <span>POPULUS EUPHRATICA / DESERT SURVIVOR</span>
              <Typography.Title level={1}>荒漠脊梁 / 生态丰碑</Typography.Title>
              <Typography.Paragraph>
                一棵胡杨连接物种演化、河流廊道、荒漠生态水文、边疆文化与现代保护科技。这里以图文档案、治理案例和科研知识图谱，完整呈现它如何生存，又为何值得守护。
              </Typography.Paragraph>
              <div>
                {[
                  "唯一能在戈壁荒漠成林的乔木树种",
                  "我国拥有全球约 61% 的胡杨林",
                  "塔里木河流域是核心分布与保护区",
                ].map((item) => (
                  <span key={item}>
                    <CheckCircleOutlined />
                    {item}
                  </span>
                ))}
              </div>
            </div>
            <aside>
              <small>物种档案编号</small>
              <strong>PE-001</strong>
              <span>杨柳科 / 杨属</span>
              <em>Populus euphratica Oliver</em>
            </aside>
          </section>

          <section className="knowledge-v2-section" id="species-archive">
            <KnowledgeTitle
              icon={<ReadOutlined />}
              index="01"
              eyebrow="SPECIES ARCHIVE"
              title="物种档案"
              description="用五组内容建立从快速认识到科学理解的完整物种名片。"
            />
            <div className="knowledge-v2-archive-grid">
              {speciesArchiveSections.map((item) => (
                <article id={`species-${item.id}`} key={item.id}>
                  <header>
                    <span>{item.index}</span>
                    <div>
                      <small>{item.eyebrow}</small>
                      <strong>{item.title}</strong>
                    </div>
                  </header>
                  <p>{item.summary}</p>
                  <ul>
                    {item.facts.map((fact) => (
                      <li key={fact}>
                        <CheckCircleOutlined />
                        {fact}
                      </li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>

            <div className="knowledge-v2-image-story">
              <figure>
                <img alt="河流与金色胡杨林" src={poplarWaterGoldenImage} />
              </figure>
              <div>
                <span>文化与景观</span>
                <Typography.Title level={3}>
                  金秋胡杨与水上胡杨
                </Typography.Title>
                <Typography.Paragraph>
                  金秋时节，胡杨叶色由绿转黄；在河流与沙漠交汇处，树影映入水面。景观之美背后，是河岸林对水文过程高度敏感的生态事实。
                </Typography.Paragraph>
                <div>
                  <span>最佳观赏期</span>
                  <strong>10 月中下旬至 11 月初</strong>
                </div>
              </div>
            </div>
          </section>

          <section
            className="knowledge-v2-section knowledge-v2-protection"
            id="protection-management"
          >
            <KnowledgeTitle
              icon={<SafetyCertificateOutlined />}
              index="02"
              eyebrow="PROTECTION MANAGEMENT"
              title="保护管理"
              description="从生态输水到样地监测，展示胡杨林保护如何由工程行动转化为可量化生态成效。"
            />
            <div className="knowledge-v2-protection-lead">
              <div>
                <span>科学保护主线</span>
                <Typography.Title level={3}>
                  水量调度 + 工程灌溉 + 长期监测 + 网格管护
                </Typography.Title>
                <Typography.Paragraph>
                  胡杨林恢复不是一次性“浇水”，而是以河流过程为基础，结合生态闸、引洪渠、地下水监测、固定样地与林长制巡护的长期系统工程。
                </Typography.Paragraph>
              </div>
              <figure>
                <img
                  alt="胡杨林森林梯度观测塔"
                  src={xjafsMonitoringTowerImage}
                />
                <figcaption>定位观测将保护成效转化为连续科学数据</figcaption>
              </figure>
            </div>
            <div className="knowledge-v2-case-list">
              {protectionCases.map((item) => (
                <article key={item.id}>
                  <header>
                    <span>{item.index}</span>
                    <strong>{item.title}</strong>
                  </header>
                  <p>{item.summary}</p>
                  <div className="knowledge-v2-case-body">
                    <section>
                      <small>保护措施</small>
                      {item.measures.map((measure) => (
                        <p key={measure}>
                          <BranchesOutlined />
                          {measure}
                        </p>
                      ))}
                    </section>
                    <section>
                      <small>关键成效</small>
                      <div>
                        {item.outcomes.map((outcome) => (
                          <span key={outcome}>{outcome}</span>
                        ))}
                      </div>
                    </section>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="knowledge-v2-section" id="knowledge-graph">
            <KnowledgeTitle
              icon={<ExperimentOutlined />}
              index="03"
              eyebrow="KNOWLEDGE GRAPH"
              title="胡杨知识图谱"
              description="保留并强化原有论文脉络、四大知识域、联合交互图谱和机制图解。"
            />
            <KnowledgeSection embedded section={section} />
          </section>
        </main>
      </div>
    </Layout>
  );
}

function KnowledgeTitle({
  icon,
  index,
  eyebrow,
  title,
  description,
}: {
  icon: React.ReactNode;
  index: string;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="knowledge-v2-title">
      <span>{icon}</span>
      <strong>{index}</strong>
      <div>
        <small>{eyebrow}</small>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Paragraph>{description}</Typography.Paragraph>
      </div>
    </div>
  );
}
