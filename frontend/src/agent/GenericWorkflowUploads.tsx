import { Alert, Button, Select, Space, Tag, Typography, Upload } from "antd";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { agentApi } from "../api/agent";
import type { AgentWorkflowUpload } from "../api/generated/types.gen";

type UploadRole = NonNullable<AgentWorkflowUpload["roleHint"]>;

export const genericRoles: {
  key: UploadRole;
  label: string;
  kind: AgentWorkflowUpload["dataType"];
}[] = [
  { key: "lithology", label: "地质图（必需）", kind: "vector" },
  { key: "faults", label: "构造线", kind: "vector" },
  { key: "coverage", label: "研究区范围", kind: "vector" },
  { key: "units", label: "填图单元表", kind: "table" },
  { key: "hematite", label: "赤铁矿化识别结果", kind: "raster" },
  { key: "chlorite", label: "绿泥石化识别结果", kind: "raster" },
  { key: "hydromica", label: "水云母化识别结果", kind: "raster" },
  { key: "calcite", label: "方解石化识别结果", kind: "raster" },
  { key: "dolomite", label: "白云石化识别结果", kind: "raster" },
];

const kindLabels = { vector: "矢量", raster: "栅格", table: "表格" } as const;

function profileSummary(item: AgentWorkflowUpload) {
  const profile = item.profile;
  if (profile.kind === "raster")
    return `${profile.width ?? "?"}×${profile.height ?? "?"} 像元，${profile.bandCount ?? "?"} 个波段`;
  const geometry = profile.geometryTypes?.length
    ? `${profile.geometryTypes.join("、")}，`
    : "";
  return `${geometry}${profile.featureCount ?? 0} ${profile.kind === "table" ? "行" : "个要素"}，字段：${profile.fields
    .map((field) => field.name)
    .join("、")}`;
}

export default function GenericWorkflowUploads({
  batchId,
  inputs,
  disabled = false,
  onInputsChange,
}: {
  batchId: string;
  inputs: Record<string, number>;
  disabled?: boolean;
  onInputsChange: Dispatch<SetStateAction<Record<string, number>>>;
}) {
  const [items, setItems] = useState<AgentWorkflowUpload[]>([]);
  const [uploading, setUploading] = useState<string>();
  const [error, setError] = useState("");
  useEffect(() => {
    setItems([]);
    setError("");
    const controller = new AbortController();
    void agentApi
      .workflowUploads(batchId, { signal: controller.signal })
      .then((result) => setItems(result.items))
      .catch(() => {
        // A new batch has nothing to restore.
      });
    return () => controller.abort();
  }, [batchId]);
  const roleOf = (item: AgentWorkflowUpload) =>
    Object.entries(inputs).find(([, id]) => id === item.resourceId)?.[0];
  const assign = (item: AgentWorkflowUpload, role: string | undefined) =>
    onInputsChange((old) => {
      const next = Object.fromEntries(
        Object.entries(old).filter(
          ([key, id]) => id !== item.resourceId && key !== role,
        ),
      );
      if (role) next[role] = item.resourceId;
      return next;
    });
  const upload = async (file: File) => {
    setError("");
    setUploading(file.name);
    try {
      const item = await agentApi.uploadWorkflowFile(batchId, file);
      setItems((old) => [...old, item]);
      const hint = item.roleHint;
      if (hint)
        onInputsChange((old) =>
          old[hint] ? old : { ...old, [hint]: item.resourceId },
        );
    } catch (reason) {
      setError(
        `${file.name}：${reason instanceof Error ? reason.message : "上传失败"}`,
      );
    } finally {
      setUploading(undefined);
    }
  };
  const remove = async (item: AgentWorkflowUpload) => {
    setError("");
    try {
      await agentApi.deleteWorkflowUpload(item.id);
      setItems((old) => old.filter((entry) => entry.id !== item.id));
      assign(item, undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    }
  };
  return (
    <section className="agent-demo-form" aria-label="上传本次资料">
      <div className="agent-demo-form-heading">
        <strong>上传本次资料</strong>
      </div>
      <p className="agent-demo-hint">
        资料只用于本次任务，不进入项目数据目录。地质图必需，构造线、研究区范围、填图单元表和蚀变识别结果可选；字段名不需要预先整理，提交后由智能体判断字段含义，您确认后再执行。
      </p>
      <Upload.Dragger
        multiple
        showUploadList={false}
        disabled={disabled || Boolean(uploading)}
        accept=".zip,.gpkg,.geojson,.json,.tif,.tiff,.csv,.xlsx"
        beforeUpload={(file) => {
          void upload(file);
          return false;
        }}
      >
        <p>
          {uploading
            ? `正在上传并识别：${uploading}`
            : "点击或拖入文件：Shapefile（ZIP）、GeoPackage、GeoJSON、GeoTIFF、CSV、Excel"}
        </p>
      </Upload.Dragger>
      {error && <Alert type="error" showIcon title={error} />}
      {items.map((item) => {
        const role = roleOf(item);
        return (
          <div key={item.id} className="agent-demo-fields">
            <Space orientation="vertical" size={2} style={{ minWidth: 0 }}>
              <Space size={6} wrap>
                <strong>{item.fileName}</strong>
                <Tag>{kindLabels[item.dataType]}</Tag>
                {item.profile.crs && <Tag>{item.profile.crs}</Tag>}
              </Space>
              <Typography.Text type="secondary">
                {profileSummary(item)}
              </Typography.Text>
              {item.profile.warnings?.map((warning) => (
                <Typography.Text key={warning} type="warning">
                  {warning}
                </Typography.Text>
              ))}
            </Space>
            <label>
              <span>资料角色</span>
              <Select
                aria-label={`${item.fileName}的资料角色`}
                allowClear
                disabled={disabled}
                value={role}
                placeholder="不使用"
                options={genericRoles
                  .filter((entry) => entry.kind === item.dataType)
                  .map((entry) => ({ value: entry.key, label: entry.label }))}
                onChange={(value: string | undefined) => assign(item, value)}
              />
            </label>
            <Button
              size="small"
              disabled={disabled}
              onClick={() => void remove(item)}
            >
              删除
            </Button>
          </div>
        );
      })}
      {items.length > 0 && !inputs.lithology && (
        <Alert type="warning" showIcon title="请把一份矢量面资料指定为地质图" />
      )}
    </section>
  );
}
