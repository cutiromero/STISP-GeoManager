import {
  ArrowLeftOutlined,
  CaretRightOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  PauseOutlined,
} from "@ant-design/icons";
import { App, Button } from "antd";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { ProjectMonitorConfig } from "../api/generated/types.gen";
import { currentLocale } from "../i18n";
import MonitorSpaceBackground from "./MonitorSpaceBackground";
import { useMonitorActivity } from "./useMonitor";

export interface MonitorFrameState {
  animated: boolean;
  visible: boolean;
}

export default function MonitorDashboardFrame({
  config,
  navigation,
  actions,
  updatedAt,
  sourceLabel,
  status,
  scene,
  children,
}: {
  config: ProjectMonitorConfig;
  navigation?: ReactNode;
  actions?: ReactNode;
  updatedAt?: string;
  sourceLabel: ReactNode;
  status: (state: MonitorFrameState) => ReactNode;
  scene?: string;
  children: (state: MonitorFrameState) => ReactNode;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const root = useRef<HTMLDivElement>(null);
  const { visible, reducedMotion } = useMonitorActivity();
  const [motionOverride, setMotionOverride] = useState<boolean>();
  const motionEnabled = motionOverride ?? !reducedMotion;
  const animated = visible && motionEnabled;
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
    return () => document.removeEventListener("fullscreenchange", update);
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
  const state = { animated, visible };
  return (
    <div
      ref={root}
      className={`ecology-monitor${scene ? " monitor-remote" : ""}`}
      data-scene={scene}
      data-motion={animated ? "running" : "paused"}
      data-reduced-motion={reducedMotion}
    >
      <MonitorSpaceBackground />
      <header className="monitor-topbar">
        <div
          className="monitor-title"
          title={t(
            scene ? `remoteMonitor.${scene}Subtitle` : "monitor.subtitle",
          )}
        >
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
            title={`${new Date(now).toLocaleString(locale, { hour12: false })}${updatedAt ? ` · ${t("monitor.updatedAt", { time: new Date(updatedAt).toLocaleString(locale, { hour12: false }) })}` : ""}`}
          >
            {new Date(now).toLocaleTimeString(locale, { hour12: false })}
          </time>
        </div>
        <div className="monitor-topbar-actions">
          {actions}
          <Button
            size="small"
            icon={motionEnabled ? <PauseOutlined /> : <CaretRightOutlined />}
            aria-label={t(
              motionEnabled ? "monitor.pauseMotion" : "monitor.playMotion",
            )}
            aria-pressed={motionEnabled}
            onClick={() => setMotionOverride(!motionEnabled)}
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
      {children(state)}
      <footer className="monitor-footer">
        <span>
          <i />
          {status(state)}
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
        <span>{sourceLabel}</span>
      </footer>
    </div>
  );
}
