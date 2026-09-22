import {
  AlertOutlined,
  BellOutlined,
  CloudOutlined,
  RadarChartOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { Layout, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import warningPoplarMountainAerialImage from "../assets/portal/warning-poplar-mountain-aerial.png";
import WorkspaceHeader from "../components/WorkspaceHeader";
import { useAppContext } from "../contexts/AppContext";

export default function WarningPage() {
  const { user } = useAppContext();
  const { t } = useTranslation();
  const plannedCapabilities: Array<{
    icon: ReactNode;
    title: string;
    description: string;
  }> = [
    {
      icon: <RadarChartOutlined />,
      title: t("warning.remoteSensingTitle"),
      description: t("warning.remoteSensingDescription"),
    },
    {
      icon: <CloudOutlined />,
      title: t("warning.climateTitle"),
      description: t("warning.climateDescription"),
    },
    {
      icon: <BellOutlined />,
      title: t("warning.responseTitle"),
      description: t("warning.responseDescription"),
    },
    {
      icon: <SafetyCertificateOutlined />,
      title: t("warning.governanceTitle"),
      description: t("warning.governanceDescription"),
    },
  ];

  return (
    <Layout className="portal-shell warning-page-shell">
      <WorkspaceHeader
        activeTab="warning"
        canBrowseData={Boolean(user?.permissions.canBrowseData)}
      />
      <main className="portal-content-page warning-page">
        <section
          className="portal-hero warning-page-hero"
          style={{
            backgroundImage: `linear-gradient(90deg, rgba(5, 29, 33, 0.95) 0%, rgba(8, 39, 43, 0.78) 42%, rgba(9, 31, 36, 0.38) 72%, rgba(4, 23, 29, 0.58) 100%), url(${warningPoplarMountainAerialImage})`,
          }}
        >
          <div>
            <Tag color="gold">{t("warning.phaseTwo")}</Tag>
            <Typography.Title level={1}>{t("warning.title")}</Typography.Title>
            <Typography.Paragraph>{t("warning.summary")}</Typography.Paragraph>
          </div>
          <AlertOutlined aria-hidden="true" />
        </section>

        <section className="warning-capability-grid">
          {plannedCapabilities.map((capability) => (
            <article key={capability.title}>
              <span>{capability.icon}</span>
              <Typography.Title level={3}>{capability.title}</Typography.Title>
              <Typography.Paragraph>
                {capability.description}
              </Typography.Paragraph>
            </article>
          ))}
        </section>

        <section className="warning-roadmap">
          <div>
            <span>01</span>
            <strong>{t("warning.step1Title")}</strong>
            <small>{t("warning.step1Description")}</small>
          </div>
          <div>
            <span>02</span>
            <strong>{t("warning.step2Title")}</strong>
            <small>{t("warning.step2Description")}</small>
          </div>
          <div>
            <span>03</span>
            <strong>{t("warning.step3Title")}</strong>
            <small>{t("warning.step3Description")}</small>
          </div>
        </section>
      </main>
    </Layout>
  );
}
