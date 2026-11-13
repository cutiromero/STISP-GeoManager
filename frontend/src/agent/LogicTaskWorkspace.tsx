import {
  CheckOutlined,
  FileTextOutlined,
  MoreOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  QuestionCircleOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { Alert, Button, Drawer, Dropdown, Modal, Spin, Tabs, Tag } from "antd";
import { useEffect, useRef, useState } from "react";
import { record } from "../map/geologyReviewData";
import { deletedWorkflowResources } from "./deletedWorkflowResources";
import { workflowNextAction } from "./workflowFeedback";
import {
  logicCurrentTitle,
  logicOutputIds,
  logicPhase,
  logicPhases,
  logicRunning,
  logicStageNames,
  logicStatus,
  logicTasks,
} from "./logicTaskPresentation";
import {
  LogicResultReview,
  LogicTaskCalculationList,
  LogicTaskProcess,
  LogicTaskSettings,
} from "./LogicTaskPanels";
import LogicTaskThinking from "./LogicTaskThinking";
import LogicReportAction from "./LogicReportAction";
import WorkflowModelActivity from "./WorkflowModelActivity";
import WorkflowDecisionTimeline from "./WorkflowDecisionTimeline";
import ThinkingStream from "./ThinkingStream";
import MultiElementStory from "./MultiElementStory";
import RetainedIssueReview from "./RetainedIssueReview";
import PreviousLogicResults from "./PreviousLogicResults";
import RunComputeTasks from "./RunComputeTasks";
import WorkflowReportFile from "./WorkflowReportFile";
import SafeMarkdown from "./SafeMarkdown";
import { useLogicTaskDetail } from "./useLogicTaskDetail";
import type { LogicTaskProps } from "./logicTaskTypes";
import "./logic-task-workspace.css";

type DrawerKind = "data" | "records" | "retained" | "thinking" | "calculations";

export default function LogicTaskWorkspace(props: LogicTaskProps) {
  const {
    workflow,
    busy = false,
    compact = false,
    onCancel,
    onPause,
    onResume,
    onConfirm,
    onReview,
    onRestart,
    inputReview,
    inputSummary = [],
    initialThinking,
    onAdjustInputs,
    onReviewRetained,
    onRetryImports,
    reviewError,
  } = props;
  const [view, setView] = useState("overview");
  const [drawer, setDrawer] = useState<DrawerKind>();
  const [stopOpen, setStopOpen] = useState(false);
  const {
    stepsDetail,
    suggestionsDetail,
    retainedDetail,
    loading,
    error,
    part,
    load,
  } = useLogicTaskDetail(workflow);
  const loadRef = useRef(load);
  loadRef.current = load;
  const key = `${workflow.projectId}:${workflow.id}`;
  const needsApproval =
    workflow.status === "waiting_approval" &&
    workflow.plan.phase === "review_modifications";
  const retainedOnly = Boolean(record(workflow.plan.retainedReview).active);
  const approvalPart = retainedOnly ? "retained" : "suggestions";
  useEffect(() => {
    setView("overview");
    setDrawer(undefined);
    setStopOpen(false);
  }, [key]);
  useEffect(() => {
    let disposed = false;
    const read = async () => {
      if (needsApproval) await loadRef.current(approvalPart);
      if (disposed || (workflow.view !== "card" && drawer !== "retained"))
        return;
      if (drawer && drawer !== "thinking")
        await loadRef.current(drawer === "retained" ? "retained" : "steps");
    };
    void read();
    return () => {
      disposed = true;
    };
  }, [
    key,
    workflow.view,
    needsApproval,
    workflow.planHash,
    drawer,
    approvalPart,
  ]);
  const detail =
    (drawer === "retained" ? retainedDetail : stepsDetail) ?? workflow;
  const loadedApproval = retainedOnly ? retainedDetail : suggestionsDetail;
  const approvalDetail = loadedApproval ?? workflow;
  const snapshotReady =
    drawer === "retained"
      ? Boolean(retainedDetail)
      : Boolean(stepsDetail) || workflow.view !== "card";
  const approvalReady =
    Boolean(loadedApproval || (!retainedOnly && workflow.view !== "card")) &&
    approvalDetail.planHash === workflow.planHash;
  const summary = workflow.taskSummary;
  const phase = logicPhase(workflow);
  const done = workflow.status === "succeeded";
  const stopped = ["failed", "interrupted", "cancelled"].includes(
    workflow.status,
  );
  const deleted = deletedWorkflowResources(workflow);
  const taskIds = logicTasks(workflow);
  const names = logicStageNames(workflow);
  const canMap =
    !deleted.length &&
    (workflow.resultResourceIds.length > 0 || taskIds.length > 0);
  const canStop = Boolean(
    onCancel &&
    [
      "queued",
      "running",
      "waiting_compute",
      "waiting_approval",
      "paused",
    ].includes(workflow.status),
  );
  const sourceCount =
    summary?.sourceCount ?? (inputSummary.length || undefined);
  const compare = (
    <Button
      type={compact ? "default" : "primary"}
      size={compact ? "small" : undefined}
      className="logic-map-link"
      target="_blank"
      rel="noopener"
      href={`/map?geologyReview=${encodeURIComponent(workflow.id)}&projectTagId=${workflow.projectId}`}
    >
      <span>查看前后对比</span>
    </Button>
  );
  const displayed = {
    ...approvalDetail,
    status: workflow.status,
    detail: workflow.detail,
    pauseRequested: workflow.pauseRequested,
    modelActivity: workflow.modelActivity,
    planHash: workflow.planHash,
    plan: {
      ...approvalDetail.plan,
      phase: workflow.plan.phase,
      stageIndex: workflow.plan.stageIndex,
    },
  };
  const refresh = () => void load(part, false, true);
  const more = [
    { key: "data", label: "本次资料与设置" },
    { key: "thinking", label: "查看分析过程" },
    { key: "records", label: "完整运行记录" },
    ...(taskIds.length ? [{ key: "calculations", label: "实际计算记录" }] : []),
    ...(canStop ? [{ key: "stop", label: "停止任务", danger: true }] : []),
  ];
  const metrics = [
    {
      key: "executed",
      label: "已执行处置",
      value: summary?.executedDispositionCount,
    },
    {
      key: "remaining",
      label: "复查剩余记录",
      value: summary?.remainingIssueCount,
    },
    {
      key: "prospect",
      label: "优先核查远景区",
      value: summary?.prospectZoneCount,
    },
  ];
  const progressText =
    summary && summary.totalCalculations > 0
      ? `已完成 ${summary.completedCalculations}/${summary.totalCalculations} 项实际计算`
      : undefined;
  const preparing = workflow.plan.phase === "review_mapping";
  const overview = (
    <div className="logic-overview">
      <div className="logic-stage-title">
        {logicRunning(workflow) && <Spin size="small" />}
        <h4>{logicCurrentTitle(workflow)}</h4>
      </div>
      {deleted.length > 0 && (
        <Alert
          type="info"
          title="部分历史成果已删除"
          description="任务与分析记录保留，重新处理时请另选资料。"
        />
      )}
      {canMap && !done && (
        <div className="logic-primary-actions">
          {compare}
          <span className="logic-description">
            {compact
              ? "可先查看当前资料与阶段成果。"
              : "可先查看当前资料与阶段成果，后续结果生成后在对比页刷新。"}
          </span>
        </div>
      )}
      {preparing && workflow.status === "waiting_approval" ? (
        (inputReview ?? <p>正在恢复资料与字段核对内容…</p>)
      ) : needsApproval ? (
        <>
          <p className="logic-description">
            请核对当前建议和执行范围；未选择及待裁定的对象保持原样。
          </p>
          {loading && !approvalReady ? (
            <div className="logic-loading">
              <Spin size="small" />
              正在读取建议…
            </div>
          ) : approvalReady && retainedOnly ? (
            <>
              <RetainedIssueReview
                key={workflow.planHash}
                workflow={displayed}
                busy={busy}
                onReview={onReview}
                reviewError={reviewError}
              />
              {displayed.modificationReview &&
                displayed.modificationReview.suggestions.length <
                  Number(record(displayed.plan.reviewIndex).total ?? 0) && (
                  <Button
                    loading={loading}
                    onClick={() => void load("retained", true)}
                  >
                    读取更多待核查对象
                  </Button>
                )}
            </>
          ) : approvalReady ? (
            <MultiElementStory
              workflow={displayed}
              focus="review"
              busy={busy}
              onReview={onReview}
              reviewError={reviewError}
            />
          ) : (
            <Button
              loading={loading}
              onClick={() => void load(approvalPart, false, true)}
            >
              读取最新处置建议
            </Button>
          )}
        </>
      ) : workflow.status === "waiting_approval" &&
        workflow.plan.phase === "review_results" ? (
        <>
          <LogicResultReview
            workflow={displayed}
            busy={busy}
            onReview={onReview}
            reviewError={reviewError}
          />
          <Button onClick={() => setView("files")}>查看候选成果</Button>
        </>
      ) : workflow.status === "waiting_approval" ? (
        <>
          {workflow.plan.reusedConfiguration === true && (
            <p className="logic-description">沿用上次已确认的角色和字段</p>
          )}
          <p>资料与算法已准备好，请核对本次资料和执行范围后继续。</p>
          <div className="logic-primary-actions">
            <Button
              type="primary"
              loading={busy}
              disabled={!onConfirm}
              onClick={onConfirm}
            >
              确认并继续
            </Button>
            <Button onClick={() => setDrawer("data")}>核对执行范围</Button>
            {workflow.plan.reusedConfiguration === true && onAdjustInputs && (
              <Button disabled={busy} onClick={onAdjustInputs}>
                修改角色和字段
              </Button>
            )}
          </div>
        </>
      ) : done ? (
        <>
          <p className="logic-description">
            修正成果已另存，待核查对象见下方清单。
          </p>
          {metrics.some((m) => m.value != null) && (
            <div className="logic-result-metrics" aria-label="实际结果统计">
              {metrics.map((metric) => (
                <div key={metric.key}>
                  <strong>
                    {metric.value == null
                      ? "—"
                      : metric.value.toLocaleString("zh-CN")}
                  </strong>
                  <span>{metric.label}</span>
                </div>
              ))}
            </div>
          )}
          <p className="logic-stat-note">
            处置数量与复查问题口径不同，降权后仍可能保留问题记录。
          </p>
          <div className="logic-primary-actions">
            {canMap && compare}
            <LogicReportAction
              workflowId={workflow.id}
              projectId={workflow.projectId}
            />
            <Button type="link" onClick={() => setView("files")}>
              查看全部成果
            </Button>
          </div>
          {summary?.retainedIssueCount != null &&
            summary.retainedIssueCount > 0 && (
              <div className="logic-retained-summary">
                <QuestionCircleOutlined />
                <div>
                  <strong>
                    {summary.retainedIssueCount} 条待裁定与例外已保留
                  </strong>
                  <p>查看具体对象和依据，再决定后续核查。</p>
                </div>
                <Button type="link" onClick={() => setDrawer("retained")}>
                  查看对象 <RightOutlined />
                </Button>
                {onReviewRetained && (
                  <Button
                    type="primary"
                    loading={busy}
                    onClick={onReviewRetained}
                  >
                    核查并选择处置
                  </Button>
                )}
              </div>
            )}
          {workflow.detail && (
            <details className="logic-result-explanation">
              <summary>结论说明</summary>
              <SafeMarkdown text={workflow.detail} />
            </details>
          )}
        </>
      ) : stopped || workflow.status === "paused" ? (
        <>
          <Alert
            type={workflow.status === "failed" ? "error" : "info"}
            title={workflow.detail}
          />
          <p className="logic-description">
            {workflow.status === "failed" &&
            workflow.plan.phase === "waiting_compute" &&
            workflow.detail.startsWith("结果入库失败")
              ? "实际计算已完成，输出文件保留。可重试入库并接着复查，无需重新计算。"
              : workflowNextAction(workflow)}
          </p>
          <div className="logic-primary-actions">
            {workflow.status === "failed" &&
            workflow.plan.phase === "waiting_compute" &&
            workflow.detail.startsWith("结果入库失败") &&
            onRetryImports ? (
              <Button type="primary" loading={busy} onClick={onRetryImports}>
                重试成果入库
              </Button>
            ) : stopped && onRestart ? (
              <Button type="primary" disabled={busy} onClick={onRestart}>
                调整后重新分析
              </Button>
            ) : null}
            {workflow.resultResourceIds.length > 0 && (
              <Button onClick={() => setView("files")}>查看已保存成果</Button>
            )}
            <Button onClick={() => setDrawer("records")}>查看原因与记录</Button>
          </div>
        </>
      ) : (
        <>
          <p className="logic-description">
            {workflow.status === "queued"
              ? "任务已保存，执行资源可用后会从当前步骤继续。"
              : workflow.detail}
          </p>
          <p className="logic-running-note">
            {workflow.pauseRequested
              ? "当前步骤到达保存点后停止后续处理。"
              : workflow.status === "queued"
                ? "无需重复提交或重新确认资料。"
                : "当前无需操作，任务进度会持续保存。"}
            {!compact && progressText && ` ${progressText}。`}
          </p>
        </>
      )}
      <LogicTaskThinking
        workflow={workflow}
        initialThinking={initialThinking}
        onExpand={() => setDrawer("thinking")}
      />
      {!preparing && (
        <div className="logic-input-summary">
          <FileTextOutlined />
          <span>
            {sourceCount ? `本次使用 ${sourceCount} 份资料` : "本次任务资料"}
          </span>
          <Button type="link" size="small" onClick={() => setDrawer("data")}>
            查看资料与设置
          </Button>
        </div>
      )}
    </div>
  );
  const files = (
    <div className="logic-files-panel">
      <p className="logic-description">
        最终成果优先显示，中间过程文件保持可追溯。
      </p>
      {!taskIds.length && !done ? (
        <p>尚未生成计算成果。</p>
      ) : (
        <RunComputeTasks
          compact
          display="files"
          terminal={done || stopped}
          taskIds={taskIds}
          autoImport={workflow.importResults}
          refreshKey={`${key}:${workflow.status}:${workflow.operatorSteps}`}
          report={
            done ? (
              <WorkflowReportFile
                workflowId={workflow.id}
                projectId={workflow.projectId}
              />
            ) : undefined
          }
          taskDisplayNames={names}
          primaryTaskIds={(Array.isArray(workflow.plan.stages)
            ? workflow.plan.stages.map(record)
            : []
          )
            .filter((s) => s.name !== "check")
            .map((s) => String(s.taskId ?? ""))
            .filter(Boolean)}
          visibleOutputIds={logicOutputIds(workflow)}
          reviewing={workflow.status === "waiting_approval"}
        />
      )}
      <PreviousLogicResults workflow={workflow} />
    </div>
  );
  return (
    <section
      className={`logic-task-workspace${compact ? " is-compact" : ""}`}
      aria-label="工作流进度卡片"
    >
      <header className="logic-task-header">
        <div>
          <div className="logic-task-heading">
            <h3>
              {compact
                ? "专业分析详情"
                : workflow.workflowType === "geology_generic"
                  ? "地质综合分析"
                  : "海德乌拉地质综合分析"}
            </h3>
            <Tag
              color={
                done
                  ? "success"
                  : workflow.status === "failed"
                    ? "error"
                    : workflow.status === "waiting_approval" ||
                        workflow.status === "paused"
                      ? "warning"
                      : "processing"
              }
            >
              {logicStatus(workflow)}
            </Tag>
          </div>
          {!compact && <p>逻辑推理 · 本次资料</p>}
        </div>
        <div className="logic-header-actions">
          {!compact && logicRunning(workflow) && onPause && (
            <Button
              aria-label="暂停"
              icon={<PauseOutlined />}
              disabled={busy || workflow.pauseRequested}
              onClick={onPause}
            >
              暂停
            </Button>
          )}
          {!compact &&
            workflow.status === "paused" &&
            onResume &&
            !deleted.length && (
              <Button
                type="primary"
                aria-label="继续"
                icon={<PlayCircleOutlined />}
                loading={busy}
                onClick={onResume}
              >
                继续
              </Button>
            )}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: more,
              onClick: ({ key: action }) =>
                action === "stop"
                  ? setStopOpen(true)
                  : setDrawer(action as DrawerKind),
            }}
          >
            <Button
              aria-label="更多任务操作"
              size={compact ? "small" : undefined}
              disabled={busy}
              icon={<MoreOutlined />}
            >
              更多
            </Button>
          </Dropdown>
        </div>
      </header>
      {!compact && (
        <ol className="logic-phase-bar" aria-label="四个分析阶段">
          {logicPhases.map((name, index) => (
            <li
              key={name}
              className={
                index < phase
                  ? "is-complete"
                  : index === phase
                    ? "is-current"
                    : ""
              }
              aria-current={index === phase ? "step" : undefined}
            >
              <span className="logic-phase-track" />
              <span>
                {index < phase && <CheckOutlined />}
                {name}
              </span>
            </li>
          ))}
        </ol>
      )}
      <Tabs
        activeKey={view}
        onChange={setView}
        destroyOnHidden={false}
        items={[
          { key: "overview", label: "概览", children: overview },
          {
            key: "files",
            label: "成果",
            children: view === "files" ? files : null,
          },
          {
            key: "process",
            label: "过程与依据",
            children: (
              <LogicTaskProcess
                workflow={workflow}
                onRecords={() => setDrawer("records")}
                onEvidence={() => setDrawer("data")}
              />
            ),
          },
        ]}
      />
      {(error || (reviewError && !needsApproval)) && (
        <Alert
          type="warning"
          title={error || reviewError}
          action={
            error ? (
              <Button size="small" loading={loading} onClick={refresh}>
                重试读取
              </Button>
            ) : undefined
          }
        />
      )}
      <Drawer
        title={
          {
            data: "本次资料与设置",
            records: "完整运行记录",
            retained: "待裁定与例外依据",
            thinking: "分析过程",
            calculations: "实际计算记录",
          }[drawer ?? "data"]
        }
        open={Boolean(drawer)}
        size={drawer === "retained" ? 800 : 680}
        styles={{ wrapper: { maxWidth: "100%" } }}
        onClose={() => setDrawer(undefined)}
        className={
          drawer === "retained"
            ? "logic-task-drawer logic-retained-drawer"
            : "logic-task-drawer"
        }
      >
        {drawer !== "thinking" && (
          <div className="logic-detail-toolbar">
            <span>详情按读取时的状态保留，不打断当前阅读。</span>
            <Button
              size="small"
              loading={loading}
              onClick={() =>
                void load(
                  drawer === "retained" ? "retained" : "steps",
                  false,
                  true,
                )
              }
            >
              读取最新记录
            </Button>
          </div>
        )}
        {error && <Alert type="warning" title={error} />}
        {loading && !snapshotReady ? (
          <div className="logic-loading">
            <Spin size="small" />
            正在读取详情…
          </div>
        ) : drawer === "data" ? (
          <LogicTaskSettings workflow={detail} inputs={inputSummary} />
        ) : drawer === "thinking" ? (
          <>
            {workflow.modelActivity ? (
              <WorkflowModelActivity workflow={workflow} />
            ) : (
              <p>暂无分析记录。</p>
            )}
            {initialThinking &&
              initialThinking !== workflow.modelActivity?.thinkingText && (
                <details open={!workflow.modelActivity}>
                  <summary>资料识别阶段的实际思考</summary>
                  <ThinkingStream text={initialThinking} working={false} />
                </details>
              )}
            {!workflow.modelActivity && !initialThinking && (
              <p>没有收到可展示的实际思考内容。</p>
            )}
          </>
        ) : drawer === "records" ? (
          <>
            <WorkflowDecisionTimeline steps={detail.steps} taskNames={names} />
            {detail.steps.length < (detail.stepCount ?? 0) && (
              <Button
                loading={loading}
                onClick={() => void load("steps", true)}
              >
                读取更多运行记录
              </Button>
            )}
          </>
        ) : drawer === "retained" ? (
          <>
            {summary?.retainedIssueCount != null && (
              <p>
                当前保留 {summary.retainedIssueCount} 条：待裁定{" "}
                {summary.reviewIssueCount ?? "—"} 条，例外{" "}
                {summary.exceptionIssueCount ?? "—"} 条。
              </p>
            )}
            {snapshotReady ? (
              <>
                <RetainedIssueReview
                  key={detail.planHash}
                  workflow={detail}
                  readonly
                />
                {detail.modificationReview &&
                  detail.modificationReview.suggestions.length <
                    Number(record(detail.plan.reviewIndex).total ?? 0) && (
                    <Button
                      loading={loading}
                      onClick={() => void load("retained", true)}
                    >
                      读取更多保留对象
                    </Button>
                  )}
              </>
            ) : (
              <p>正在读取对象依据…</p>
            )}
          </>
        ) : drawer === "calculations" ? (
          <>
            <LogicTaskCalculationList workflow={workflow} />
            <RunComputeTasks
              compact
              display="tasks"
              terminal={done || stopped}
              taskIds={taskIds}
              autoImport={workflow.importResults}
              refreshKey={`${key}:${workflow.status}:${workflow.operatorSteps}`}
              taskDisplayNames={names}
            />
          </>
        ) : null}
      </Drawer>
      <Modal
        title="停止本次任务？"
        open={stopOpen}
        okText="停止任务"
        cancelText="继续处理"
        okButtonProps={{ danger: true }}
        onCancel={() => setStopOpen(false)}
        onOk={() => {
          setStopOpen(false);
          onCancel?.();
        }}
      >
        <p>停止后续处理，已提交的计算可能继续完成。已有文件与记录保持。</p>
      </Modal>
    </section>
  );
}
