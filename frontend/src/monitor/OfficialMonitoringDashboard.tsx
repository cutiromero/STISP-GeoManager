import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Space, Spin } from "antd";
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
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
const sceneTitles = {
  landcover: ["地表覆盖解译", "LAND COVER INTELLIGENCE"],
  spartina: ["互花米草分布监测", "COASTAL HABITAT MONITORING"],
  wildfire: ["野火遥感观测", "WILDFIRE EARTH OBSERVATION"],
} as const;

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
  const { animated } = useMonitorActivity();
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailure("");
    void requestJson<OfficialMonitoringList>(
      `/api/ecology/monitoring/official/?scene=${scene}`,
      {
        signal: controller.signal,
      },
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        setItems(result.items);
        setCurrent(0);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setItems([]);
        setFailure(
          error instanceof Error ? error.message : "暂时无法读取正式成果",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
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
  const product = items[current];
  const [title, english] = sceneTitles[scene];
  const primaryKey =
    scene === "landcover"
      ? "valid_area_km2"
      : scene === "spartina"
        ? "area_ha"
        : product?.observation?.unit === "W m-2"
          ? "frp_w_m2"
          : "burned_area_ha";
  const measured =
    product?.metrics.filter((metric) => metric.value != null) ?? [];
  const primary =
    measured.find((metric) => metric.key === primaryKey) ?? measured[0];
  const primaryValue =
    primary?.value == null
      ? "—"
      : new Intl.NumberFormat("zh-CN", {
          maximumFractionDigits: 3,
          ...(Math.abs(primary.value) >= 1e12
            ? { notation: "scientific" as const }
            : {}),
        }).format(primary.value);
  const secondary = measured
    .filter((metric) => metric.key !== primary?.key)
    .slice(0, 3);
  const date = !product?.observedStart
    ? "观测期未登记"
    : product.observedStart === product.observedEnd
      ? product.observedStart
      : `${product.observedStart} — ${product.observedEnd}`;
  const hasMap = Boolean(
    product?.display || product?.resource.dataType === "vector",
  );
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
      status={() => (product ? "正式成果展示 · 只读" : "正式成果展示")}
      sourceLabel={english}
    >
      {({ animated: mapMotion }) => (
        <main className="monitor-layout">
          <section className="monitor-globe-panel" aria-label="正式成果地图">
            <ProductMap
              config={config}
              product={hasMap ? product : undefined}
              animated={mapMotion}
              information
              focusProduct
              readOnly
              preparedDisplay={product?.display}
            />
            <div className="official-map-caption">
              <span className="official-map-caption-label">地理空间观测</span>
              <h2 title={product?.regionLabel}>
                {product?.regionLabel ?? "项目成果全景"}
              </h2>
              {product && <span>{date}</span>}
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
                  业务流处理完成后，在数据中心登记主地图成果，即可在这里展示。
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
                ) : explanation ? (
                  <MonitorPanel title="成果说明">
                    <p className="official-interpretation">{explanation}</p>
                  </MonitorPanel>
                ) : null}
              </div>
            )}
          </aside>
        </main>
      )}
    </MonitorDashboardFrame>
  );
}
