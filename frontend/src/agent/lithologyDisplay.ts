import type { AgentModificationSuggestion } from "../api/generated/types.gen";

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export const missingSymbol = "地质符号未登记";
const unitId = /(?<![A-Za-z0-9_-])U\d{3,}(?![A-Za-z0-9_-])/g;
const featureId =
  /(?<![A-Za-z0-9_])(?:F\d{4,}|AR-\d+|A-U\d{3,})(?![A-Za-z0-9_])/g;
const valueText = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

export function expertLithologyText(
  value: string,
  names: Record<string, unknown> = {},
) {
  return value
    .replace(featureId, "图斑")
    .replace(unitId, (code) => valueText(names[code]) || missingSymbol);
}

export function geologyUnitName(
  symbol: unknown,
  name: unknown,
  normalizedCode: unknown = "",
) {
  // A separately recorded display symbol is authoritative, even if its spelling
  // happens to resemble a calculation key.
  const rawCode = valueText(normalizedCode);
  const display =
    valueText(symbol) ||
    (/^(?:U\d{3,}|F\d{4,}|AR-\d+)$/.test(rawCode) ? "" : rawCode);
  const title = valueText(name);
  return display && title && display !== title
    ? `${display}（${title}）`
    : display || title || missingSymbol;
}

export function issueLithologyDisplay(
  suggestion?: Pick<AgentModificationSuggestion, "observations">,
) {
  const value = record(suggestion?.observations?.lithology_display);
  const codes = record(value.codes);
  return {
    current: valueText(value.current),
    target: valueText(value.target),
    codes,
  };
}

export function issueObjectTitle(suggestion: AgentModificationSuggestion) {
  if (suggestion.element !== "lithology") return suggestion.featureId;
  const display = issueLithologyDisplay(suggestion);
  const observed = record(suggestion.observations);
  return (
    display.current ||
    geologyUnitName(
      observed.display_symbol,
      observed.observed_unit_name ?? observed.name,
      observed.observed_code,
    )
  );
}

export function issueReason(suggestion: AgentModificationSuggestion) {
  if (suggestion.element !== "lithology") return suggestion.reason;
  const display = issueLithologyDisplay(suggestion);
  return display.current
    ? suggestion.reason
    : expertLithologyText(suggestion.reason, display.codes);
}

export function issueTargetTitle(
  suggestion: Pick<
    AgentModificationSuggestion,
    | "element"
    | "candidateTargetCode"
    | "observations"
    | "suggestedState"
    | "action"
  >,
) {
  const target = suggestion.candidateTargetCode;
  if (suggestion.element !== "lithology") return target ?? "";
  const display = issueLithologyDisplay(suggestion);
  if (display.target) return display.target;
  const prefix = `${suggestion.action} `;
  const raw =
    target ||
    (suggestion.suggestedState.startsWith(prefix)
      ? suggestion.suggestedState.slice(prefix.length)
      : "");
  return raw ? expertLithologyText(raw, display.codes) : "";
}
