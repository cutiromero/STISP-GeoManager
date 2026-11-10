export const RESOURCE_SEARCH_DELAY_MS = 280;

export function searchTerms(query: string) {
  return [...new Set(query.slice(0, 200).trim().split(/\s+/u).filter(Boolean))];
}

export function highlightParts(text: string, query: string) {
  const terms = searchTerms(query);
  if (!terms.length) return [{ start: 0, text, matched: false }];
  const pattern = new RegExp(
    terms
      .sort((left, right) => right.length - left.length)
      .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|"),
    "giu",
  );
  const parts = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index;
    if (start > offset)
      parts.push({
        start: offset,
        text: text.slice(offset, start),
        matched: false,
      });
    parts.push({ start, text: match[0], matched: true });
    offset = start + match[0].length;
  }
  if (offset < text.length)
    parts.push({ start: offset, text: text.slice(offset), matched: false });
  return parts;
}

export function scheduleResourceSearch<Result>(
  request: (signal: AbortSignal) => Promise<Result>,
  callbacks: {
    success: (result: Result) => void;
    error: (reason: unknown) => void;
    settled: () => void;
  },
) {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    void request(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) callbacks.success(result);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) callbacks.error(reason);
      })
      .finally(() => {
        if (!controller.signal.aborted) callbacks.settled();
      });
  }, RESOURCE_SEARCH_DELAY_MS);
  return () => {
    clearTimeout(timer);
    controller.abort();
  };
}
