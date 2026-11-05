import {
  AimOutlined,
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Empty, Spin, Tag } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { agentApi } from "../api/agent";
import type {
  AgentWorkflow,
  GeoJsonFeatureCollection,
} from "../api/generated/types.gen";
import WorkflowReportFile from "../agent/WorkflowReportFile";
import {
  geologyReviewOutcome,
  geologyReviewOutcomeDescription,
  geologyReviewOutcomeLabel,
} from "../agent/geologyReviewOutcome";
import { getActiveProject } from "../projects/session";
import { useProjectContext } from "../projects/ProjectContext";
import GeologyReviewMaps from "./GeologyReviewMaps";
import MultiElementWorkspace from "./MultiElementWorkspace";
import {
  previewSuggestions,
  queryReviewMap,
  reviewBounds,
  reviewResourceIds,
  reviewSuggestionIndex,
} from "./geologyReviewData";
import "./geology-review-workspace.css";
import { isMultiElementFamily } from "../agent/multiElementScenario";
import { formatArea } from "../utils/area";

type Maps = {
  before: GeoJsonFeatureCollection;
  after: GeoJsonFeatureCollection | null;
  differences: GeoJsonFeatureCollection;
};

export default function GeologyReviewWorkspace({
  workflowId,
  projectTagId,
  suggestionId,
}: {
  workflowId: string;
  projectTagId: string | null;
  suggestionId: string | null;
}) {
  const navigate = useNavigate();
  const project = useProjectContext();
  const currentProject = project?.current ?? getActiveProject();
  const [workflow, setWorkflow] = useState<AgentWorkflow | null>(null);
  const [data, setData] = useState<Maps | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState(0);
  const [focus, setFocus] = useState<[number, number, number, number] | null>(
    null,
  );
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      setError("");
      setLoading(true);
      setData(null);
      setWorkflow(null);
      try {
        if (projectTagId && projectTagId !== currentProject)
          throw new Error("请切换到检查任务所属项目后查看");
        const value = await agentApi.workflow(workflowId, {
          view: "compare",
          limit: 25,
          suggestionId: suggestionId ?? undefined,
        });
        if (disposed) return;
        if (
          !(
            value.workflowType === "geology_map_review" ||
            isMultiElementFamily(value.workflowType)
          )
        )
          throw new Error("此任务不属于地质成果检查案例");
        if (
          String(value.projectId) !== currentProject ||
          getActiveProject() !== currentProject
        )
          throw new Error("检查任务不属于当前项目，请切换项目后查看");
        if (isMultiElementFamily(value.workflowType)) {
          setWorkflow(value);
          return;
        }
        const ids = reviewResourceIds(value);
        const outcome = geologyReviewOutcome(value);
        if (!ids.before) throw new Error("检查记录尚无可用的待检查地质图");
        if (outcome && (ids.after || ids.differences))
          throw new Error("检查记录与修正成果不一致，请核对任务状态");
        if (
          (ids.after || ids.differences) &&
          !value.modificationReview?.approvedSuggestionIds.length
        )
          throw new Error("修正成果缺少已保存的批准记录，请先核对任务状态");
        if (Boolean(ids.after) !== Boolean(ids.differences))
          throw new Error("修正结果与实际修改范围尚未全部就绪，请稍后刷新");
        const [before, after, actual] = await Promise.all([
          queryReviewMap(ids.before, { loadStyle: true }),
          ids.after
            ? queryReviewMap(ids.after, { loadStyle: true })
            : Promise.resolve(null),
          ids.differences
            ? queryReviewMap(ids.differences)
            : Promise.resolve(null),
        ]);
        if (disposed) return;
        const differences: GeoJsonFeatureCollection = outcome
          ? { type: "FeatureCollection", features: [] }
          : (actual ?? previewSuggestions(value));
        setWorkflow(value);
        setData({ before, after, differences });
        const target = reviewSuggestionIndex(value, differences, suggestionId);
        setSelected(Math.max(0, target));
        const targetFeature =
          target >= 0 ? differences.features[target] : undefined;
        setFocus(
          targetFeature
            ? reviewBounds({
                type: "FeatureCollection",
                features: [targetFeature],
              })
            : reviewBounds(before),
        );
      } catch (reason) {
        if (!disposed)
          setError(reason instanceof Error ? reason.message : "地图读取失败");
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    void load();
    return () => {
      disposed = true;
    };
  }, [workflowId, projectTagId, currentProject, reload, suggestionId]);
  const current = data?.differences.features[selected];
  const properties = current?.properties ?? {};
  const actual = Boolean(data?.after);
  const outcome = geologyReviewOutcome(workflow);
  const editSubmitted =
    workflow &&
    Array.isArray(workflow.plan.stages) &&
    workflow.plan.stages.some(
      (stage) =>
        stage &&
        typeof stage === "object" &&
        "identifier" in stage &&
        stage.identifier === "geology-map-correct" &&
        "taskId" in stage &&
        Boolean(stage.taskId),
    );
  const summary = useMemo(() => {
    const features = data?.differences.features ?? [];
    const ids = new Set(
      features.map((feature) => feature.properties.feature_id),
    );
    const area = features.reduce(
      (sum, feature) =>
        sum +
        (feature.properties.kind === "fill_gap"
          ? Number(feature.properties.area_m2 ?? 0)
          : 0),
      0,
    );
    return { count: ids.size, area: Number.isFinite(area) ? area : 0 };
  }, [data]);
  const locate = (index: number) => {
    setSelected(index);
    const feature = data?.differences.features[index];
    if (feature)
      setFocus(
        reviewBounds({ type: "FeatureCollection", features: [feature] }),
      );
  };
  if (
    workflow &&
    isMultiElementFamily(workflow.workflowType) &&
    String(workflow.projectId) === currentProject
  )
    return (
      <MultiElementWorkspace
        workflow={workflow}
        suggestionId={suggestionId}
        onReload={() => setReload((value) => value + 1)}
        onPage={async (offset) => {
          const next = await agentApi.workflow(workflowId, {
            view: "compare",
            limit: 25,
            offset,
          });
          if (getActiveProject() !== currentProject) return;
          if (next.planHash !== workflow.planHash)
            throw new Error("成果已更新，请刷新后继续浏览");
          setWorkflow(next);
        }}
      />
    );
  return (
    <main className="geology-review-workspace">
      <header className="geology-review-workspace-header">
        <div>
          <span className="geology-review-eyebrow">地理工作台演示案例</span>
          <h1>地质成果智能检查与修正</h1>
          <p>
            {outcome
              ? geologyReviewOutcomeDescription(outcome)
              : actual
                ? "两张地图共享视角与类别配色，橙色边界标出算法实际修改的位置。"
                : editSubmitted
                  ? "修正任务已提交，当前显示获批建议；结果就绪后可刷新对照。"
                  : "核对建议的位置、依据和范围，返回对话选择批准后执行。"}
          </p>
        </div>
        <div className="geology-review-workspace-actions">
          {workflow && (
            <Button
              onClick={() =>
                navigate(
                  `/map?geologyCompare=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}${suggestionId ? `&suggestion=${encodeURIComponent(suggestionId)}` : ""}`,
                )
              }
            >
              在地理工作台对比
            </Button>
          )}
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate("/agent/workbench")}
          >
            返回对话
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => setReload((value) => value + 1)}
          >
            刷新结果
          </Button>
          {!outcome && (
            <Button
              type="primary"
              icon={<AimOutlined />}
              disabled={!data?.differences.features.length}
              onClick={() => locate(selected)}
            >
              定位修改处
            </Button>
          )}
        </div>
      </header>
      {error && <Alert type="error" showIcon title={error} />}
      {loading && (
        <div className="geology-review-workspace-loading">
          <Spin />
          正在读取真实图件与检查记录…
        </div>
      )}
      {data && workflow && String(workflow.projectId) === currentProject && (
        <>
          <div className="geology-review-workspace-body">
            <section className="geology-review-map-area">
              <GeologyReviewMaps
                {...data}
                bounds={focus}
                onSelect={locate}
                inspectionOnly={Boolean(outcome)}
                previewLabel={
                  outcome
                    ? "检查后原图，保持不变"
                    : editSubmitted
                      ? "建议范围，修正结果准备中"
                      : "建议修改范围，尚未执行"
                }
              />
            </section>
            <aside className="geology-review-map-inspector">
              <Tag color={actual || outcome === "no_changes" ? "blue" : "gold"}>
                {outcome
                  ? geologyReviewOutcomeLabel(outcome)
                  : actual
                    ? "真实修正结果"
                    : editSubmitted
                      ? "修正结果准备中"
                      : "建议修改，尚未执行"}
              </Tag>
              <h2>
                {outcome
                  ? "本轮检查结果"
                  : actual
                    ? "实际修改了哪里"
                    : "发现的问题"}
              </h2>
              <p>
                {outcome
                  ? geologyReviewOutcomeDescription(outcome)
                  : actual
                    ? `本次修改涉及${summary.count}个图斑、${data.differences.features.length}条操作记录；补齐覆盖${(summary.area / 10000).toFixed(2)}公顷，其余为属性更新。`
                    : editSubmitted
                      ? "已提交修正任务，当前显示获批建议范围；实际修改结果就绪后请刷新查看。"
                      : "批准前展示的是建议范围，地图内容保持当前状态。"}
              </p>
              <div className="geology-review-change-list">
                {data.differences.features.map((feature, index) => (
                  <button
                    type="button"
                    key={String(
                      feature.id ??
                        feature.properties.issue_id ??
                        feature.properties.suggestion_id ??
                        feature.properties.feature_id,
                    )}
                    className={selected === index ? "is-selected" : ""}
                    onClick={() => locate(index)}
                  >
                    <span>
                      {feature.properties.kind === "fill_gap"
                        ? "填补内部漏填"
                        : "更新地层时代"}
                    </span>
                    <small>
                      {formatArea(Number(feature.properties.area_m2 ?? 0))}
                    </small>
                  </button>
                ))}
              </div>
              {current ? (
                <section className="geology-review-selected-change">
                  <h3>{actual ? "前后变化" : "建议修改"}</h3>
                  <dl>
                    <dt>当前状态</dt>
                    <dd>
                      {String(
                        properties.current_label ||
                          properties.old_value ||
                          "未分类",
                      )}
                    </dd>
                    <dt>{actual ? "修正后状态" : "建议状态"}</dt>
                    <dd>
                      {String(
                        properties.suggested_label ||
                          properties.new_value ||
                          "待核对",
                      )}
                    </dd>
                    <dt>原因与依据</dt>
                    <dd>
                      {String(
                        properties.verified_reason ||
                          properties.reason ||
                          "请查看检查报告",
                      )}
                    </dd>
                  </dl>
                  {actual && (
                    <p className="geology-review-verified">
                      <CheckCircleOutlined /> 算法输出的实际差异
                    </p>
                  )}
                </section>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    outcome === "no_changes"
                      ? "本轮没有需要修改的对象"
                      : outcome === "requires_evidence"
                        ? "请查看报告中的疑点和补充资料建议"
                        : "尚未形成修改建议"
                  }
                />
              )}
              <p className="geology-review-workspace-note">
                {outcome
                  ? "两侧显示同一份待检查地质图，本轮没有生成修正图。拖动、缩放任一地图，两边同步。"
                  : "点击橙色区域或上方条目查看变化；拖动、缩放任一地图，两边同步。"}
              </p>
            </aside>
          </div>
          {workflow.status === "succeeded" && (
            <div className="geology-review-workspace-report">
              <WorkflowReportFile
                workflowId={workflow.id}
                projectId={workflow.projectId}
              />
            </div>
          )}
        </>
      )}
    </main>
  );
}
