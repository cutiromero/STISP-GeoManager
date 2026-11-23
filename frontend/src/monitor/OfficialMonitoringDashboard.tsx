import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Space, Spin } from "antd";
import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from "react";
import { requestJson } from "../api/client";
import type {
  OfficialMonitoringList,
  OfficialMonitoringProduct,
  ProjectMonitorConfig,
} from "../api/generated/types.gen";
import MonitorDashboardFrame from "./MonitorDashboardFrame";
import { MonitorPanel } from "./MonitorPanels";
import ProductMap from "./ProductMap";
import { useMonitorActivity } from "./useMonitor";
import "./official-monitoring.css";

const rotationMs = 13000;
const glacierRefreshMs = 30000;
const overviewPageSize = 4;
const primaryNumber = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 3,
});
const scientificNumber = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 3,
  notation: "scientific",
});
const registrationTime = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
});
const sceneTitles = {
  glacier: ["冰川遥感监测", "GLACIER MONITORING"],
  landcover: ["地表覆盖解译", "LAND COVER INTELLIGENCE"],
  spartina: ["互花米草分布监测", "COASTAL HABITAT MONITORING"],
  wildfire: ["野火遥感观测", "WILDFIRE EARTH OBSERVATION"],
} as const;

function mainMetric(
  scene: OfficialMonitoringList["scene"],
  product: OfficialMonitoringProduct | undefined,
) {
  const key =
    scene === "glacier"
      ? product?.kind === "model" ? "ice_area_km2" : "valid_coverage_percent"
      : scene === "landcover"
        ? "valid_area_km2"
        : scene === "spartina"
          ? "area_ha"
          : product?.observation?.unit === "W m-2"
            ? "frp_w_m2"
            : "burned_area_ha";
  const measured =
    product?.metrics.filter((metric) => metric.value != null) ?? [];
  return {
    primary: measured.find((metric) => metric.key === key) ?? measured[0],
    measured,
  };
}

function formatMetric(value: number | null | undefined) {
  if (value == null) return "—";
  return (Math.abs(value) >= 1e12 ? scientificNumber : primaryNumber).format(
    value,
  );
}

function observedPeriod(product: OfficialMonitoringProduct) {
  if (product.scene === "glacier") {
    return product.registrationDate ? `登记期：${product.registrationDate}` : "登记期待补充";
  }
  const { observedStart: start, observedEnd: end } = product;
  return start && end && start !== end
    ? `${start} — ${end}`
    : start || end || "观测期未登记";
}

