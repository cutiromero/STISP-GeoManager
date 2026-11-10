import { Fragment, memo } from "react";
import { highlightParts, searchTerms } from "./resourceSearch";

function Highlight({ text, query }: { text: string; query: string }) {
  return highlightParts(text, query).map((part) =>
    part.matched ? (
      <mark key={part.start}>{part.text}</mark>
    ) : (
      <Fragment key={part.start}>{part.text}</Fragment>
    ),
  );
}

export const ResourceSearchLabel = memo(function ResourceSearchLabel({
  name,
  description,
  query,
  details,
}: {
  name: string;
  description?: string;
  query: string;
  details?: string;
}) {
  const descriptionMatch = searchTerms(query).some(
    (term) =>
      !name.toLowerCase().includes(term.toLowerCase()) &&
      description?.toLowerCase().includes(term.toLowerCase()),
  );
  return (
    <span
      role="group"
      aria-label={name}
      style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}
    >
      <Highlight text={name} query={query} />
      {details}
      {descriptionMatch && (
        <small style={{ display: "block" }}>
          说明：
          <Highlight text={description ?? ""} query={query} />
        </small>
      )}
    </span>
  );
});
