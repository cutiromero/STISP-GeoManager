import { useAuditText } from "../i18n/auditUi";
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Image,
  Input,
  Layout,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspaceHeader from "../components/WorkspaceHeader";
import {
  platformApi,
  type ContentArticle,
  type ContentArticleInput,
} from "../api/platform";
import { useAppContext } from "../contexts/AppContext";
import "../styles/editorial.css";

const knowledgeCategories = [
  "遥感基础",
  "GIS 与地图制图",
  "空间智能感知",
  "时序与时空分析",
  "地理知识与基础模型",
  "应用案例",
];
const newsCategories = ["学术会议", "学术交流", "科研进展", "团队活动"];

export default function EditorialPage({
  kind,
}: {
  kind: "knowledge" | "news";
}) {
  const ui = useAuditText();
  const { articleId } = useParams();
  const navigate = useNavigate();
  const { user } = useAppContext();
  const { message } = App.useApp();
  const [items, setItems] = useState<ContentArticle[]>([]);
  const [article, setArticle] = useState<ContentArticle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [manage, setManage] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [editing, setEditing] = useState<ContentArticle | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [removedAssets, setRemovedAssets] = useState<number[]>([]);
  const [preview, setPreview] = useState(false);
  const [form] = Form.useForm();
  const categories =
    kind === "knowledge" ? knowledgeCategories : newsCategories;
  const base = kind === "knowledge" ? "/knowledge" : "/news";
  const sequence = useRef(0);
  const editSession = useRef(0);
  const pendingIds = useRef(new Set<number>());
  const [uploading, setUploading] = useState(0);
  const load = useCallback(async () => {
    const generation = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await platformApi.articles({
        kind,
        q,
        category,
        offset: (page - 1) * 12,
        limit: 12,
        ...(manage ? { manage: "1" } : {}),
      });
      if (generation !== sequence.current) return;
      setItems(result.items);
      setTotal(result.total);
      setCanEdit(result.canEdit);
      if (articleId) {
        const detail = await platformApi.article(Number(articleId));
        if (generation !== sequence.current) return;
        if (detail.kind !== kind) throw new Error(ui("内容类型不匹配"));
        setArticle(detail);
      } else setArticle(null);
    } catch (e) {
      if (generation === sequence.current)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (generation === sequence.current) setLoading(false);
    }
  }, [kind, q, category, page, manage, articleId]);
  useEffect(() => {
    void load();
    return () => {
      sequence.current += 1;
    };
  }, [load]);
  useEffect(
    () => () => {
      editSession.current += 1;
      for (const id of pendingIds.current)
        void platformApi.discardAsset(id).catch(() => {});
    },
    [],
  );
  async function cancelEdit() {
    editSession.current += 1;
    setEditing(null);
    const ids = [...pendingIds.current];
    pendingIds.current.clear();
    const results = await Promise.allSettled(
      ids.map((id) => platformApi.discardAsset(id)),
    );
    if (results.some((r) => r.status === "rejected"))
      message.warning(
        "暂存附件清理未完成，24 小时后自动过期 / Temporary files expire after 24 hours",
      );
  }
  function edit(item: ContentArticle | "new") {
    editSession.current += 1;
    pendingIds.current.clear();
    setEditing(item);
    setRemovedAssets([]);
    form.resetFields();
    form.setFieldsValue(
      item === "new"
        ? {
            title: "",
            summary: "",
            category: categories[0],
            body: "",
            status: "draft",
            source: "",
            linksText: "",
            pinned: false,
          }
        : {
            ...item,
            coverAssetId: item.assets.find((a) => a.url === item.coverUrl)?.id,
            linksText: item.links
              .map((l) => `${l.title} | ${l.url}`)
              .join("\n"),
          },
    );
  }
  async function save() {
    if (uploading) return;
    try {
      const values = await form.validateFields();
      setSaving(true);
      const links = String(values.linksText || "")
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          const index = line.indexOf("|");
          if (index < 1)
            throw new Error(ui("学习链接请按“资料名称 | https://地址”填写"));
          return {
            title: line.slice(0, index).trim(),
            url: line.slice(index + 1).trim(),
          };
        });
      const body: ContentArticleInput = {
        removeAssetIds: removedAssets,
        commitAssetIds: [...pendingIds.current],
        assetCaptions:
          editing && editing !== "new"
            ? editing.assets.map((a) => ({ id: a.id, caption: a.caption }))
            : [],
        coverAssetId: values.coverAssetId ?? null,
        kind,
        title: values.title,
        category: values.category,
        body: values.body,
        summary: values.summary ?? "",
        source: values.source ?? "",
        status: values.status,
        pinned: Boolean(values.pinned),
        eventDate: values.eventDate ?? "",
        links,
        ...(editing && editing !== "new" ? { revision: editing.revision } : {}),
      };
      await platformApi.saveArticle(
        editing && editing !== "new" ? editing.id : null,
        body,
      );
      pendingIds.current.clear();
      editSession.current += 1;
      setEditing(null);
      await load();
      message.success(ui("内容已保存"));
    } catch (e) {
      message.error(e instanceof Error ? e.message : ui("请检查表单内容"));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Layout className="editorial-page">
      <WorkspaceHeader
        activeTab={kind === "knowledge" ? "knowledge" : "news"}
        canBrowseData={true}
      />
      <main className="editorial-main">
        <section
          className={`editorial-hero ${kind === "news" ? "editorial-hero-news" : ""}`}
        >
          <span className="editorial-eyebrow">
            {kind === "knowledge" ? "KNOWLEDGE & DISCOVERY" : "TEAM & RESEARCH"}
          </span>
          <h1>
            {kind === "knowledge"
              ? ui("理解时空，探索智能")
              : ui("团队新闻动态")}
          </h1>
          <p>
            {kind === "knowledge"
              ? ui(
                  "从遥感观测、地图表达，到空间感知与时空推理。用图文认识基础知识，沿学习链接继续探索。",
                )
              : ui(
                  "记录学术交流、研究进展与团队活动，分享研究中的发现与思考。",
                )}
          </p>
        </section>
        <div className="editorial-toolbar">
          <Space wrap>
            <Button
              type={!category ? "primary" : "default"}
              onClick={() => {
                setCategory("");
                setPage(1);
                navigate(base);
              }}
            >
              {ui("全部")}
            </Button>
            {categories.map((c) => (
              <Button
                key={ui(c)}
                type={category === c ? "primary" : "default"}
                onClick={() => {
                  setCategory(c);
                  setPage(1);
                  navigate(base);
                }}
              >
                {ui(c)}
              </Button>
            ))}
          </Space>
          <Input.Search
            placeholder={ui("搜索知识或新闻")}
            allowClear
            onSearch={(value) => {
              setQ(value);
              setPage(1);
              navigate(base);
            }}
            style={{ width: 260 }}
          />
        </div>
        {canEdit && (
          <div className="editorial-manage">
            <Space>
              <Switch
                checked={manage}
                onChange={(value) => {
                  setManage(value);
                  setPage(1);
                }}
                checkedChildren={ui("管理内容")}
                unCheckedChildren={ui("公开视图")}
              />
              <Button onClick={() => edit("new")}>
                {kind === "knowledge"
                  ? ui("新建内容") + " · " + ui("知识")
                  : ui("新建内容") + " · " + ui("新闻")}
              </Button>
            </Space>
          </div>
        )}
        {error ? (
          <Card>
            <Typography.Text type="danger">{error}</Typography.Text>
            <Button onClick={() => void load()}>{ui("重新加载")}</Button>
          </Card>
        ) : loading ? (
          <div className="editorial-loading">
            <Spin size="large" />
          </div>
        ) : article ? (
          <article className="editorial-detail">
            <Button onClick={() => navigate(base)}>{ui("返回列表")}</Button>
            <Space style={{ float: "right" }}>
              {canEdit && (
                <Button onClick={() => edit(article)}>{ui("编辑内容")}</Button>
              )}
            </Space>
            <Tag color="blue">{ui(article.category)}</Tag>
            <h1>{article.title}</h1>
            <p className="editorial-meta">
              {kind === "news" && article.eventDate
                ? `${ui("活动日期")} ${article.eventDate} · `
                : ""}
              {article.publishedAt
                ? `${ui("已发布")} ${article.publishedAt.slice(0, 10)}`
                : ui("草稿")}
            </p>
            <p className="editorial-summary">{article.summary}</p>
            {article.coverUrl && (
              <Image
                className="editorial-cover"
                src={article.coverUrl}
                alt={article.title}
              />
            )}
            <ArticleBody body={article.body} />
            {article.assets.some(
              (a) =>
                a.mimeType.startsWith("image/") && a.url !== article.coverUrl,
            ) && (
              <section className="editorial-gallery">
                <h2>{ui(kind === "news" ? "会议现场" : "图文资料")}</h2>
                <Image.PreviewGroup>
                  {article.assets
                    .filter(
                      (a) =>
                        a.mimeType.startsWith("image/") &&
                        a.url !== article.coverUrl,
                    )
                    .map((a) => (
                      <figure key={a.id}>
                        <Image src={a.url} alt={a.caption || a.name} />
                        <figcaption>{a.caption}</figcaption>
                      </figure>
                    ))}
                </Image.PreviewGroup>
              </section>
            )}
            {article.assets.some((a) => a.mimeType === "application/pdf") && (
              <section>
                <h2>{ui("相关资料")}</h2>
                {article.assets
                  .filter((a) => a.mimeType === "application/pdf")
                  .map((a) => (
                    <p key={a.id}>
                      <a href={a.url} target="_blank" rel="noreferrer">
                        {kind === "news" ? a.caption || a.name : a.name}（PDF）
                      </a>
                    </p>
                  ))}
              </section>
            )}
            {article.links.length > 0 && (
              <section className="editorial-links">
                <h2>{ui("继续学习")}</h2>
                {article.links.map((l) => (
                  <a
                    key={`${l.title}:${l.url}`}
                    href={safeLink(l.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {l.title}
                    <span>{ui("访问资料 ↗")}</span>
                  </a>
                ))}
              </section>
            )}
            {kind === "knowledge" && (
              <footer className="editorial-source">
                {ui("素材来源、课件页码")}：{article.source || ui("团队整理")}
              </footer>
            )}
          </article>
        ) : (
          <>
            <div className="editorial-grid">
              {items.map((item) => (
                <Card
                  key={item.id}
                  className="editorial-card"
                  cover={
                    item.coverUrl ? (
                      <img
                        loading="lazy"
                        src={item.coverUrl}
                        alt={item.title}
                      />
                    ) : (
                      <div className="editorial-card-placeholder">
                        {ui(item.category)}
                      </div>
                    )
                  }
                >
                  <Tag color="blue">{ui(item.category)}</Tag>
                  {manage && (
                    <Tag>
                      {ui(
                        {
                          draft: "草稿",
                          published: "已发布",
                          archived: "已下架",
                        }[item.status],
                      )}
                    </Tag>
                  )}
                  <Typography.Title level={3}>
                    <button onClick={() => navigate(`${base}/${item.id}`)}>
                      {item.title}
                    </button>
                  </Typography.Title>
                  <p>{item.summary}</p>
                  <div className="editorial-card-foot">
                    <span>
                      {item.eventDate || item.publishedAt.slice(0, 10)}
                    </span>
                    <Button
                      type="link"
                      onClick={() => navigate(`${base}/${item.id}`)}
                    >
                      {ui("阅读全文 →")}
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
            {items.length === 0 && (
              <Empty
                description={
                  manage
                    ? ui("当前项目暂无内容，可新建条目")
                    : ui("当前项目暂无已发布内容")
                }
              />
            )}
            <Pagination
              style={{ marginTop: 28, textAlign: "center" }}
              current={page}
              total={total}
              pageSize={12}
              showSizeChanger={false}
              onChange={setPage}
            />
          </>
        )}
        {!user && (
          <p className="editorial-public-note">
            {ui("科普与团队动态为平台公共内容，所有人均可阅读已发布内容。")}
          </p>
        )}
      </main>
      <Modal
        open={Boolean(editing)}
        title={editing === "new" ? ui("新建内容") : ui("编辑内容")}
        width={900}
        onCancel={() => {
          if (!saving) void cancelEdit();
        }}
        cancelButtonProps={{ disabled: saving }}
        closable={!saving}
        onOk={() => void save()}
        confirmLoading={saving || uploading > 0}
        okText={ui("保存")}
        cancelText={ui("取消")}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item hidden name="coverAssetId">
            <Input />
          </Form.Item>
          <Button onClick={() => setPreview(true)}>{ui("预览正文")}</Button>
          <Form.Item
            name="title"
            label={ui("标题")}
            rules={[{ required: true }]}
          >
            <Input maxLength={180} />
          </Form.Item>
          <Space align="start" wrap>
            <Form.Item
              name="category"
              label={ui("分类")}
              rules={[{ required: true }]}
            >
              <Select
                style={{ width: 200 }}
                options={categories.map((c) => ({ value: c, label: ui(c) }))}
              />
            </Form.Item>
            <Form.Item name="status" label={ui("发布状态")}>
              <Select
                style={{ width: 150 }}
                options={[
                  { value: "draft", label: ui("草稿") },
                  { value: "published", label: ui("已发布") },
                  { value: "archived", label: ui("已下架") },
                ]}
              />
            </Form.Item>
            {kind === "news" && (
              <Form.Item name="eventDate" label={ui("活动日期")}>
                <Input type="date" />
              </Form.Item>
            )}
            <Form.Item name="pinned" valuePropName="checked" label={ui("置顶")}>
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name="summary" label={ui("摘要")}>
            <Input.TextArea rows={2} maxLength={800} />
          </Form.Item>
          <Form.Item
            name="body"
            label={ui("正文（段落以空行分隔，## 表示小标题）")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={12} />
          </Form.Item>
          <Form.Item
            name="linksText"
            label={ui("学习链接，每行：资料名称 | https://地址")}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="source"
            label={ui(
              kind === "news" ? "编辑备注（仅内部保存）" : "素材来源、课件页码",
            )}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          {editing && editing !== "new" ? (
            <>
              <Upload
                showUploadList={false}
                beforeUpload={(file) => {
                  const session = editSession.current;
                  setUploading((n) => n + 1);
                  void platformApi
                    .uploadAsset(editing.id, file)
                    .then((asset) => {
                      if (session !== editSession.current) {
                        if (asset.pending)
                          void platformApi
                            .discardAsset(asset.id)
                            .catch(() => {});
                        return;
                      }
                      if (asset.pending) pendingIds.current.add(asset.id);
                      setEditing((current) => {
                        if (
                          !current ||
                          current === "new" ||
                          current.id !== editing.id
                        )
                          return current;
                        return current.assets.some((a) => a.id === asset.id)
                          ? current
                          : { ...current, assets: [...current.assets, asset] };
                      });
                      message.success(ui("附件已暂存，保存内容后生效"));
                    })
                    .catch((e) => message.error(e.message))
                    .finally(() => setUploading((n) => Math.max(0, n - 1)));
                  return false;
                }}
                accept="image/png,image/jpeg,image/webp,application/pdf"
              >
                <Button>{ui("上传图片或 PDF")}</Button>
              </Upload>
              <Space wrap style={{ marginTop: 12 }}>
                {editing.assets.map((a) => (
                  <Card size="small" key={a.id}>
                    <Space orientation="vertical">
                      <span>{a.name}</span>
                      <Input
                        aria-label={`${ui("图片或附件说明")}: ${a.name}`}
                        placeholder={ui("图片或附件说明")}
                        value={a.caption}
                        onChange={(e) =>
                          setEditing({
                            ...editing,
                            assets: editing.assets.map((x) =>
                              x.id === a.id
                                ? { ...x, caption: e.target.value }
                                : x,
                            ),
                          })
                        }
                      />
                      <Space>
                        {a.mimeType.startsWith("image/") && (
                          <Button
                            size="small"
                            onClick={() => {
                              form.setFieldValue("coverAssetId", a.id);
                              message.success(ui("已选择封面，保存内容后生效"));
                            }}
                          >
                            {ui("设为封面")}
                          </Button>
                        )}
                        <Button
                          danger
                          size="small"
                          onClick={() => {
                            if (a.pending) {
                              pendingIds.current.delete(a.id);
                              void platformApi
                                .discardAsset(a.id)
                                .catch((e) => message.error(e.message));
                            } else setRemovedAssets((ids) => [...ids, a.id]);
                            setEditing({
                              ...editing,
                              assets: editing.assets.filter(
                                (x) => x.id !== a.id,
                              ),
                            });
                            if (form.getFieldValue("coverAssetId") === a.id)
                              form.setFieldValue("coverAssetId", null);
                          }}
                        >
                          {ui("移除附件")}
                        </Button>
                      </Space>
                    </Space>
                  </Card>
                ))}
              </Space>
            </>
          ) : (
            <p>{ui("先保存草稿，再添加图片或 PDF 附件。")}</p>
          )}
        </Form>
      </Modal>
      <Modal
        open={preview}
        title={form.getFieldValue("title") || ui("内容预览")}
        footer={null}
        width={850}
        onCancel={() => setPreview(false)}
      >
        <ArticleBody body={form.getFieldValue("body") ?? ""} />
      </Modal>
    </Layout>
  );
}

function safeLink(url: string) {
  return /^https?:\/\//i.test(url) ? url : undefined;
}
function ArticleBody({ body }: { body: string }) {
  return (
    <div className="editorial-body">
      {bodyBlocks(body).map(({ text, key }) =>
        text.startsWith("## ") ? (
          <h2 key={key}>{text.slice(3)}</h2>
        ) : (
          <p key={key}>{text}</p>
        ),
      )}
    </div>
  );
}

function bodyBlocks(body: string) {
  const counts = new Map<string, number>();
  return body.split(/\n\s*\n/).map((text) => {
    const count = (counts.get(text) ?? 0) + 1;
    counts.set(text, count);
    return { text, key: `${text}:${count}` };
  });
}
