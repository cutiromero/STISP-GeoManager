import {
  ArrowRightOutlined,
  FileTextOutlined,
  GlobalOutlined,
  InfoCircleOutlined,
  LinkOutlined,
  MailOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { Button, Collapse, Layout, Typography } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import {
  aboutNavigationSections,
  aboutSectionByKey,
} from "../about/aboutSections";
import { teamMembers } from "../about/teamProfile";
import { teamInstitution } from "../about/institution";
import digitalCity from "../assets/spatiotemporal/digital-city.png";
import digitalEarth from "../assets/spatiotemporal/digital-earth.png";
import aircasLogo from "../assets/team/aircas-logo.png";
import WorkspaceHeader from "../components/WorkspaceHeader";
import CardCover from "../components/CardCover";
import { platformBrand } from "../config/platformBrand";
import { useAppContext } from "../contexts/AppContext";
import { DocsSection } from "./KnowledgeHelpSections";
import { EnglishHelpCenter } from "./EnglishEditorialPages";
import "../styles/team-introduction.css";

const icons: Record<string, ReactNode> = {
  system: <InfoCircleOutlined />,
  team: <TeamOutlined />,
  contact: <MailOutlined />,
  docs: <FileTextOutlined />,
};
const englishTitles: Record<string, string> = {
  system: "Platform",
  team: "Our Team",
  contact: "Contact",
  docs: "Help Center",
};
const englishSummaries: Record<string, string> = {
  system: "Mission and capabilities",
  team: "Research and people",
  contact: "Research collaboration",
  docs: "Guides and workflows",
};

export default function AboutV2Page() {
  const { user } = useAppContext();
  const { i18n } = useTranslation();
  const en = i18n.language.startsWith("en");
  const navigate = useNavigate();
  const params = useParams();
  const active = aboutSectionByKey(params.section);
  if (
    params.section === "members" ||
    (params.section === "team" && params.institutionId)
  ) {
    return <Navigate to="/about/team" replace />;
  }
  return (
    <Layout className="workspace">
      <WorkspaceHeader
        activeTab="about"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="workspace-body workspace-body-about">
        <aside className="about-page-nav-panel">
          <div className="about-page-panel-head">
            <Typography.Text strong>
              {en ? "About Us" : "关于我们"}
            </Typography.Text>
          </div>
          <div className="about-page-nav-list">
            {aboutNavigationSections.map((section) => (
              <button
                key={section.key}
                type="button"
                aria-current={section.key === active.key ? "page" : undefined}
                className={`about-page-nav-item${section.key === active.key ? " about-page-nav-item-active" : ""}`}
                onClick={() => navigate(section.path)}
              >
                <span className="about-page-nav-icon">
                  {icons[section.key]}
                </span>
                <span>
                  <strong>
                    {en ? englishTitles[section.key] : section.title}
                  </strong>
                  <small>
                    {en ? englishSummaries[section.key] : section.navSummary}
                  </small>
                </span>
              </button>
            ))}
          </div>
          <div className="air-about-affiliation">
            <span>AIR / CAS</span>
            <strong>
              {en
                ? "Aerospace Information Research Institute"
                : teamInstitution.name}
            </strong>
          </div>
        </aside>
        <main className="about-page-main-panel air-about">
          {active.key === "team" ? (
            <TeamIntroduction en={en} />
          ) : active.key === "contact" ? (
            <ContactSection en={en} />
          ) : active.key === "docs" ? (
            en ? (
              <EnglishHelpCenter />
            ) : (
              <DocsSection section={active} />
            )
          ) : (
            <PlatformOverview en={en} onTeam={() => navigate("/about/team")} />
          )}
        </main>
      </div>
    </Layout>
  );
}

function InstitutionIdentity({ en }: { en: boolean }) {
  return (
    <a
      className="air-institution-identity"
      href={teamInstitution.website}
      target="_blank"
      rel="noreferrer"
    >
      <img
        src={aircasLogo}
        alt={en ? teamInstitution.englishName : teamInstitution.name}
      />
      <span>
        {en
          ? "Aerospace Information Research Institute / Chinese Academy of Sciences"
          : teamInstitution.name}{" "}
        <LinkOutlined />
      </span>
    </a>
  );
}

function TeamIntroduction({ en }: { en: boolean }) {
  const focusAreas = en
    ? [
        [
          "01",
          "Remote-sensing intelligence",
          "Information extraction, image segmentation and fine-scale mapping from high-resolution imagery.",
        ],
        [
          "02",
          "Spatiotemporal computing",
          "Spatiotemporal information extraction, high-performance computation and multimodal agents.",
        ],
        [
          "03",
          "Geological remote sensing",
          "Hyperspectral mineral identification, intelligent core logging and mineral exploration.",
        ],
        [
          "04",
          "Ecological applications",
          "Agricultural remote sensing, land degradation, carbon sinks and environmental risk modelling.",
        ],
      ]
    : [
        [
          "01",
          "遥感智能解译",
          "面向高分辨率遥感影像，开展信息提取、影像分割与精细制图研究。",
        ],
        [
          "02",
          "时空智能计算",
          "围绕时空信息提取、高性能计算与多模态智能体，推进数据与知识协同。",
        ],
        [
          "03",
          "地质遥感与找矿",
          "聚焦高光谱矿物识别、岩心智能编录和找矿预测，服务自然资源调查。",
        ],
        [
          "04",
          "生态环境应用",
          "研究农业生态、土地退化、森林碳汇与灾害环境风险，连接观测与建模。",
        ],
      ];
  return (
    <>
      <section
        className="air-team-hero"
        style={{
          backgroundImage: `linear-gradient(90deg, rgba(9, 30, 53, .96), rgba(9, 30, 53, .72) 55%, rgba(9, 30, 53, .2)), url(${digitalCity})`,
        }}
      >
        <span className="air-eyebrow">OUR TEAM / AIR CAS</span>
        <Typography.Title level={1}>
          {en ? "Spatiotemporal Intelligence Research Team" : "团队介绍"}
        </Typography.Title>
        <p className="air-team-subtitle">
          {en ? teamInstitution.englishName : teamInstitution.name}
        </p>
        <p>
          {en
            ? "Our research brings together remote-sensing interpretation, spatiotemporal computing, geological exploration and ecological modelling. We connect multi-source observations with information extraction and research services."
            : "围绕遥感智能解译、时空信息计算、地质资源调查与生态环境建模开展研究，连接多源观测、信息提取和科研服务。"}
        </p>
        <div className="air-hero-facts">
          <span>{en ? "High-resolution remote sensing" : "高分辨率遥感"}</span>
          <span>{en ? "Spatiotemporal intelligence" : "时空智能"}</span>
          <span>{en ? "Research collaboration" : "科研协同"}</span>
        </div>
      </section>
      <section className="air-section air-institution-section">
        <div>
          <span className="air-eyebrow">INSTITUTION</span>
          <Typography.Title level={2}>
            {en ? "Our institution" : "依托单位"}
          </Typography.Title>
          <p>
            {en
              ? "The Aerospace Information Research Institute of the Chinese Academy of Sciences brings together expertise in electronics, remote sensing, satellite ground stations and optoelectronics. The platform supports the team's work on Earth observation, geospatial information and research-data services."
              : "中国科学院空天信息创新研究院（简称“空天院”）在电子学、遥感应用、遥感卫星地面站及光电研究等领域积累的基础上整合组建。平台围绕团队在对地观测、地理信息与智能计算方面的研究，提供数据管理、空间分析和成果共享服务。"}
          </p>
          <a href={teamInstitution.profileUrl} target="_blank" rel="noreferrer">
            {en ? "Institute profile" : "空天院院情简介"} <LinkOutlined />
          </a>
        </div>
        <InstitutionIdentity en={en} />
      </section>
      <section className="air-section">
        <SectionHeading
          eyebrow="RESEARCH DIRECTIONS"
          title={en ? "Research directions" : "研究方向"}
        />
        <div className="air-research-grid">
          {focusAreas.map(([id, title, description]) => (
            <article key={id}>
              <span>{id}</span>
              <h3>
                <strong>{title}</strong>
              </h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="air-section">
        <SectionHeading
          eyebrow="PEOPLE & PUBLICATIONS"
          title={en ? "Meet the team" : "团队成员与研究成果"}
        />
        <p className="air-section-description">
          {en
            ? "Explore each member's research interests, publications and contact details."
            : "了解成员的研究方向、学术成果与联系方式。"}
        </p>
        <div className="air-member-grid">
          {teamMembers.map((member) => (
            <article className="air-member-card" key={member.id}>
              <div className="air-member-summary">
                <CardCover
                  className="air-member-portrait"
                  thumbnailUrl={member.portrait}
                  alt={
                    en ? `${member.englishName} portrait` : `${member.name}照片`
                  }
                  aspectRatio="26 / 35"
                />
                <div>
                  <h3>{en ? member.englishName : member.name}</h3>
                  <span className="air-member-role">
                    {member.id === "shen-zhanfeng"
                      ? en
                        ? "Research Professor / Doctoral Supervisor"
                        : "研究员 / 博士生导师"
                      : en
                        ? "Team member"
                        : "团队成员"}
                  </span>
                  <p>{en ? member.focusEn : member.focus}</p>
                  <a
                    className="air-member-email"
                    href={`mailto:${member.email}`}
                  >
                    <MailOutlined aria-hidden="true" />
                    {member.email}
                  </a>
                  {member.id === "shen-zhanfeng" ? (
                    <a
                      className="air-profile-link"
                      href={teamInstitution.supervisorUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {en ? "UCAS profile" : "中国科学院大学导师主页"}{" "}
                      <LinkOutlined />
                    </a>
                  ) : null}
                </div>
              </div>
              {member.publications.length > 0 ? (
                <Collapse
                  ghost
                  className="air-publications"
                  items={[
                    {
                      key: member.id,
                      label: en
                        ? `Publications (${member.publications.length})`
                        : `论文成果（${member.publications.length}）`,
                      children: (
                        <ol>
                          {member.publications.map((publication) => (
                            <li key={publication.title}>
                              {publication.url ? (
                                <a
                                  href={publication.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {publication.title} <LinkOutlined />
                                </a>
                              ) : (
                                publication.title
                              )}
                            </li>
                          ))}
                        </ol>
                      ),
                    },
                  ]}
                />
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function PlatformOverview({ en, onTeam }: { en: boolean; onTeam: () => void }) {
  const capabilities = en
    ? [
        [
          "Data catalog",
          "Manage imagery, vectors, observations, tables and research outputs through shared metadata and permissions.",
        ],
        [
          "Geospatial visualization",
          "Explore multi-source layers in the geo workspace, inspect attributes and organize thematic scenes.",
        ],
        [
          "Analysis and applications",
          "Connect spatial queries and tabular analysis with remote-sensing and environmental research workflows.",
        ],
        [
          "Research collaboration",
          "Discover, manage and share research resources with traceable access and ownership.",
        ],
      ]
    : [
        [
          "多源数据管理",
          "统一组织遥感影像、空间矢量、观测记录、表格与科研成果，规范元数据和访问权限。",
        ],
        [
          "地理空间可视化",
          "在地理工作台中加载多源图层、查看属性、开展空间查询并组织专题场景。",
        ],
        [
          "分析与应用",
          "连接空间查询、表格分析与专题制图，服务遥感解译及资源环境研究。",
        ],
        [
          "科研协同共享",
          "围绕数据发现、成果管理和权限控制，支持可追溯的科研资源共享。",
        ],
      ];
  return (
    <>
      <section
        className="air-team-hero"
        style={{
          backgroundImage: `linear-gradient(90deg, rgba(9, 30, 53, .95), rgba(9, 30, 53, .55)), url(${digitalEarth})`,
        }}
      >
        <span className="air-eyebrow">SPATIOTEMPORAL INTELLIGENCE</span>
        <Typography.Title level={1}>
          {en ? platformBrand.englishName : platformBrand.chineseName}
        </Typography.Title>
        <p className="air-team-subtitle">
          {en ? teamInstitution.englishName : teamInstitution.name}
        </p>
        <p>
          {en
            ? "Connecting Earth observation, geospatial information and intelligent computation in one research workspace."
            : "连接空天观测、地理信息与智能计算，构建面向科研的数据服务工作台。"}
        </p>
        <Button
          type="primary"
          icon={<ArrowRightOutlined />}
          iconPlacement="end"
          onClick={onTeam}
        >
          {en ? "Meet our team" : "了解我们的团队"}
        </Button>
      </section>
      <section className="air-section">
        <SectionHeading
          eyebrow="PLATFORM CAPABILITIES"
          title={en ? "From data to research services" : "从多源数据到科研服务"}
        />
        <div className="air-research-grid">
          {capabilities.map(([title, description]) => (
            <article key={title}>
              <h3>
                <strong>{title}</strong>
              </h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="air-section air-institution-section">
        <div>
          <Typography.Title level={2}>
            {en ? "Research institution" : "平台依托单位"}
          </Typography.Title>
          <p>{en ? teamInstitution.englishName : teamInstitution.name}</p>
          <p>
            {en
              ? "The platform connects the team's research in intelligent remote sensing, spatiotemporal computing and resource-environment applications."
              : "平台结合团队在遥感智能解译、时空信息计算与资源环境应用方面的研究，支撑数据组织、分析与成果展示。"}
          </p>
        </div>
        <InstitutionIdentity en={en} />
      </section>
    </>
  );
}

function ContactSection({ en }: { en: boolean }) {
  return (
    <section className="air-section">
      <SectionHeading
        eyebrow="CONTACT & COLLABORATION"
        title={en ? "Contact us" : "联系我们"}
      />
      <p className="air-section-description">
        {en ? teamInstitution.englishName : teamInstitution.name}
      </p>
      <div className="air-contact-grid">
        {teamMembers.slice(0, 2).map((member) => (
          <article key={member.id}>
            <MailOutlined />
            <h3>{en ? member.englishName : member.name}</h3>
            <p>{en ? member.focusEn : member.focus}</p>
            <a href={`mailto:${member.email}`}>{member.email}</a>
          </article>
        ))}
      </div>
      <div className="air-contact-address">
        <GlobalOutlined />
        <div>
          <strong>{en ? "Research correspondence" : "科研通信地址"}</strong>
          <p>
            {en ? teamInstitution.addressEn : teamInstitution.address} /{" "}
            {teamInstitution.postalCode}
          </p>
          <a
            href={teamInstitution.supervisorUrl}
            target="_blank"
            rel="noreferrer"
          >
            {en ? "Official faculty contact details" : "导师主页联系信息"}{" "}
            <LinkOutlined />
          </a>
        </div>
      </div>
    </section>
  );
}

function SectionHeading({
  eyebrow,
  title,
}: {
  eyebrow: string;
  title: string;
}) {
  return (
    <div className="air-section-heading">
      <span className="air-eyebrow">{eyebrow}</span>
      <Typography.Title level={2}>{title}</Typography.Title>
    </div>
  );
}
