import base from "../../../backend/apps/knowledge/seed_entries.json";
import geology from "../../../backend/apps/knowledge/seed_entries_20261009.json";
import zones from "../../../backend/apps/knowledge/seed_entries_20261010.json";
import type {
  KnowledgeDomain,
  KnowledgeEntry,
} from "../api/generated/types.gen";

// Use the published seeds and the historical migration's exact domain assignment.
const legacyGroups: [KnowledgeDomain, string[]][] = [
  ["pipelines", ["管道", "油气", "输油", "输气", "pipeline"]],
  ["geology", ["地质", "矿物", "岩性", "岩石", "填图", "蚀变", "矿产", "断层"]],
  [
    "arid_ecology",
    ["干旱", "生态", "植被", "荒漠", "胡杨", "ndvi", "savi", "蒸散"],
  ],
  [
    "remote_sensing",
    ["遥感", "卫星", "影像", "波段", "反射率", "landsat", "sentinel", "ndwi"],
  ],
];
export const realKnowledgeEntries: KnowledgeEntry[] = [
  ...base,
  ...geology,
  ...zones,
].map((item, index) => {
  const text = `${item.title} ${item.category} ${item.statement}`.toLowerCase();
  const domain =
    "domain" in item
      ? (item.domain as KnowledgeDomain)
      : (legacyGroups.find(([, words]) =>
          words.some((word) => text.includes(word)),
        )?.[0] ?? "geology");
  return {
    ...item,
    id: index + 1,
    projectTagId: 1,
    revision: 1,
    updatedAt: "2026-10-10T00:00:00Z",
    domain,
    status: "published",
    ruleKind: item.ruleKind as KnowledgeEntry["ruleKind"],
  };
});
