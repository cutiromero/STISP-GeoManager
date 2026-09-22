import { Card, Space, Tag, Typography } from "antd";
import { EnvironmentOutlined, FileTextOutlined } from "@ant-design/icons";
import { useEnglishLanguage } from "../i18n/useEnglishLanguage";

export default function DataSchemaOverview({
  canBrowseData,
}: {
  canBrowseData: boolean;
}) {
  const english = useEnglishLanguage();
  if (!canBrowseData) return null;
  return (
    <Card
      style={{ marginBottom: 16 }}
      title={english ? "Data organization" : "数据组织方式"}
    >
      <Space wrap align="start" size={24}>
        <div>
          <Tag color="blue" icon={<EnvironmentOutlined />}>
            {english ? "Geographic data" : "地理数据"}
          </Tag>
          <Typography.Paragraph>
            {english
              ? "Vectors, rasters and tables with parsed coordinates."
              : "具有已解析地理坐标的矢量、栅格和坐标表格，可进入地理工作台。"}
          </Typography.Paragraph>
        </div>
        <div>
          <Tag color="cyan" icon={<FileTextOutlined />}>
            {english ? "Non-geographic data" : "非地理数据"}
          </Tag>
          <Typography.Paragraph>
            {english
              ? "Tables, documents and images without coordinates."
              : "没有地理坐标的表格、文档、图片等资料，可用于查阅与数据分析。"}
          </Typography.Paragraph>
        </div>
      </Space>
      <Typography.Text type="secondary">
        {english
          ? "Classification follows parsed coordinates. Project tags determine access."
          : "分类依据坐标解析结果自动确定。数据分类和资料夹用于组织资料，访问权限由项目标签决定。"}
      </Typography.Text>
    </Card>
  );
}
