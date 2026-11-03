import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { StrictMode, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ShareCheckResponse,
  ShareInvitation,
} from "../api/generated/types.gen";
import InvitationCenter from "./InvitationCenter";
import ShareButton from "./ShareButton";
import {
  shareCheck,
  shareInvitation,
  shareList,
  shareTarget,
} from "./sharingTestFixtures";

const mocks = vi.hoisted(() => ({
  check: vi.fn(),
  invite: vi.fn(),
  list: vi.fn(),
  respond: vi.fn(),
  read: vi.fn(),
  open: vi.fn(),
  choose: vi.fn(),
}));
vi.mock("../api/sharing", () => ({ sharingApi: mocks }));
vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => ({ user: { id: 1 } }),
}));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({ current: "1", choose: mocks.choose }),
}));

function Location() {
  const location = useLocation();
  return (
    <span data-testid="location">
      {location.pathname}
      {location.search}
    </span>
  );
}
function show(children: ReactNode, strict = false) {
  const content = (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <MemoryRouter initialEntries={["/map"]}>
          <div>原页面仍可操作</div>
          {children}
          <Location />
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>
  );
  return render(strict ? <StrictMode>{content}</StrictMode> : content);
}
function defer<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function openShare() {
  fireEvent.click(screen.getByRole("button", { name: "分享地质成果工程" }));
  return screen.findByRole("textbox", { name: "接收方用户名" });
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.list.mockResolvedValue(shareList());
  mocks.check.mockResolvedValue(shareCheck());
  mocks.invite.mockResolvedValue(shareInvitation());
  mocks.open.mockResolvedValue({ target: shareTarget() });
});

