import {
  DatabaseOutlined,
  DownloadOutlined,
  EnvironmentOutlined,
  FileExcelOutlined,
  FileOutlined,
  PictureOutlined,
} from "@ant-design/icons";
import { Alert, Button, Collapse, Modal, Table } from "antd";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { computeApi, downloadComputeFile } from "../api/compute";
import type {
  AgentComputeTaskTracking,
  ComputeOutput,
  ComputePreview,
  ComputeTask,
} from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

const importNames: Record<string, string> = {
  none: "待入库",
  queued: "等待入库",
  running: "正在入库",
  ready: "已入库",
  failed: "入库失败",
  deleted: "目录数据已删除",
};

function FileIcon({ kind }: { kind: string }) {
  return kind === "table" ? (
    <FileExcelOutlined />
  ) : ["raster", "vector", "image"].includes(kind) ? (
    <PictureOutlined />
  ) : (
    <FileOutlined />
  );
}

function ResultMetadata({ output }: { output: ComputeOutput }) {
  const ui = useComputeText();
  const data = output.metadata;
  const parts: string[] = [];
  if (typeof data.width === "number" && typeof data.height === "number")
    parts.push(`${data.width} × ${data.height}`);
  if (typeof data.bands === "number")
    parts.push(ui(`${data.bands} 波段`, `${data.bands} band(s)`));
  if (typeof data.crs === "string") parts.push(data.crs);
  if (typeof data.features === "number")
    parts.push(ui(`${data.features} 个要素`, `${data.features} features`));
  if (typeof data.rows === "number")
    parts.push(ui(`${data.rows} 行`, `${data.rows} rows`));
  return parts.length ? (
    <span className="agent-compute-muted">{parts.join(" · ")}</span>
  ) : null;
}

