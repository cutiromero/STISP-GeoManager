import type { AgentResearchScenario } from "../api/generated/types.gen";

export type ResearchDemoLaunch = {
  scenario: AgentResearchScenario;
  projectId: number;
  prompt: string;
  token: string;
};

export function researchDemoLaunch(
  value: unknown,
  projectId: string | undefined,
): ResearchDemoLaunch | null {
  if (!value || typeof value !== "object") return null;
  const data = value as Record<string, unknown>;
  if (
    !["ecology_investigation", "geology_correction"].includes(
      String(data.scenario),
    ) ||
    !Number.isInteger(data.projectId) ||
    String(data.projectId) !== projectId ||
    typeof data.prompt !== "string" ||
    !data.prompt.trim() ||
    typeof data.token !== "string" ||
    data.token.length < 8 ||
    data.token.length > 80
  )
    return null;
  return data as ResearchDemoLaunch;
}
