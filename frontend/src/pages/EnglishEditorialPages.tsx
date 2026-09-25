import { canReadHelp, downloadHelp } from "../about/helpAccess";
import helpContent from "../about/helpContent.json";
import {
  BranchesOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  GlobalOutlined,
  LinkOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Button, Layout, Typography } from "antd";
import type { ReactNode } from "react";
import poplarWaterGoldenImage from "../assets/about/poplar-water-golden.jpeg";
import xjafsMonitoringTowerImage from "../assets/about/xjafs-monitoring-tower.png";
import knowledgeAncientPoplarImage from "../assets/portal/knowledge-ancient-poplar.png";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";

const genomePapers = [
  {
    title:
      "Chromosome-scale assemblies of the male and female Populus euphratica genomes reveal the molecular basis of sex determination and sexual dimorphism",
    meta: "Communications Biology · 2022",
    url: "https://doi.org/10.1038/s42003-022-04145-7",
  },
  {
    title:
      "The chromosome-scale genome and population genomics reveal the adaptative evolution of Populus pruinosa to desertification environment",
    meta: "Horticulture Research · 2024",
    url: "https://doi.org/10.1093/hr/uhae034",
  },
];

const remoteSensingPapers = [
  {
    title:
      "Individual Populus euphratica tree detection in sparse desert forests based on constrained 2D bin packing",
    meta: "IEEE TGRS · 2024",
    url: "https://doi.org/10.1109/TGRS.2024.3391352",
  },
  {
    title:
      "Ecological restoration trajectory of the Taitema Lake wetland in arid northwest China",
    meta: "Ecological Indicators · 2024",
    url: "https://doi.org/10.1016/j.ecolind.2024.111956",
  },
  {
    title:
      "Vegetation growth improvement inadequately represents the ecological restoration of Populus euphratica forests",
    meta: "Ecological Indicators · 2025",
    url: "https://doi.org/10.1016/j.ecolind.2025.113086",
  },
];

export function EnglishHelpCenter() {
  const { user } = useAppContext();
  const guides = helpContent.english.filter(guide => canReadHelp(guide.id, user));
  return (
    <section className="about-v2-section">
      <Typography.Title level={2}>Platform help</Typography.Title>
      <Typography.Paragraph>
        Updated 18 September 2026. Project access, data workflows and
        cartography.
      </Typography.Paragraph>
      <Button
        onClick={() => downloadHelp(guides.map(g => `# ${g.title}\n\n${g.items.join("\n\n")}`).join("\n\n"), true)}
      >
        Download my help guide
      </Button>
      {guides.map((guide) => (
        <article key={guide.id}>
          <Typography.Title level={3}>{guide.title}</Typography.Title>
          {guide.items.map((item) => (
            <Typography.Paragraph key={item}>{item}</Typography.Paragraph>
          ))}
        </article>
      ))}
    </section>
  );
}

const speciesArchive = [
  {
    id: "profile",
    index: "01",
    eyebrow: "MEET THE SPECIES",
    title: "Species profile",
    summary:
      "Populus euphratica Oliver is a dominant tree of desert riparian forests and one of the few species able to form natural woodland under wind, heat, drought, and salinity.",
    facts: [
      "Mature trees can exceed ten metres; tiny wind-dispersed seeds carry silky hairs.",
      "Linear, ovate, and kidney-shaped leaves can occur on one individual.",
      "China holds about 61% of the world's P. euphratica forest, most in Xinjiang.",
      "More than 90% of Xinjiang's natural stands occur in the Tarim River Basin.",
    ],
  },
  {
    id: "ecology",
    index: "02",
    eyebrow: "DESERT KEYSTONE",
    title: "Ecological value",
    summary:
      "Poplar forests support carbon storage, wind and sand control, river-bank stability, habitat continuity, and biodiversity.",
    facts: [
      "Deep roots stabilize mobile sand and reduce near-surface wind speed.",
      "Riparian stands connect river processes with oasis ecological security.",
      "Satellite, UAV, field-station, and AI observations form an integrated monitoring system.",
    ],
  },
  {
    id: "culture",
    index: "03",
    eyebrow: "RESILIENCE AND MEMORY",
    title: "Cultural meaning",
    summary:
      "Persistence in harsh landscapes has made the poplar a symbol of endurance, guardianship, and commitment.",
    facts: [
      "Extreme aridity slows wood decay, so dead trunks can remain upright for long periods.",
      "Drought, wind, and salinity tolerance underpin its image as a desert guardian.",
      "Golden autumn forests and water-reflected poplars are distinctive Tarim landscapes.",
    ],
  },
  {
    id: "survival",
    index: "04",
    eyebrow: "WATER AND HETEROPHYLLY",
    title: "Survival strategies",
    summary:
      "Heterophylly, deep roots, atmospheric-water use, and salt regulation form a multi-layered adaptation strategy.",
    facts: [
      "Narrow lower leaves reduce water loss; broader upper leaves support light capture.",
      "Canopies can intercept condensed water and redistribute it through the root zone.",
      "Main roots may reach deep groundwater while lateral roots spread long distances.",
      "Bark and leaves help regulate excess salts and internal ion balance.",
    ],
  },
  {
    id: "research",
    index: "05",
    eyebrow: "NATURAL STRESS-RESISTANCE LIBRARY",
    title: "Research value",
    summary:
      "Poplar systems support research on salt and drought tolerance, climate response, river change, and desert ecohydrology.",
    facts: [
      "Genome research identifies stress-tolerance resources for breeding and restoration.",
      "Tree rings, populations, and landscapes record climate and river dynamics.",
      "Alternating flooding and drought provide a natural carbon-water laboratory.",
    ],
  },
] as const;

