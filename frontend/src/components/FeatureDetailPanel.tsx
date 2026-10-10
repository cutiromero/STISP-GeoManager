import { AimOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Descriptions, Empty, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { FeatureInfo } from "../types";

interface Props {
  feature: FeatureInfo | null;
}

const priorityFieldLabels: Record<string, readonly [string, string]> = {
  change_old: ["修改前值", "Previous value"],
  change_new: ["修改后值", "Updated value"],
  change_reason: ["修改原因", "Reason for change"],
  change_evidence: ["修改依据", "Change evidence"],
  check_status: ["检查状态", "Check status"],
  change_fields: ["修改字段", "Changed fields"],
  priority_class: ["调查优先类别", "Survey priority class"],
  priority_rank: ["调查优先顺序", "Survey priority rank"],
  reason: ["判断原因", "Reason"],
  evidence_sources: ["证据来源", "Evidence sources"],
  coverage: ["有效覆盖比例", "Valid coverage fraction"],
  mean_change: ["平均变化值", "Mean change"],
  decline_fraction: ["下降面积占比", "Declining area fraction"],
};
const priorityFieldOrder = new Map(
  Object.keys(priorityFieldLabels).map((key, index) => [key, index]),
);

export default function FeatureDetailPanel({ feature }: Props) {
  const { t, i18n } = useTranslation();
  const english = (i18n.resolvedLanguage ?? i18n.language)
    .toLowerCase()
    .startsWith("en");
  const entries = Object.entries(feature?.properties ?? {})
    .filter(([, value]) => value !== undefined)
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
