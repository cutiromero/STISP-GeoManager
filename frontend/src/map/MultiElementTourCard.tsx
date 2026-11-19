import { Tag } from "antd";
import { MultiElementEvidence } from "../agent/MultiElementStory";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import {
  archivePartitionDetails,
  isArchivePartition,
  tourLabels,
  type TourChange,
} from "./multiElementTour";
import { formatArea } from "../utils/area";

type Feature = GeoJsonFeatureCollection["features"][number];
export default function MultiElementTourCard({
  change,
  before,
  after,
  algorithm,
  loading = false,
  cleanResults = false,
}: {
  change: TourChange;
  before?: Feature;
  after?: Feature;
  algorithm: { name: string; version: string; taskId: string };
  loading?: boolean;
  cleanResults?: boolean;
}) {
  const labels = tourLabels(change, before, after, loading);
  const refs = change.suggestion.ruleRefs ?? [];
  const p = change.feature.properties;
  const partition = isArchivePartition(change)
    ? archivePartitionDetails(change)
    : null;
  const observedConflict = Number(
    change.suggestion.observations?.archive_conflict_fraction,
  );
  const reportConflict =
    Number.isFinite(observedConflict) &&
    observedConflict >= 0 &&
    observedConflict <= 1;
  const host =
    typeof p.host_feature_id === "string" ? p.host_feature_id.trim() : "";
  const recorded = (key: string) =>
    p[key] !== undefined && Number.isFinite(Number(p[key]));
  const metric = (key: string) =>
    recorded(key) ? formatArea(Number(p[key])) : "本次结果未记录";
  const length = (key: string) =>
    recorded(key)
      ? `${Number(p[key]).toLocaleString("zh-CN", { maximumFractionDigits: 1 })} 米`
      : "本次结果未记录";
  const operation = partition
    ? `在获批范围内实际改类 ${metric("class_change_area_m2")}。原为${partition.before.label}；改为${partition.targets.map((unit) => `${unit.label}${unit.pixels ? ` ${unit.pixels.toLocaleString("zh-CN")} 像元` : ""}`).join("、") || "变更表所列分类"}。此处没有并入宿主图斑。`
    : change.action === "set_code"
      ? `地质代号由 ${labels.before} 更新为 ${labels.after}。${cleanResults && p.host_feature_id ? `已并入相邻同单元宿主 ${p.host_feature_id}，原编号记入修正记录。` : ""}`
      : change.action === "exclude"
        ? cleanResults
          ? "已从最终成果删除；原始资料及修改前范围保留在输入和修正记录中。"
          : "原构造记录已保留，改为灰色虚线，本轮不参与后续分析。"
        : change.action === "downweight"
          ? `${labels.before} → ${labels.after.replace("证据权重 ", "")}；保留识别范围与原记录。`
          : change.action === "merge"
            ? `按获批范围合并为 ${labels.after}，去除内部接边 ${length("removed_internal_boundary_m")}。`
            : change.action === "reclassify"
              ? `岩性由 ${labels.before} 调整为 ${labels.after}。${cleanResults && host ? `实际接收图斑编号 ${host}，并入情况以变更记录为准。` : "更新类别及对应属性。"}`
              : `${labels.before} → ${labels.after}。`;
  return (
    <section className="multi-tour-card" aria-label="当前修改故事">
      <div className="multi-tour-card-heading">
        <h2>{labels.title}</h2>
        <Tag color="blue">用户已批准，算法已执行</Tag>
      </div>
      <div className="multi-tour-explanation">
        <div>
          <span>01</span>
          <p>
            <strong>发现了什么</strong>
            {partition
              ? `现图标为${partition.before.label}。${reportConflict ? `核查范围内，早期模型与现图分类不一致的像元占 ${(observedConflict * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%。` : "早期模型与现图分类存在分歧。"}这说明两版分类有分歧，需要核对接触关系。`
              : change.suggestion.title}
          </p>
        </div>
        <div>
          <span>02</span>
          <p>
            <strong>哪条知识支持</strong>
            {refs.length
              ? refs.map((ref) => ref.title).join("；")
              : "本轮冻结规则，具体引用见检查记录。"}
          </p>
        </div>
        <div>
          <span>03</span>
          <p>
            <strong>算法实际做了什么</strong>
            {operation}
            <small>
              {algorithm.name} {algorithm.version}
            </small>
          </p>
        </div>
      </div>
      <p className="multi-tour-interpretation">{labels.note}</p>
      {partition && p.actual_geometry_unavailable === true && (
        <p role="status">实际变更轮廓暂不可用；地图未标为实际改类范围。</p>
      )}
      <details className="multi-tour-evidence">
        <summary>展开知识来源、实际测量与任务依据</summary>
        <p>
          对象 {change.suggestion.featureId}；实际算法 {algorithm.name}{" "}
          {algorithm.version}；任务 {algorithm.taskId || "尚无任务编号"}。
        </p>
        <p>
          涉及对象面积：{metric("involved_area_m2")}
          ；实际覆盖变化面积：{metric("geometry_change_area_m2")}
          ；分类变化面积：{metric("class_change_area_m2")}
          。涉及对象面积包含本次操作触及的对象，覆盖变化面积按实际几何结果统计。
        </p>
        <p title={change.resultRef.checksum}>
          实际变更表第 {change.resultRef.rowIndex} 行；输出{" "}
          {change.resultRef.outputId}
          ；文件校验 {change.resultRef.checksum.slice(0, 12)}。
        </p>
        <MultiElementEvidence suggestion={change.suggestion} />
      </details>
    </section>
  );
}
