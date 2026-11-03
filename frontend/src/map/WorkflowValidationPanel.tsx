import { DownloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Collapse,
  Flex,
  Modal,
  Spin,
  Table,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import SafeMarkdown from "../agent/SafeMarkdown";
import { agentApi } from "../api/agent";
import { downloadComputeFile } from "../api/compute";
import type {
  AgentWorkflowReportPreview,
  AgentWorkflowValidation,
  AgentWorkflowValidationFile,
  AgentWorkflowValidationSection,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";
import { getActiveProject } from "../projects/session";

type ScalarRow = {
  rowKey: string;
  values: AgentWorkflowValidationSection["rows"][number];
};

function tableRows(rows: AgentWorkflowValidationSection["rows"]): ScalarRow[] {
  const occurrences = new Map<string, number>();
  return rows.map((values) => {
    const signature = JSON.stringify(values);
    const count = (occurrences.get(signature) ?? 0) + 1;
    occurrences.set(signature, count);
    return { rowKey: `${signature}:${count}`, values };
  });
}

export default function WorkflowValidationPanel({
  workflowId,
}: {
  workflowId: string;
}) {
  return (
    <ValidationPanel
      key={`${getActiveProject()}:${workflowId}`}
      workflowId={workflowId}
    />
  );
}

function ValidationPanel({ workflowId }: { workflowId: string }) {
  const ui = useComputeText();
  const [expanded, setExpanded] = useState(false);
  const [validation, setValidation] = useState<AgentWorkflowValidation>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const inFlight = useRef(false);
  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );

  const load = async () => {
    if (inFlight.current) return;
    const request = ++sequence.current;
    inFlight.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await agentApi.workflowValidation(workflowId);
      if (sequence.current === request) setValidation(result);
    } catch (reason) {
      if (sequence.current === request)
        setError(
          reason instanceof Error
            ? reason.message
            : ui("独立评价读取失败", "Unable to read validation"),
        );
    } finally {
      inFlight.current = false;
      if (sequence.current === request) setLoading(false);
    }
  };

  const scalar = (value: string | number | boolean | null | undefined) => {
    if (value === null || value === undefined) return ui("未定义", "Undefined");
    if (typeof value === "boolean")
      return value ? ui("是", "Yes") : ui("否", "No");
    return String(value);
  };

  return (
    <section
      aria-label={ui("独立评价", "Independent validation")}
      style={{ minWidth: 0, maxWidth: "100%" }}
    >
      <Collapse
        activeKey={expanded ? ["validation"] : []}
        onChange={(keys) => {
          const open = keys.includes("validation");
          setExpanded(open);
          if (open && !validation) void load();
        }}
        items={[
          {
            key: "validation",
            label: ui("独立评价", "Independent validation"),
            children: (
              <Flex vertical gap={12} style={{ minWidth: 0 }}>
                {loading && (
                  <Spin description={ui("读取独立评价", "Reading validation")}>
                    <div style={{ minHeight: 48 }} />
                  </Spin>
                )}
                {error && (
                  <Alert
                    type="warning"
                    showIcon
                    title={error}
                    action={
                      <Button size="small" onClick={() => void load()}>
                        {ui("重试读取", "Retry")}
                      </Button>
                    }
                  />
                )}
                {validation && (
                  <>
                    {validation.scope && (
                      <Typography.Paragraph style={{ marginBottom: 0 }}>
                        {validation.scope}
                      </Typography.Paragraph>
                    )}
                    <Alert
                      type="info"
                      showIcon
                      title={
                        validation.summary ||
                        ui(
                          "当前任务尚未登记独立评价。",
                          "No independent validation is registered for this workflow.",
                        )
                      }
                    />
                    {validation.available && (
                      <>
                        {validation.sections.map((section) => (
                          <section
                            key={section.key}
                            aria-label={section.title}
                            style={{ minWidth: 0 }}
                          >
                            <Typography.Title level={5}>
                              {section.title}
                            </Typography.Title>
                            {section.summary && (
                              <Typography.Paragraph>
                                {section.summary}
                              </Typography.Paragraph>
                            )}
                            <Table<ScalarRow>
                              size="small"
                              rowKey="rowKey"
                              pagination={false}
                              scroll={{ x: "max-content" }}
                              columns={section.columns.map((column) => ({
                                key: column.key,
                                title: column.label,
                                render: (_value: unknown, row: ScalarRow) =>
                                  scalar(row.values[column.key]),
                              }))}
                              dataSource={tableRows(section.rows)}
                            />
                          </section>
                        ))}
                        {validation.files.map((file) => (
                          <ValidationFile
                            key={file.key}
                            workflowId={workflowId}
                            file={file}
                          />
                        ))}
                      </>
                    )}
                  </>
                )}
              </Flex>
            ),
          },
        ]}
      />
    </section>
  );
}

