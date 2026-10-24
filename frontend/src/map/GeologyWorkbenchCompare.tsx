import { LeftOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import { Alert, Button, Segmented, Spin } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { geologyReviewOutcome } from "../agent/geologyReviewOutcome";
import GeologyReviewMaps from "./GeologyReviewMaps";
import { reviewBounds, reviewSuggestionIndex } from "./geologyReviewData";
import {
  loadWorkbenchReviewComparison,
  type RegisterReviewLayer,
  type WorkbenchReviewComparison,
} from "./geologyWorkbenchCompareData";
import "./geology-review-workspace.css";
import "./geology-workbench-compare.css";

export default function GeologyWorkbenchCompare({
  workflowId,
  projectId,
  projectTagId,
  suggestionId,
  accessToken,
  canLoad,
  comparisonVisible,
  registerLayer,
  onVisibilityChange,
  onSuggestionChange,
  onSwitchProject,
}: {
  workflowId: string;
  projectId: string;
  projectTagId: string | null;
  suggestionId: string | null;
  accessToken: string;
  canLoad: boolean;
  comparisonVisible: boolean;
  registerLayer: RegisterReviewLayer;
  onVisibilityChange: (visible: boolean) => void;
  onSuggestionChange: (id: string | null) => void;
  onSwitchProject?: () => void;
}) {
  const [data, setData] = useState<WorkbenchReviewComparison | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(0);
  const latest = useRef({ registerLayer });
  latest.current = { registerLayer };
  useEffect(() => {
    let disposed = false;
    setData(null);
    setError("");
    setLoading(true);
    if (!canLoad) {
      setError("当前账号没有查询和加载检查成果图层的权限");
      setLoading(false);
      return;
    }
    void loadWorkbenchReviewComparison({
      workflowId,
      projectId,
      projectTagId,
      registerLayer: (profile, result) =>
        latest.current.registerLayer(profile, result),
      isCurrent: () => !disposed,
    })
      .then((value) => {
        if (!disposed) setData(value);
      })
      .catch((reason: unknown) => {
        if (!disposed)
          setError(
            reason instanceof Error ? reason.message : "检查成果读取失败",
          );
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [workflowId, projectId, projectTagId, canLoad, revision]);
  useEffect(() => {
    if (!data) return;
    setSelected(
      Math.max(
        0,
        reviewSuggestionIndex(data.workflow, data.differences, suggestionId),
      ),
    );
  }, [data, suggestionId]);
  const features = data?.differences.features ?? [];
  const current = features[selected];
  const properties = current?.properties ?? {};
  const outcome = geologyReviewOutcome(data?.workflow);
  const focus = current
    ? reviewBounds({ type: "FeatureCollection", features: [current] })
    : data
      ? reviewBounds(data.before)
      : null;
  const spotlight =
    current && data
      ? {
          before: {
            type: "FeatureCollection" as const,
            features:
              properties.kind === "fill_gap"
                ? [
                    {
                      ...current,
                      properties: { ...properties, _review_outlineOnly: true },
                    },
                  ]
                : data.before.features.filter(
                    (feature) =>
                      String(feature.properties.feature_id ?? feature.id) ===
                      String(properties.feature_id),
                  ),
          },
          after: {
            type: "FeatureCollection" as const,
            features:
              properties.kind === "fill_gap"
                ? [
                    {
                      ...current,
                      properties: {
                        ...properties,
                        _review_outlineOnly: !data.after,
                      },
                    },
                  ]
                : (data.after ?? data.before).features.filter(
                    (feature) =>
                      String(feature.properties.feature_id ?? feature.id) ===
                      String(properties.feature_id),
                  ),
          },
          beforeLabel: String(
            properties.current_label || properties.old_value || "未分类",
          ),
          afterLabel: String(
            properties.suggested_label || properties.new_value || "待核对",
          ),
        }
      : null;
  const select = (index: number) => {
    setSelected(index);
    const feature = features[index];
    const suggestion = data?.workflow.modificationReview?.suggestions.find(
      (item) =>
        item.id === feature?.properties.suggestion_id ||
        (item.featureId === String(feature?.properties.feature_id) &&
          item.kind === feature?.properties.kind),
    );
    onSuggestionChange(suggestion?.id ?? null);
  };
  return (
    <section
      className={`geology-workbench-compare ${comparisonVisible ? "is-comparing" : "is-single"}`}
      aria-label="地理工作台地质成果对比"
    >
      <header className="geology-workbench-compare-toolbar">
        <div>
          <strong>地质成果检查与修正</strong>
          <small>
            {comparisonVisible
              ? "同一视角核对修改，单图模式可管理图层与查询数据"
              : "成果已加载到图层，可查看属性、空间查询和导出"}
          </small>
        </div>
        <Segmented
          aria-label="地图显示方式"
          value={comparisonVisible ? "compare" : "single"}
          options={[
            { label: "单图", value: "single" },
            { label: "前后对比", value: "compare" },
          ]}
          onChange={(value) => onVisibilityChange(value === "compare")}
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => setRevision((value) => value + 1)}
        >
          刷新成果
        </Button>
        <Link
          to={`/map?geologyReview=${encodeURIComponent(workflowId)}&projectTagId=${projectId}`}
        >
          独立对比页
        </Link>
      </header>
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            onSwitchProject && (
              <Button onClick={onSwitchProject}>切换项目</Button>
            )
          }
        />
      )}
      {comparisonVisible && loading && (
        <div className="geology-workbench-compare-loading">
          <Spin />
          正在读取真实图件与检查记录…
        </div>
      )}
      {comparisonVisible && data && (
        <>
          <div className="geology-workbench-compare-maps">
            <GeologyReviewMaps
              before={data.before}
              after={data.after}
              differences={data.differences}
              bounds={focus}
              onSelect={select}
              accessToken={accessToken}
              beforeLabel={data.beforeName}
              afterLabel={data.afterName}
              inspectionOnly={Boolean(outcome)}
              previewLabel={outcome ? "检查后原图，保持不变" : data.afterName}
              compactLegend
              spotlight={spotlight}
            />
          </div>
          <div className="geology-workbench-compare-detail">
            {current ? (
              <>
                <nav aria-label="切换修改位置">
                  <Button
                    size="small"
                    icon={<LeftOutlined />}
                    disabled={selected === 0}
                    onClick={() => select(selected - 1)}
                  >
                    上一处
                  </Button>
                  <strong>
                    第 {selected + 1} 处，共 {features.length} 处
                  </strong>
                  <Button
                    size="small"
                    icon={<RightOutlined />}
                    disabled={selected >= features.length - 1}
                    onClick={() => select(selected + 1)}
                  >
                    下一处
                  </Button>
                </nav>
                <p>
                  <strong>{data.after ? "实际变化" : "建议修改"}：</strong>
                  {String(
                    properties.current_label ||
                      properties.old_value ||
                      "未分类",
                  )}
                  <span aria-hidden="true"> → </span>
                  {String(
                    properties.suggested_label ||
                      properties.new_value ||
                      "待核对",
                  )}
                </p>
                <p>
                  <strong>原因与依据：</strong>
                  {String(
                    properties.verified_reason ||
                      properties.reason ||
                      "详见检查报告",
                  )}
                </p>
              </>
            ) : (
              <p>
                {outcome
                  ? "本轮保留原图；检查结论与待核查事项见报告。"
                  : "当前尚无可显示的修改范围，请刷新成果或返回对话继续。"}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
