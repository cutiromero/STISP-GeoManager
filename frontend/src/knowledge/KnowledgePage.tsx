import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Input,
  Layout,
  Pagination,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
} from "antd";
import {
  ArrowRightOutlined,
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useProjectContext } from "../projects/ProjectContext";
import { useAppContext } from "../contexts/AppContext";
import { knowledgeApi } from "../api/knowledge";
import type {
  KnowledgeEntry,
  KnowledgeEntryList,
  KnowledgeSource,
  KnowledgeDomain,
} from "../api/generated/types.gen";
import KnowledgeNetwork from "./KnowledgeNetwork";
import KnowledgeEditor, { ruleLabels, stateLabels } from "./KnowledgeEditor";
import KnowledgeCheck from "./KnowledgeCheck";
import KnowledgeLibrary from "./KnowledgeLibrary";
import { KNOWLEDGE_DOMAINS, domainLabel } from "./domains";
import "./knowledge.css";

function sourceLink(url: string) {
  try {
    const value = new URL(url);
    return ["https:", "http:"].includes(value.protocol) &&
      !value.username &&
      !value.password
      ? value.href
      : undefined;
  } catch {
    return undefined;
  }
}
function Sources({ sources }: { sources: KnowledgeSource[] }) {
  return (
    <div className="knowledge-sources">
      {sources.length ? (
        sources.map((source, index) => (
          <article key={`${source.title}:${source.url}:${source.locator}`}>
            <span className="knowledge-source-number">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              {sourceLink(source.url) ? (
                <a
                  href={sourceLink(source.url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {source.title} <LinkOutlined />
                </a>
              ) : (
                <strong>{source.title}</strong>
              )}
              {source.locator && <p>{source.locator}</p>}
              {source.excerpt && <blockquote>{source.excerpt}</blockquote>}
            </div>
          </article>
        ))
      ) : (
        <p className="knowledge-muted">该草稿尚未补充来源。</p>
      )}
    </div>
  );
}
function FieldList({
  title,
  items,
  empty,
}: {
  title: string;
  items: string[];
  empty: string;
}) {
  return (
    <section className="knowledge-detail-field">
      <h3>{title}</h3>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="knowledge-muted">{empty}</p>
      )}
    </section>
  );
}

