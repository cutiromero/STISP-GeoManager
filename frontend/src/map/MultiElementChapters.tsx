import { Button, Tag } from "antd";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import { record } from "./geologyReviewData";
import type { TourChange } from "./multiElementTour";

export type StoryChapter =
  | "all"
  | "lithology"
  | "structure"
  | "alteration"
  | "investigation";
const chapters: { key: StoryChapter; label: string }[] = [
  { key: "all", label: "总览" },
  { key: "lithology", label: "岩性" },
  { key: "structure", label: "构造" },
  { key: "alteration", label: "矿物" },
  { key: "investigation", label: "调查建议" },
];
const actualTrue = (value: unknown) =>
  value === true || value === 1 || /^(true|1)$/i.test(String(value));
export default function MultiElementChapters({
  workflow,
  active,
  tour,
  onChange,
  intersections,
}: {
  workflow: AgentWorkflow;
  active: StoryChapter;
  tour: TourChange[];
  onChange: (chapter: StoryChapter) => void;
  intersections?: {
    before?: GeoJsonFeatureCollection;
    after?: GeoJsonFeatureCollection;
  };
}) {
  const stages = (
    Array.isArray(workflow.plan.stages) ? workflow.plan.stages : []
  ).map(record);
  const suggestions = workflow.modificationReview?.suggestions ?? [];
  const approved = new Set(
    workflow.modificationReview?.approvedSuggestionIds ?? [],
  );
  const relevant = suggestions.filter(
    (item) =>
      active === "all" || active === "investigation" || item.element === active,
  );
  const disposition = [
    { label: "保留", value: "keep", color: "blue" },
    { label: "降权", value: "downweight", color: "gold" },
    { label: "待裁定", value: "review", color: "purple" },
    { label: "本轮不参与", value: "exclude", color: "default" },
  ];
  const relation = (source?: GeoJsonFeatureCollection) =>
    source
      ? {
          geometric: source.features.filter(
            (feature) => !actualTrue(feature.properties.inferred),
          ).length,
          inferred: source.features.filter((feature) =>
            actualTrue(feature.properties.inferred),
          ).length,
        }
      : null;
  const before = relation(intersections?.before),
    after = relation(intersections?.after);
  const check = stages.find((stage) => stage.name === "check");
  const apply = stages.find((stage) => stage.name === "apply");
  const recheck = stages.find((stage) => stage.name === "recheck");
  return (
    <section className="multi-story-chapters" aria-label="海德乌拉讲解章节">
      <nav aria-label="选择讲解章节">
        {chapters.map((chapter) => (
          <Button
            key={chapter.key}
            aria-label={`查看${chapter.label}章节`}
            type={active === chapter.key ? "primary" : "text"}
            onClick={() => onChange(chapter.key)}
          >
            {chapter.label}
            {chapter.key !== "investigation" && (
              <span className="multi-story-chapter-count">
                {
                  tour.filter(
                    (item) =>
                      chapter.key === "all" ||
                      item.suggestion.element === chapter.key,
                  ).length
                }
              </span>
            )}
          </Button>
        ))}
      </nav>
      <details className="multi-story-process">
        <summary>
          资料 → 疑点 → 知识 → 建议 → 批准 → 实际修改 → 复核 → 调查建议
        </summary>
        <ol className="multi-story-timeline" aria-label="当次任务的故事链">
          <li data-done={workflow.resourceIds.length > 0}>
            <strong>读取资料</strong>
            <span>{workflow.resourceIds.length}份本次输入</span>
          </li>
          <li data-done={check?.status === "completed"}>
            <strong>发现疑点</strong>
            <span>{suggestions.length}项已保存建议</span>
          </li>
          <li
            data-done={suggestions.some(
              (item) => item.knowledgeRefs.length || item.ruleRefs?.length,
            )}
          >
            <strong>查阅知识</strong>
            <span>逐处查看实际引用</span>
          </li>
          <li data-done={approved.size > 0}>
            <strong>用户批准</strong>
            <span>{approved.size}项获批操作</span>
          </li>
          <li data-done={apply?.status === "completed"}>
            <strong>实际修改</strong>
            <span>{tour.length}处执行后变化</span>
          </li>
          <li data-done={recheck?.status === "completed"}>
            <strong>重新检查</strong>
            <span>
              {recheck?.status === "completed"
                ? "已返回复核结果"
                : "以任务状态为准"}
            </span>
          </li>
          <li
            data-done={Boolean(workflow.plan.multiElementMap?.afterProspects)}
          >
            <strong>调查建议</strong>
            <span>比较前后实际核查区</span>
          </li>
        </ol>
        <div className="multi-story-dispositions" aria-label="当前章节处置分布">
          {disposition.map((item) => {
            const entries = relevant.filter(
              (suggestion) => suggestion.action === item.value,
            );
            const executed = entries.filter((suggestion) =>
              tour.some((change) => change.key === suggestion.id),
            ).length;
            return (
              <Tag key={item.value} color={item.color}>
                {item.label} {entries.length}项
                {executed > 0 ? `，实际${executed}项` : ""}
              </Tag>
            );
          })}
          <small>建议与执行分别统计，未批准对象保留。</small>
        </div>
        {active === "structure" && (
          <p className="multi-story-section-note">
            {before && after
              ? `交汇由当次前后构造分别计算：几何交汇 ${before.geometric} → ${after.geometric} 处，推测交汇 ${before.inferred} → ${after.inferred} 处。`
              : "此历史任务未保存完整的改前交汇图层，可查看已保存结果。"}
            实心点为实际相交，空心点为允许间距内的推测；不参与分析的线仍保留为灰色虚线。
          </p>
        )}
        {active === "lithology" && (
          <p className="multi-story-section-note">
            逐处核对代号、岩性类别与同单元图斑整理。修改由本次知识条件、实际空间测量与批准操作共同确定；涉及面积与覆盖变化面积在各处依据中分别展示。
          </p>
        )}
        {active === "alteration" && (
          <p className="multi-story-section-note">
            识别范围保留，处理状态与证据权重分开表达。降权对象继续参与后续分析，待裁定对象保留核查依据。
          </p>
        )}
      </details>
    </section>
  );
}
