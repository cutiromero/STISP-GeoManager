import { Alert, Button } from "antd";
import { useEffect, useState } from "react";
import { moduleEntry } from "./clientBuild";

export default function ClientUpdateNotice() {
  const [updated, setUpdated] = useState(false);
  useEffect(() => {
    const entry = moduleEntry(document);
    if (!entry.startsWith("/static/")) return;
    const controller = new AbortController();
    const check = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const response = await fetch("/", {
          cache: "no-store",
          headers: { Accept: "text/html" },
          signal: controller.signal,
        });
        if (!response.ok) return;
        const next = moduleEntry(
          new DOMParser().parseFromString(await response.text(), "text/html"),
        );
        if (next && next !== entry && !controller.signal.aborted)
          setUpdated(true);
      } catch {
        /* A connectivity failure is not a release change. */
      }
    };
    const refresh = () => {
      void check();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    const interval = window.setInterval(refresh, 60000);
    void check();
    return () => {
      controller.abort();
      clearInterval(interval);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  return updated ? (
    <Alert
      banner
      type="info"
      title="平台已更新，请刷新后使用新版流程。已开始的任务继续保存。"
      description="刷新前请保留尚未发送的文字。"
      action={
        <Button onClick={() => window.location.reload()}>刷新使用新版</Button>
      }
    />
  ) : null;
}
