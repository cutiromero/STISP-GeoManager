import {
  BellOutlined,
  CheckOutlined,
  CloseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Badge,
  Button,
  Drawer,
  Empty,
  Pagination,
  Segmented,
  Space,
  Spin,
  Tag,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { sharingApi, type ShareInvitation } from "../api/sharing";
import type { ShareInvitationList } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import { createUuid } from "../utils/uuid";
import {
  invitationsChanged,
  notifyInvitationsChanged,
  safeSharePath,
  useShareText,
} from "./shareUi";
import { parseShareList } from "./shareResponses";
import "./sharing.css";

type Box = "received" | "sent";
const pageSize = 12;

export default function InvitationCenter() {
  const ui = useShareText();
  const { user } = useAppContext();
  const signedIn = Boolean(
    user && user.username !== "guest" && !user.roles?.includes("游客"),
  );
  const project = useProjectContext();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<Box>("received");
  const [lists, setLists] = useState<Partial<Record<Box, ShareInvitationList>>>(
    {},
  );
  const [pages, setPages] = useState<Record<Box, number>>({
    received: 1,
    sent: 1,
  });
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<Box, string>>>({});
  const [busy, setBusy] = useState<number[]>([]);
  const generation = useRef(0);
  const busyRef = useRef(new Set<number>());
  const refreshing = useRef<Partial<Record<Box, number>>>({});
  const requests = useRef<Record<Box, number>>({ received: 0, sent: 0 });
  const pageRef = useRef(pages);
  pageRef.current = pages;

  const refresh = useCallback(
    async (selected: Box) => {
      if (!signedIn) return;
      const offset = (pageRef.current[selected] - 1) * pageSize;
      if (refreshing.current[selected] === offset) return;
      const current = generation.current;
      const token = ++requests.current[selected];
      refreshing.current[selected] = offset;
      try {
        const data = parseShareList(
          await sharingApi.list(selected, offset, pageSize),
        );
        if (
          current !== generation.current ||
          token !== requests.current[selected]
        )
          return;
        setLists((prior) => ({ ...prior, [selected]: data }));
        setErrors((prior) => ({ ...prior, [selected]: "" }));
      } catch (reason) {
        if (
          current === generation.current &&
          token === requests.current[selected] &&
          reason instanceof Error &&
          reason.name !== "AbortError"
        )
          setErrors((prior) => ({ ...prior, [selected]: reason.message }));
      } finally {
        if (
          current === generation.current &&
          token === requests.current[selected]
        )
          delete refreshing.current[selected];
      }
    },
    [user?.id, signedIn],
  );

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([refresh("received"), refresh("sent")]);
    setLoading(false);
  }, [refresh]);

  useEffect(() => {
    generation.current += 1;
    refreshing.current = {};
    busyRef.current.clear();
    setBusy([]);
    pageRef.current = { received: 1, sent: 1 };
    setPages(pageRef.current);
    setLists({});
    setErrors({});
    if (!signedIn) return;
    void refreshAll();
    const recheck = () => {
      if (document.visibilityState === "visible") void refreshAll();
    };
    const timer = window.setInterval(recheck, 60_000);
    window.addEventListener("focus", recheck);
    window.addEventListener(invitationsChanged, recheck);
    return () => {
      generation.current += 1;
      window.clearInterval(timer);
      window.removeEventListener("focus", recheck);
      window.removeEventListener(invitationsChanged, recheck);
    };
  }, [refreshAll, user?.id, signedIn]);

  async function act(
    invitation: ShareInvitation,
    operation: () => Promise<unknown>,
  ) {
    if (busyRef.current.has(invitation.id)) return;
    busyRef.current.add(invitation.id);
    setBusy([...busyRef.current]);
    try {
      await operation();
      notifyInvitationsChanged();
    } catch (reason) {
      message.error(
        reason instanceof Error
          ? reason.message
          : ui("操作失败，请重试", "Action failed. Try again."),
      );
    } finally {
      busyRef.current.delete(invitation.id);
      setBusy([...busyRef.current]);
    }
  }

  async function respond(
    invitation: ShareInvitation,
    decision: "accept" | "reject",
  ) {
    const current = generation.current;
    const updated = await sharingApi.respond(
      invitation.id,
      decision,
      createUuid(),
    );
    if (current !== generation.current) return;
    setLists((prior) => ({
      ...prior,
      received: prior.received
        ? {
            ...prior.received,
            items: prior.received.items.map((item) =>
              item.id === updated.id ? updated : item,
            ),
          }
        : undefined,
    }));
    message.success(
      updated.detail ||
        (decision === "accept"
          ? ui("已接受分享，可点击打开", "Share accepted. You can now open it.")
          : ui(
              "已拒绝分享，对方会收到通知",
              "Share rejected. The sender will be notified.",
            )),
    );
  }

  async function openInvitation(invitation: ShareInvitation) {
    const current = generation.current;
    const data = await sharingApi.open(invitation.id);
    if (current !== generation.current) return;
    const path = safeSharePath(data.target.openUrl);
    if (!path)
      throw new Error(
        ui(
          "分享入口不可用，请联系管理员",
          "The share link is unavailable. Contact an administrator.",
        ),
      );
    const go = () => {
      setOpen(false);
      navigate(path);
    };
    if (project && String(data.target.projectTagId) !== project.current)
      project.choose(String(data.target.projectTagId), go);
    else go();
  }

  if (!signedIn) return null;
  const list = lists[box];
  const unread =
    (lists.received?.unreadCount ?? 0) + (lists.sent?.unreadCount ?? 0);
  const label = (invitation: ShareInvitation) =>
    ({
      pending: ui("等待接受", "Awaiting response"),
      accepted: ui("已接受", "Accepted"),
      rejected: ui("已拒绝", "Declined"),
      unavailable: ui("已不可用", "Unavailable"),
    })[invitation.status];

  return (
    <>
      <Badge count={unread} size="small" overflowCount={99}>
        <Button
          className="share-center-trigger"
          type="text"
          icon={<BellOutlined />}
          title={ui("分享通知", "Share notifications")}
          aria-label={ui("分享通知", "Share notifications")}
          onClick={() => {
            setOpen(true);
            void refreshAll();
          }}
        />
      </Badge>
      <Drawer
        title={ui("分享通知", "Share notifications")}
        open={open}
        onClose={() => setOpen(false)}
        size={620}
      >
        <div className="share-center-toolbar">
          <Segmented<Box>
            value={box}
            onChange={setBox}
            options={[
              { value: "received", label: ui("收到的邀请", "Received") },
              { value: "sent", label: ui("我发出的邀请", "Sent") },
            ]}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            aria-label={ui("刷新分享通知", "Refresh share notifications")}
            onClick={() => void refreshAll()}
          />
        </div>
        {errors[box] && (
          <Alert
            type="error"
            showIcon
            title={errors[box]}
            style={{ marginBottom: 16 }}
          />
        )}
        <Spin spinning={loading && !list}>
          {!list?.items.length ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={ui("暂无分享邀请", "No share invitations")}
            />
          ) : (
            <div className="share-center-list">
              {list.items.map((invitation) => {
                const other =
                  box === "received" ? invitation.sender : invitation.recipient;
                const working = busy.includes(invitation.id);
                return (
                  <article
                    className={`share-invitation${invitation.unread ? " is-unread" : ""}`}
                    key={invitation.id}
                  >
                    <div className="share-invitation-header">
                      <div className="share-invitation-heading">
                        <strong>{invitation.target.name}</strong>
                        <small>
                          {box === "received"
                            ? ui("来自", "From")
                            : ui("发给", "To")}{" "}
                          {other.displayName || other.username} (
                          {other.username})
                        </small>
                        <small>{invitation.target.projectName}</small>
                      </div>
                      <Tag
                        color={
                          {
                            pending: "blue",
                            accepted: "success",
                            rejected: "default",
                            unavailable: "warning",
                          }[invitation.status]
                        }
                      >
                        {label(invitation)}
                      </Tag>
                    </div>
                    <div className="share-invitation-detail">
                      {invitation.detail ||
                        ui(
                          "接受后可只读查看分享内容。",
                          "Accept to view the shared item in read-only mode.",
                        )}
                    </div>
                    <div className="share-invitation-footer">
                      <span className="share-invitation-time">
                        {new Date(
                          invitation.respondedAt || invitation.createdAt,
                        ).toLocaleString()}
                      </span>
                      <Space wrap size={6}>
                        {box === "received" && invitation.canRespond && (
                          <>
                            <Button
                              size="small"
                              disabled={working}
                              icon={<CloseOutlined />}
                              aria-label={ui("拒绝", "Decline")}
                              onClick={() =>
                                void act(invitation, () =>
                                  respond(invitation, "reject"),
                                )
                              }
                            >
                              {ui("拒绝", "Decline")}
                            </Button>
                            <Button
                              size="small"
                              type="primary"
                              disabled={working}
                              icon={<CheckOutlined />}
                              aria-label={ui("接受分享", "Accept")}
                              onClick={() =>
                                void act(invitation, () =>
                                  respond(invitation, "accept"),
                                )
                              }
                            >
                              {ui("接受分享", "Accept")}
                            </Button>
                          </>
                        )}
                        {invitation.status === "accepted" && (
                          <Button
                            size="small"
                            type="primary"
                            aria-label={ui("打开", "Open")}
                            disabled={working}
                            onClick={() =>
                              void act(invitation, () =>
                                openInvitation(invitation),
                              )
                            }
                          >
                            {ui("打开", "Open")}
                          </Button>
                        )}
                        {invitation.unread && (
                          <Button
                            type="text"
                            size="small"
                            aria-label={ui("标为已读", "Mark read")}
                            disabled={working}
                            onClick={() =>
                              void act(invitation, () =>
                                sharingApi.read(invitation.id),
                              )
                            }
                          >
                            {ui("标为已读", "Mark read")}
                          </Button>
                        )}
                      </Space>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </Spin>
        {(list?.total ?? 0) > pageSize && (
          <div className="share-center-pagination">
            <Pagination
              size="small"
              current={pages[box]}
              total={list?.total}
              pageSize={pageSize}
              showSizeChanger={false}
              onChange={(page) => {
                pageRef.current = { ...pageRef.current, [box]: page };
                setPages(pageRef.current);
                void refresh(box);
              }}
            />
          </div>
        )}
      </Drawer>
    </>
  );
}
