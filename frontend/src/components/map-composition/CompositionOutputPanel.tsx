import { Alert, Button, Input, Select, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { CompositionIssue } from "../../map-composition/render";

interface Props {
  issues: CompositionIssue[];
  format: "png" | "jpg" | "pdf";
  note: string;
  canExport: boolean;
  exporting: boolean;
  disabled: boolean;
  onFormatChange: (format: "png" | "jpg" | "pdf") => void;
  onNoteChange: (note: string) => void;
  onGenerate: () => void;
}

export default function CompositionOutputPanel({
  issues,
  format,
  note,
  canExport,
  exporting,
  disabled,
  onFormatChange,
  onNoteChange,
  onGenerate,
}: Props) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  return (
    <aside className="map-composition-output-pane">
      <Typography.Title level={5}>
        {english ? "Output checks" : "出图检查"}
      </Typography.Title>
      <div className="composition-issues">
        {issues.length === 0 ? (
          <Alert
            type="success"
            showIcon
            title={english ? "Layout checks passed" : "版式检查通过"}
          />
        ) : (
          issues.map((issue) => (
            <Alert
              key={issue.message}
              type={issue.level}
              showIcon
              title={issue.message}
            />
          ))
        )}
      </div>
      <Typography.Title level={5}>
        {english ? "Generate thematic result" : "生成专题成果"}
      </Typography.Title>
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Select
          value={format}
          style={{ width: "100%" }}
          options={[
            { label: english ? "PDF for print" : "PDF 正式打印", value: "pdf" },
            {
              label: english ? "PNG lossless image" : "PNG 无损图片",
              value: "png",
            },
            {
              label: english ? "JPG compressed image" : "JPG 压缩图片",
              value: "jpg",
            },
          ]}
          onChange={onFormatChange}
        />
        <Input.TextArea
          rows={3}
          value={note}
          placeholder={english ? "Version note (optional)" : "版本说明（可选）"}
          onChange={(event) => onNoteChange(event.target.value)}
        />
        <Tag color={canExport ? "green" : "default"}>
          {canExport
            ? english
              ? "Result export permitted"
              : "具备成果导出权限"
            : english
              ? "Result export not permitted"
              : "没有成果导出权限"}
        </Tag>
        <Button
          block
          type="primary"
          disabled={!canExport || disabled}
          loading={exporting}
          onClick={onGenerate}
        >
          {english ? "Generate and download" : "生成并下载"}{" "}
          {format.toUpperCase()}
        </Button>
      </Space>
    </aside>
  );
}
