import {
  DatabaseOutlined,
  DeleteOutlined,
  FileOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Space } from "antd";
import { useEffect, useRef, useState } from "react";
import WorkflowCatalogPicker from "../agent/WorkflowCatalogPicker";
import { businessFlowsApi } from "../api/businessFlows";
import { useComputeText } from "../compute/ui";
import { getActiveProject } from "../projects/session";

type ImageChoice = { id: number; name: string };

export default function BusinessFlowImageSelection({
  flowId,
  role,
  image,
  disabled,
  canImport,
  onChange,
}: {
  flowId: number;
  role: { key: string; label: string; description: string };
  image?: number;
  disabled: boolean;
  canImport: boolean;
  onChange: (id?: number) => void;
}) {
  const ui = useComputeText();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<ImageChoice>();
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState("");
  const restoreRequest = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => restoreRequest.current?.abort(), []);

  const select = (item?: ImageChoice) => {
    setChoice(item);
    setError("");
    onChange(item?.id);
  };
  const restore = async () => {
    if (restoreRequest.current) return;
    const controller = new AbortController();
    restoreRequest.current = controller;
    const options = { signal: controller.signal };
    setRestoring(true);
    setError("");
    try {
      const history = await businessFlowsApi.runs(options);
      if (controller.signal.aborted) return;
      const prior = history.items.find((run) => run.flowId === flowId);
      const run = prior && (await businessFlowsApi.run(prior.id, options));
      if (controller.signal.aborted) return;
      const row = run?.inputPreparation?.items.find(
        (item) => item.role === role.key && item.sourceType === "raster",
      );
      if (!row?.sourceId) {
        setError(ui("没有可沿用的影像，请选择本次任务资料。", "Choose an image for this task."));
        return;
      }
      select({ id: row.sourceId, name: row.sourceName });
    } catch (reason) {
      if (!controller.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : ui("暂时无法读取上次配置", "Could not load the previous configuration"),
        );
    } finally {
      if (!controller.signal.aborted) {
        restoreRequest.current = undefined;
        setRestoring(false);
      }
    }
  };
  const name = choice?.id === image ? choice?.name : role.label;
  return (
    <section className="flow-materials" aria-label={ui("任务资料", "Task data")}>
      <div className="flow-materials-heading">
        <div>
          <strong>{ui("任务资料", "Task data")}</strong>
          <span>{ui(`${image ? 1 : 0} 份已选`, `${image ? 1 : 0} selected`)}</span>
        </div>
      </div>
      <Space wrap className="flow-materials-tools">
        {!image && (
          <Button loading={restoring} disabled={disabled} onClick={() => void restore()}>
            {ui("沿用上次配置", "Reuse previous configuration")}
          </Button>
        )}
        <Button
          icon={<PlusOutlined aria-hidden="true" />}
          disabled={disabled || restoring}
          onClick={() => setOpen(true)}
        >
          {ui("选择系统数据", "Choose system data")}
        </Button>
        {canImport && (
          <Button
            icon={<UploadOutlined aria-hidden="true" />}
            href={`/resources/data/import?projectTagId=${getActiveProject()}`}
            target="_blank"
            rel="noreferrer"
          >
            {ui("上传影像", "Upload imagery")}
          </Button>
        )}
      </Space>
      {error && <Alert type="warning" title={error} />}
      {image ? (
        <div className="flow-materials-list">
          <div className="flow-materials-row">
            <span className="flow-materials-file-icon"><DatabaseOutlined /></span>
            <strong title={name}>{name}</strong>
            <small className="flow-materials-file-meta">{role.label}</small>
            <Button
              size="small"
              type="text"
              icon={<DeleteOutlined />}
              aria-label={`移除${name}`}
              disabled={disabled}
              onClick={() => select()}
            />
          </div>
        </div>
      ) : (
        <div className="flow-materials-empty">
          <FileOutlined />
          <strong>{role.label}</strong>
          <p>{role.description}</p>
        </div>
      )}
      {open && (
        <WorkflowCatalogPicker
          polished
          single
          rasterOnly
          attachedIds={image ? [image] : []}
          disabled={disabled}
          onClose={() => setOpen(false)}
          onConfirm={([item]) => {
            if (!item) return;
            select(item);
            setOpen(false);
          }}
        />
      )}
    </section>
  );
}
