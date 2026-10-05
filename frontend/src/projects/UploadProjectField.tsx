import { Alert, Form, Select, Space, Typography } from "antd";
import { useProjectContext } from "./ProjectContext";
import { useEnglishLanguage, localText } from "../i18n/useEnglishLanguage";

/** Upload destination is deliberately independent of the browsing project. */
export function UploadProjectField({
  value,
  onChange,
  locked,
}: {
  value: number;
  onChange: (value: number) => void;
  locked: boolean;
}) {
  const context = useProjectContext();
  const english = useEnglishLanguage();
  const l = (zh: string, en: string) => localText(english, zh, en);
  const projects = context?.projects ?? [
    { id: 1, name: "公开", isActive: true },
  ];
  const valid = projects.some((project) => project.id === value);
  return (
    <div className="admin-section-card" style={{ padding: 20 }}>
      <Form layout="vertical" component={false}>
        <Form.Item
          label={l("所属项目标签", "Destination project tag")}
          required
          validateStatus={valid ? undefined : "error"}
          help={
            !valid
              ? l(
                  "该项目已不可访问，请重新选择文件和项目。",
                  "This project is no longer accessible. Choose a project and file again.",
                )
              : undefined
          }
        >
          <Select
            aria-label={l("所属项目标签", "Destination project tag")}
            value={value}
            onChange={onChange}
            disabled={locked || !projects.length}
            style={{ width: "100%", maxWidth: 420 }}
            showSearch
            optionFilterProp="label"
            options={projects.map((project) => ({
              value: project.id,
              label: `${project.name}${project.isActive ? "" : "（停用）"}`,
            }))}
          />
        </Form.Item>
      </Form>
      <Space orientation="vertical" style={{ width: "100%" }}>
        {locked && (
          <Typography.Text type="secondary">
            {l(
              "重新选择文件后可修改所属项目。",
              "Reset the selected file to change its project.",
            )}
          </Typography.Text>
        )}
        <Alert
          showIcon
          type={value === 1 ? "warning" : "info"}
          title={
            value === 1
              ? l(
                  "公开项目：所有人可访问。请确认这份数据可以公开。",
                  "Public project: accessible to everyone. Confirm this data can be public.",
                )
              : l(
                  "仅该项目成员和超管可访问。",
                  "Only project members and super admins can access it.",
                )
          }
        />
      </Space>
    </div>
  );
}
