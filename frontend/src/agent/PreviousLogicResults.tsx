import { useState } from "react";
import type { AgentWorkflow } from "../api/generated/types.gen";
import { record } from "../map/geologyReviewData";
import RunComputeTasks from "./RunComputeTasks";
import { logicStageNames } from "./logicTaskPresentation";

export default function PreviousLogicResults({
  workflow,
}: {
  workflow: AgentWorkflow;
}) {
  const [open, setOpen] = useState<string[]>([]);
  const history = Array.isArray(workflow.plan.previousRounds)
    ? workflow.plan.previousRounds.map(record)
    : [];
  if (!history.length) return null;
  return (
    <section className="logic-previous-results" aria-label="上一轮成果">
      <h4>上一轮成果</h4>
      <p className="logic-muted">
        每轮的实际计算文件和记录分别保留，可按需读取。
      </p>
      {history.map((snapshot) => {
        const key = String(snapshot.planHash);
        const stages = Array.isArray(snapshot.stages)
          ? snapshot.stages.map(record)
          : [];
        const tasks = stages
          .map((stage) => String(stage.taskId ?? ""))
          .filter(Boolean);
        const names = logicStageNames({
          ...workflow,
          plan: { ...workflow.plan, stages },
        });
        return (
          <details key={key} open={open.includes(key)}>
            <summary
              onClick={(event) => {
                event.preventDefault();
                setOpen((previous) =>
                  previous.includes(key)
                    ? previous.filter((item) => item !== key)
                    : [...previous, key],
                );
              }}
            >
              查看已保存的一轮成果（{tasks.length} 项计算）
            </summary>
            {open.includes(key) && (
              <RunComputeTasks
                display="files"
                compact
                terminal
                taskIds={tasks}
                autoImport={workflow.importResults}
                refreshKey={key}
                taskDisplayNames={names}
                primaryTaskIds={stages
                  .filter((stage) => stage.name !== "check")
                  .map((stage) => String(stage.taskId ?? ""))
                  .filter(Boolean)}
              />
            )}
          </details>
        );
      })}
    </section>
  );
}
