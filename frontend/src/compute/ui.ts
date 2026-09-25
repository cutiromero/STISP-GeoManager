import { useTranslation } from "react-i18next";
import translations from "./builtin.en.json";
export function builtinEnglish(text: string): string {
  const dictionary: Record<string, string> = translations;
  if (dictionary[text]) return dictionary[text];
  if (/^附加影像\d+$/.test(text))
    return text.replace("附加影像", "Additional image ");
  const generic = "；按任务生成独立结果，保留输入数据。";
  const example = "的标准接入示例；管理员须使用小样试运行并核对结果后发布。";
  if (text.endsWith(generic))
    return `${builtinEnglish(text.slice(0, -generic.length))}; produce a separate result and preserve the input data.`;
  if (text.endsWith(example))
    return `${builtinEnglish(text.slice(0, -example.length))} integration example. Validate a small trial before publication.`;
  return text;
}
export function useComputeText() {
  const { i18n } = useTranslation();
  return (zh: string, en?: string) =>
    i18n.resolvedLanguage?.startsWith("en") ? (en ?? builtinEnglish(zh)) : zh;
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
