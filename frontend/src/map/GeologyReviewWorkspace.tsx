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
import { useAppContext } from "../contexts/AppContext";
import { getActiveProject } from "../projects/session";
import { useProjectContext } from "../projects/ProjectContext";
import GeologyReviewMaps from "./GeologyReviewMaps";
import {
  previewSuggestions,
  queryReviewMap,
  reviewBounds,
  reviewResourceIds,
  reviewSuggestionIndex,
} from "./geologyReviewData";
import "./geology-review-workspace.css";

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
  const { bootstrap } = useAppContext();
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
      try {
        if (projectTagId && projectTagId !== currentProject)
          throw new Error("请切换到检查任务所属项目后查看");
        const value = await agentApi.workflow(workflowId);
        if (disposed) return;
        if (value.workflowType !== "geology_map_review")
          throw new Error("此任务不属于地质成果检查案例");
        if (
          String(value.projectId) !== currentProject ||
          getActiveProject() !== currentProject
        )
          throw new Error("检查任务不属于当前项目，请切换项目后查看");
        const ids = reviewResourceIds(value);
        if (!ids.before) throw new Error("检查记录尚无可用的待检查地质图");
        if (
          (ids.after || ids.differences) &&
          !value.modificationReview?.approvedSuggestionIds.length
        )
          throw new Error("修正成果缺少已保存的批准记录，请先核对任务状态");
        if (Boolean(ids.after) !== Boolean(ids.differences))
          throw new Error("修正结果与实际修改范围尚未全部就绪，请稍后刷新");
        const [before, after, actual] = await Promise.all([
          queryReviewMap(ids.before),
          ids.after ? queryReviewMap(ids.after) : Promise.resolve(null),
          ids.differences
            ? queryReviewMap(ids.differences)
            : Promise.resolve(null),
        ]);
        if (disposed) return;
        const differences = actual ?? previewSuggestions(value);
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
      (sum, feature) => sum + Number(feature.properties.area_m2 ?? 0),
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
  return (
    <main className="geology-review-workspace">
      <header className="geology-review-workspace-header">
        <div>
          <span className="geology-review-eyebrow">地理工作台 · 演示案例</span>
          <h1>地质成果智能检查与修正</h1>
          <p>
            {actual
              ? "两张地图共享视角与类别配色，橙色边界标出算法实际修改的位置。"
              : editSubmitted
                ? "修正任务已提交，当前显示获批建议；结果就绪后可刷新对照。"
                : "核对建议的位置、依据和范围，返回对话选择批准后执行。"}
          </p>
        </div>
        <div className="geology-review-workspace-actions">
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
          <Button
            type="primary"
            icon={<AimOutlined />}
            disabled={!data?.differences.features.length}
            onClick={() => locate(selected)}
          >
            定位修改处
          </Button>
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
                accessToken={bootstrap.map.mapboxAccessToken}
                bounds={focus}
                onSelect={locate}
                previewLabel={
                  editSubmitted
                    ? "建议范围 · 修正结果准备中"
                    : "建议修改范围 · 尚未执行"
                }
              />
            </section>
            <aside className="geology-review-map-inspector">
              <Tag color={actual ? "blue" : "gold"}>
                {actual
                  ? "真实修正结果"
                  : editSubmitted
                    ? "修正结果准备中"
                    : "建议修改 · 尚未执行"}
              </Tag>
              <h2>{actual ? "实际修改了哪里" : "发现的问题"}</h2>
              <p>
                {actual
                  ? `本次修改涉及${summary.count}个图斑，范围合计${(summary.area / 10000).toFixed(2)}公顷。`
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
                      {Number(feature.properties.area_m2 ?? 0).toLocaleString(
                        "zh-CN",
                        { maximumFractionDigits: 1 },
                      )}{" "}
                      平方米
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
                  description="尚未形成修改建议"
                />
              )}
              <p className="geology-review-workspace-note">
                点击橙色区域或上方条目查看变化；拖动、缩放任一地图，两边同步。
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
