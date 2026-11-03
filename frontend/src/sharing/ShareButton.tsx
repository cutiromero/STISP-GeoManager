import { ShareAltOutlined, UserOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { sharingApi, type ShareKind } from "../api/sharing";
import type { ShareCheckResponse } from "../api/generated/types.gen";
import { createUuid } from "../utils/uuid";
import { notifyInvitationsChanged, useShareText } from "./shareUi";
import "./sharing.css";

export default function ShareButton({
  kind,
  objectId,
  name,
  disabled = false,
  type = "default",
}: {
  kind: ShareKind;
  objectId: number;
  name: string;
  disabled?: boolean;
  type?: "default" | "link";
}) {
  const ui = useShareText();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size="small"
        type={type}
        icon={<ShareAltOutlined />}
        disabled={disabled}
        aria-label={ui(`分享${name}`, `Share ${name}`)}
        onClick={() => setOpen(true)}
      >
        {ui("分享", "Share")}
      </Button>
      {open && (
        <ShareDialog
          kind={kind}
          objectId={objectId}
          name={name}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ShareDialog({
  kind,
  objectId,
  name,
  onClose,
}: {
  kind: ShareKind;
  objectId: number;
  name: string;
  onClose: () => void;
}) {
  const ui = useShareText();
  const { message } = App.useApp();
  const [username, setUsername] = useState("");
  const [checked, setChecked] = useState<ShareCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const lock = useRef(false);
  const alive = useRef(true);
  const requestKey = useRef(createUuid());
  const exactName = username.trim();
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current += 1;
    };
  }, []);

  async function check() {
    if (!exactName) return;
    const token = ++sequence.current;
    setChecking(true);
    setChecked(null);
    setError("");
    try {
      const data = await sharingApi.check(kind, objectId, exactName);
      if (alive.current && sequence.current === token) setChecked(data);
    } catch (reason) {
      if (alive.current && sequence.current === token)
        setError(
          reason instanceof Error
            ? reason.message
            : ui("无法核验接收方", "Unable to verify recipient"),
        );
    } finally {
      if (alive.current && sequence.current === token) setChecking(false);
    }
  }

  async function send() {
    if (!checked?.eligible || checking || lock.current) return;
    lock.current = true;
    setSending(true);
    setError("");
    try {
      const invitation = await sharingApi.invite(
        kind,
        objectId,
        exactName,
        requestKey.current,
      );
      notifyInvitationsChanged();
      if (!alive.current) return;
      message.success(
        invitation.status === "accepted"
          ? ui(
              "该用户已接受此分享，可在分享通知中查看",
              "This recipient has already accepted the share",
            )
          : ui(
              `邀请已发给 ${invitation.recipient.displayName || invitation.recipient.username}，等待对方接受`,
              `Invitation sent to ${invitation.recipient.displayName || invitation.recipient.username}`,
            ),
      );
      onClose();
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error
            ? reason.message
            : ui("邀请发送失败", "Unable to send invitation"),
        );
    } finally {
      lock.current = false;
      if (alive.current) setSending(false);
    }
  }

  return (
    <Modal
      open
      title={ui("邀请分享", "Invite to view")}
      width={480}
      className="share-invite-modal"
      onCancel={() => {
        if (!sending) onClose();
      }}
      closable={!sending}
      mask={{ closable: !sending }}
      footer={[
        <Button
          key="cancel"
          disabled={sending}
          onClick={onClose}
          aria-label={ui("取消", "Cancel")}
        >
          {ui("取消", "Cancel")}
        </Button>,
        <Button
          key="send"
          type="primary"
          loading={sending}
          aria-label={ui("发送邀请", "Send invitation")}
          disabled={!checked?.eligible || checking}
          onClick={() => void send()}
        >
          {ui("发送邀请", "Send invitation")}
        </Button>,
      ]}
    >
      <div className="share-invite-target">
        <ShareAltOutlined />
        <div>
          <strong>{name}</strong>
          <span>
            {ui("对方接受后可只读查看", "Read-only access after acceptance")}
          </span>
        </div>
      </div>
      <Form layout="vertical" requiredMark={false}>
        <Form.Item
          label={ui("接收方用户名", "Recipient username")}
          extra={ui(
            "填写完整登录用户名，先核验权限，再发送邀请。",
            "Enter the exact sign-in username and verify access before sending.",
          )}
        >
          <Space.Compact className="share-recipient-input">
            <Input
              prefix={<UserOutlined />}
              autoComplete="off"
              placeholder={ui("请输入完整用户名", "Exact username")}
              aria-label={ui("接收方用户名", "Recipient username")}
              value={username}
              disabled={sending}
              onChange={(event) => {
                sequence.current += 1;
                setUsername(event.target.value);
                setChecked(null);
                setChecking(false);
                setError("");
                requestKey.current = createUuid();
              }}
              onPressEnter={() => {
                if (!checking && !sending) void check();
              }}
            />
            <Button
              loading={checking}
              aria-label={ui("核验", "Verify")}
              disabled={!exactName || sending}
              onClick={() => void check()}
            >
              {ui("核验", "Verify")}
            </Button>
          </Space.Compact>
        </Form.Item>
      </Form>
      {checked && (
        <Alert
          showIcon
          type={checked.eligible ? "success" : "warning"}
          title={
            checked.eligible
              ? ui(
                  `可邀请 ${checked.recipient?.displayName || checked.recipient?.username || exactName}`,
                  `Ready to invite ${checked.recipient?.displayName || exactName}`,
                )
              : ui("暂时无法分享", "Sharing unavailable")
          }
          description={checked.detail}
        />
      )}
      {error && <Alert showIcon type="error" title={error} />}
      <Typography.Paragraph type="secondary" className="share-invite-note">
        {ui(
          "邀请不会替对方确认，也不会授予项目管理或编辑权限。",
          "The recipient decides whether to accept. Project management and editing permissions are unchanged.",
        )}
      </Typography.Paragraph>
    </Modal>
  );
}
