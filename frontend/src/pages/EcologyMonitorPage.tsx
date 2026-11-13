import {
  ArrowLeftOutlined,
  CloseOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  PauseOutlined,
  CaretRightOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  ConfigProvider,
  Result,
  Space,
  Spin,
  theme,
} from "antd";
import {
  type CSSProperties,
  type ReactNode,
  Suspense,
  lazy,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { currentLocale } from "../i18n";
import MonitorSpaceBackground from "../monitor/MonitorSpaceBackground";
import {
  AlertsPanel,
  AssessmentPanel,
  MetricsPanel,
  MonitorNumber,
  RankingPanel,
  RiskPanel,
  TrendPanel,
} from "../monitor/MonitorPanels";
import { createMonitorSource } from "../monitor/source";
import { useMonitorProject } from "../monitor/project";
import { metricPrecision, metricUnits, riskColors } from "../monitor/state";
import { metricIds, type MonitorDataSource } from "../monitor/types";
import { useMonitor, useMonitorActivity } from "../monitor/useMonitor";
import RemoteSensingDashboard from "../monitor/RemoteSensingDashboard";
import "./ecology-monitor.css";

const MonitorGlobe = lazy(() => import("../monitor/MonitorGlobe"));

export default function EcologyMonitorPage() {
  const project = useMonitorProject();
  const { i18n, t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const config = project?.monitorConfig;
  const scenes =
    config?.scenes ??
    (config?.source === "remote_sensing_products"
      ? ["spartina", "wildfire"]
      : []);
  const choices = [
    ...(config?.source === "tarim_poplar_mock" ? ["poplar"] : []),
    ...scenes,
  ];
  const selectedScene = choices.includes(search.get("scene") ?? "")
    ? search.get("scene")!
    : choices[0];
  const source = useMemo(
    () =>
      project && config?.source === "tarim_poplar_mock"
        ? createMonitorSource({
            projectId: project.id,
            locale: currentLocale(),
            config,
          })
        : undefined,
    [project?.id, config, i18n.resolvedLanguage],
  );
  if (
    !project ||
    !config ||
    !choices.length ||
    (selectedScene === "poplar" && !source)
  )
    return (
      <Result
        status={project ? "info" : "403"}
        title={t(project ? "monitor.notConfigured" : "monitor.notEnabled")}
        extra={
          <Button onClick={() => navigate("/results")}>
            {t("monitor.back")}
          </Button>
        }
      />
    );
  return (
    <ConfigProvider
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#65dfc8",
          colorBgContainer: "#102737",
          colorText: "#e2f2f7",
          colorBorder: "#315566",
          borderRadius: 6,
          fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <App>
        {selectedScene === "spartina" || selectedScene === "wildfire" ? (
          <RemoteSensingDashboard
            key={`${project.id}:${selectedScene}:${i18n.resolvedLanguage}`}
            config={config}
            scene={selectedScene}
            navigation={sceneNavigation()}
          />
        ) : (
          source && (
            <EcologyMonitorDashboard
              key={`${project.id}:${i18n.resolvedLanguage}`}
              source={source}
              config={config}
              navigation={sceneNavigation()}
            />
          )
        )}
      </App>
    </ConfigProvider>
  );

  function sceneNavigation() {
    if (choices.length < 2) return null;
    return (
      <Space
        className="monitor-scene-navigation"
        role="navigation"
        aria-label={t("remoteMonitor.scenes")}
      >
        {choices.map((scene) => (
          <Button
            key={scene}
            size="small"
            type={scene === selectedScene ? "primary" : "default"}
            aria-pressed={scene === selectedScene}
            aria-label={t(`remoteMonitor.${scene}`)}
            onClick={() =>
              setSearch((previous) => {
                const next = new URLSearchParams(previous);
                next.set("scene", scene);
                next.set("projectTagId", String(project!.id));
                return next;
              })
            }
          >
            {t(`remoteMonitor.${scene}`)}
          </Button>
        ))}
      </Space>
    );
  }
}

export function EcologyMonitorDashboard({
  source,
  config,
  navigation,
}: {
  source: MonitorDataSource;
  config: ProjectMonitorConfig;
  navigation?: ReactNode;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { snapshot, error, lastEvent } = useMonitor(source);
  const { visible, reducedMotion } = useMonitorActivity();
  const [motionOverride, setMotionOverride] = useState<boolean>();
  const motionEnabled = motionOverride ?? !reducedMotion;
  const animated = visible && motionEnabled;
  const navigate = useNavigate();
  const root = useRef<HTMLDivElement>(null);
  const [selectedId, setSelectedId] = useState<string>();
  const [now, setNow] = useState(Date.now);
  const [fullscreen, setFullscreen] = useState(false);
  const locale = currentLocale();
  useEffect(() => {
    if (!visible) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [visible]);
  useEffect(() => {
    const update = () =>
      setFullscreen(document.fullscreenElement === root.current);
    document.addEventListener("fullscreenchange", update);
    return () => {
      document.removeEventListener("fullscreenchange", update);
    };
  }, []);
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (root.current?.requestFullscreen)
        await root.current.requestFullscreen();
      else message.info(t("monitor.fullscreenUnavailable"));
    } catch {
      message.info(t("monitor.fullscreenUnavailable"));
    }
  };
  const selected = snapshot?.stations.find(
    (station) => station.id === selectedId,
  );
  const activeAlerts =
    snapshot?.alerts.filter((alert) => !alert.resolvedAt).length ?? 0;
  return (
    <div
      ref={root}
      className="ecology-monitor"
      data-motion={animated ? "running" : "paused"}
      data-reduced-motion={reducedMotion}
    >
      <MonitorSpaceBackground />
      <header className="monitor-topbar">
        <div className="monitor-title" title={t("monitor.subtitle")}>
          <div className="monitor-title-mark" aria-hidden="true">
            ◎
          </div>
          <div>
            <h1>{config.title}</h1>
          </div>
        </div>
        {navigation}
        <div className="monitor-topbar-meta">
          <time
            title={`${new Date(now).toLocaleString(locale, { hour12: false })} · ${t(
              "monitor.updatedAt",
              {
                time: snapshot
                  ? new Date(snapshot.updatedAt).toLocaleTimeString(locale, {
                      hour12: false,
                    })
                  : "—",
              },
            )}`}
          >
            {new Date(now).toLocaleTimeString(locale, { hour12: false })}
          </time>
        </div>
        <div className="monitor-topbar-actions">
          <Button
            size="small"
            icon={motionEnabled ? <PauseOutlined /> : <CaretRightOutlined />}
            aria-label={t(
              motionEnabled ? "monitor.pauseMotion" : "monitor.playMotion",
            )}
            onClick={() => setMotionOverride(!motionEnabled)}
            aria-pressed={motionEnabled}
          >
            {t(motionEnabled ? "monitor.pauseMotion" : "monitor.playMotion")}
          </Button>
          <Button
            size="small"
            icon={
              fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />
            }
            onClick={() => void toggleFullscreen()}
          >
            {t(fullscreen ? "monitor.exitFullscreen" : "monitor.fullscreen")}
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
      {error ? (
        <div className="monitor-loading">
          <Alert type="error" title={t("monitor.sourceError")} />
        </div>
      ) : !snapshot ? (
        <div className="monitor-loading">
          <Spin aria-label={t("common.loading")} />
        </div>
      ) : (
        <main className="monitor-layout">
          <section
            className="monitor-globe-panel"
            aria-label={t("monitor.networkTitle")}
          >
            <Suspense
              fallback={
                <div className="monitor-loading">
                  <Spin />
                </div>
              }
            >
              <MonitorGlobe
                initialView={config.initialView}
                snapshot={snapshot}
                lastEvent={lastEvent}
                animated={animated}
                onSelect={setSelectedId}
              />
            </Suspense>
            {selected && (
              <aside
                className="monitor-station-card"
                aria-label={t("monitor.stationDetails")}
              >
                <div className="monitor-station-card-title">
                  <div>
                    <small>
                      {t(`monitor.type.${selected.type}`)} · {selected.section}
                    </small>
                    <h3>{selected.name}</h3>
                  </div>
                  <Button
                    type="text"
                    size="small"
                    icon={<CloseOutlined />}
                    aria-label={t("monitor.closeDetails")}
                    onClick={() => setSelectedId(undefined)}
                  />
                </div>
                <span
                  className="monitor-status"
                  style={
                    {
                      "--status-color": riskColors[selected.level],
                    } as CSSProperties
                  }
                >
                  {t(`monitor.level.${selected.level}`)}
                </span>
                <dl>
                  {metricIds.map((metric) => (
                    <div key={metric}>
                      <dt>{t(`monitor.metric.${metric}`)}</dt>
                      <dd>
                        {selected.readings[metric].toFixed(
                          metricPrecision[metric],
                        )}
                        <small>{metricUnits[metric]}</small>
                      </dd>
                    </div>
                  ))}
                </dl>
                <p>{selected.recentEvent}</p>
                <time>
                  {new Date(selected.updatedAt).toLocaleTimeString(locale, {
                    hour12: false,
                  })}
                </time>
              </aside>
            )}
          </section>
          <div className="monitor-information">
            <div className="monitor-summary">
              <div>
                <span>{t("monitor.stationCount")}</span>
                <strong>
                  <MonitorNumber value={snapshot.stations.length} />
                  <small>{t("monitor.siteUnit")}</small>
                </strong>
              </div>
              <div>
                <span>{t("monitor.activeAlerts")}</span>
                <strong
                  className="monitor-warm"
                  data-testid="active-alert-count"
                >
                  <MonitorNumber value={activeAlerts} />
                  <small>{t("monitor.alertUnit")}</small>
                </strong>
              </div>
              <div>
                <span>{t("monitor.receivedEvents")}</span>
                <strong data-testid="event-count">
                  <MonitorNumber value={snapshot.sequence} />
                  <small>{t("monitor.eventUnit")}</small>
                </strong>
              </div>
            </div>

            <RiskPanel snapshot={snapshot} />
            <MetricsPanel snapshot={snapshot} />
            <TrendPanel snapshot={snapshot} locale={locale} />
            <AlertsPanel
              snapshot={snapshot}
              animated={animated}
              locale={locale}
              onSelect={setSelectedId}
            />
            <RankingPanel snapshot={snapshot} onSelect={setSelectedId} />
            <AssessmentPanel snapshot={snapshot} />
          </div>
        </main>
      )}
      <footer className="monitor-footer">
        <span>
          <i />
          {t(visible ? "monitor.feedRunning" : "monitor.feedPaused")}
        </span>
        <span>
          {t(
            motionEnabled
              ? "monitor.rotationHint"
              : reducedMotion
                ? "monitor.motionReduced"
                : "monitor.motionPaused",
          )}
        </span>
        <span>{t("monitor.simulationOnly")}</span>
      </footer>
    </div>
  );
}
