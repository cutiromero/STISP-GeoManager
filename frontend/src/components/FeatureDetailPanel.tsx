import { AimOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Descriptions, Empty, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { FeatureInfo } from "../types";

interface Props {
  feature: FeatureInfo | null;
}

export default function FeatureDetailPanel({ feature }: Props) {
  const { t } = useTranslation();
  const entries = Object.entries(feature?.properties ?? {}).filter(
    ([, value]) => value !== undefined,
  );

  return (
    <section className="panel-section feature-detail-panel">
      <div className="panel-title">
        <InfoCircleOutlined style={{ fontSize: 18 }} />
        <Typography.Title level={5}>
          {t("map.featureInformation")}
        </Typography.Title>
      </div>
      {feature ? (
        <>
          <div className="feature-detail-heading">
            <AimOutlined style={{ fontSize: 15 }} />
            <Typography.Text strong>{feature.layerName}</Typography.Text>
            <Tag color="green">{t("map.clickSelected")}</Tag>
          </div>
          {entries.length > 0 ? (
            <Descriptions size="small" column={1} bordered>
              {entries.map(([key, value]) => (
                <Descriptions.Item key={key} label={key}>
                  {String(value ?? "-")}
                </Descriptions.Item>
              ))}
            </Descriptions>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("map.featureNoProperties")}
            />
          )}
        </>
      ) : (
        <Empty
          className="feature-detail-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("map.clickFeatureForProperties")}
        />
      )}
    </section>
  );
}
