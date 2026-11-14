import { Alert, Button, Drawer, Select, Space, Spin } from "antd";
import { useEffect, useMemo, useState } from "react";
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

export default function LandcoverTaskDrawer({
  page,
  flow,
  onChanged,
  onClose,
  records = false,
  startNew = false,
  defaultSourceId,
}: {
  page?: MonitoringProductList;
  flow?: BusinessFlowRun;
  onChanged: (flow: BusinessFlowRun) => void;
  onClose: () => void;
  records?: boolean;
  startNew?: boolean;
  defaultSourceId?: number;
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
  const [all, setAll] = useState(false);
  const [classes, setClasses] = useState("all");
  const [rows, setRows] = useState<BusinessFlowRunList["items"]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const resources = page?.inputResources ?? [];
  const initialInputs = useMemo(
    () =>
      Object.fromEntries(
        (all
          ? resources
          : resources.filter((resource) => resource.id === defaultSourceId)
                .length
            ? resources.filter((resource) => resource.id === defaultSourceId)
            : resources.slice(0, 1)
        ).map((resource) => [`image:${resource.id}`, resource.id]),
      ),
    [all, resources, defaultSourceId],
  );
  const inputLabels = useMemo(
    () =>
      Object.fromEntries(
        resources.map((resource) => [resource.id, resource.name]),
      ),
    [resources],
  );
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
      title={ui("地表覆盖任务", "Land-cover task")}
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
          <div className="monitor-task-options">
            <Button onClick={() => setAll((value) => !value)}>
              {all
                ? ui("使用当前样区", "Use current region")
                : ui("选择全部样区", "Select all regions")}
            </Button>
            <Select
              aria-label={ui("解译模式", "Interpretation mode")}
              value={classes}
              onChange={setClasses}
              options={[
                { value: "all", label: ui("完整六类", "Complete land cover") },
                { value: "building", label: ui("建筑提取", "Buildings") },
                { value: "water", label: ui("水体提取", "Water") },
                { value: "road", label: ui("道路提取", "Roads") },
                { value: "forest", label: ui("林地提取", "Forest") },
                { value: "farmland", label: ui("耕地提取", "Farmland") },
                {
                  value: "building,water",
                  label: ui("建筑与水体", "Buildings and water"),
                },
              ]}
            />
          </div>
          {bootstrap ? (
            <BusinessFlowLaunch
              key={`${all}:${classes}`}
              launch={page.businessFlow}
              model={bootstrap.defaultAgentModel}
              compact
              presentation="task"
              initialInputs={initialInputs}
              inputLabels={inputLabels}
              parameters={{ nodeParameters: { interpret: { classes } } }}
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
