import { monitorTaskWritingGuidance } from "./productNarrative";
import { Button, Select } from "antd";
import { useMemo, useState, type ComponentProps } from "react";
import { useComputeText } from "../compute/ui";
import MonitorTaskDrawer from "./MonitorTaskDrawer";

type Props = Omit<
  ComponentProps<typeof MonitorTaskDrawer>,
  | "title"
  | "initialInputs"
  | "inputLabels"
  | "parameters"
  | "launchOptions"
  | "launchKey"
> & { defaultSourceId?: number };

export default function LandcoverTaskDrawer({
  defaultSourceId,
  ...props
}: Props) {
  const ui = useComputeText();
  const [all, setAll] = useState(false);
  const [classes, setClasses] = useState("all");
  const resources = props.page?.inputResources ?? [];
  const initialInputs = useMemo(
    () =>
      Object.fromEntries(
        (all
          ? resources
          : resources.filter((r) => r.id === defaultSourceId).length
            ? resources.filter((r) => r.id === defaultSourceId)
            : resources.slice(0, 1)
        ).map((r) => [`image:${r.id}`, r.id]),
      ),
    [all, resources, defaultSourceId],
  );
  const inputLabels = Object.fromEntries(resources.map((r) => [r.id, r.name]));
  return (
    <MonitorTaskDrawer
      {...props}
      page={
        props.page && {
          ...props.page,
          businessFlow: props.page.businessFlow && {
            ...props.page.businessFlow,
            goal: `${props.page.businessFlow.goal} ${monitorTaskWritingGuidance}`,
          },
        }
      }
      title={ui("地表覆盖任务", "Land-cover task")}
      initialInputs={initialInputs}
      inputLabels={inputLabels}
      parameters={{ nodeParameters: { interpret: { classes } } }}
      launchKey={`${all}:${classes}`}
      launchOptions={
        <div className="monitor-task-options">
          <Button onClick={() => setAll((v) => !v)}>
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
      }
    />
  );
}
