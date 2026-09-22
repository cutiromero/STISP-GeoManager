import { ProjectLabel } from "../projects/ProjectLabel";
import {
  AppstoreOutlined,
  BarChartOutlined,
  CalendarOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileExcelOutlined,
  FileOutlined,
  FileImageOutlined,
  FilePdfOutlined,
  GlobalOutlined,
  PieChartOutlined,
  PictureOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Image,
  Input,
  Layout,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import type { TFunction } from "i18next";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import resultsPoplarReflectionImage from "../assets/portal/results-poplar-reflection.png";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";
import type { MapComposition, ResultArtifact } from "../types";
import { downloadBlob } from "../utils/download";

type ResultSource = "all" | "mapping" | "analysis" | "imported";
type ResultView = "cards" | "list";
type PublishedResult =
  | { key: string; kind: "mapping"; item: MapComposition }
  | { key: string; kind: "artifact"; item: ResultArtifact };

type SourceOverview = {
  key: Exclude<ResultSource, "all">;
  label: string;
  shortLabel: string;
  count: number;
  percentage: number;
  color: string;
};

type TrendOverview = {
  key: string;
  label: string;
  count: number;
};

type ResultsOverviewData = {
  total: number;
  thisMonth: number;
  downloadable: number;
  downloadRate: number;
  formatCount: number;
  latestPublishedAt?: string;
  sources: SourceOverview[];
  trend: TrendOverview[];
};

const sourceOverviewMeta = [
  { key: "mapping", color: "#287b63" },
  { key: "analysis", color: "#4f86c6" },
  { key: "imported", color: "#d99a3d" },
] as const;

export default function ResultsPage() {
  const { message } = App.useApp();
  const { t, i18n } = useTranslation();
  const { user } = useAppContext();
  const [mapItems, setMapItems] = useState<MapComposition[]>([]);
  const [artifactItems, setArtifactItems] = useState<ResultArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [source, setSource] = useState<ResultSource>("all");
  const [format, setFormat] = useState<string>();
  const [view, setView] = useState<ResultView>("cards");
  const [detail, setDetail] = useState<PublishedResult | null>(null);
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const canViewMapping = Boolean(user?.permissions.canViewMapCompositions);
  const canViewArtifactResults = Boolean(
    user?.permissions.canViewResultArtifacts,
  );
  const canViewResults = canViewMapping || canViewArtifactResults;
  const locale = i18n.resolvedLanguage === "en-US" ? "en-US" : "zh-CN";
  const sourceOptions: Array<{ value: ResultSource; label: string }> = [
    { value: "all", label: t("results.sourceAll") },
    { value: "mapping", label: t("results.sourceMapping") },
    { value: "analysis", label: t("results.sourceAnalysisFilter") },
    { value: "imported", label: t("results.sourceImportedFilter") },
  ];
  const formatOptions = [
    { value: "png", label: t("results.imageFormat", { format: "PNG" }) },
    { value: "jpg", label: t("results.imageFormat", { format: "JPG" }) },
    { value: "jpeg", label: t("results.imageFormat", { format: "JPEG" }) },
    { value: "pdf", label: t("results.documentFormat", { format: "PDF" }) },
    { value: "csv", label: t("results.tableFormat", { format: "CSV" }) },
    { value: "xlsx", label: t("results.tableFormat", { format: "XLSX" }) },
  ];

  const loadResults = useCallback(async () => {
    setLoading(true);
    const [mappingResult, artifactResult] = await Promise.allSettled([
      canViewMapping
        ? api
            .mapCompositions({ status: "published" })
            .then((response) =>
              response.items.filter((item) => item.publishedVersion),
            )
        : Promise.resolve([]),
      canViewArtifactResults
        ? api
            .resultArtifacts()
            .then((response) =>
              response.items.filter((item) => item.status === "published"),
            )
        : Promise.resolve([]),
    ]);

    if (mappingResult.status === "fulfilled") {
      setMapItems(mappingResult.value);
    } else {
      setMapItems([]);
      message.error(
        errorMessage(mappingResult.reason, t("results.mappingLoadFailed")),
      );
    }
    if (artifactResult.status === "fulfilled") {
      setArtifactItems(artifactResult.value);
    } else {
      setArtifactItems([]);
      message.error(
        errorMessage(artifactResult.reason, t("results.artifactLoadFailed")),
      );
    }
    setLoading(false);
  }, [canViewArtifactResults, canViewMapping, message, t]);

  useEffect(() => {
    void loadResults();
  }, [loadResults]);

  const publishedResults = useMemo<PublishedResult[]>(
    () => [
      ...mapItems.map((item) => ({
        key: `mapping-${item.id}`,
        kind: "mapping" as const,
        item,
      })),
      ...artifactItems.map((item) => ({
        key: `artifact-${item.id}`,
        kind: "artifact" as const,
        item,
      })),
    ],
    [artifactItems, mapItems],
  );

  const filteredItems = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLocaleLowerCase("zh-CN");
    return publishedResults.filter((result) => {
      const matchesSource = source === "all" || resultSource(result) === source;
      const matchesFormat = format ? resultFormat(result) === format : true;
      const matchesKeyword = normalizedKeyword
        ? resultSearchText(result, t)
            .toLocaleLowerCase("zh-CN")
            .includes(normalizedKeyword)
        : true;
      return matchesSource && matchesFormat && matchesKeyword;
    });
  }, [format, keyword, publishedResults, source, t]);

  const overview = useMemo(
    () => buildResultsOverview(publishedResults, t, locale),
    [locale, publishedResults, t],
  );

  async function downloadResult(result: PublishedResult) {
    if (!resultCanDownload(result)) return;
    setDownloadingKey(result.key);
    try {
      const response =
        result.kind === "mapping"
          ? await api.downloadMapCompositionVersion(
              result.item.id,
              result.item.publishedVersion!.versionNumber,
            )
          : await api.downloadResultArtifact(result.item.id);
      downloadBlob(response.blob, response.filename);
      message.success(t("results.downloadStarted"));
    } catch (error) {
      message.error(errorMessage(error, t("results.downloadFailed")));
    } finally {
      setDownloadingKey((current) => (current === result.key ? null : current));
    }
  }

  return (
    <Layout className="portal-shell results-page-shell">
      <WorkspaceHeader
        activeTab="results"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
        mapCompositions={mapItems}
      />
      <main className="portal-content-page results-page">
        <section
          className="portal-hero results-page-hero"
          style={{
            backgroundImage: `linear-gradient(90deg, rgba(5, 31, 31, 0.94) 0%, rgba(8, 42, 38, 0.76) 42%, rgba(13, 38, 34, 0.4) 70%, rgba(5, 24, 27, 0.64) 100%), url(${resultsPoplarReflectionImage})`,
          }}
        >
          <div>
            <Tag color="green">{t("results.heroTag")}</Tag>
            <Typography.Title level={1}>{t("results.title")}</Typography.Title>
            <Typography.Paragraph>{t("results.summary")}</Typography.Paragraph>
          </div>
          <div className="results-page-stats">
            <Statistic
              title={t("results.publishedResults")}
              value={publishedResults.length}
              suffix={t("results.itemSuffix")}
            />
            <Statistic
              title={t("results.downloadable")}
              value={publishedResults.filter(resultCanDownload).length}
              suffix={t("results.itemSuffix")}
            />
            <Statistic
              title={t("results.resultSources")}
              value={new Set(publishedResults.map(resultSource)).size}
              suffix={t("results.typeSuffix")}
            />
          </div>
        </section>

        {!canViewResults && (
          <Alert
            showIcon
            type="warning"
            title={t("results.permissionTitle")}
            description={t("results.permissionDescription")}
          />
        )}

        <ResultsOverview
          data={overview}
          loading={loading}
          selectedSource={source}
          onSourceChange={setSource}
        />

        <section className="results-page-toolbar">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder={t("results.searchPlaceholder")}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <Select<ResultSource>
            value={source}
            options={sourceOptions}
            onChange={setSource}
          />
          <Select
            allowClear
            placeholder={t("results.formatPlaceholder")}
            value={format}
            options={formatOptions}
            onChange={setFormat}
          />
          <Segmented<ResultView>
            value={view}
            onChange={setView}
            options={[
              {
                value: "cards",
                label: t("results.cardView"),
                icon: <AppstoreOutlined />,
              },
              {
                value: "list",
                label: t("results.listView"),
                icon: <FileImageOutlined />,
              },
            ]}
          />
        </section>

        <Spin spinning={loading}>
          {filteredItems.length ? (
            <section
              className={`result-card-grid${
                view === "list" ? " result-card-grid-list" : ""
              }`}
            >
              {filteredItems.map((item) => (
                <ResultCard
                  item={item}
                  key={item.key}
                  downloading={downloadingKey === item.key}
                  onDetail={() => setDetail(item)}
                  onDownload={() => void downloadResult(item)}
                />
              ))}
            </section>
          ) : (
            <Empty
              className="results-page-empty"
              description={emptyDescription(source, t)}
            />
          )}
        </Spin>
      </main>

      <Drawer
        size="large"
        title={detail ? resultName(detail) : t("results.detailTitle")}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
      >
        {detail && <ResultDetail item={detail} />}
      </Drawer>
    </Layout>
  );
}

