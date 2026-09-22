import { useTranslation } from "react-i18next";
export function useComputeText() {
  const { i18n } = useTranslation();
  return (zh: string, en: string) =>
    i18n.resolvedLanguage?.startsWith("en") ? en : zh;
}
export const taskStatusLabels: Record<string, [string, string]> = {
  queued: ["排队中", "Queued"],
  validating: ["校验中", "Validating"],
  running: ["计算中", "Running"],
  cancelling: ["正在取消", "Cancelling"],
  succeeded: ["已完成", "Completed"],
  failed: ["失败", "Failed"],
  cancelled: ["已取消", "Cancelled"],
  interrupted: ["执行中断", "Interrupted"],
};
export const importStatusLabels: Record<string, [string, string]> = {
  none: ["未入库", "Not imported"],
  queued: ["等待入库", "Import queued"],
  running: ["入库中", "Importing"],
  ready: ["已入库", "Imported"],
  failed: ["入库失败", "Import failed"],
};
export function statusText(
  ui: (zh: string, en: string) => string,
  status: string,
  labels = taskStatusLabels,
) {
  const label = labels[status];
  return label ? ui(label[0], label[1]) : status;
}
