import { useAuditText } from "../i18n/auditUi";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { useProjectContext } from "../projects/ProjectContext";
import { platformApi, type ProjectTag } from "../api/platform";
import { api } from "../api/client";
import type { User } from "../types";

export default function ProjectManagementPage() {
  const ui = useAuditText();
  const context = useProjectContext();
  const { message, modal } = App.useApp();
  const [form] = Form.useForm();
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserId] = useState<number>();
  const [ids, setIds] = useState<number[]>([]);
  const selectionSequence = useRef(0);
  const [loadingAssignment, setLoadingAssignment] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (context?.canAssign)
      void api
        .adminUsers()
        .then((r) => setUsers(r.items))
        .catch((e) => message.error(e.message));
  }, [context?.canAssign, message]);
  async function chooseUser(id: number) {
    const sequence = ++selectionSequence.current;
    setUserId(id);
    setIds([]);
    setLoadingAssignment(true);
    try {
      const result = await platformApi.assignment(id);
      if (sequence === selectionSequence.current) setIds(result.projectIds);
    } catch (e) {
      if (sequence === selectionSequence.current) {
        setUserId(undefined);
        message.error(String(e));
      }
    } finally {
      if (sequence === selectionSequence.current) setLoadingAssignment(false);
    }
  }
  async function toggle(p: ProjectTag, isActive: boolean) {
    try {
      await platformApi.updateProject(p.id, { name: p.name, isActive });
      await context?.refresh();
    } catch (e) {
      message.error(String(e));
    }
  }
  return (
    <div className="admin-page-stack">
      <Typography.Title level={2}>{ui("项目标签管理")}</Typography.Title>
      <Typography.Paragraph type="secondary">
        {ui(
          "公开项目向所有人开放。项目标签由超管设置，用户的项目访问范围由超管分配。",
        )}
      </Typography.Paragraph>
      {!context?.canAssign ? (
        <Card>{ui("当前账号没有标签管理权限。")}</Card>
      ) : (
        <>
          <Table
            rowKey="id"
            pagination={false}
            dataSource={context.assignableProjects}
            columns={[
              { title: ui("项目标签"), dataIndex: "name" },
              { title: ui("编码"), dataIndex: "code" },
              { title: ui("说明"), dataIndex: "description" },
              {
                title: ui("维护"),
                render: (_, p) => (
                  <Button
                    disabled={!context.canManage || p.isDefault}
                    onClick={() => {
                      let values = {
                        name: p.name,
                        description: p.description,
                        sortOrder: p.sortOrder,
                      };
                      modal.confirm({
                        title: ui("编辑项目标签"),
                        content: (
                          <Space orientation="vertical">
                            <Typography.Text type="secondary">
                              {ui("编码")}：{p.code} ·{" "}
                              {ui(
                                "项目编码创建后不可修改；可修改项目名称和说明。",
                              )}
                            </Typography.Text>
                            <Input
                              defaultValue={p.name}
                              onChange={(e) => {
                                values.name = e.target.value;
                              }}
                            />
                            <Input.TextArea
                              defaultValue={p.description}
                              onChange={(e) => {
                                values.description = e.target.value;
                              }}
                            />
                            <InputNumber
                              defaultValue={p.sortOrder}
                              onChange={(v) => {
                                if (v !== null) values.sortOrder = v;
                              }}
                            />
                          </Space>
                        ),
                        onOk: async () => {
                          await platformApi.updateProject(p.id, values);
                          await context.refresh();
                        },
                      });
                    }}
                  >
                    {ui("编辑")}
                  </Button>
                ),
              },
              {
                title: ui("启用"),
                render: (_, p) => (
                  <Switch
                    checked={p.isActive}
                    disabled={!context.canManage || p.isDefault}
                    onChange={(v) => void toggle(p, v)}
                  />
                ),
              },
            ]}
          />
          {context.canManage && (
            <Card title={ui("新建项目标签")} style={{ marginTop: 20 }}>
              <Form
                form={form}
                layout="inline"
                onFinish={async (values) => {
                  setSaving(true);
                  try {
                    await platformApi.createProject(values);
                    form.resetFields();
                    await context.refresh();
                    message.success(ui("项目已创建"));
                  } catch (e) {
                    message.error(String(e));
                  } finally {
                    setSaving(false);
                  }
                }}
              >
                <Form.Item name="name" rules={[{ required: true }]}>
                  <Input placeholder={ui("项目名称")} maxLength={120} />
                </Form.Item>
                <Form.Item
                  name="code"
                  rules={[{ required: true, pattern: /^[a-zA-Z0-9_-]+$/ }]}
                >
                  <Input placeholder={ui("英文或数字编码")} />
                </Form.Item>
                <Form.Item name="description">
                  <Input placeholder={ui("项目说明")} />
                </Form.Item>
                <Form.Item name="sortOrder" initialValue={100}>
                  <InputNumber aria-label={ui("排序")} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={saving}>
                  {ui("创建标签")}
                </Button>
              </Form>
            </Card>
          )}
          <Card title={ui("分配用户标签")} style={{ marginTop: 20 }}>
            <Space wrap>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder={ui("选择用户")}
                style={{ width: 220 }}
                value={userId}
                onChange={(id) => void chooseUser(id)}
                options={users.map((u) => ({
                  value: u.id,
                  label: u.username,
                }))}
              />
              <Select
                mode="multiple"
                disabled={!userId || loadingAssignment || saving}
                placeholder={ui("选择私有项目标签")}
                style={{ minWidth: 360 }}
                value={ids}
                onChange={setIds}
                options={context.assignableProjects
                  .filter((p) => !p.isDefault && p.isActive)
                  .map((p) => ({ value: p.id, label: p.name }))}
              />
              <Button
                type="primary"
                disabled={!userId || loadingAssignment || saving}
                onClick={async () => {
                  if (!userId) return;
                  try {
                    setSaving(true);
                    await platformApi.assign(userId, ids);
                    await context.refresh();
                    message.success(ui("标签分配已保存"));
                    setSaving(false);
                  } catch (e) {
                    message.error(String(e));
                    setSaving(false);
                  }
                }}
              >
                {ui("保存分配")}
              </Button>
            </Space>
            <p>
              {ui(
                "公开项目自动可读，无需分配。超级管理员始终拥有全部项目权限。",
              )}
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
