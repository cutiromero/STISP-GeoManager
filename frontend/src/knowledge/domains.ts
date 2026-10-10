import type { KnowledgeDomain } from "../api/generated/types.gen";

export const KNOWLEDGE_DOMAINS: {
  id: KnowledgeDomain;
  label: string;
  description: string;
  color: string;
}[] = [
  {
    id: "remote_sensing",
    label: "遥感基础",
    description: "传感器、光谱与影像预处理，连接数据和指数算法。",
    color: "#3176ab",
  },
  {
    id: "pipelines",
    label: "油气管道相关",
    description: "管道走廊、地质灾害与遥感巡查，理解监测证据。",
    color: "#587da5",
  },
  {
    id: "geology",
    label: "遥感地质填图逻辑推理",
    description: "岩性、矿物与构造关系，结合条件开展地质推理。",
    color: "#5a6a99",
  },
  {
    id: "arid_ecology",
    label: "干旱区生态安全治理",
    description: "植被指数、水分与生态变化，支撑干旱区治理分析。",
    color: "#408a98",
  },
];
export const domainLabel = (id?: KnowledgeDomain) =>
  KNOWLEDGE_DOMAINS.find((item) => item.id === id)?.label ?? "未分区";
