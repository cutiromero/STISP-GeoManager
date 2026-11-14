import { ReloadOutlined } from "@ant-design/icons";
import { Button, Empty, Spin } from "antd";
import { type CSSProperties, type ReactNode, Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type {
  MonitoringMetric,
  MonitoringProduct,
  MonitoringProductList,
  ProjectMonitorConfig,
} from "../api/generated/types.gen";
import { currentLocale } from "../i18n";
import MonitorDashboardFrame from "./MonitorDashboardFrame";
import { MonitorAssessmentCard, MonitorPanel } from "./MonitorPanels";
import MonitorProductSelector from "./MonitorProductSelector";
import { useMonitorProductSelection } from "./useMonitorProductSelection";
import { MonitorDataStatus } from "./MonitorLayerStatus";
import { useMonitoringProducts } from "./useMonitoringProducts";
import "./remote-sensing-monitor.css";

const ProductMap = lazy(() => import("./ProductMap"));

export default function RemoteSensingDashboard({
  scene,
  config,
  navigation,
}: {
  scene: MonitoringProductList["scene"];
  config: ProjectMonitorConfig;
  navigation: ReactNode;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { page, loading, failure, setFailure, setRevision, loadMore } =
    useMonitoringProducts(scene);
  const selection = useMonitorProductSelection({
    items: page?.items ?? [],
    references: page?.referenceResources ?? [],
  });
  const selected = selection.selected;
  const metrics = selected?.metrics ?? emptyMetrics(scene);
  const primary =
    metrics.find(
      (metric) =>
        metric.key === (scene === "spartina" ? "area_ha" : "mean_probability"),
    ) ?? metrics[0]!;
  const preferred = [
    ...metrics.filter((metric) => metric.value !== null),
    ...metrics.filter((metric) => metric.value === null),
  ].slice(0, 4);
  return (
    <MonitorDashboardFrame
      config={config}
      scene={scene}
      navigation={navigation}
      updatedAt={selected?.registeredAt}
      actions={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          aria-label={t("remoteMonitor.refresh")}
          onClick={() => setRevision((value) => value + 1)}
          loading={loading}
        >
          {t("remoteMonitor.refresh")}
        </Button>
      }
      sourceLabel={
        selected
          ? t(`remoteMonitor.kind.${selected.kind}`)
          : t("remoteMonitor.sourceMode")
      }
      status={() => t(`remoteMonitor.${scene}MapNote`)}
    >
      {({ animated }) => (
        <>
          <MonitorDataStatus
            title={t("remoteMonitor.products")}
            loading={loading}
            error={failure}
          />
          <main className="monitor-layout">
            <section
              className="monitor-globe-panel"
              aria-label={t("remoteMonitor.map")}
            >
              <Suspense
                fallback={
                  <MonitorDataStatus
                    title={t("remoteMonitor.loadingMap")}
                    loading
                  />
                }
              >
                <ProductMap
                  product={selected}
                  resource={selection.reference}
                  config={config}
                  animated={animated}
                />
              </Suspense>
            </section>
            <div className="monitor-information">
              <div className="monitor-summary">
                <div>
                  <span>{t("remoteMonitor.productCount")}</span>
                  <strong>
                    {page?.items.length ?? "—"}
                    <small>{t("remoteMonitor.productUnit")}</small>
                  </strong>
                </div>
                <div>
                  <span>{t("remoteMonitor.productType")}</span>
                  <strong className="monitor-summary-text">
                    {selected ? t(`remoteMonitor.kind.${selected.kind}`) : "—"}
                  </strong>
                </div>
                <div>
                  <span>{t("remoteMonitor.productQuality")}</span>
                  <strong className="monitor-summary-text monitor-warm">
                    {selected
                      ? t(`remoteMonitor.quality.${selected.quality}`)
                      : "—"}
                  </strong>
                </div>
              </div>
              <MonitorPanel
                title={t(
                  scene === "spartina"
                    ? "remoteMonitor.distributionOverview"
                    : "remoteMonitor.riskOverview",
                )}
              >
                <div className="monitor-risk-content">
                  <div
                    className="monitor-gauge monitor-product-gauge"
                    style={metricNumberStyle(primary)}
                    role="img"
                    aria-label={`${primary.label} ${metricValue(primary)} ${metricUnit(primary)}`}
                  >
                    <svg viewBox="0 0 120 120" aria-hidden="true">
                      <circle
                        cx="60"
                        cy="60"
                        r="47"
                        fill="none"
                        stroke="#254a52"
                        strokeWidth="7"
                      />
                      <circle
                        cx="60"
                        cy="60"
                        r="41"
                        fill="none"
                        stroke="#65dfc8"
                        strokeOpacity="0.3"
                        strokeWidth="1"
                      />
                    </svg>
                    <div className="monitor-gauge-value">
                      <span className="monitor-number">
                        {metricValue(primary)}
                      </span>
                      <small>{metricUnit(primary)}</small>
                    </div>
                  </div>
                  <ul className="monitor-risk-legend monitor-product-overview">
                    <li>
                      <i style={{ background: "#65dfc8" }} />
                      <span>{primary.label}</span>
                    </li>
                    <li>
                      <span>{t("remoteMonitor.scope")}</span>
                      <strong>{t(`remoteMonitor.${scene}Scope`)}</strong>
                    </li>
                    <li>
                      <span>{t("remoteMonitor.observed")}</span>
                      <strong>
                        {selected
                          ? periodLabel(
                              selected,
                              t("remoteMonitor.unknownTime"),
                            )
                          : "—"}
                      </strong>
                    </li>
                  </ul>
                </div>
              </MonitorPanel>
              <MonitorPanel title={t("remoteMonitor.keyMetrics")}>
                <div className="monitor-metrics">
                  {preferred.map((metric) => (
                    <div
                      className="monitor-metric"
                      key={metric.key}
                      style={metricNumberStyle(metric)}
                    >
                      <span>{metric.label}</span>
                      <strong>
                        <span className="monitor-number">
                          {metricValue(metric)}
                        </span>
                        <small>{metricUnit(metric)}</small>
                      </strong>
                    </div>
                  ))}
                </div>
              </MonitorPanel>
              <MonitorPanel
                className="monitor-trend-panel monitor-products-panel"
                title={t("remoteMonitor.products")}
                extra={
                  <span className="monitor-panel-caption">
                    {t(`remoteMonitor.${scene}`)}
                  </span>
                }
              >
                <div className="monitor-product-list" aria-busy={loading}>
                  {loading && !page ? (
                    <Spin />
                  ) : !page?.items.length &&
                    !page?.referenceResources?.length ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={t(
                        failure
                          ? "remoteMonitor.unavailable"
                          : "remoteMonitor.waiting",
                      )}
                    />
                  ) : (
                    <MonitorProductSelector
                      selection={selection}
                      presentation="list"
                    />
                  )}
                  {page?.nextBeforeId && (
                    <Button
                      size="small"
                      block
                      loading={loading}
                      onClick={() => void loadMore()}
                    >
                      {t("remoteMonitor.loadMore")}
                    </Button>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel
                className="monitor-product-info-panel"
                title={t("remoteMonitor.limitations")}
              >
                <div className="monitor-panel-scroll">
                  {selected ? (
                    <>
                      <dl className="monitor-product-info">
                        <dt>{t("remoteMonitor.source")}</dt>
                        <dd>{selected.sourceLabel}</dd>
                        <dt>{t("remoteMonitor.observed")}</dt>
                        <dd>
                          {periodLabel(
                            selected,
                            t("remoteMonitor.unknownTime"),
                          )}
                        </dd>
                        {selected.model && (
                          <>
                            <dt>{t("remoteMonitor.model")}</dt>
                            <dd>
                              {selected.model.name} · {selected.model.version} ·{" "}
                              {selected.model.variant}
                            </dd>
                          </>
                        )}
                        {selected.threshold !== null && (
                          <>
                            <dt>{t("remoteMonitor.threshold")}</dt>
                            <dd>{selected.threshold}</dd>
                          </>
                        )}
                        {selected.timing.validStart && (
                          <>
                            <dt>{t("remoteMonitor.validPeriod")}</dt>
                            <dd>
                              {selected.timing.validStart} —{" "}
                              {selected.timing.validEnd}
                            </dd>
                          </>
                        )}
                      </dl>
                      <details className="monitor-product-method">
                        <summary>{t("remoteMonitor.evidence")}</summary>
                        <p>{selected.statisticsMethod}</p>
                        {selected.model && (
                          <p className="monitor-product-hash">
                            SHA-256 · {selected.model.checkpointSha256}
                          </p>
                        )}
                        <ul>
                          {[...new Set(selected.limitations)].map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </details>
                    </>
                  ) : (
                    <div className="monitor-panel-empty">
                      {t("remoteMonitor.noProductInfo")}
                    </div>
                  )}
                </div>
              </MonitorPanel>
              <MonitorPanel
                title={t("remoteMonitor.route")}
                extra={
                  <Button
                    size="small"
                    type="text"
                    onClick={() => navigate("/business-flows")}
                  >
                    {t("remoteMonitor.openFlows")}
                  </Button>
                }
              >
                <ol className="monitor-route-grid">
                  {(page?.route ?? []).map((step, index) => (
                    <li key={step}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      {step}
                    </li>
                  ))}
                </ol>
              </MonitorPanel>
              <MonitorAssessmentCard
                summary={
                  selected?.interpretation ?? t("remoteMonitor.noConclusion")
                }
                badge={
                  selected
                    ? t(`remoteMonitor.quality.${selected.quality}`)
                    : undefined
                }
              />
            </div>
          </main>
        </>
      )}
    </MonitorDashboardFrame>
  );
}

function periodLabel(product: MonitoringProduct, unknown: string) {
  if (!product.observedStart) return unknown;
  return product.observedStart === product.observedEnd
    ? product.observedStart
    : `${product.observedStart} — ${product.observedEnd}`;
}
function metricValue(metric: MonitoringMetric) {
  if (metric.value === null) return "—";
  return (
    metric.key === "mean_probability" ? metric.value * 100 : metric.value
  ).toLocaleString(currentLocale(), {
    maximumFractionDigits: metric.key === "patch_count" ? 0 : 2,
  });
}
function metricUnit(metric: MonitoringMetric) {
  return metric.key === "mean_probability" ? "%" : metric.unit;
}
function metricNumberStyle(metric: MonitoringMetric): CSSProperties {
  return {
    "--monitor-value-width": metricValue(metric).length * 0.62,
  } as CSSProperties;
}
function emptyMetrics(
  scene: MonitoringProductList["scene"],
): MonitoringMetric[] {
  return scene === "spartina"
    ? [
        { key: "area_ha", label: "分布面积", unit: "ha", value: null },
        { key: "patch_count", label: "斑块数量", unit: "个", value: null },
        {
          key: "valid_area_km2",
          label: "有效统计面积",
          unit: "km²",
          value: null,
        },
        {
          key: "coverage_percent",
          label: "有效区覆盖比例",
          unit: "%",
          value: null,
        },
      ]
    : [
        {
          key: "mean_probability",
          label: "有效区平均概率",
          unit: "",
          value: null,
        },
        {
          key: "high_risk_area_km2",
          label: "阈值以上区域面积",
          unit: "km²",
          value: null,
        },
        {
          key: "valid_coverage_percent",
          label: "有效数据覆盖率",
          unit: "%",
          value: null,
        },
        {
          key: "burned_area_ha",
          label: "观测烧毁面积",
          unit: "ha",
          value: null,
        },
      ];
}
