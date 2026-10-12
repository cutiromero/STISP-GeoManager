import { ArrowRightOutlined, NodeIndexOutlined } from "@ant-design/icons";
import { Alert, Button, Tag } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { agentApi } from "../api/agent";
import type { AgentResearchDemoList } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import { useComputeText } from "../compute/ui";
import { createUuid } from "../utils/uuid";
import "./research-demo-showcase.css";

export default function ResearchDemoShowcase() {
  const { user } = useAppContext();
  const project = useProjectContext();
  const navigate = useNavigate();
  const ui = useComputeText();
  const [items, setItems] = useState<AgentResearchDemoList["items"]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!user) return;
    let disposed = false;
    void agentApi.researchDemos().then(
      (data) => {
        if (!disposed) setItems(Array.isArray(data.items) ? data.items : []);
      },
      (reason: unknown) => {
        if (disposed) return;
        const status =
          typeof reason === "object" && reason && "status" in reason
            ? Number(reason.status)
            : 0;
        if (![401, 403].includes(status))
          setError(
            reason instanceof Error
              ? reason.message
              : ui("案例暂时无法加载", "Unable to load demonstrations"),
          );
      },
    );
    return () => {
      disposed = true;
    };
  }, [user?.id]);
  if (!items.length && !error) return null;
  return (
    <section
      className="research-demo-showcase"
      aria-label={ui("智能科研体验", "Research demonstrations")}
    >
      <div className="research-demo-showcase-heading">
        <div>
          <span className="research-demo-eyebrow">
            {ui("智能科研体验", "Research demonstrations")}
          </span>
          <h2>
            {ui(
              "用一句话，开启一项研究",
              "Start a research task with a request",
            )}
          </h2>
          <p>
            {ui(
              "从问题出发，联动数据、算法与知识，沿着实际结果推进判断。",
              "Connect data, algorithms and knowledge, then follow the actual results.",
            )}
          </p>
        </div>
        <Tag color="blue">
          {ui("实际计算 · 可追溯依据", "Real computation · traceable evidence")}
        </Tag>
      </div>
      {error && <Alert type="warning" title={error} />}
      <div className="research-demo-list">
        {items.map((item) => (
          <article
            key={`${item.projectId}:${item.scenario}`}
            className="research-demo-entry"
          >
            <span className="research-demo-symbol">
              <NodeIndexOutlined />
            </span>
            <div className="research-demo-entry-body">
              <h3>{item.title}</h3>
              <Tag color="blue">
                {item.sampleNature === "real_map_with_demonstration_errors"
                  ? ui(
                      "真实底图 · 演示录入错误",
                      "Real map · demonstration entry errors",
                    )
                  : ui(
                      "模拟资料 · 真实计算",
                      "Synthetic inputs · real computation",
                    )}
              </Tag>
              <p>
                {item.scenario === "geology_age_correction"
                  ? ui(
                      "读取真实地质图副本，按辞书与适用条件修正时代录入，复核并查看前后地图。",
                      "Check age entries in a real-map copy using dictionary conditions, then review the before and after maps.",
                    )
                  : item.scenario === "ecology_investigation"
                    ? ui(
                        "发现植被变化，解释线索，安排调查；补充观测后更新建议。",
                        "Discover vegetation changes, explain evidence and update investigation priorities.",
                      )
                    : ui(
                        "检查填图问题，依据调查与规则纠偏，复核并对照地图。",
                        "Check mapping issues, correct them using evidence and compare the maps.",
                      )}
              </p>
              <span className="research-demo-project">{item.projectName}</span>
            </div>
            <Button
              type="primary"
              aria-label={`${item.available ? ui("开始体验", "Try it") : ui("准备中", "Preparing")}：${item.title}`}
              icon={<ArrowRightOutlined />}
              iconPlacement="end"
              disabled={
                !item.available ||
                !project?.projects.some((entry) => entry.id === item.projectId)
              }
              onClick={() =>
                project?.choose(
                  String(item.projectId),
                  () =>
                    navigate("/agent/workbench", {
                      state: { researchDemo: { ...item, token: createUuid() } },
                    }),
                  { confirm: false },
                )
              }
            >
              {item.available
                ? ui("开始体验", "Try it")
                : ui("准备中", "Preparing")}
            </Button>
          </article>
        ))}
      </div>
    </section>
  );
}