function ValidationFile({
  workflowId,
  file,
}: {
  workflowId: string;
  file: AgentWorkflowValidationFile;
}) {
  const ui = useComputeText();
  const [preview, setPreview] = useState<AgentWorkflowReportPreview>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"preview" | "download">();
  const sequence = useRef(0);
  const inFlight = useRef(false);
  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );
  const perform = async (action: "preview" | "download") => {
    if (inFlight.current || (action === "download" && !file.canDownload))
      return;
    const request = ++sequence.current;
    inFlight.current = true;
    setBusy(action);
    setError("");
    try {
      if (action === "preview") {
        const result = await agentApi.workflowValidationPreview(
          workflowId,
          file.key,
        );
        if (sequence.current === request) setPreview(result);
      } else await downloadComputeFile(file.downloadUrl, file.fileName);
    } catch (reason) {
      if (sequence.current === request)
        setError(
          reason instanceof Error
            ? reason.message
            : ui(
                "评价文件读取失败，请重试",
                "Unable to read validation file. Please retry.",
              ),
        );
    } finally {
      inFlight.current = false;
      if (sequence.current === request) setBusy(undefined);
    }
  };
  return (
    <article aria-label={file.fileName} style={{ minWidth: 0 }}>
      <Flex justify="space-between" gap={8} align="center" wrap>
        <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
          <Typography.Text strong>{file.fileName}</Typography.Text>{" "}
          <Typography.Text type="secondary">
            {file.sizeBytes.toLocaleString()} {ui("字节", "bytes")}
          </Typography.Text>
        </div>
        <Flex gap={8} wrap>
          {file.previewUrl && (
            <Button
              size="small"
              aria-label={`${ui("在线预览", "Preview")} ${file.fileName}`}
              loading={busy === "preview"}
              disabled={Boolean(busy && busy !== "preview")}
              onClick={() => void perform("preview")}
            >
              {ui("在线预览", "Preview")}
            </Button>
          )}
          {file.canDownload && (
            <Button
              size="small"
              icon={<DownloadOutlined aria-hidden="true" />}
              aria-label={`${ui("下载", "Download")} ${file.fileName}`}
              loading={busy === "download"}
              disabled={Boolean(busy && busy !== "download")}
              onClick={() => void perform("download")}
            >
              {ui("下载", "Download")}
            </Button>
          )}
        </Flex>
      </Flex>
      {error && <Alert type="warning" title={error} />}
      <Modal
        open={Boolean(preview)}
        title={file.fileName}
        footer={null}
        width={960}
        onCancel={() => setPreview(undefined)}
      >
        {preview && (
          <div
            className="agent-report-preview"
            style={{ overflowWrap: "anywhere", overflowX: "auto" }}
          >
            <SafeMarkdown text={preview.content} />
            {preview.truncated && (
              <Alert
                type="info"
                title={ui(
                  "预览已截断，完整内容见原始评价文件。",
                  "This preview is truncated. See the original validation file for the complete content.",
                )}
              />
            )}
          </div>
        )}
      </Modal>
    </article>
  );
}