function ResultsOverview({
  data,
  loading,
  selectedSource,
  onSourceChange,
}: {
  data: ResultsOverviewData;
  loading: boolean;
  selectedSource: ResultSource;
  onSourceChange: (source: ResultSource) => void;
}) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "en-US" ? "en-US" : "zh-CN";
  const trendMaximum = Math.max(...data.trend.map((item) => item.count), 1);
  const donutBackground = buildDonutBackground(data.sources, data.total);

  return (
    <section
      className="results-overview"
      aria-labelledby="results-overview-title"
    >
      <header className="results-overview-heading">
        <div>
          <Space size={8}>
            <PieChartOutlined />
            <Typography.Title id="results-overview-title" level={2}>
              {t("results.overviewTitle")}
            </Typography.Title>
          </Space>
          <Typography.Paragraph>
            {t("results.overviewSummary")}
          </Typography.Paragraph>
        </div>
        <Space wrap>
          <Tag color="green">{t("results.realtime")}</Tag>
          <Typography.Text type="secondary">
            {data.latestPublishedAt
              ? t("results.recentPublished", {
                  date: formatShortDate(data.latestPublishedAt, locale, t),
                })
              : t("results.noPublishedRecords")}
          </Typography.Text>
        </Space>
      </header>

      <Spin spinning={loading}>
        <div className="results-overview-metrics">
          <OverviewMetric
            icon={<DatabaseOutlined />}
            label={t("results.total")}
            value={data.total}
            suffix={t("results.itemSuffix")}
            note={t("results.totalNote")}
          />
          <OverviewMetric
            icon={<CalendarOutlined />}
            label={t("results.addedThisMonth")}
            value={data.thisMonth}
            suffix={t("results.itemSuffix")}
            note={t("results.addedThisMonthNote")}
          />
          <OverviewMetric
            icon={<DownloadOutlined />}
            label={t("results.openDownload")}
            value={data.downloadable}
            suffix={t("results.itemSuffix")}
            note={t("results.downloadRate", { rate: data.downloadRate })}
          />
          <OverviewMetric
            icon={<FileOutlined />}
            label={t("results.fileFormats")}
            value={data.formatCount}
            suffix={t("results.formatTypeSuffix")}
            note={t("results.fileFormatsNote")}
          />
        </div>

        <div className="results-overview-charts">
          <article className="results-overview-chart results-source-chart">
            <div className="results-chart-title">
              <div>
                <Typography.Title level={3}>
                  {t("results.sourceComposition")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("results.sourceCompositionNote")}
                </Typography.Text>
              </div>
              {selectedSource !== "all" && (
                <Button type="link" onClick={() => onSourceChange("all")}>
                  {t("results.showAll")}
                </Button>
              )}
            </div>
            <div className="results-source-chart-body">
              <div
                className={`results-donut${data.total ? "" : " is-empty"}`}
                style={{ background: donutBackground }}
                role="img"
                aria-label={buildSourceSummary(data.sources, data.total, t)}
              >
                <div className="results-donut-center">
                  <strong>{data.total}</strong>
                  <span>{t("results.total")}</span>
                </div>
              </div>
              <div className="results-source-legend">
                {data.sources.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={
                      selectedSource === item.key ? "is-selected" : undefined
                    }
                    aria-pressed={selectedSource === item.key}
                    onClick={() =>
                      onSourceChange(
                        selectedSource === item.key ? "all" : item.key,
                      )
                    }
                  >
                    <span
                      className="results-source-dot"
                      style={{ backgroundColor: item.color }}
                    />
                    <span>
                      <small>{item.label}</small>
                      <strong>
                        {item.count} {t("results.itemSuffix")}
                      </strong>
                    </span>
                    <b>{item.percentage}%</b>
                  </button>
                ))}
              </div>
            </div>
          </article>

          <article className="results-overview-chart results-trend-chart">
            <div className="results-chart-title">
              <div>
                <Typography.Title level={3}>
                  {t("results.sixMonthTrend")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("results.sixMonthTrendNote")}
                </Typography.Text>
              </div>
              <BarChartOutlined />
            </div>
            <div
              className="results-trend-plot"
              role="img"
              aria-label={buildTrendSummary(data.trend, t)}
            >
              {data.trend.map((item) => (
                <div className="results-trend-column" key={item.key}>
                  <div className="results-trend-value">{item.count}</div>
                  <div className="results-trend-track">
                    <div
                      className={`results-trend-bar${item.count ? "" : " is-zero"}`}
                      style={{
                        height: item.count
                          ? `${Math.max((item.count / trendMaximum) * 100, 12)}%`
                          : "4px",
                      }}
                    />
                  </div>
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
            {!data.total && (
              <div className="results-trend-empty-note">
                {t("results.trendEmpty")}
              </div>
            )}
          </article>
        </div>
      </Spin>
    </section>
  );
}

function OverviewMetric({
  icon,
  label,
  value,
  suffix,
  note,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  suffix: string;
  note: string;
}) {
  const { i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "en-US" ? "en-US" : "zh-CN";
  return (
    <article className="results-overview-metric">
      <span className="results-overview-metric-icon">{icon}</span>
      <div>
        <small>{label}</small>
        <strong>
          {value.toLocaleString(locale)}
          <em>{suffix}</em>
        </strong>
        <span>{note}</span>
      </div>
    </article>
  );
}

function buildResultsOverview(
  results: PublishedResult[],
  t: TFunction,
  locale: "zh-CN" | "en-US",
  now = new Date(),
): ResultsOverviewData {
  const total = results.length;
  const downloadable = results.filter(resultCanDownload).length;
  const sourceCounts = new Map<Exclude<ResultSource, "all">, number>();
  const validPublicationDates = results
    .map((item) => resultPublishedAt(item))
    .filter((value): value is string => Boolean(value))
    .map((value) => ({ value, date: new Date(value) }))
    .filter(({ date }) => !Number.isNaN(date.getTime()));

  for (const result of results) {
    const resultSourceKey = resultSource(result);
    sourceCounts.set(
      resultSourceKey,
      (sourceCounts.get(resultSourceKey) ?? 0) + 1,
    );
  }

  const sources = sourceOverviewMeta.map((item) => {
    const count = sourceCounts.get(item.key) ?? 0;
    const labelKey =
      item.key === "mapping"
        ? "results.sourceMapping"
        : item.key === "analysis"
          ? "results.sourceAnalysis"
          : "results.sourceImported";
    const shortLabelKey =
      item.key === "mapping"
        ? "results.sourceMappingShort"
        : item.key === "analysis"
          ? "results.sourceAnalysisShort"
          : "results.sourceImportedShort";
    return {
      ...item,
      label: t(labelKey),
      shortLabel: t(shortLabelKey),
      count,
      percentage: total ? Math.round((count / total) * 100) : 0,
    };
  });

  const trend = Array.from({ length: 6 }, (_, index) => {
    const monthDate = new Date(
      now.getFullYear(),
      now.getMonth() - (5 - index),
      1,
    );
    const key = monthKey(monthDate);
    return {
      key,
      label:
        locale === "en-US"
          ? monthDate.toLocaleDateString(locale, { month: "short" })
          : t("results.monthLabel", { month: monthDate.getMonth() + 1 }),
      count: validPublicationDates.filter(({ date }) => monthKey(date) === key)
        .length,
    };
  });

  const latestPublication = validPublicationDates.reduce<
    { value: string; date: Date } | undefined
  >(
    (latest, current) =>
      !latest || current.date.getTime() > latest.date.getTime()
        ? current
        : latest,
    undefined,
  );

  return {
    total,
    thisMonth: validPublicationDates.filter(
      ({ date }) => monthKey(date) === monthKey(now),
    ).length,
    downloadable,
    downloadRate: total ? Math.round((downloadable / total) * 100) : 0,
    formatCount: new Set(
      results.map((item) => resultFormat(item).toLowerCase()),
    ).size,
    latestPublishedAt: latestPublication?.value,
    sources,
    trend,
  };
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function buildDonutBackground(sources: SourceOverview[], total: number) {
  if (!total) return "conic-gradient(#dfe9e4 0 100%)";
  let start = 0;
  const segments = sources.map((source) => {
    const end = start + (source.count / total) * 100;
    const segment = `${source.color} ${start}% ${end}%`;
    start = end;
    return segment;
  });
  return `conic-gradient(${segments.join(", ")})`;
}

function buildSourceSummary(
  sources: SourceOverview[],
  total: number,
  t: TFunction,
) {
  if (!total) return t("results.sourceSummaryEmpty");
  return t("results.sourceSummary", {
    summary: sources
      .map(
        (source) =>
          `${source.label} ${source.count} ${t("results.itemSuffix")}`,
      )
      .join(", "),
  });
}

function buildTrendSummary(trend: TrendOverview[], t: TFunction) {
  return t("results.trendSummary", {
    summary: trend
      .map((item) => `${item.label} ${item.count} ${t("results.itemSuffix")}`)
      .join(", "),
  });
}

function formatShortDate(
  value: string,
  locale: "zh-CN" | "en-US",
  t: TFunction,
) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t("results.dateUnknown");
  return date.toLocaleDateString(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function ResultCard({
  item,
  downloading,
  onDetail,
  onDownload,
}: {
  item: PublishedResult;
  downloading: boolean;
  onDetail: () => void;
  onDownload: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="result-card" cover={<ResultCover item={item} />}>
      <ProjectLabel id={item.item.projectTagId} />
      <Space orientation="vertical" size={10} className="full-width">
        <Space wrap>
          <Tag color={sourceTagColor(resultSource(item))}>
            {sourceLabel(item, t)}
          </Tag>
          <Tag>{resultFormat(item).toUpperCase()}</Tag>
          {item.kind === "mapping" && (
            <Tag>V{item.item.publishedVersion!.versionNumber}</Tag>
          )}
        </Space>
        <Typography.Title level={3}>{resultName(item)}</Typography.Title>
        <Typography.Text type="secondary">
          {resultProvider(item, t)}
        </Typography.Text>
        <Typography.Paragraph ellipsis={{ rows: 2 }}>
          {resultDescription(item) || t("results.noDescription")}
        </Typography.Paragraph>
        <Space wrap>
          <Button icon={<EyeOutlined />} onClick={onDetail}>
            {t("results.viewDetails")}
          </Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            disabled={!resultCanDownload(item)}
            loading={downloading}
            onClick={onDownload}
          >
            {t("results.downloadResult")}
          </Button>
        </Space>
      </Space>
    </Card>
  );
}

function ResultCover({ item }: { item: PublishedResult }) {
  const { t } = useTranslation();
  const previewUrl = resultPreviewUrl(item);
  const format = resultFormat(item);
  const imagePreview = resultPreviewIsImage(item);
  return (
    <div
      className={`result-card-cover${imagePreview ? "" : " result-card-cover-file"}`}
    >
      {previewUrl && imagePreview ? (
        <Image
          alt={t("results.previewAlt", { name: resultName(item) })}
          preview={false}
          src={previewUrl}
        />
      ) : (
        <div className="result-file-cover-placeholder">
          {resultFormatIcon(item)}
          <strong>{format.toUpperCase()}</strong>
          <span>{sourceLabel(item, t)}</span>
        </div>
      )}
      <Tag color="green">{t("results.published")}</Tag>
    </div>
  );
}

function ResultDetail({ item }: { item: PublishedResult }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage === "en-US" ? "en-US" : "zh-CN";
  const format = resultFormat(item);
  const previewUrl = resultPreviewUrl(item);
  const imagePreview = resultPreviewIsImage(item);
  return (
    <Space orientation="vertical" size={20} className="full-width">
      {previewUrl && imagePreview && (
        <Image
          alt={t("results.previewAlt", { name: resultName(item) })}
          src={previewUrl}
        />
      )}
      {previewUrl && !imagePreview && format === "pdf" && (
        <iframe
          className="result-pdf-preview"
          loading="lazy"
          referrerPolicy="no-referrer"
          sandbox=""
          src={previewUrl}
          title={t("results.pdfPreview", { name: resultName(item) })}
        />
      )}
      {!imagePreview && format !== "pdf" && (
        <Alert
          showIcon
          type="info"
          title={t("results.previewUnsupported")}
          description={t("results.previewUnsupportedDescription")}
        />
      )}
      <Typography.Paragraph>
        {resultDescription(item) || t("results.noDescription")}
      </Typography.Paragraph>
      <div className="result-detail-grid">
        <span>
          <small>{t("results.source")}</small>
          <strong>{sourceLabel(item, t)}</strong>
        </span>
        <span>
          <small>{t("results.resultFormat")}</small>
          <strong>{format.toUpperCase()}</strong>
        </span>
        <span>
          <small>{t("results.provider")}</small>
          <strong>{resultProvider(item, t)}</strong>
        </span>
        <span>
          <small>{t("results.category")}</small>
          <strong>{resultCategory(item, t)}</strong>
        </span>
        <span>
          <small>{t("results.owner")}</small>
          <strong>{resultOwner(item, t)}</strong>
        </span>
        <span>
          <small>{t("results.publishedAt")}</small>
          <strong>{formatDate(resultPublishedAt(item), locale, t)}</strong>
        </span>
      </div>
    </Space>
  );
}

function resultSource(item: PublishedResult): Exclude<ResultSource, "all"> {
  if (item.kind === "mapping") return "mapping";
  return item.item.sourceType === "analysis" ? "analysis" : "imported";
}

function sourceLabel(item: PublishedResult, t: TFunction) {
  const source = resultSource(item);
  if (source === "mapping") return t("results.sourceMapping");
  if (source === "analysis") return t("results.sourceAnalysis");
  return t("results.sourceImported");
}

function sourceTagColor(source: Exclude<ResultSource, "all">) {
  if (source === "mapping") return "green";
  if (source === "analysis") return "blue";
  return "gold";
}

function resultName(item: PublishedResult) {
  return item.item.name;
}

function resultDescription(item: PublishedResult) {
  return item.item.description;
}

function resultFormat(item: PublishedResult) {
  return item.kind === "mapping"
    ? item.item.publishedVersion!.format
    : item.item.fileFormat;
}

function resultProvider(item: PublishedResult, t: TFunction) {
  return item.kind === "mapping"
    ? t("results.projectSource", { name: item.item.projectName })
    : t("results.providerSource", {
        name: item.item.provider || t("results.notProvided"),
      });
}

function resultCategory(item: PublishedResult, t: TFunction) {
  return item.kind === "mapping"
    ? t("results.mappingCategory")
    : item.item.categoryPath.map((category) => category.name).join(" / ");
}

function resultOwner(item: PublishedResult, t: TFunction) {
  return (
    item.item.owner.displayName ||
    item.item.owner.username ||
    t("results.notRecorded")
  );
}

function resultPublishedAt(item: PublishedResult) {
  return item.kind === "mapping"
    ? (item.item.publishedAt ?? item.item.publishedVersion!.createdAt)
    : (item.item.publishedAt ?? item.item.createdAt);
}

function resultPreviewUrl(item: PublishedResult) {
  return item.kind === "mapping"
    ? item.item.publishedVersion!.previewUrl
    : item.item.previewUrl;
}

function resultPreviewIsImage(item: PublishedResult) {
  return (
    item.kind === "mapping" ||
    ["png", "jpg", "jpeg"].includes(resultFormat(item))
  );
}

function resultCanDownload(item: PublishedResult) {
  return item.item.canDownload;
}

function resultSearchText(item: PublishedResult, t: TFunction) {
  return [
    resultName(item),
    resultDescription(item),
    resultProvider(item, t),
    resultCategory(item, t),
    resultOwner(item, t),
  ].join(" ");
}

function resultFormatIcon(item: PublishedResult) {
  const format = resultFormat(item);
  if (format === "pdf") return <FilePdfOutlined />;
  if (["csv", "xlsx"].includes(format)) return <FileExcelOutlined />;
  if (resultSource(item) === "analysis") return <BarChartOutlined />;
  if (resultSource(item) === "mapping") return <GlobalOutlined />;
  return <PictureOutlined />;
}

function emptyDescription(source: ResultSource, t: TFunction) {
  if (source === "analysis") return t("results.emptyAnalysis");
  if (source === "imported") return t("results.emptyImported");
  if (source === "mapping") return t("results.emptyMapping");
  return t("results.emptyFiltered");
}

function formatDate(
  value: string | null | undefined,
  locale: "zh-CN" | "en-US",
  t: TFunction,
) {
  return value
    ? new Date(value).toLocaleString(locale, { hour12: false })
    : t("results.notRecorded");
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
