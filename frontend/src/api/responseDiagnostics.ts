export const RESPONSE_DIAGNOSTICS_KEY = "platform:api-response-errors";
const MAX_RECORDS = 20;

type FieldStructure = {
  type: string;
  length?: number;
  fields?: Record<string, FieldStructure>;
  samples?: FieldStructure[];
  omittedFields?: number;
};

export class ResponseFormatError extends Error {
  readonly issue: string;

  constructor(issue: string) {
    super("对话服务返回内容异常，请重试，当前聊天记录已保留");
    this.name = "ResponseFormatError";
    this.issue = issue;
  }
}

/** Keep routing information, while removing credentials and query values. */
function diagnosticUrl(value: string) {
  try {
    const url = new URL(value, window.location.origin);
    url.username = "";
    url.password = "";
    url.hash = "";
    const query = new URLSearchParams();
    for (const key of url.searchParams.keys()) query.set(key, "[redacted]");
    url.search = query.toString();
    return url.href.slice(0, 1500);
  } catch {
    return "unavailable";
  }
}

/** Describe actual keys/types, never string, number or boolean content. */
export function responseFieldStructure(
  value: unknown,
  depth = 0,
  budget = { remaining: 300 },
): FieldStructure {
  if (budget.remaining-- <= 0) return { type: "structure_limit" };
  if (value === null) return { type: "null" };
  if (Array.isArray(value)) {
    return {
      type: "array",
      length: value.length,
      ...(depth < 4
        ? {
            samples: value
              .slice(0, 3)
              .map((item) => responseFieldStructure(item, depth + 1, budget)),
          }
        : {}),
    };
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    return {
      type: "object",
      ...(depth < 4
        ? {
            fields: Object.fromEntries(
              keys
                .slice(0, 60)
                .map((key) => [
                  key.slice(0, 100),
                  responseFieldStructure(
                    (value as Record<string, unknown>)[key],
                    depth + 1,
                    budget,
                  ),
                ]),
            ),
            ...(keys.length > 60 ? { omittedFields: keys.length - 60 } : {}),
          }
        : {}),
    };
  }
  return { type: typeof value };
}

export function recordResponseDiagnostic(
  requestUrl: string,
  response: Response,
  data: unknown,
  issue: string,
) {
  const record = {
    time: new Date().toISOString(),
    page: window.location.pathname,
    requestedUrl: diagnosticUrl(requestUrl),
    finalUrl: diagnosticUrl(response.url || requestUrl),
    // Synthetic responses may not expose a URL; do not invent one.
    finalUrlAvailable: Boolean(response.url),
    redirected: response.redirected,
    status: response.status,
    contentType: (response.headers.get("Content-Type") ?? "").slice(0, 200),
    issue,
    structure: responseFieldStructure(data),
  };
  console.warn("Platform API response anomaly", record);
  try {
    const stored: unknown = JSON.parse(
      sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY) ?? "[]",
    );
    const previous = Array.isArray(stored) ? stored : [];
    sessionStorage.setItem(
      RESPONSE_DIAGNOSTICS_KEY,
      JSON.stringify([...previous.slice(-(MAX_RECORDS - 1)), record]),
    );
  } catch {
    // The failed request remains recoverable when browser storage is blocked.
  }
}

export function downloadResponseDiagnostics() {
  let stored = "[]";
  try {
    stored = sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY) ?? "[]";
  } catch {
    // Export remains available when storage is blocked.
  }
  const blob = new Blob([stored], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "智能体异常响应诊断.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
