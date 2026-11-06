import { DownloadOutlined } from "@ant-design/icons";
import { Alert, Button } from "antd";
import { useEffect, useRef, useState } from "react";
import { downloadComputeFile } from "../api/compute";
import { prepareReport } from "./WorkflowReportFile";

export default function LogicReportAction({
  workflowId,
  projectId,
}: {
  workflowId: string;
  projectId: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    sequence.current++;
    pending.current = false;
    setError("");
    setBusy(false);
    return () => {
      sequence.current++;
    };
  }, [workflowId, projectId]);
  const download = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const key = sequence.current;
    try {
      const report = await prepareReport(workflowId);
      if (key !== sequence.current) return;
      if (!report.canDownload)
        throw new Error("当前账号没有报告下载权限，可在成果中查看允许的操作");
      await downloadComputeFile(report.downloadUrl, report.fileName);
    } catch (reason) {
      if (key === sequence.current)
        setError(reason instanceof Error ? reason.message : "暂时无法下载报告");
    } finally {
      if (key === sequence.current) {
        setBusy(false);
        pending.current = false;
      }
    }
  };
  return (
    <div className="logic-report-action">
      <Button
        aria-label="下载报告"
        icon={<DownloadOutlined />}
        loading={busy}
        onClick={() => void download()}
      >
        下载报告
      </Button>
      {error && <Alert type="warning" title={error} />}
    </div>
  );
}