describe("exact username invitation", () => {
  it("requires verification, invalidates it on edits, and prevents duplicate sends", async () => {
    const send = defer<ShareInvitation>();
    mocks.invite.mockReturnValue(send.promise);
    show(
      <ShareButton kind="workspace" objectId={17} name="地质成果工程" />,
      true,
    );
    const input = await openShare();
    const sendButton = screen.getByRole("button", { name: "发送邀请" });
    expect(sendButton).toBeDisabled();
    fireEvent.change(input, { target: { value: "  researcher  " } });
    fireEvent.click(screen.getByRole("button", { name: "核验" }));
    await waitFor(() => expect(sendButton).toBeEnabled());
    expect(mocks.check).toHaveBeenCalledWith("workspace", 17, "researcher");
    fireEvent.change(input, { target: { value: "second" } });
    expect(sendButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "核验" }));
    await waitFor(() => expect(sendButton).toBeEnabled());
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);
    expect(mocks.invite).toHaveBeenCalledOnce();
    expect(mocks.invite).toHaveBeenCalledWith(
      "workspace",
      17,
      "second",
      expect.any(String),
    );
    send.resolve(shareInvitation());
    expect(await screen.findByText(/邀请已发给 科研用户/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("ignores an old verification when the username has changed", async () => {
    const check = defer<ShareCheckResponse>();
    mocks.check.mockReturnValueOnce(check.promise);
    show(<ShareButton kind="workspace" objectId={17} name="地质成果工程" />);
    const input = await openShare();
    fireEvent.change(input, { target: { value: "old" } });
    fireEvent.click(screen.getByRole("button", { name: "核验" }));
    fireEvent.change(input, { target: { value: "new" } });
    check.resolve(shareCheck("old"));
    await waitFor(() => expect(mocks.check).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "发送邀请" })).toBeDisabled();
    expect(mocks.invite).not.toHaveBeenCalled();
  });

  it("shows an ineligible reason and keeps sending disabled", async () => {
    mocks.check.mockResolvedValue({
      eligible: false,
      detail: "接收方没有这个项目的查看权限",
    });
    show(<ShareButton kind="workspace" objectId={17} name="地质成果工程" />);
    const input = await openShare();
    fireEvent.change(input, { target: { value: "visitor" } });
    fireEvent.click(screen.getByRole("button", { name: "核验" }));
    expect(
      await screen.findByText("接收方没有这个项目的查看权限"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送邀请" })).toBeDisabled();
  });
});

describe("invitation notification center", () => {
  it.each(["malformed", "404"])(
    "keeps the original page usable after %s without a popup",
    async (mode) => {
      if (mode === "malformed") mocks.list.mockResolvedValue({ canChat: true });
      else mocks.list.mockRejectedValue(new Error("分享服务暂不可用（404）"));
      show(<InvitationCenter />);
      await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
      expect(screen.getByText("原页面仍可操作")).toBeVisible();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(document.querySelector(".ant-message-notice")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "分享通知" }));
      const drawer = await screen.findByRole("dialog");
      const error =
        mode === "malformed"
          ? "分享服务返回内容不完整，请稍后重试"
          : "分享服务暂不可用（404）";
      expect(await within(drawer).findByText(error)).toBeInTheDocument();
      expect(screen.getByText("原页面仍可操作")).toBeVisible();
    },
  );

  it("rejects without opening or granting an entry, and prevents duplicate responses", async () => {
    let invitation = shareInvitation();
    const decision = defer<ShareInvitation>();
    mocks.list.mockImplementation((box: string) =>
      Promise.resolve(shareList(box === "received" ? [invitation] : [])),
    );
    mocks.respond.mockReturnValue(decision.promise);
    show(<InvitationCenter />);
    fireEvent.click(screen.getByRole("button", { name: "分享通知" }));
    const reject = await screen.findByRole("button", { name: "拒绝" });
    fireEvent.click(reject);
    fireEvent.click(reject);
    expect(mocks.respond).toHaveBeenCalledOnce();
    expect(mocks.respond).toHaveBeenCalledWith(
      23,
      "reject",
      expect.any(String),
    );
    invitation = shareInvitation({
      status: "rejected",
      canRespond: false,
      detail: "已拒绝",
    });
    decision.resolve(invitation);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "拒绝" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "打开" }),
    ).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("accepts, then rechecks the actual target before opening", async () => {
    let invitation = shareInvitation();
    mocks.list.mockImplementation((box: string) =>
      Promise.resolve(shareList(box === "received" ? [invitation] : [])),
    );
    mocks.respond.mockImplementation(async () => {
      invitation = shareInvitation({
        status: "accepted",
        canRespond: false,
        detail: "接受成功",
      });
      return invitation;
    });
    show(<InvitationCenter />);
    fireEvent.click(screen.getByRole("button", { name: "分享通知" }));
    fireEvent.click(await screen.findByRole("button", { name: "接受分享" }));
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    await waitFor(() => expect(mocks.open).toHaveBeenCalledWith(23));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/map?sceneId=17",
      ),
    );
  });

  it("shows the sender both acceptance and rejection decisions", async () => {
    mocks.list.mockImplementation((box: string) =>
      Promise.resolve(
        shareList(
          box === "sent"
            ? [
                shareInvitation({
                  id: 23,
                  status: "accepted",
                  canRespond: false,
                  detail: "科研用户接受了分享",
                }),
                shareInvitation({
                  id: 24,
                  status: "rejected",
                  canRespond: false,
                  detail: "另一用户拒绝了分享",
                }),
              ]
            : [],
        ),
      ),
    );
    show(<InvitationCenter />);
    fireEvent.click(screen.getByRole("button", { name: "分享通知" }));
    fireEvent.click(await screen.findByText("我发出的邀请"));
    expect(await screen.findByText("科研用户接受了分享")).toBeVisible();
    expect(screen.getByText("另一用户拒绝了分享")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "接受分享" }),
    ).not.toBeInTheDocument();
  });

  it("refuses a target outside the allowed in-app routes", async () => {
    mocks.list.mockResolvedValue(
      shareList([shareInvitation({ status: "accepted", canRespond: false })]),
    );
    mocks.open.mockResolvedValue({
      target: shareTarget({ openUrl: "https://other.invalid/" }),
    });
    show(<InvitationCenter />);
    fireEvent.click(screen.getByRole("button", { name: "分享通知" }));
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    expect(
      await screen.findByText("分享入口不可用，请联系管理员"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/map$/);
  });
});