export default function OfficialMonitoringDashboard({
  config,
  navigation,
  scene,
}: {
  config: ProjectMonitorConfig;
  navigation: ReactNode;
  scene: OfficialMonitoringList["scene"];
}) {
  const [items, setItems] = useState<OfficialMonitoringProduct[]>([]);
  const [current, setCurrent] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState("");
  const [revision, setRevision] = useState(0);
  const [showOriginal, setShowOriginal] = useState(false);
  const { animated } = useMonitorActivity();
  const selected = useRef<number | undefined>(undefined);
  selected.current = items[current]?.id;
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    async function load(initial: boolean) {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      if (initial) {
        setLoading(true);
        setFailure("");
      }
      try {
        const { items: next } = await requestJson<OfficialMonitoringList>(
          `/api/ecology/monitoring/official/?scene=${scene}`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        const index = next.findIndex((row) => row.id === selected.current);
        setItems(next);
        setCurrent(initial || index < 0 ? 0 : index);
        setFailure("");
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        setItems([]);
        setCurrent(0);
        setFailure(error instanceof Error ? error.message : "暂时无法读取正式成果");
      } finally {
        inFlight = false;
        if (initial && !controller.signal.aborted) setLoading(false);
      }
    }
    void load(true);
    const timer = scene === "glacier" ? window.setInterval(() => {
      if (document.visibilityState === "visible") void load(false);
    }, glacierRefreshMs) : undefined;
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [scene, revision]);
  const rotating = animated && !paused && !hovered && items.length > 1;
  useEffect(() => {
    if (!rotating) return;
    const timer = window.setInterval(
      () => setCurrent((index) => (index + 1) % items.length),
      rotationMs,
    );
    return () => window.clearInterval(timer);
  }, [rotating, items.length]);
  const choose = (offset: number) => {
    setPaused(true);
    setCurrent((index) => (index + offset + items.length) % items.length);
  };
  const selectResult = (index: number) => {
    setPaused(true);
    setCurrent(index);
  };
  const product = items[current];
  const [title, english] = sceneTitles[scene];
  const { primary, measured } = mainMetric(scene, product);
  const primaryValue = formatMetric(primary?.value);
  const secondary = measured
    .filter((metric) => metric.key !== primary?.key)
    .slice(0, 3);
  const isGlacier = scene === "glacier";
  const comparison = isGlacier && showOriginal ? product?.comparison : null;
  const display = comparison?.display ?? product?.display;
  const hasMap = Boolean(display || product?.resource.dataType === "vector");
  const explanation = product?.interpretation || product?.statisticsMethod;
  return (
    <MonitorDashboardFrame
      config={{ ...config, title }}
      scene={scene}
      displayOnly
      navigation={navigation}
      actions={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => setRevision((v) => v + 1)}
        >
          刷新成果
        </Button>
      }
      updatedAt={items[0]?.registeredAt}
      status={() =>
        isGlacier
          ? "按登记期查看分类变化"
          : product
            ? "正式成果展示 · 只读"
            : "正式成果展示"
      }
      sourceLabel={english}
    >
      {({ animated: mapMotion }) => (
        <main className="monitor-layout">
          <section className="monitor-globe-panel" aria-label="正式成果地图">
            <ProductMap
              config={config}
              product={hasMap ? product : undefined}
              resource={comparison?.resource}
              focusKey={isGlacier ? product?.id : undefined}
              animated={mapMotion}
              information
              focusProduct
              readOnly
              preparedDisplay={display}
            />
            <div className="official-map-caption">
              <span className="official-map-caption-label">{isGlacier ? "样区成果" : "地理空间观测"}</span>
              <h2 title={product?.regionLabel}>
                {product?.regionLabel ?? "项目成果全景"}
              </h2>
              {product && <span>{observedPeriod(product)}</span>}
              {isGlacier && product?.comparison && (
                <Space
                  className="official-glacier-map-toggle"
                  role="group"
                  aria-label="影像与分类对照"
                >
                  <Button
                    size="small"
                    type={comparison ? "default" : "primary"}
                    aria-pressed={!comparison}
                    onClick={() => setShowOriginal(false)}
                  >
                    分类结果
                  </Button>
                  <Button
                    size="small"
                    type={comparison ? "primary" : "default"}
                    aria-pressed={!!comparison}
                    onClick={() => setShowOriginal(true)}
                  >
                    原始影像
                  </Button>
                  {comparison && <small>第 1 波段灰度</small>}
                </Space>
              )}
            </div>
            {product && !hasMap && (
              <div className="official-map-note">
                地图切片暂不可用，已登记统计仍可查看。
              </div>
            )}
          </section>
          <aside
            className="official-insights"
            aria-label="区域观测指标"
            onPointerEnter={() => setHovered(true)}
            onPointerLeave={() => setHovered(false)}
          >
            <header className="official-insights-heading">
              <div className="official-insights-title">
                <h2>解译统计</h2>
                {product && <span className="official-status">已登记</span>}
              </div>
              {items.length > 1 && (
                <div
                  className="official-region-controls"
                  role="group"
                  aria-label="区域浏览"
                >
                  <span
                    className="official-counter"
                    title={rotating ? "区域轮播中" : "区域浏览"}
                  >
                    {current + 1} <small>/ {items.length}</small>
                  </span>
                  <Space size={4}>
                    <Button
                      size="small"
                      aria-label="上一区域"
                      icon={<ArrowLeftOutlined />}
                      onClick={() => choose(-1)}
                    />
                    <Button
                      size="small"
                      aria-label={paused ? "播放区域轮播" : "暂停区域轮播"}
                      icon={
                        paused ? (
                          <PlayCircleOutlined />
                        ) : (
                          <PauseCircleOutlined />
                        )
                      }
                      onClick={() => setPaused((value) => !value)}
                    />
                    <Button
                      size="small"
                      aria-label="下一区域"
                      icon={<ArrowRightOutlined />}
                      onClick={() => choose(1)}
                    />
                  </Space>
                </div>
              )}
            </header>
            {failure ? (
              <Alert type="error" showIcon title={failure} />
            ) : loading && !product ? (
              <div className="official-empty monitor-panel">
                <Spin />
                <p>正在读取正式登记成果</p>
              </div>
            ) : !product ? (
              <MonitorPanel
                title="暂无可展示的正式成果"
                className="official-empty"
              >
                <p>
                  {isGlacier
                    ? "冰川业务流完成后，分类图会自动显示在这里。"
                    : "业务流处理完成后，在数据中心登记主地图成果，即可在这里展示。"}
                </p>
              </MonitorPanel>
            ) : (
              <div className="official-region-story" key={product.id}>
                <MonitorPanel
                  title={primary?.label ?? "区域观测值"}
                  extra={
                    product.observation?.product && (
                      <span className="monitor-panel-caption">
                        {product.observation.product.toUpperCase()}
                      </span>
                    )
                  }
                >
                  <div className="official-hero-stat">
                    <strong
                      style={
                        {
                          "--metric-length": String(primaryValue.length),
                        } as CSSProperties
                      }
                    >
                      {primaryValue}
                    </strong>
                    {primary?.unit && <small>{primary.unit}</small>}
                  </div>
                  {!!secondary.length && (
                    <dl className="official-metric-strip">
                      {secondary.map((metric) => (
                        <div key={metric.key}>
                          <dt>{metric.label}</dt>
                          <dd>
                            {new Intl.NumberFormat("zh-CN", {
                              maximumFractionDigits: 2,
                            }).format(metric.value!)}{" "}
                            <small>{metric.unit}</small>
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </MonitorPanel>
                {isGlacier && product.kind === "model" && <GlacierChange product={product} />}
                {product.classification?.categories.length ? (
                  <MonitorPanel title="地类面积占比">
                    <div className="official-composition">
                      {product.classification.categories
                        .slice(0, 6)
                        .map((row) => (
                          <div
                            key={row.code}
                            style={
                              {
                                "--class-color": row.color,
                                "--class-share": `${row.percent}%`,
                              } as CSSProperties
                            }
                          >
                            <span>
                              <i />
                              {row.name}
                            </span>
                            <b aria-hidden="true" />
                            <strong>
                              {new Intl.NumberFormat("zh-CN", {
                                maximumFractionDigits: 1,
                              }).format(row.percent)}
                              %
                            </strong>
                          </div>
                        ))}
                    </div>
                  </MonitorPanel>
                ) : !isGlacier && explanation ? (
                  <MonitorPanel title="成果说明">
                    <p className="official-interpretation">{explanation}</p>
                  </MonitorPanel>
                ) : null}
              </div>
            )}
            {!failure &&
              product &&
              (isGlacier || items.length > 1 ? (
                <OfficialRegionOverview
                  scene={scene}
                  items={items}
                  current={current}
                  onSelect={selectResult}
                  onKeyboardFocus={() => setPaused(true)}
                />
              ) : (
                <OfficialResultArchive product={product} />
              ))}
          </aside>
        </main>
      )}
    </MonitorDashboardFrame>
  );
}

function SignedGlacierChange({ value }: { value: number }) {
  const direction = value > 0 ? "positive" : value < 0 ? "negative" : "unchanged";
  return (
    <span className="glacier-change-signed" data-direction={direction}>
      {value > 0 ? "+" : ""}{formatMetric(value)}
    </span>
  );
}

function GlacierChange({ product }: { product: OfficialMonitoringProduct }) {
  const change = product.glacierChange;
  const codeOnly = change?.basis === "registered_codes";
  return (
    <MonitorPanel title="登记期变化" className="official-glacier-change"
      extra={change && <span className="monitor-panel-caption">{change.baselineDate} → {product.registrationDate}</span>}>
      {change ? (
        <>
          <dl className="official-metric-strip">
            <div className="glacier-change-overlap">
              <dt>共同有效面积</dt>
              <dd>{formatMetric(change.commonAreaKm2)} <small>km²</small></dd>
            </div>
            <div className="glacier-change-share">
              <dt>{codeOnly ? "编码变化占比" : "分类变化占比"}</dt>
              <dd>{formatMetric(change.changedPercent)} <small>%</small></dd>
            </div>
            {change.netIceAreaKm2 != null && (
              <div>
                <dt>冰川分类面积净变化</dt>
                <dd><SignedGlacierChange value={change.netIceAreaKm2} /> <small>km²</small></dd>
              </div>
            )}
            {codeOnly && (
              <div>
                <dt>编码 1 / 2 面积差</dt>
                <dd>
                  <SignedGlacierChange value={change.netClass1Km2} /> /{" "}
                  <SignedGlacierChange value={change.netClass2Km2} /> <small>km²</small>
                </dd>
              </div>
            )}
          </dl>
          <p>{codeOnly ? "上期为交接标准图，只比较类别编码。" : "只统计两期共同有效范围。"}</p>
        </>
      ) : <p>暂无可对比的前一登记期。</p>}
    </MonitorPanel>
  );
}

function OfficialRegionOverview({
  scene,
  items,
  current,
  onSelect,
  onKeyboardFocus,
}: {
  scene: OfficialMonitoringList["scene"];
  items: OfficialMonitoringProduct[];
  current: number;
  onSelect: (index: number) => void;
  onKeyboardFocus: () => void;
}) {
  const scrollable = scene === "glacier";
  const start = scrollable ? 0 : Math.floor(current / overviewPageSize) * overviewPageSize;
  const end = scrollable ? items.length : Math.min(start + overviewPageSize, items.length);
  return (
    <MonitorPanel
      title="区域成果一览"
      className="official-overview"
      extra={
        <div className="official-overview-nav">
          <span className="monitor-panel-caption">
            {!scrollable && items.length > overviewPageSize
              ? `${start + 1}–${end} / ${items.length} 项`
              : `${items.length} 项已登记`}
          </span>
          {!scrollable && items.length > overviewPageSize && (
            <Space size={4}>
              <Button
                size="small"
                icon={<ArrowLeftOutlined />}
                aria-label="上一组成果"
                disabled={start === 0}
                onClick={() => onSelect(start - overviewPageSize)}
              />
              <Button
                size="small"
                icon={<ArrowRightOutlined />}
                aria-label="下一组成果"
                disabled={end === items.length}
                onClick={() => onSelect(end)}
              />
            </Space>
          )}
        </div>
      }
    >
      <ul className="official-overview-list">
        {items.slice(start, end).map((item, offset) => {
          const index = start + offset;
          const { primary } = mainMetric(scene, item);
          return (
            <li key={item.id}>
              <button
                type="button"
                className="official-overview-row"
                aria-pressed={index === current}
                onClick={() => onSelect(index)}
                onFocus={(event) => {
                  if (event.currentTarget.matches(":focus-visible"))
                    onKeyboardFocus();
                }}
              >
                <span className="official-overview-index" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="official-overview-name">
                  <strong title={item.regionLabel}>{item.regionLabel}</strong>
                  <small>{observedPeriod(item)}</small>
                </span>
                <span className="official-overview-metric">
                  <small>{primary?.label ?? "统计未登记"}</small>
                  <strong>
                    {formatMetric(primary?.value)}
                    {primary?.unit && <small>{primary.unit}</small>}
                  </strong>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </MonitorPanel>
  );
}

function OfficialResultArchive({
  product,
}: {
  product: OfficialMonitoringProduct;
}) {
  const timestamp = new Date(product.registeredAt);
  const method = product.model
    ? [product.model.name, product.model.version].filter(Boolean).join(" · ")
    : product.observation?.product.toUpperCase();
  const quality = {
    passed: "已核验",
    unverified: "未核验",
    needs_review: "待复核",
  }[product.quality];
  return (
    <MonitorPanel title="成果档案" className="official-overview">
      <dl className="official-archive">
        <div>
          <dt>观测期</dt>
          <dd>{observedPeriod(product)}</dd>
        </div>
        {Number.isFinite(timestamp.getTime()) && (
          <div>
            <dt>登记时间</dt>
            <dd>
              <time dateTime={product.registeredAt}>
                {registrationTime.format(timestamp)}
              </time>
            </dd>
          </div>
        )}
        {method && (
          <div>
            <dt>{product.model ? "解译模型" : "观测产品"}</dt>
            <dd>{method}</dd>
          </div>
        )}
        {quality && (
          <div>
            <dt>核验状态</dt>
            <dd>{quality}</dd>
          </div>
        )}
        {product.sourceLabel && (
          <div className="official-archive-wide">
            <dt>资料来源</dt>
            <dd>{product.sourceLabel}</dd>
          </div>
        )}
        {product.statisticsMethod &&
          product.interpretation &&
          product.statisticsMethod !== product.interpretation && (
            <div className="official-archive-wide">
              <dt>统计口径</dt>
              <dd>{product.statisticsMethod}</dd>
            </div>
          )}
      </dl>
    </MonitorPanel>
  );
}
