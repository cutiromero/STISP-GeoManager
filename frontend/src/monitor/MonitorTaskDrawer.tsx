import "./monitor-task-drawer.css";
import { Alert, Button, Drawer, Space, Spin } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  BusinessFlowRun,
  BusinessFlowRunList,
  MonitoringProductList,
} from "../api/generated/types.gen";
import { businessFlowsApi } from "../api/businessFlows";
import BusinessFlowLaunch from "../businessflows/BusinessFlowLaunch";
import BusinessFlowActivity from "../businessflows/BusinessFlowActivity";
import { useAgentBootstrapState } from "../agent/useAgentBootstrap";
import { useComputeText } from "../compute/ui";

export default function MonitorTaskDrawer({
  page,
  flow,
  onChanged,
  onClose,
  records = false,
  startNew = false,
  title,
  initialInputs,
  inputLabels,
  parameters,
  launchOptions,
  launchKey,
}: {
  page?: MonitoringProductList;
  flow?: BusinessFlowRun;
  onChanged: (flow: BusinessFlowRun) => void;
  onClose: () => void;
  records?: boolean;
  startNew?: boolean;
  title: string;
  initialInputs: Record<string, number>;
  inputLabels: Record<number, string>;
  parameters?: import("react").ComponentProps<
    typeof BusinessFlowLaunch
  >["parameters"];
  launchOptions?: import("react").ReactNode;
  launchKey?: string;
}) {
  const ui = useComputeText();
  const navigate = useNavigate();
  const { bootstrap } = useAgentBootstrapState();
  const [launch, setLaunch] = useState(startNew);
  const [record, setRecord] = useState<BusinessFlowRun>();
  const displayed = records && record ? record : flow;
  const updateDisplayed = (next: BusinessFlowRun) => {
    if (records) setRecord(next);
    if (next.id === flow?.id) onChanged(next);
  };
  const [rows, setRows] = useState<BusinessFlowRunList["items"]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (!records) return;
    const controller = new AbortController();
    setLoading(true);
    void businessFlowsApi
      .runs({ signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted)
          setRows(
            result.items.filter(
              (row) => row.flowId === page?.businessFlow?.definitionId,
            ),
          );
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "无法读取处理记录",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [records, page?.businessFlow?.definitionId]);
  const openRecord = async (id: string) => {
    setLoading(true);
    setError(undefined);
    try {
      setRecord(await businessFlowsApi.run(id));
      setLaunch(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法打开处理记录");
    } finally {
      setLoading(false);
    }
  };
  const terminal =
    displayed &&
    ["succeeded", "failed", "cancelled", "interrupted"].includes(
      displayed.status,
    );
  return (
    <Drawer
      open
      title={title}
      size={600}
      onClose={onClose}
      className="monitor-task-drawer"
      destroyOnHidden
    >
      {error && <Alert type="error" title={error} />}
      {loading && <Spin />}
      {records && (
        <div className="monitor-task-records">
          {rows.map((row) => (
            <Button key={row.id} block onClick={() => void openRecord(row.id)}>
              {row.name} · {new Date(row.updatedAt).toLocaleString()}
            </Button>
          ))}
        </div>
      )}
      {!launch && displayed && (
        <>
          <BusinessFlowActivity flow={displayed} onChanged={updateDisplayed} />
          <Space wrap>
            <Button
              onClick={() =>
                navigate(
                  `/agent/workbench?projectTagId=${displayed.projectId}&conversationId=${displayed.conversationId}&runId=${displayed.runId}`,
                )
              }
            >
              {ui("在智能体中打开", "Open in agent")}
            </Button>
            <Button
              onClick={() =>
                navigate(
                  `/business-flows?projectTagId=${displayed.projectId}&flow=${displayed.flowId}&version=${displayed.versionId}`,
                )
              }
            >
              {ui("查看业务流", "View flow")}
            </Button>
            {terminal && (
              <Button onClick={() => setLaunch(true)}>
                {ui("新建解译任务", "New interpretation task")}
              </Button>
            )}
          </Space>
        </>
      )}
      {launch && page?.businessFlow && (
        <>
          {launchOptions}
          {bootstrap ? (
            <BusinessFlowLaunch
              key={launchKey}
              launch={page.businessFlow}
              model={bootstrap.defaultAgentModel}
              compact
              presentation="task"
              initialInputs={initialInputs}
              inputLabels={inputLabels}
              parameters={parameters}
              onStarted={(value) => {
                onChanged(value);
                setRecord(undefined);
                setLaunch(false);
              }}
              onCancel={onClose}
            />
          ) : (
            <Spin />
          )}
        </>
      )}
    </Drawer>
  );
}
