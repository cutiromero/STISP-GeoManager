import {
  CheckCircleOutlined,
  StopOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { BorderBeam, Card, Col, Row, Statistic, Typography } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { oceanBorderBeam } from "../components/oceanBorderBeam";

export type UserSummaryMetrics = {
  active: number;
  disabled: number;
  groups: number;
};

export function UserSummaryCards({ metrics }: { metrics: UserSummaryMetrics }) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  return (
    <Row gutter={[16, 16]}>
      <UserSummaryCard
        title={english ? "Active accounts" : "启用账号"}
        value={metrics.active}
        suffix={english ? "" : "个"}
        icon={<CheckCircleOutlined />}
        description={
          english ? "Accounts that can sign in" : "当前可登录平台的账号"
        }
      />
      <UserSummaryCard
        title={english ? "Disabled accounts" : "停用账号"}
        value={metrics.disabled}
        suffix={english ? "" : "个"}
        icon={<StopOutlined />}
        description={
          english ? "Accounts blocked from signing in" : "已禁止登录的平台账号"
        }
      />
      <UserSummaryCard
        title={english ? "Roles" : "角色数量"}
        value={metrics.groups}
        suffix={english ? "" : "个"}
        icon={<TeamOutlined />}
        description={
          english
            ? "Permission roles available for assignment"
            : "当前可分配的权限角色"
        }
      />
    </Row>
  );
}

function UserSummaryCard({
  title,
  value,
  suffix,
  icon,
  description,
}: {
  title: string;
  value: number;
  suffix: string;
  icon: ReactNode;
  description: string;
}) {
  return (
    <Col xs={24} sm={12} xl={8}>
      <BorderBeam color={oceanBorderBeam}>
        <Card className="admin-dashboard-metric" variant="borderless">
          <div className="admin-dashboard-metric-icon">{icon}</div>
          <Statistic title={title} value={value} suffix={suffix} />
          <Typography.Text type="secondary">{description}</Typography.Text>
        </Card>
      </BorderBeam>
    </Col>
  );
}
