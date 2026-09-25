import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { requestJson } from "../api/client";
import type {
  AccountAccess,
  AdminPermissionItem,
  ResearchApplicationRequest,
} from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";

export const readAccess = () => requestJson<AccountAccess>("/api/auth/access/");

export function OwnedPermissions({
  items,
  actions = [],
}: {
  items: AdminPermissionItem[];
  actions?: string[];
}) {
  const groups = [...new Set(items.map((p) => p.group))];
  return (
    <div className="account-owned-permissions">
      {groups.map((group) => (
        <section key={group} style={{ marginBottom: 16 }}>
          <Typography.Text strong>{group}</Typography.Text>
          <ul>
            {items
              .filter((p) => p.group === group)
              .map((p) => (
                <li key={p.id}>{p.label}</li>
              ))}
          </ul>
        </section>
      ))}
      {actions.length > 0 && (
        <ul>
          {actions.map((action) => (
            <li key={action}>{action}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LoginAccessNotice() {
  const { user } = useAppContext();
  const { i18n } = useTranslation();
  const en = i18n.language.startsWith("en");
  const [access, setAccess] = useState<AccountAccess | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!user || sessionStorage.getItem("show-account-access") !== "1") return;
    let active = true;
    sessionStorage.removeItem("show-account-access");
    setAccess(null);
    setError("");
    setOpen(true);
    readAccess()
      .then((value) => {
        if (active) setAccess(value);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [user?.id]);
  return (
    <Modal
      title={en ? "Your available features" : "当前账号可用功能"}
      open={open && !!user}
      onCancel={() => setOpen(false)}
      footer={
        <Button type="primary" onClick={() => setOpen(false)}>
          {en ? "Got it" : "我知道了"}
        </Button>
      }
      width={720}
    >
      <Typography.Paragraph>
        {en
          ? "These are your current tool and agent permissions. You can review them in your profile."
          : "以下是你当前可使用的工具和智能体功能，可在个人设置中随时查看。"}
      </Typography.Paragraph>
      {error && <Alert type="error" title={error} />}
      <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {access && (
          <OwnedPermissions
            items={access.permissions}
            actions={access.agentActions}
          />
        )}
      </div>
    </Modal>
  );
}

export function AccountAccessCard() {
  const { user, setUser } = useAppContext();
  const { i18n } = useTranslation();
  const en = i18n.language.startsWith("en");
  const [access, setAccess] = useState<AccountAccess | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [form] = Form.useForm<ResearchApplicationRequest>();
  async function refresh() {
    try {
      setAccess(await readAccess());
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    void refresh();
  }, [user?.id, en]);
  async function submit(values: ResearchApplicationRequest) {
    setBusy(true);
    setError("");
    try {
      const result = await requestJson<AccountAccess>(
        "/api/auth/research-application/",
        { method: "POST", body: values },
      );
      setAccess(result);
      setApplying(false);
      if (user)
        setUser({
          ...user,
          displayName: values.displayName,
          department: values.department,
        });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const status = access?.application?.status;
  return (
    <>
      <Card
        title={en ? "My available features" : "我的可用功能"}
        extra={<Button onClick={refresh}>{en ? "Refresh" : "刷新权限"}</Button>}
      >
        {error && <Alert type="error" title={error} />}
        {access && (
          <OwnedPermissions
            items={access.permissions}
            actions={access.agentActions}
          />
        )}
      </Card>
      {(access?.researchEligible || access?.application) && (
        <Card title={en ? "Research-user application" : "申请成为科研用户"}>
          {status && (
            <Alert
              type={
                status === "approved"
                  ? "success"
                  : status === "rejected"
                    ? "warning"
                    : "info"
              }
              title={
                status === "pending"
                  ? en
                    ? "Submitted — awaiting super administrator review"
                    : "已申请，等待超级管理员审核"
                  : status === "approved"
                    ? en
                      ? "Application approved"
                      : "申请已通过"
                    : en
                      ? "Application declined; you may revise and resubmit"
                      : "申请未通过，可修改后重新提交"
              }
              description={access?.application?.reviewNote}
            />
          )}
          {access?.researchEligible && (
            <>
              <Typography.Paragraph style={{ marginTop: 16 }}>
                {en
                  ? "After approval, the research role adds the following features under the current configuration:"
                  : "按当前角色配置，审核通过后将新增以下功能："}
              </Typography.Paragraph>
              {access.researchAdditionalPermissions.length ? (
                <Space wrap>
                  {access.researchAdditionalPermissions.map((p) => (
                    <Tag key={p.id}>{p.label}</Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Paragraph>
                  {en
                    ? "Your account already has the currently configured research features."
                    : "当前账号已具备科研角色现有的功能权限。"}
                </Typography.Paragraph>
              )}
              <Typography.Paragraph>
                {en
                  ? "Project data access is assigned separately. Agent features also follow the current service policy."
                  : "项目数据访问范围另行分配；智能体功能同时受当前服务策略控制。"}
              </Typography.Paragraph>
              <Button
                type="primary"
                disabled={status === "pending"}
                onClick={() => {
                  form.setFieldsValue({
                    displayName: user?.displayName,
                    department: user?.department,
                    reason: access.application?.reason ?? "",
                  });
                  setApplying(true);
                }}
              >
                {status === "pending"
                  ? en
                    ? "Application submitted"
                    : "已申请"
                  : en
                    ? "Apply for research access"
                    : "申请成为科研用户"}
              </Button>
            </>
          )}
        </Card>
      )}
      <Modal
        title={en ? "Research-user application" : "科研用户申请"}
        open={applying}
        onCancel={() => setApplying(false)}
        onOk={() => form.submit()}
        confirmLoading={busy}
        okText={en ? "Submit application" : "提交申请"}
        cancelText={en ? "Cancel" : "取消"}
      >
        {error && <Alert type="error" title={error} />}
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item
            name="displayName"
            label={en ? "Name" : "姓名"}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={150} />
          </Form.Item>
          <Form.Item
            name="department"
            label={en ? "Affiliation" : "单位或部门"}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item
            name="reason"
            label={en ? "Research needs" : "科研需求和申请说明"}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input.TextArea maxLength={2000} rows={4} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
