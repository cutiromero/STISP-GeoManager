import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Upload,
} from "antd";
import {
  ArrowRightOutlined,
  FileTextOutlined,
  ReloadOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { knowledgeApi } from "../api/knowledge";
import type {
  KnowledgeDocumentList,
  KnowledgeDocumentSearch,
  KnowledgeWikiList,
  KnowledgeWikiPage,
} from "../api/generated/types.gen";
import SafeMarkdown from "../agent/SafeMarkdown";
import WikiNetwork from "./WikiNetwork";

const statusNames: Record<string, string> = {
  pending: "等待处理",
  processing: "建立索引",
  finalizing: "补充整理",
  completed: "可检索",
  failed: "处理失败",
  cancelled: "已取消",
};
function detailOf(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
function safeUrl(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export default function KnowledgeLibrary({
  mode,
}: {
  mode: "library" | "wiki";
}) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<KnowledgeDocumentList | null>(
    null,
  );
  const [wiki, setWiki] = useState<KnowledgeWikiList | null>(null);
  const [search, setSearch] = useState<KnowledgeDocumentSearch | null>(null);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [page, setPage] = useState<KnowledgeWikiPage | null>(null);
  const [retrying, setRetrying] = useState<number | null>(null);
  const [form] = Form.useForm<{
    title: string;
    sourceUrl: string;
    visibility: string;
  }>();
  const alive = useRef(true);
  const request = useRef(0);
  const refreshing = useRef(false);
  const searchSequence = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      request.current++;
      searchSequence.current++;
    };
  }, []);
  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    const sequence = ++request.current;
    try {
      const [docs, pages] = await Promise.all([
        knowledgeApi.documents(),
        knowledgeApi.wiki(),
      ]);
      if (!alive.current || sequence !== request.current) return;
      setDocuments(docs);
      setWiki(pages);
      setError("");
    } catch (failure) {
      if (alive.current && sequence === request.current) {
        setError(detailOf(failure));
        setDocuments(null);
        setWiki(null);
        setPage(null);
        setSearch(null);
      }
    } finally {
      refreshing.current = false;
      if (alive.current && sequence === request.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const processing =
    documents?.items.some((item) =>
      ["pending", "processing", "finalizing"].includes(item.status),
    ) ||
    wiki?.active ||
    (wiki?.pendingTasks ?? 0) > 0;
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 10000);
    return () => clearInterval(timer);
  }, [documents, wiki, processing, refresh]);

  async function submitSearch(value: string) {
    const trimmed = value.trim();
    const sequence = ++searchSequence.current;
    if (!trimmed) {
      setSearch(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    setQuery(trimmed);
    try {
      const result = await knowledgeApi.searchDocuments(trimmed);
      if (alive.current && sequence === searchSequence.current)
        setSearch(result);
    } catch (failure) {
      if (alive.current && sequence === searchSequence.current)
        void message.error(detailOf(failure));
    } finally {
      if (alive.current && sequence === searchSequence.current)
        setSearching(false);
    }
  }
  async function upload() {
    if (!file) {
      void message.warning("请先选择一份资料");
      return;
    }
    const values = await form.validateFields();
    const body = new FormData();
    body.append("file", file);
    body.append("title", values.title);
    body.append("visibility", values.visibility);
    body.append("sourceUrl", values.sourceUrl || "");
    setUploading(true);
    try {
      const result = await knowledgeApi.uploadDocument(body);
      if (!alive.current) return;
      setUploadOpen(false);
      setFile(null);
      form.resetFields();
      void message.info(
        result.status === "failed"
          ? result.detail
          : "资料已保存，正在建立索引并整理 Wiki",
      );
      await refresh();
    } catch (failure) {
      if (alive.current) void message.error(detailOf(failure));
    } finally {
      if (alive.current) setUploading(false);
    }
  }
  async function retry(id: number) {
    setRetrying(id);
    try {
      await knowledgeApi.retryDocument(id);
      await refresh();
    } catch (failure) {
      if (alive.current) void message.error(detailOf(failure));
    } finally {
      if (alive.current) setRetrying(null);
    }
  }
  const handoff = (text: string) =>
    navigate("/agent/workbench", {
      state: {
        query: `请检索平台知识库的资料原文，结合来源回答：${text}。涉及平台数据时再查找对应数据和算法。`,
      },
    });
  return (
    <section
      className="knowledge-library"
      aria-label={mode === "wiki" ? "自动 Wiki" : "文档知识库"}
    >
      <div className="knowledge-records-heading">
        <div>
          <span className="knowledge-section-index">
            {mode === "wiki" ? "WIKI / LIVING KNOWLEDGE" : "LIBRARY / EVIDENCE"}
          </span>
          <h2>
            {mode === "wiki" ? "从资料长出知识" : "带着问题，找到原文依据"}
          </h2>
          <p>
            {mode === "wiki"
              ? "新资料经过整理形成主题页，沿着关联阅读，并回到文献核对。"
              : "上传资料后建立语义与关键词索引，换一种说法也能寻找相关段落。"}
          </p>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
            刷新
          </Button>
          {documents?.canUpload && (
            <Button
              type="primary"
              icon={<UploadOutlined />}
              disabled={!documents.enabled}
              onClick={() => setUploadOpen(true)}
            >
              添加资料
            </Button>
          )}
        </Space>
      </div>
      {error && <Alert type="error" title={error} showIcon />}
      {documents && !documents.enabled && (
        <Alert
          type="info"
          title={documents.detail || "文档服务尚未配置"}
          showIcon
        />
      )}
      {loading ? (
        <div className="knowledge-loading">
          <Spin />
          <span>正在读取资料…</span>
        </div>
      ) : mode === "library" ? (
        <>
          <Input.Search
            aria-label="检索资料原文"
            placeholder="例如：如何用遥感光谱识别与矿化有关的蚀变？"
            maxLength={1000}
            enterButton="检索原文"
            allowClear
            loading={searching}
            onSearch={(value) => void submitSearch(value)}
            disabled={!documents?.enabled}
          />
          {search && (
            <section
              className="knowledge-search-results"
              aria-label="原文检索结果"
            >
              <div className="knowledge-library-result-heading">
                <h3>找到 {search.items.length} 段依据</h3>
                <Button
                  icon={<ArrowRightOutlined />}
                  onClick={() => handoff(query)}
                >
                  交给智能体分析
                </Button>
              </div>
              {!search.available && (
                <Alert type="warning" title={search.detail} />
              )}
              {search.available && !search.items.length && (
                <Empty description="尚未找到相关原文，可换个描述或补充资料" />
              )}
              {search.items.map((item) => (
                <article
                  className="knowledge-passage"
                  key={`${item.documentId}:${item.chunkId}`}
                >
                  <Space wrap>
                    <Tag>
                      {item.matchType === "vector" ? "语义匹配" : "关键词匹配"}
                    </Tag>
                    <strong>{item.title}</strong>
                  </Space>
                  <blockquote>{item.content}</blockquote>
                  {safeUrl(item.sourceUrl) && (
                    <a
                      href={safeUrl(item.sourceUrl)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看原始来源 ↗
                    </a>
                  )}
                </article>
              ))}
            </section>
          )}
          <div className="knowledge-library-result-heading">
            <h3>资料架 · {documents?.items.length ?? 0} 份</h3>
            <span className="knowledge-muted">
              PDF / Word / Markdown / 文本
            </span>
          </div>
          {documents?.items.length ? (
            <div className="knowledge-document-list">
              {documents.items.map((item) => (
                <article key={item.id}>
                  <FileTextOutlined className="knowledge-document-icon" />
                  <div>
                    <h3>{item.title}</h3>
                    <p>
                      {item.filename} ·{" "}
                      {item.projectTagId === 1 ? "公共资料" : "当前项目"} ·{" "}
                      {item.visibility === "owner_only"
                        ? "仅本人"
                        : "项目成员可见"}
                    </p>
                    <small>{item.detail}</small>
                    {safeUrl(item.sourceUrl) && (
                      <a
                        href={safeUrl(item.sourceUrl)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        原始来源 ↗
                      </a>
                    )}
                  </div>
                  <Space orientation="vertical" align="end">
                    <Tag
                      color={
                        item.status === "completed"
                          ? "green"
                          : item.status === "failed"
                            ? "red"
                            : "blue"
                      }
                    >
                      {statusNames[item.status]}
                    </Tag>
                    {item.canManage &&
                      ["failed", "cancelled"].includes(item.status) && (
                        <Button
                          size="small"
                          loading={retrying === item.id}
                          onClick={() => void retry(item.id)}
                        >
                          重试处理
                        </Button>
                      )}
                  </Space>
                </article>
              ))}
            </div>
          ) : (
            <Empty description="添加一份资料，开始积累可检索的知识" />
          )}
        </>
      ) : (
        <>
          {wiki && !wiki.available && (
            <Alert type="warning" title={wiki.detail} />
          )}
          {processing && (
            <p className="knowledge-wiki-progress">
              <Spin size="small" /> 正在整理资料与主题，待处理任务{" "}
              {wiki?.pendingTasks ?? 0} 项；完成后自动更新。
            </p>
          )}
          <WikiNetwork pages={wiki?.items ?? []} onOpen={setPage} />
          <p className="knowledge-muted">
            Wiki 由资料自动整理；格式化知识中的条件核查规则由维护者单独审定。
          </p>
          <div className="knowledge-record-grid">
            {wiki?.items.map((item) => (
              <article className="knowledge-record" key={item.id}>
                <div className="knowledge-record-meta">
                  <Tag>自动整理</Tag>
                  <span>
                    v{item.version} · {item.sources.length} 项来源
                  </span>
                </div>
                <h3>
                  <button onClick={() => setPage(item)}>{item.title}</button>
                </h3>
                <p>{item.summary || item.content.slice(0, 160)}</p>
                <footer>
                  <span>{item.links.length} 个关联主题</span>
                  <Button type="text" onClick={() => setPage(item)}>
                    阅读主题 <ArrowRightOutlined />
                  </Button>
                </footer>
              </article>
            ))}
          </div>
          {!wiki?.items.length && (
            <Empty
              description={
                processing
                  ? "资料正在整理，主题页生成后会出现在这里"
                  : "上传资料后，自动生成主题与关联"
              }
            />
          )}
        </>
      )}
      <Modal
        title="添加知识资料"
        open={uploadOpen}
        onCancel={() => {
          if (!uploading) setUploadOpen(false);
        }}
        onOk={() => void upload()}
        confirmLoading={uploading}
        okText="保存并整理"
        cancelText="取消"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ visibility: "project" }}
        >
          <Form.Item label="资料文件" required>
            <Upload
              accept=".pdf,.docx,.txt,.md,.csv,.json"
              maxCount={1}
              fileList={
                file ? [{ uid: "source", name: file.name, status: "done" }] : []
              }
              onRemove={() => {
                setFile(null);
              }}
              beforeUpload={(value) => {
                if (value.size > 20 * 1024 * 1024) {
                  void message.error("资料不能超过 20 MB");
                  return Upload.LIST_IGNORE;
                }
                setFile(value);
                if (!form.getFieldValue("title"))
                  form.setFieldValue(
                    "title",
                    value.name.replace(/\.[^.]+$/, ""),
                  );
                return false;
              }}
            >
              <Button icon={<UploadOutlined />} disabled={uploading}>
                选择文件
              </Button>
            </Upload>
            <p className="knowledge-muted">
              支持文字型 PDF、Word 与文本文件，最多 20 MB。
            </p>
          </Form.Item>
          <Form.Item
            name="title"
            label="资料名称"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={180} />
          </Form.Item>
          <Form.Item
            name="sourceUrl"
            label="来源链接"
            rules={[{ type: "url", message: "请填写完整的 HTTP(S) 链接" }]}
          >
            <Input placeholder="文献 DOI 或原始发布页面（选填）" />
          </Form.Item>
          <Form.Item name="visibility" label="可见范围">
            <Select
              options={[
                { value: "project", label: "当前项目成员" },
                { value: "owner_only", label: "仅本人" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        title="Wiki 主题"
        open={!!page}
        onClose={() => setPage(null)}
        size={760}
        className="knowledge-detail"
      >
        {page && (
          <>
            <Tag>自动整理 · v{page.version}</Tag>
            <h2>{page.title}</h2>
            <div className="knowledge-wiki-content">
              <SafeMarkdown text={page.content} />
            </div>
            <h3>引用资料</h3>
            {page.sources.map((source) => (
              <p key={source.documentId}>
                {safeUrl(source.sourceUrl) ? (
                  <a
                    href={safeUrl(source.sourceUrl)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {source.title} ↗
                  </a>
                ) : (
                  source.title
                )}
              </p>
            ))}
            <h3>关联主题</h3>
            <Space wrap>
              {page.links.map((id) => {
                const target = wiki?.items.find((item) => item.id === id);
                return target ? (
                  <Button key={id} onClick={() => setPage(target)}>
                    {target.title}
                  </Button>
                ) : null;
              })}
            </Space>
            <p>
              <Button
                type="primary"
                icon={<ArrowRightOutlined />}
                onClick={() => handoff(page.title)}
              >
                结合原文询问智能体
              </Button>
            </p>
          </>
        )}
      </Drawer>
    </section>
  );
}
