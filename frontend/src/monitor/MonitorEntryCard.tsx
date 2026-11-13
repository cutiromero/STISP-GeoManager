import { ArrowRightOutlined, GlobalOutlined } from "@ant-design/icons";
import { Button, Card, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { monitorPath, useMonitorProject } from "./project";
import "./monitor-entry.css";

export default function MonitorEntryCard() {
  const project = useMonitorProject();
  const { t } = useTranslation();
  const navigate = useNavigate();
  if (!project) return null;
  const open = () => navigate(monitorPath);
  return (
    <Card className="monitor-entry" onClick={open}>
      <div className="monitor-entry-content">
        <GlobalOutlined className="monitor-entry-icon" />
        <div className="monitor-entry-copy">
          <Tag color="cyan">
            {t(
              project.monitorConfig?.source === "remote_sensing_products" ||
                project.monitorConfig?.scenes?.length
                ? "remoteMonitor.entryTag"
                : "monitor.entryTag",
            )}
          </Tag>
          <h2>{t("monitor.entryTitle")}</h2>
          <p>{project.monitorConfig?.title ?? t("monitor.notConfigured")}</p>
        </div>
        <Button
          type="primary"
          size="large"
          icon={<ArrowRightOutlined />}
          onClick={(event) => {
            event.stopPropagation();
            open();
          }}
        >
          {t("monitor.enter")}
        </Button>
      </div>
    </Card>
  );
}
