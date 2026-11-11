import { DeleteOutlined } from "@ant-design/icons";
import { Alert, App, Button, Checkbox, Input, Modal, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { platformApi, type ProjectTag } from "../api/platform";
import type { ProjectDeletionPreview } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

export default function ProjectDeleteButton({ project, disabled, onDeleted }: {
  project: ProjectTag; disabled: boolean; onDeleted: () => Promise<void>;
}) {
  const ui = useComputeText();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<ProjectDeletionPreview>();
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setPreview(undefined); setError(""); setName(""); setConfirmed(false);
    void platformApi.previewProjectDeletion(project.id, { signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setPreview(value); })
      .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [open, project.id]);
  const remove = async () => {
    if (!preview || !confirmed || name !== project.name || pending) return;
    setPending(true);
    try {
      const result = await platformApi.deleteProject(project.id, {
        confirmedName: name, deleteExclusiveData: true, confirmationToken: preview.confirmationToken,
      });
      setOpen(false);
      message.success(result.detail);
      await onDeleted();
    } catch (reason) {
      setError(String(reason));
    } finally { setPending(false); }
  };
  return <>
    <Button danger disabled={disabled || project.isDefault} icon={<DeleteOutlined />} onClick={() => setOpen(true)}>{ui("删除", "Delete")}</Button>
    {open && <Modal open title={ui("删除项目", "Delete project")} onCancel={() => { if (!pending) setOpen(false); }}
      onOk={() => void remove()} confirmLoading={pending} okText={ui("删除项目及独占数据", "Delete project and exclusive data")}
      cancelText={ui("取消", "Cancel")} closable={!pending} mask={{ closable: !pending }}
      okButtonProps={{ danger: true, disabled: !preview || !confirmed || name !== project.name }} cancelButtonProps={{ disabled: pending }}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph>{ui(`将删除“${project.name}”及其独占的原始资料、任务与成果。其他项目仍引用的数据与共用底层文件会保留。`, `Delete “${project.name}” and its exclusive source data, tasks, and results. Data referenced by other projects and shared files are retained.`)}</Typography.Paragraph>
        {!preview && !error && <Spin size="small" />}
        {preview && <Typography.Text>{ui(`清理 ${preview.resourceCount} 项独占资料、${preview.recordCount} 条记录，文件约 ${(preview.estimatedBytes / 1024 ** 2).toFixed(1)} MiB；保留 ${preview.sharedResourceCount} 项通用资料、${preview.sharedFileCount} 项共享存储引用。`, `Remove ${preview.resourceCount} exclusive datasets and ${preview.recordCount} records (about ${(preview.estimatedBytes / 1024 ** 2).toFixed(1)} MiB); retain ${preview.sharedResourceCount} shared datasets and ${preview.sharedFileCount} shared storage references.`)}</Typography.Text>}
        {error && <Alert type="error" title={error} showIcon />}
        <Input aria-label={ui("输入完整项目名称", "Enter the full project name")} value={name} disabled={!preview || pending}
          placeholder={project.name} maxLength={120} onChange={event => setName(event.target.value)} />
        <Checkbox checked={confirmed} disabled={!preview || pending} onChange={event => setConfirmed(event.target.checked)}>
          {ui("确认清理项目独占内容，删除后无法恢复；通用资料保留", "Remove exclusive project data permanently; retain shared data")}
        </Checkbox>
      </Space>
    </Modal>}
  </>;
}