const protectionCases = [
  {
    index: "CASE 01",
    title: "Tarim River poplar-forest rescue program",
    summary:
      "Long-term ecological water delivery, regulated diversion, rotational inundation, and grid-based stewardship raise groundwater and restore natural regeneration.",
    measures: [
      "Continuous lower-reach ecological water delivery since 2000.",
      "Small-flow, long-duration allocation improves flooding and groundwater recharge.",
      "Ecological gates direct limited water to priority natural stands.",
    ],
    outcomes: [
      "Groundwater rise: 6–8 m",
      "Vegetation cover: 8.35% → 11.62%",
      "Plant species: 17 → 46",
      "Young and middle-aged trees: >80%",
    ],
  },
  {
    index: "CASE 02",
    title: "Flood-based irrigation of one million mu in Luntai",
    summary:
      "Seasonal floodwater is routed through channels, retaining structures, and nine ecological gates to natural forests along the Tarim River.",
    measures: [
      "Coverage includes 168 km of the middle and lower main channel.",
      "Routine replenishment has continued since 2019.",
      "More than 2,000 mu of planted forest is included.",
    ],
    outcomes: [
      "Million-mu routine replenishment",
      "Natural stands prioritized",
      "Planted stands maintained",
    ],
  },
  {
    index: "CASE 03",
    title: "Integrated restoration in Halakun, Kalpin",
    summary:
      "Atmospheric enhancement, surface-water regulation, and groundwater recharge are evaluated with monitoring wells and permanent plots.",
    measures: [
      "Ecological replenishment from 2022 to 2025.",
      "Targeted rain and snow enhancement operations.",
      "Groundwater wells and vegetation plots track recovery.",
    ],
    outcomes: [
      "Groundwater rise: 1.32 m",
      "Canopy closure: 4.71% → 7.67%",
      "Total vegetation cover: 18.39%",
    ],
  },
] as const;

