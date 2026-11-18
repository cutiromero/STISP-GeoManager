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
        <main className="official-monitor-main">
          <section className="official-map-stage" aria-label="正式成果地图">
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
              <span className="official-eyebrow">
                <i /> 地理空间观测
              </span>
              <strong>{product?.regionLabel ?? "项目成果全景"}</strong>
              {product && <span>{date}</span>}
            </div>
            {product && !hasMap && (
              <div className="official-map-note">
                地图切片暂不可用，已登记统计仍可查看。
              </div>
            )}
          </section>
          <aside
            className="official-intelligence"
            aria-label="区域观测指标"
            onPointerEnter={() => setHovered(true)}
            onPointerLeave={() => setHovered(false)}
          >
            <div className="official-intelligence-header">
              <span className="official-eyebrow">
                <i /> {english}
              </span>
              <span className="official-counter">
                {String(current + (product ? 1 : 0)).padStart(2, "0")}{" "}
                <small>/ {String(items.length).padStart(2, "0")}</small>
              </span>
            </div>
            {failure ? (
              <Alert type="error" showIcon title={failure} />
            ) : loading && !product ? (
              <div className="official-empty">
                <Spin />
                <p>正在读取正式登记成果</p>
              </div>
            ) : !product ? (
              <div className="official-empty">
                <span className="official-empty-icon">◎</span>
                <h2>暂无可展示的正式成果</h2>
                <p>
                  业务流处理完成后，在数据中心登记主地图成果，即可在这里展示。
                </p>
              </div>
            ) : (
              <div className="official-region-story" key={product.id}>
                <h2 title={product.regionLabel}>{product.regionLabel}</h2>
                <div className="official-period">
                  <span>{date}</span>
                  <span>
                    {product.observation?.product?.toUpperCase() ||
                      "已登记成果"}
                  </span>
                </div>
                <div className="official-hero-stat">
                  <span>{primary?.label ?? "区域观测值"}</span>
                  <div>
                    <strong>
                      {primary?.value == null
                        ? "—"
                        : new Intl.NumberFormat("zh-CN", {
                            maximumFractionDigits: 3,
                          }).format(primary.value)}
                    </strong>
                    <small>{primary?.unit}</small>
                  </div>
                  <span className="official-data-line" aria-hidden="true" />
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
                {product.classification?.categories.length ? (
                  <div
                    className="official-composition"
                    aria-label="地类面积占比"
                  >
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
                ) : (
                  <p className="official-interpretation">
                    {product.interpretation || product.statisticsMethod}
                  </p>
                )}
              </div>
            )}
            {items.length > 1 && (
              <div className="official-region-controls">
                <span>{rotating ? "区域轮播中" : "区域浏览"}</span>
                <Space size={8}>
                  <Button
                    aria-label="上一区域"
                    icon={<ArrowLeftOutlined />}
                    onClick={() => choose(-1)}
                  />
                  <Button
                    aria-label={paused ? "播放区域轮播" : "暂停区域轮播"}
                    icon={
                      paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />
                    }
                    onClick={() => setPaused((value) => !value)}
                  />
                  <Button
                    aria-label="下一区域"
                    icon={<ArrowRightOutlined />}
                    onClick={() => choose(1)}
                  />
                </Space>
              </div>
            )}
          </aside>
        </main>
      )}
    </MonitorDashboardFrame>
  );
}
