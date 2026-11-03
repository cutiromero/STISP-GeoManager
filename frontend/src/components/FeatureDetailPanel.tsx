import { AimOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Descriptions, Empty, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { FeatureInfo } from "../types";
import { isHiddenField, priorityFieldLabels } from "../map/featureFields";

interface Props {
  feature: FeatureInfo | null;
}

const priorityFieldOrder = new Map(
  Object.keys(priorityFieldLabels).map((key, index) => [key, index]),
);

export default function FeatureDetailPanel({ feature }: Props) {
  const { t, i18n } = useTranslation();
  const english = (i18n.resolvedLanguage ?? i18n.language)
    .toLowerCase()
    .startsWith("en");
  const entries = Object.entries(feature?.properties ?? {})
    .filter(([key, value]) => value !== undefined && !isHiddenField(key))
    .sort(
      ([left], [right]) =>
        (priorityFieldOrder.get(left) ?? priorityFieldOrder.size) -
        (priorityFieldOrder.get(right) ?? priorityFieldOrder.size),
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
                <Descriptions.Item
                  key={key}
                  label={priorityFieldLabels[key]?.[english ? 1 : 0] ?? key}
                >
                  <span className="feature-detail-value">
                    {String(value ?? "-")}
                  </span>
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
