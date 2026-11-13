import {
  ArrowLeftOutlined,
  FullscreenOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Spin, Tag } from "antd";
import {
  type ReactNode,
  Suspense,
  lazy,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type {
  MonitoringProduct,
  MonitoringProductList,
  ProjectMonitorConfig,
} from "../api/generated/types.gen";
import { currentLocale } from "../i18n";
import { getMonitoringProducts } from "./productApi";
import MonitorSpaceBackground from "./MonitorSpaceBackground";
import { useMonitorActivity } from "./useMonitor";
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
  const { animated } = useMonitorActivity();
  const root = useRef<HTMLDivElement>(null);
  const pending = useRef<AbortController | undefined>(undefined);
  const [page, setPage] = useState<MonitoringProductList>();
  const [selectedId, setSelectedId] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<string>();
  const [revision, setRevision] = useState(0);
  const selected =
    page?.items.find((item) => item.id === selectedId) ?? page?.items[0];

  useEffect(() => {
    const controller = new AbortController();
    pending.current?.abort();
    pending.current = controller;
    setPage(undefined);
    setFailure(undefined);
    setLoading(true);
    setSelectedId(undefined);
    void getMonitoringProducts(scene, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPage(value);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setFailure(
            error instanceof Error ? error.message : t("monitor.sourceError"),
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => pending.current?.abort();
  }, [scene, revision, t]);

  const loadMore = async () => {
    if (!page?.nextBeforeId || loading) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setFailure(undefined);
    try {
      const value = await getMonitoringProducts(
        scene,
        controller.signal,
        page.nextBeforeId,
      );
      if (!controller.signal.aborted)
        setPage((previous) =>
          previous
            ? {
                ...value,
                items: [
                  ...previous.items,
                  ...value.items.filter(
                    (item) =>
                      !previous.items.some((entry) => entry.id === item.id),
                  ),
                ],
              }
            : value,
        );
    } catch (error) {
      if (!controller.signal.aborted) {
        setPage(undefined);
        setFailure(
          error instanceof Error ? error.message : t("monitor.sourceError"),
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const title = t(`remoteMonitor.${scene}`);
  return (
    <div
      ref={root}
      className="ecology-monitor remote-monitor"
      data-scene={scene}
      data-motion={animated ? "running" : "paused"}
    >
      <MonitorSpaceBackground />
      <header className="monitor-topbar">
        <div className="monitor-title">
          <div className="monitor-title-mark" aria-hidden="true">
            ◎
          </div>
          <div>
            <span>{t("remoteMonitor.eyebrow")}</span>
            <h1>{config.title}</h1>
          </div>
        </div>
        {navigation}
        <div className="monitor-topbar-actions">
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => setRevision((value) => value + 1)}
            loading={loading}
          >
            {t("remoteMonitor.refresh")}
          </Button>
          <Button
            size="small"
            icon={<FullscreenOutlined />}
            onClick={() => {
              const operation = document.fullscreenElement
                ? document.exitFullscreen()
                : root.current?.requestFullscreen?.();
              void operation?.catch(() =>
                setFailure(t("monitor.fullscreenUnavailable")),
              );
            }}
          >
            {t("monitor.fullscreen")}
          </Button>
          <Button
            size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate("/results")}
          >
            {t("monitor.back")}
          </Button>
        </div>
      </header>
      <div className="remote-scene-heading">
        <div>
          <span className="remote-scene-number">
            {scene === "spartina" ? "01" : "02"}
          </span>
          <h2>{title}</h2>
          <p>{t(`remoteMonitor.${scene}Subtitle`)}</p>
        </div>
        <Tag color={scene === "spartina" ? "green" : "orange"}>
          {t("remoteMonitor.catalogued")}
        </Tag>
      </div>
      {failure && (
        <Alert
          type="error"
          title={failure}
          closable
          onClose={() => setFailure(undefined)}
        />
      )}
      <main className="remote-monitor-layout">
        <aside
          className="remote-products remote-panel"
          aria-label={t("remoteMonitor.products")}
        >
          <div className="remote-panel-heading">
            <h3>{t("remoteMonitor.products")}</h3>
            <span>{page?.items.length ?? "—"}</span>
          </div>
          {loading && !page ? (
            <div className="remote-product-loading">
              <Spin />
            </div>
          ) : !page?.items.length ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                failure
                  ? t("remoteMonitor.unavailable")
                  : t("remoteMonitor.waiting")
              }
            />
          ) : (
            <div className="remote-product-list">
              {page.items.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`remote-product-choice${item.id === selected?.id ? " selected" : ""}`}
                  aria-pressed={item.id === selected?.id}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span>{t(`remoteMonitor.kind.${item.kind}`)}</span>
                  <strong>{item.name}</strong>
                  <time>
                    {periodLabel(item, t("remoteMonitor.unknownTime"))}
                  </time>
                  <small>{t(`remoteMonitor.quality.${item.quality}`)}</small>
                </button>
              ))}
            </div>
          )}
          {page?.nextBeforeId && (
            <Button block loading={loading} onClick={() => void loadMore()}>
              {t("remoteMonitor.loadMore")}
            </Button>
          )}
          <div className="remote-readiness">
            <h4>{t("remoteMonitor.scope")}</h4>
            <span>{t(`remoteMonitor.${scene}Scope`)}</span>
          </div>
        </aside>
        <section className="remote-map-panel">
          <Suspense
            fallback={
              <div className="remote-map-pending">
                <Spin />
                <span>{t("remoteMonitor.loadingMap")}</span>
              </div>
            }
          >
            <ProductMap product={selected} config={config} />
          </Suspense>
          <div className="remote-map-footnote">
            {t(`remoteMonitor.${scene}MapNote`)}
          </div>
        </section>
        <aside
          className="remote-details remote-panel"
          aria-label={t("remoteMonitor.details")}
        >
          <div className="remote-panel-heading">
            <h3>{t("remoteMonitor.details")}</h3>
            {selected && (
              <Tag color={selected.quality === "passed" ? "cyan" : "gold"}>
                {t(`remoteMonitor.quality.${selected.quality}`)}
              </Tag>
            )}
          </div>
          <div className="remote-metric-grid">
            {(selected?.metrics ?? emptyMetrics(scene))
              .filter(
                (metric) =>
                  metric.value !== null ||
                  emptyMetrics(scene).some(
                    (primary) => primary.key === metric.key,
                  ),
              )
              .map((metric) => (
                <div className="remote-metric" key={metric.key}>
                  <span>{metric.label}</span>
                  <strong>
                    {metric.value === null
                      ? "—"
                      : metric.value.toLocaleString(currentLocale(), {
                          maximumFractionDigits:
                            metric.key === "mean_probability" ? 4 : 2,
                        })}
                    <small>{metric.unit}</small>
                  </strong>
                </div>
              ))}
          </div>
          {selected ? (
            <>
              <p className="remote-interpretation">{selected.interpretation}</p>
              <dl className="remote-provenance">
                <dt>{t("remoteMonitor.observed")}</dt>
                <dd>{periodLabel(selected, t("remoteMonitor.unknownTime"))}</dd>
                {selected.model && (
                  <>
                    <dt>{t("remoteMonitor.model")}</dt>
                    <dd>{`${selected.model.name} · ${selected.model.version} · ${selected.model.variant}`}</dd>
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
                    <dd>{`${selected.timing.validStart} — ${selected.timing.validEnd}`}</dd>
                  </>
                )}
                <dt>{t("remoteMonitor.source")}</dt>
                <dd>{selected.sourceLabel}</dd>
              </dl>
              <details className="remote-evidence">
                <summary>{t("remoteMonitor.evidence")}</summary>
                <p>{selected.statisticsMethod}</p>
                {selected.model && (
                  <p className="remote-hash">
                    SHA-256 · {selected.model.checkpointSha256}
                  </p>
                )}
                <p>
                  {t("remoteMonitor.registered")}{" "}
                  {new Date(selected.registeredAt).toLocaleString(
                    currentLocale(),
                    { hour12: false },
                  )}
                </p>
              </details>
              <details className="remote-limitations">
                <summary>{t("remoteMonitor.limitations")}</summary>
                <ul>
                  {[...new Set(selected.limitations)].map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </details>
            </>
          ) : (
            <div className="remote-no-result">
              <h4>{t("remoteMonitor.noConclusion")}</h4>
            </div>
          )}
        </aside>
      </main>
      <footer className="remote-route">
        <div>
          <span>{t("remoteMonitor.route")}</span>
        </div>
        <ol>
          {(page?.route ?? []).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <Button onClick={() => navigate("/business-flows")}>
          {t("remoteMonitor.openFlows")}
        </Button>
      </footer>
    </div>
  );
}

function periodLabel(product: MonitoringProduct, unknown: string) {
  if (!product.observedStart) return unknown;
  return product.observedStart === product.observedEnd
    ? product.observedStart
    : `${product.observedStart} — ${product.observedEnd}`;
}

function emptyMetrics(
  scene: MonitoringProductList["scene"],
): MonitoringProduct["metrics"] {
  return scene === "spartina"
    ? [
        { key: "area_ha", label: "分布面积", unit: "ha", value: null },
        { key: "patch_count", label: "斑块数量", unit: "个", value: null },
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
      ];
}
