import type { BusinessFlowSpec } from "../api/generated/types.gen";

const codes = {
  "huanjiang-landcover": "landcover",
  "spartina-distribution": "spartina",
  "wildfire-history-observation": "wildfire",
} as const;

// Profiles choose friendly input controls only. The frozen version and server
// validation determine what can execute, including on an edited or copied flow.
export function monitoringFlowProfile(spec?: BusinessFlowSpec, code?: string) {
  if (!spec || spec.adapter !== "research_flow") return undefined;
  const named =
    code &&
    Object.prototype.hasOwnProperty.call(codes, code) &&
    codes[code as keyof typeof codes];
  if (named) return named;
  const roles = new Set(spec.inputRequirements.map((row) => row.key));
  const keys = new Set(
    spec.nodes.flatMap(
      (node) => node.contract?.requiredOutputs.map((row) => row.name) ?? [],
    ),
  );
  if (roles.has("cube") && keys.has("observation") && keys.has("series"))
    return "wildfire";
  if (
    ["march", "august", "december"].every((role) => roles.has(role)) &&
    keys.has("probability")
  )
    return "spartina";
  if (
    roles.has("image") &&
    keys.has("classification") &&
    keys.has("statistics")
  )
    return "landcover";
  return undefined;
}
