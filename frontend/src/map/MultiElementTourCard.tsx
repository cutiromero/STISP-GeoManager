import { Tag } from "antd";
import { MultiElementEvidence } from "../agent/MultiElementStory";
import type { GeoJsonFeatureCollection } from "../api/generated/types.gen";
import { tourLabels, type TourChange } from "./multiElementTour";

type Feature = GeoJsonFeatureCollection["features"][number];
export default function MultiElementTourCard({
  change,
  before,
  after,
  algorithm,
}: {
  change: TourChange;
  before?: Feature;
  after?: Feature;
  algorithm: { name: string; version: string; taskId: string };
}) {
  const labels = tourLabels(change, before, after);
  const refs = change.suggestion.ruleRefs ?? [];
  const p = change.feature.properties;
  const metric = (key: string, suffix: string) =>
    p[key] !== undefined && Number.isFinite(Number(p[key]))
      ? `${Number(p[key]).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}${suffix}`
      : "本次结果未记录";
  const operation =
    change.action === "set_code"
      ? `地质代号由 ${labels.before} 更新为 ${labels.after}。`
      : change.action === "exclude"
        ? "原构造记录已保留，改为灰色虚线，本轮不参与后续分析。"
        : change.action === "downweight"
          ? `${labels.before} → ${labels.after.replace("证据权重 ", "")}；保留识别范围与原记录。`
          : change.action === "merge"
            ? `按获批范围合并为 ${labels.after}，去除内部接边 ${metric("removed_internal_boundary_m", "米")}。`
            : change.action === "reclassify"
              ? `岩性由 ${labels.before} 调整为 ${labels.after}，更新类别及对应属性。`
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
            {change.suggestion.title}
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
      <details className="multi-tour-evidence">
        <summary>展开知识来源、实际测量与任务依据</summary>
        <p>
          对象 {change.suggestion.featureId}；实际算法 {algorithm.name}{" "}
          {algorithm.version}；任务 {algorithm.taskId || "尚无任务编号"}。
        </p>
        <p>
          涉及对象面积：{metric("involved_area_m2", "平方米")}
          ；实际覆盖变化面积：{metric("geometry_change_area_m2", "平方米")}
          ；分类变化面积：{metric("class_change_area_m2", "平方米")}
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