export default function KnowledgePage() {
  const project = useProjectContext();
  const { user } = useAppContext();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const currentProject = Number(project?.current ?? "1");
  const [data, setData] = useState<KnowledgeEntryList | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>();
  const [domain, setDomain] = useState<KnowledgeDomain>();
  const [manage, setManage] = useState(false);
  const [section, setSection] = useState("rules");
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [node, setNode] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeEntry | null>(null);
  const [editing, setEditing] = useState<KnowledgeEntry | "new" | null>(null);
  const sequence = useRef(0);
  useEffect(() => {
    const generation = ++sequence.current;
    setLoading(true);
    setError("");
    setNode(null);
    void knowledgeApi
      .entries({
        q: query,
        category,
        domain,
        manage,
        offset: (page - 1) * 100,
        limit: 100,
      })
      .then((value) => {
        if (generation === sequence.current) setData(value);
      })
      .catch((failure: unknown) => {
        if (generation === sequence.current) {
          setData(null);
          setError(
            failure instanceof Error ? failure.message : String(failure),
          );
        }
      })
      .finally(() => {
        if (generation === sequence.current) setLoading(false);
      });
    return () => {
      sequence.current += 1;
    };
  }, [query, category, domain, manage, page, reload, currentProject, user?.id]);
  const items = data?.items ?? [];
  const visible = node
    ? items.filter((entry) => entry.subject === node || entry.object === node)
    : items;
  const sourceCount = new Set(
    items.flatMap((entry) =>
      entry.sources.map((source) => `${source.title}:${source.url}`),
    ),
  ).size;
  function handoff(entry?: KnowledgeEntry) {
    const prompt = entry
      ? `请结合知识条目 #${entry.id}「${entry.title}」（版本 ${entry.revision}）及其来源核查当前项目数据。适用条件：${entry.conditions.join("；") || "请先确认适用条件"}。请先检索并核对最新条目、实际数据及算法，再提出处理计划。`
      : `请结合平台知识库检索${query ? `“${query}”的相关知识，并核查` : "相关规则，核查"}当前项目的数据与可用算法，提出有依据的处理计划。`;
    navigate("/agent/workbench", {
      state: {
        query: prompt,
        knowledgeEntryIds: entry ? [entry.id] : [],
        knowledgeSelection:
          entry?.domain || domain
            ? { mode: "manual", domains: [entry?.domain ?? domain] }
            : { mode: "all", domains: [] },
      },
    });
  }
  function saved(entry: KnowledgeEntry) {
    setEditing(null);
    setDetail(entry);
    setReload((value) => value + 1);
    void message.success("知识条目已保存");
  }
  return (
    <Layout className="knowledge-page">
      <WorkspaceHeader activeTab="knowledgeBase" canBrowseData />
      <main className="knowledge-main">
        <header className="knowledge-intro">
          <div className="knowledge-intro-copy">
            <span className="knowledge-eyebrow">EARTH SCIENCE / KNOWLEDGE</span>
            <h1>知识有依据，推理有边界。</h1>
            <p>
              从矿物关系、光谱证据到数据处理方法，把知识的适用条件与来源放在一起。沿着关系探索，也让智能体在处理数据时有据可查。
            </p>
            <Space wrap>
              <Tag>当前项目与公共基础资料</Tag>
              <Button
                type="link"
                onClick={() => handoff()}
                icon={<ArrowRightOutlined />}
                iconPlacement="end"
              >
                带着知识进入智能体
              </Button>
            </Space>
          </div>
          <div className="knowledge-intro-index">
            <span>知识库</span>
            <strong>
              {data?.total ?? "—"}
              <small>条格式化知识</small>
            </strong>
            <p>
              当前页 {sourceCount} 项来源
              <br />
              每条关系均可追溯到知识条目
            </p>
          </div>
        </header>
        <section className="knowledge-domains" aria-label="知识分区">
          <div className="knowledge-domains-heading">
            <h2>按研究方向探索</h2>
            <Button
              type={domain ? "text" : "primary"}
              aria-pressed={!domain}
              onClick={() => {
                setDomain(undefined);
                setCategory(undefined);
                setPage(1);
              }}
            >
              全部知识
            </Button>
          </div>
          <div className="knowledge-domain-grid">
            {KNOWLEDGE_DOMAINS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`knowledge-domain${domain === item.id ? " is-selected" : ""}`}
                aria-pressed={domain === item.id}
                onClick={() => {
                  setDomain(item.id);
                  setCategory(undefined);
                  setPage(1);
                }}
                style={{ "--domain-color": item.color } as CSSProperties}
              >
                <span className="knowledge-domain-index">
                  {String(KNOWLEDGE_DOMAINS.indexOf(item) + 1).padStart(2, "0")}
                </span>
                <strong>{item.label}</strong>
                <p>{item.description}</p>
                <span className="knowledge-domain-count">
                  {data?.domains?.find((value) => value.id === item.id)
                    ?.count ?? "—"}{" "}
                  条知识 <ArrowRightOutlined />
                </span>
              </button>
            ))}
          </div>
        </section>
        <Tabs
          activeKey={section}
          onChange={setSection}
          items={[
            { key: "rules", label: "格式化知识" },
            { key: "library", label: "资料检索" },
            { key: "wiki", label: "自动 Wiki" },
          ]}
        />
        {section !== "rules" ? (
          <KnowledgeLibrary
            key={`${currentProject}:${user?.id}:${domain ?? "all"}`}
            mode={section === "wiki" ? "wiki" : "library"}
            domain={domain}
          />
        ) : (
          <>
            <div className="knowledge-toolbar">
              <Input.Search
                aria-label="检索知识"
                placeholder="搜索矿物、条件、方法或关键词"
                prefix={<SearchOutlined />}
                allowClear
                maxLength={300}
                onSearch={(value) => {
                  setQuery(value);
                  setPage(1);
                }}
              />
              <Select
                aria-label="知识领域"
                value={category}
                allowClear
                placeholder="全部细分类"
                options={(data?.categories ?? []).map((value) => ({
                  value,
                  label: value,
                }))}
                onChange={(value) => {
                  setCategory(value);
                  setPage(1);
                }}
              />
              {data?.canEdit && (
                <Space wrap>
                  <Switch
                    checked={manage}
                    onChange={(value) => {
                      setManage(value);
                      setPage(1);
                    }}
                    checkedChildren="维护视图"
                    unCheckedChildren="已发布"
                    aria-label="维护视图"
                  />
                  <Button
                    icon={<PlusOutlined />}
                    onClick={() => setEditing("new")}
                  >
                    新建知识
                  </Button>
                </Space>
              )}
            </div>
            {loading ? (
              <div className="knowledge-loading">
                <Spin />
                <span>正在读取知识与来源…</span>
              </div>
            ) : error ? (
              <Alert
                showIcon
                type="error"
                title="知识库暂时无法读取"
                description={error}
                action={
                  <Button onClick={() => setReload((value) => value + 1)}>
                    重新加载
                  </Button>
                }
              />
            ) : (
              <>
                <KnowledgeNetwork
                  entries={items}
                  selected={node}
                  onSelect={setNode}
                  onOpen={setDetail}
                  domain={domain}
                  onDomainSelect={(id) => {
                    if (KNOWLEDGE_DOMAINS.some((item) => item.id === id)) {
                      setDomain(id as KnowledgeDomain);
                      setCategory(undefined);
                      setPage(1);
                    }
                  }}
                />
                <section
                  className="knowledge-records"
                  aria-label="格式化知识条目"
                >
                  <div className="knowledge-records-heading">
                    <div>
                      <span className="knowledge-section-index">
                        02 / KNOWLEDGE RECORDS
                      </span>
                      <h2>读懂一条知识，再使用它</h2>
                      <p>
                        陈述、条件和来源一起构成依据。点击条目查看解释、例外与核查方式。
                      </p>
                    </div>
                    <div>
                      {node && (
                        <Tag closable onClose={() => setNode(null)}>
                          {node}
                        </Tag>
                      )}
                      <span className="knowledge-muted">
                        当前显示 {visible.length} 条
                      </span>
                    </div>
                  </div>
                  {visible.length ? (
                    <div className="knowledge-record-grid">
                      {visible.map((entry) => (
                        <article className="knowledge-record" key={entry.id}>
                          <div className="knowledge-record-meta">
                            <Tag>{domainLabel(entry.domain)}</Tag>
                            <Tag>{entry.category}</Tag>
                            <span>
                              {entry.projectTagId === 1
                                ? "公共基础资料"
                                : "当前项目"}{" "}
                              · v{entry.revision}
                            </span>
                            {entry.status !== "published" && (
                              <Tag>{stateLabels[entry.status]}</Tag>
                            )}
                          </div>
                          <h3>
                            <button onClick={() => setDetail(entry)}>
                              {entry.title}
                            </button>
                          </h3>
                          <div className="knowledge-relation">
                            <span>{entry.subject}</span>
                            <em>{entry.predicate}</em>
                            <span>{entry.object}</span>
                          </div>
                          <p className="knowledge-statement">
                            {entry.statement}
                          </p>
                          <dl>
                            <dt>适用条件</dt>
                            <dd>
                              {entry.conditions.join("；") ||
                                "使用前核对研究对象与观测条件"}
                            </dd>
                            <dt>核查方式</dt>
                            <dd>{ruleLabels[entry.ruleKind]}</dd>
                          </dl>
                          <footer>
                            <span>
                              {entry.sources.length} 项来源
                              {entry.exceptions.length
                                ? ` · ${entry.exceptions.length} 项例外 / 核验条件`
                                : ""}
                            </span>
                            <Button
                              type="text"
                              onClick={() => setDetail(entry)}
                            >
                              查看依据 <ArrowRightOutlined />
                            </Button>
                          </footer>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <Empty
                      description={
                        node
                          ? "当前页没有关联的知识条目"
                          : "没有匹配的知识，试试其他关键词或领域"
                      }
                    />
                  )}
                  {(data?.total ?? 0) > 100 && (
                    <Pagination
                      current={page}
                      pageSize={100}
                      total={data?.total}
                      showSizeChanger={false}
                      onChange={setPage}
                    />
                  )}
                </section>
              </>
            )}
          </>
        )}
      </main>
      <Drawer
        open={!!detail}
        onClose={() => setDetail(null)}
        size={680}
        title="知识依据"
        className="knowledge-detail"
        extra={
          detail && data?.canEdit && detail.projectTagId === currentProject ? (
            <Button icon={<EditOutlined />} onClick={() => setEditing(detail)}>
              维护条目
            </Button>
          ) : null
        }
      >
        {detail && (
          <>
            <Space wrap>
              <Tag>{domainLabel(detail.domain)}</Tag>
              <Tag>{detail.category}</Tag>
              <Tag>{stateLabels[detail.status]}</Tag>
              <span className="knowledge-muted">
                v{detail.revision} ·{" "}
                {detail.projectTagId === 1 ? "公共基础资料" : "当前项目"}
              </span>
            </Space>
            <h2>{detail.title}</h2>
            <div className="knowledge-relation">
              <span>{detail.subject}</span>
              <em>{detail.predicate}</em>
              <span>{detail.object}</span>
            </div>
            <p className="knowledge-detail-statement">{detail.statement}</p>
            {detail.explanation && (
              <p className="knowledge-explanation">{detail.explanation}</p>
            )}
            <FieldList
              title="适用条件"
              items={detail.conditions}
              empty="条目尚未列出条件，使用前请核对研究对象与观测情境。"
            />
            <FieldList
              title="例外与核验条件"
              items={detail.exceptions}
              empty="条目尚未列出具体例外。"
            />
            {detail.aliases.length > 0 && (
              <p>
                {detail.aliases.map((alias) => (
                  <Tag key={alias}>{alias}</Tag>
                ))}
              </p>
            )}
            <section className="knowledge-detail-field">
              <h3>来源与证据</h3>
              <Sources sources={detail.sources} />
            </section>
            <p className="knowledge-muted">
              核查方式：{ruleLabels[detail.ruleKind]} · 更新于{" "}
              {new Date(detail.updatedAt).toLocaleDateString("zh-CN")}
            </p>
            <Button
              type="primary"
              icon={<ArrowRightOutlined />}
              iconPlacement="end"
              onClick={() => handoff(detail)}
            >
              交给智能体
            </Button>
            {detail.ruleKind !== "none" && detail.status === "published" && (
              <KnowledgeCheck
                key={`${detail.id}:${detail.revision}`}
                entry={detail}
              />
            )}
          </>
        )}
      </Drawer>
      {editing && (
        <KnowledgeEditor
          key={editing === "new" ? "new" : `${editing.id}:${editing.revision}`}
          entry={editing === "new" ? null : editing}
          categories={data?.categories ?? []}
          defaultDomain={domain}
          onClose={() => setEditing(null)}
          onSaved={saved}
        />
      )}
    </Layout>
  );
}
