import {
  DatabaseOutlined,
  DownloadOutlined,
  FileTextOutlined,
} from "@ant-design/icons";
import { Alert, Button, Modal } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { agentApi } from "../api/agent";
import { downloadComputeFile } from "../api/compute";
import type {
  AgentWorkflowReport,
  AgentWorkflowReportPreview,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import "./workflow-deliverables.css";
import SafeMarkdown from "./SafeMarkdown";

// Cards that open together for the same task share one prepare request.
const pendingReports = new Map<string, Promise<AgentWorkflowReport>>();

export function prepareReport(workflowId: string) {
  let pending = pendingReports.get(workflowId);
  if (!pending) {
    pending = agentApi
      .prepareWorkflowReport(workflowId)
      .finally(() => pendingReports.delete(workflowId));
    pendingReports.set(workflowId, pending);
  }
  return pending;
}

export default function WorkflowReportFile({
  workflowId,
  projectId,
}: {
  workflowId: string;
  projectId: number;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const [report, setReport] = useState<AgentWorkflowReport>();
  const [preview, setPreview] = useState<AgentWorkflowReportPreview>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<
    "prepare" | "preview" | "download" | "import" | undefined
  >("prepare");
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  useEffect(() => {
    const request = ++sequence.current;
    setReport(undefined);
    setPreview(undefined);
    setError("");
    setBusy("prepare");
    void prepareReport(workflowId)
      .then((result) => {
        if (sequence.current === request) setReport(result);
      })
      .catch((reason) => {
        if (sequence.current === request)
          setError(
            reason instanceof Error ? reason.message : "暂时无法生成报告",
          );
      })
      .finally(() => {
        if (sequence.current === request) setBusy(undefined);
      });
    return () => {
      sequence.current++;
    };
  }, [workflowId, revision]);
  const perform = async (action: "preview" | "download" | "import") => {
    if (!report || inFlight.current) return;
    const request = sequence.current;
    inFlight.current = true;
    setBusy(action);
    setError("");
    try {
      if (action === "preview") {
        const next = await agentApi.previewWorkflowReport(workflowId);
        if (sequence.current === request) setPreview(next);
      } else if (action === "import") {
        const next = await agentApi.importWorkflowReport(workflowId);
        if (sequence.current === request) setReport(next);
      } else await downloadComputeFile(report.downloadUrl, report.fileName);
    } catch (reason) {
      if (sequence.current === request)
        setError(reason instanceof Error ? reason.message : "暂时无法读取报告");
    } finally {
      inFlight.current = false;
      if (sequence.current === request) setBusy(undefined);
    }
  };
  return (
    <>
      <article
        className="agent-file-row is-report"
        aria-label={ui("科研报告文件", "Research report file")}
      >
        <span className="agent-file-icon" aria-hidden="true">
          <FileTextOutlined />
        </span>
        <div className="agent-file-main">
          <div className="agent-file-title">
            <strong>
              {report?.label || ui("科研分析报告", "Research analysis report")}
            </strong>
            <span>
              {report?.resourceId
                ? ui("已入库", "Imported")
                : busy === "prepare"
                  ? ui("正在整理报告", "Preparing report")
                  : ui("Markdown 文档", "Markdown document")}
            </span>
          </div>
          {report && (
            <span className="agent-file-name">
              {report.fileName} / {(report.sizeBytes / 1024).toFixed(1)} KB
            </span>
          )}
          {report?.resourceLocation && (
            <span className="agent-file-location">
              {report.resourceLocation}
            </span>
          )}
          <div className="agent-file-actions">
            {report && (
              <Button
                key="preview-report"
                size="small"
                type="link"
                loading={busy === "preview"}
                disabled={Boolean(busy && busy !== "preview")}
                onClick={() => void perform("preview")}
              >
                {ui("在线预览", "Preview")}
              </Button>
            )}
            {report?.canDownload && (
              <Button
                size="small"
                type="link"
                icon={<DownloadOutlined aria-hidden="true" />}
                loading={busy === "download"}
                disabled={Boolean(busy && busy !== "download")}
                onClick={() => void perform("download")}
              >
                {ui("下载", "Download")}
              </Button>
            )}
            {report?.resourceId ? (
              <Button
                key="open-report"
                size="small"
                type="link"
                onClick={() =>
                  navigate(
                    `/resources/catalog?resourceId=${report.resourceId}&projectTagId=${projectId}`,
                  )
                }
              >
                {ui("打开入库文档", "Open imported document")}
              </Button>
            ) : (
              report?.canImport && (
                <Button
                  key="import-report"
                  size="small"
                  type="link"
                  icon={<DatabaseOutlined aria-hidden="true" />}
                  loading={busy === "import"}
                  disabled={Boolean(busy && busy !== "import")}
                  onClick={() => void perform("import")}
                >
                  {ui("将报告入库", "Import report")}
                </Button>
              )
            )}
            {!report && error && (
              <Button
                size="small"
                type="link"
                onClick={() => setRevision((value) => value + 1)}
              >
                {ui("重试生成报告", "Retry report")}
              </Button>
            )}
          </div>
          {error && <Alert type="warning" title={error} />}
        </div>
      </article>
      <Modal
        open={Boolean(preview)}
        title={report?.label || ui("科研分析报告", "Research analysis report")}
        footer={null}
        width={960}
        onCancel={() => setPreview(undefined)}
      >
        {preview && (
          <div className="agent-report-preview">
            <SafeMarkdown text={preview.content} />
            {preview.truncated && (
              <Alert
                type="info"
                title={ui(
                  "预览已显示前半部分，下载可查看完整报告。",
                  "This preview is truncated. Download the complete report.",
                )}
              />
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