export function EnglishKnowledgePage() {
  const { user } = useAppContext();
  return (
    <Layout className="workspace">
      <WorkspaceHeader
        activeTab="knowledge"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <div className="workspace-body workspace-body-about">
        <aside className="about-page-nav-panel knowledge-page-nav-panel">
          <div className="about-page-panel-head">
            <Typography.Text strong>Poplar Knowledge</Typography.Text>
          </div>
          <nav
            className="knowledge-v2-primary-nav"
            aria-label="Poplar knowledge navigation"
          >
            {[
              [
                "01",
                "Species archive",
                "Profile, value, culture, survival, and research",
                "#species-archive",
              ],
              [
                "02",
                "Protection and management",
                "Water delivery, flood irrigation, and restoration",
                "#protection-management",
              ],
              [
                "03",
                "Research knowledge network",
                "Papers, mechanisms, and applications",
                "#knowledge-graph",
              ],
            ].map(([index, title, summary, href]) => (
              <a href={href} key={index}>
                <span>{index}</span>
                <strong>{title}</strong>
                <small>{summary}</small>
              </a>
            ))}
          </nav>
          <div className="knowledge-v2-species-links">
            <strong>Species archive</strong>
            {speciesArchive.map((item) => (
              <a href={`#species-${item.id}`} key={item.id}>
                {item.index} {item.title}
              </a>
            ))}
          </div>
          <p className="knowledge-page-nav-note">
            Begin with the species, continue through conservation practice, then
            explore genomic, leaf-development, and stress-adaptation evidence.
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
              <span>POPULUS EUPHRATICA · DESERT SURVIVOR</span>
              <Typography.Title level={1}>
                A keystone tree of desert river corridors
              </Typography.Title>
              <Typography.Paragraph>
                One poplar connects species evolution, riparian corridors,
                desert ecohydrology, regional culture, and modern conservation
                technology. Explore how it survives and why it matters through
                visual archives, management cases, and a research network.
              </Typography.Paragraph>
              <div>
                {[
                  "A natural tree-forming species of extreme arid lands",
                  "About 61% of global natural stands occur in China",
                  "The Tarim River Basin is a core conservation region",
                ].map((item) => (
                  <span key={item}>
                    <CheckCircleOutlined />
                    {item}
                  </span>
                ))}
              </div>
            </div>
            <aside>
              <small>Species archive</small>
              <strong>PE-001</strong>
              <span>Salicaceae · Populus</span>
              <em>Populus euphratica Oliver</em>
            </aside>
          </section>
          <section className="knowledge-v2-section" id="species-archive">
            <EnglishKnowledgeTitle
              icon={<ReadOutlined />}
              index="01"
              eyebrow="SPECIES ARCHIVE"
              title="Species archive"
              description="Five connected sections move from rapid identification to scientific understanding."
            />
            <div className="knowledge-v2-archive-grid">
              {speciesArchive.map((item) => (
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
                <img
                  alt="Golden poplar forest beside a river"
                  src={poplarWaterGoldenImage}
                />
              </figure>
              <div>
                <span>LANDSCAPE AND ECOLOGY</span>
                <Typography.Title level={3}>
                  Golden autumn and water-reflected poplars
                </Typography.Title>
                <Typography.Paragraph>
                  Autumn colour and river reflections create iconic landscapes.
                  Their beauty also reveals how tightly desert riparian forests
                  are coupled to river processes, groundwater, and the timing of
                  water delivery.
                </Typography.Paragraph>
                <div>
                  <span>Typical viewing period</span>
                  <strong>Mid-October to early November</strong>
                </div>
              </div>
            </div>
          </section>
          <section
            className="knowledge-v2-section knowledge-v2-protection"
            id="protection-management"
          >
            <EnglishKnowledgeTitle
              icon={<SafetyCertificateOutlined />}
              index="02"
              eyebrow="PROTECTION MANAGEMENT"
              title="Protection and management"
              description="From ecological water delivery to field monitoring, conservation actions become measurable evidence."
            />
            <div className="knowledge-v2-protection-lead">
              <div>
                <span>Integrated conservation pathway</span>
                <Typography.Title level={3}>
                  Water allocation + flood irrigation + long-term monitoring +
                  stewardship
                </Typography.Title>
                <Typography.Paragraph>
                  Restoration is not a single watering event. It is a long-term
                  program based on river processes, ecological gates, diversion
                  channels, groundwater monitoring, permanent plots, and field
                  stewardship.
                </Typography.Paragraph>
              </div>
              <figure>
                <img
                  alt="Poplar-forest observation tower"
                  src={xjafsMonitoringTowerImage}
                />
                <figcaption>
                  Long-term observations convert management outcomes into
                  continuous scientific evidence.
                </figcaption>
              </figure>
            </div>
            <div className="knowledge-v2-case-list">
              {protectionCases.map((item) => (
                <article key={item.index}>
                  <header>
                    <span>{item.index}</span>
                    <strong>{item.title}</strong>
                  </header>
                  <p>{item.summary}</p>
                  <div className="knowledge-v2-case-body">
                    <section>
                      <small>Measures</small>
                      {item.measures.map((measure) => (
                        <p key={measure}>
                          <BranchesOutlined />
                          {measure}
                        </p>
                      ))}
                    </section>
                    <section>
                      <small>Key outcomes</small>
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
            <EnglishKnowledgeTitle
              icon={<ExperimentOutlined />}
              index="03"
              eyebrow="RESEARCH KNOWLEDGE NETWORK"
              title="From scientific papers to conservation decisions"
              description="Research themes, representative papers, mechanisms, and applications are kept in one evidence-aware view."
            />
            <div className="about-page-card-grid about-page-knowledge-theme-grid">
              {[
                [
                  "01",
                  "Genome and sex determination",
                  "Male and female genomes, the sex-linked region, ARR17 regulation, and molecular markers form a mechanism-to-application chain.",
                ],
                [
                  "02",
                  "Heterophylly",
                  "Leaf development, methylation, and transcriptomic response explain leaf-form plasticity.",
                ],
                [
                  "03",
                  "Stress adaptation",
                  "Salt and drought response, WOX-family evidence, and comparative P. pruinosa genomics support resistant germplasm.",
                ],
                [
                  "04",
                  "Conservation application",
                  "Remote sensing, germplasm conservation, water delivery, and restoration translate evidence into management.",
                ],
              ].map(([index, title, body]) => (
                <article
                  className="about-page-feature-card about-page-knowledge-theme-card"
                  key={index}
                >
                  <span>{index}</span>
                  <strong>{title}</strong>
                  <p>{body}</p>
                </article>
              ))}
            </div>
            <section className="about-page-knowledge-paper-wall">
              <div className="about-page-block-title">
                <ReadOutlined />
                <Typography.Title level={3}>
                  Representative research evidence
                </Typography.Title>
              </div>
              <div className="about-page-paper-wall-layout">
                <div className="about-page-paper-feature-column">
                  {genomePapers.map((paper) => (
                    <article
                      className="about-page-paper-cover-card about-page-paper-cover-feature"
                      key={paper.title}
                    >
                      <div className="about-page-paper-cover-head">
                        <span>PE</span>
                        <small>{paper.meta}</small>
                      </div>
                      <strong>{paper.title}</strong>
                      <em>
                        Genome resources connect sex determination, adaptive
                        evolution, germplasm conservation, and restoration.
                      </em>
                      {paper.url ? (
                        <a href={paper.url} rel="noreferrer" target="_blank">
                          Open publication <LinkOutlined />
                        </a>
                      ) : null}
                    </article>
                  ))}
                </div>
                <div className="about-page-paper-support-grid">
                  {remoteSensingPapers.slice(0, 2).map((paper) => (
                    <article
                      className="about-page-paper-cover-card"
                      key={paper.title}
                    >
                      <div className="about-page-paper-cover-head">
                        <span>RS</span>
                        <small>{paper.meta}</small>
                      </div>
                      <strong>{paper.title}</strong>
                      <em>
                        Remote sensing connects individual trees and restoration
                        trajectories to landscape monitoring.
                      </em>
                      {paper.url ? (
                        <a href={paper.url} rel="noreferrer" target="_blank">
                          Open publication <LinkOutlined />
                        </a>
                      ) : null}
                    </article>
                  ))}
                </div>
              </div>
            </section>
            <section className="about-page-knowledge-mechanism-section">
              <div className="about-page-block-title">
                <SafetyCertificateOutlined />
                <Typography.Title level={3}>
                  Core mechanisms and evidence chains
                </Typography.Title>
              </div>
              <div className="about-page-knowledge-mechanism-grid">
                {[
                  [
                    "Sex determination",
                    "Male and female genomes → sex-linked region → ARR17 regulation → early molecular identification",
                    ["Genome", "SLR", "ARR17", "Markers"],
                  ],
                  [
                    "Heterophylly",
                    "Leaf development → methylation regulation → transcriptomic response → leaf-form plasticity",
                    ["Leaf form", "Methylation", "Transcriptome", "Water use"],
                  ],
                  [
                    "Dryland adaptation",
                    "Comparative genome → population differentiation → stress expression → resistant germplasm",
                    [
                      "P. pruinosa",
                      "WOX genes",
                      "Salt and drought",
                      "Restoration",
                    ],
                  ],
                ].map(([title, body, tags]) => (
                  <article
                    className="about-page-mechanism-card"
                    key={title as string}
                  >
                    <div>
                      <span className="about-page-feature-icon">
                        <SafetyCertificateOutlined />
                      </span>
                      <small>Evidence chain</small>
                    </div>
                    <strong>{title as string}</strong>
                    <p>{body as string}</p>
                    <div className="about-page-chip-list">
                      {(tags as string[]).map((tag) => (
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
                  <Typography.Title level={3}>
                    Desert guardian and green ecological barrier
                  </Typography.Title>
                </div>
                <Typography.Paragraph>
                  Through drought tolerance, salt regulation, deep rooting, and
                  river-bank stabilization, P. euphratica protects oases while
                  providing material for germplasm conservation,
                  climate-response research, and restoration.
                </Typography.Paragraph>
              </div>
              <div className="about-page-knowledge-value-grid">
                {[
                  [
                    "61%",
                    "Global share in China",
                    "A major responsibility for conservation and monitoring",
                  ],
                  [
                    "90%+",
                    "Xinjiang stands in the Tarim Basin",
                    "A core link between river management and regeneration",
                  ],
                  [
                    "Multi-scale",
                    "Evidence network",
                    "Genomes, samples, plots, populations, landscapes, and remote sensing",
                  ],
                ].map(([value, label, detail]) => (
                  <article key={label}>
                    <strong>{value}</strong>
                    <span>{label}</span>
                    <p>{detail}</p>
                  </article>
                ))}
              </div>
            </section>
          </section>
        </main>
      </div>
    </Layout>
  );
}

function EnglishKnowledgeTitle({
  icon,
  index,
  eyebrow,
  title,
  description,
}: {
  icon: ReactNode;
  index: string;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="knowledge-v2-title">
      <span>{icon}</span>
      <div>
        <small>
          {index} · {eyebrow}
        </small>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Paragraph>{description}</Typography.Paragraph>
      </div>
    </div>
  );
}