export default function WorkflowDeliverables({
  items,
  busy,
  reviewing = false,
  report,
  heading = true,
  taskDisplayNames,
  primaryTaskIds,
  onImport,
}: {
  items: AgentComputeTaskTracking[];
  busy?: number;
  reviewing?: boolean;
  report?: ReactNode;
  heading?: boolean;
  taskDisplayNames?: Record<string, string>;
  primaryTaskIds?: string[];
  onImport: (output: ComputeOutput, task: ComputeTask) => void;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<ComputePreview>();
  const [previewName, setPreviewName] = useState("");
  const [reading, setReading] = useState<number>();
  const [error, setError] = useState("");
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const perform = async (
    output: ComputeOutput,
    action: "preview" | "download",
  ) => {
    if (reading !== undefined) return;
    setReading(output.id);
    setError("");
    try {
      if (action === "download")
        await downloadComputeFile(output.downloadUrl, output.fileName);
      else {
        const result = await computeApi.preview(output.id);
        if (alive.current) {
          setPreview(result);
          setPreviewName(output.fileName || output.label);
        }
      }
    } catch (reason) {
      if (alive.current)
        setError(reason instanceof Error ? reason.message : "暂时无法读取文件");
    } finally {
      if (alive.current) setReading(undefined);
    }
  };
  const files = items.flatMap((item) =>
    item.task.outputs.map((output) => ({ ...item, output })),
  );
  const primary = primaryTaskIds?.length
    ? files.filter(({ task }) => primaryTaskIds.includes(task.id))
    : files;
  const intermediate = primaryTaskIds?.length
    ? files.filter(({ task }) => !primaryTaskIds.includes(task.id))
    : [];
  if (!files.length && !report) return null;
  return (
    <section
      className="agent-deliverables"
      aria-label={ui("生成的文件", "Generated files")}
    >
      {heading && <h3>{ui("生成的文件", "Generated files")}</h3>}
      {error && <Alert type="warning" title={error} />}
      <div className="agent-file-list">{report}</div>
      {[primary, intermediate].map((entries, group) => {
        if (!entries.length) return null;
        const rows = (
          <div className="agent-file-list">
            {entries.map(({ task, autoImport, output }) => {
              const canMap =
                task.status === "succeeded" &&
                (!output.expired ||
                  Boolean(output.resourceId && output.mapUrl)) &&
                (output.kind === "raster" ||
                  (output.kind === "vector" &&
                    Boolean(output.resourceId && output.mapUrl)));
              return (
                <article
                  className={`agent-file-row is-${output.kind}`}
                  key={`${task.id}:${output.id}`}
                >
                  <span className="agent-file-icon" aria-hidden="true">
                    <FileIcon kind={output.kind} />
                  </span>
                  <div className="agent-file-main">
                    <div className="agent-file-title">
                      <strong>{ui(output.label)}</strong>
                      <span>
                        {output.expired
                          ? ui("临时结果已过期", "Temporary result expired")
                          : ui(
                              importNames[output.importStatus] ??
                                output.importStatus,
                            )}
                      </span>
                    </div>
                    <div className="agent-file-caption">
                      <span className="agent-file-name">{output.fileName}</span>
                      <span className="agent-file-source">
                        {ui(taskDisplayNames?.[task.id] ?? task.name)}
                      </span>
                    </div>
                    <ResultMetadata output={output} />
                    {output.importStatus === "ready" && (
                      <span className="agent-file-location">
                        {output.resourceLocation ||
                          ui(
                            "已存入当前项目的数据资源",
                            "Saved in this project's data resources",
                          )}
                      </span>
                    )}
                    {output.importError && (
                      <span className="agent-decision-error">
                        {output.importError}
                      </span>
                    )}
                    <div className="agent-file-actions">
                      {canMap && (
                        <Button
                          size="small"
                          type="link"
                          icon={<EnvironmentOutlined aria-hidden="true" />}
                          onClick={() =>
                            navigate(
                              output.mapUrl ||
                                `/map?computeOutputId=${output.id}&projectTagId=${task.projectTagId}`,
                            )
                          }
                        >
                          {ui("在地理工作台查看", "View in map workspace")}
                        </Button>
                      )}
                      {!output.expired &&
                        task.status === "succeeded" &&
                        output.kind !== "archive" &&
                        output.kind !== "raster" && (
                          <Button
                            size="small"
                            type="link"
                            loading={reading === output.id}
                            onClick={() => void perform(output, "preview")}
                          >
                            {ui("在线预览", "Preview")}
                          </Button>
                        )}
                      {!output.expired && output.downloadUrl && (
                        <Button
                          size="small"
                          type="link"
                          icon={<DownloadOutlined aria-hidden="true" />}
                          loading={reading === output.id}
                          onClick={() => void perform(output, "download")}
                        >
                          {ui("下载", "Download")}
                        </Button>
                      )}
                      {output.resourceId ? (
                        <Button
                          size="small"
                          type="link"
                          onClick={() =>
                            navigate(
                              `/resources/catalog?resourceId=${output.resourceId}&projectTagId=${task.projectTagId}`,
                            )
                          }
                        >
                          {ui("打开入库数据", "Open imported data")}
                        </Button>
                      ) : !reviewing &&
                        task.status === "succeeded" &&
                        !output.expired &&
                        output.kind !== "archive" &&
                        ["none", "failed"].includes(output.importStatus) ? (
                        <Button
                          size="small"
                          type="link"
                          icon={<DatabaseOutlined aria-hidden="true" />}
                          loading={busy === output.id}
                          disabled={busy !== undefined && busy !== output.id}
                          onClick={() => onImport(output, task)}
                        >
                          {output.importStatus === "failed"
                            ? ui("重试入库", "Retry import")
                            : ui("将结果入库", "Import result")}
                        </Button>
                      ) : null}
                    </div>
                    {!output.resourceId &&
                      output.importStatus === "none" &&
                      !output.expired &&
                      (reviewing || autoImport) && (
                        <span className="agent-compute-muted">
                          {reviewing
                            ? ui(
                                "等待审核确认后继续保存成果",
                                "Results will be saved after your review",
                              )
                            : ui(
                                "已按您的要求安排入库",
                                "Import was requested",
                              )}
                        </span>
                      )}
                  </div>
                </article>
              );
            })}
          </div>
        );
        return group === 0 ? (
          <div key="final">{rows}</div>
        ) : (
          <Collapse
            key="intermediate"
            ghost
            size="small"
            className="agent-intermediate-files"
            items={[
              {
                key: "files",
                label: ui(
                  `中间过程文件 · ${entries.length} 个`,
                  `Intermediate files · ${entries.length}`,
                ),
                children: rows,
              },
            ]}
          />
        );
      })}
      <Modal
        open={Boolean(preview)}
        title={ui(`文件预览 · ${previewName}`, `File preview · ${previewName}`)}
        width={920}
        footer={null}
        onCancel={() => setPreview(undefined)}
      >
        {preview &&
          (preview.columns.length ? (
            <Table
              size="small"
              scroll={{ x: true }}
              pagination={{ pageSize: 10 }}
              rowKey="row"
              columns={preview.columns.map((field, index) => ({
                key: field,
                title: field,
                render: (_, row: { values: unknown[] }) =>
                  String(row.values[index] ?? ""),
              }))}
              dataSource={preview.rows.map((values, index) => ({
                row: `preview-${index}`,
                values,
              }))}
            />
          ) : (
            <p>
              {ui(
                "此文件可下载查看；空间图层可在地理工作台打开。",
                "Download this file, or open spatial results in the map workspace.",
              )}
            </p>
          ))}
      </Modal>
    </section>
  );
}
