import { Fragment, type ReactNode } from "react";
import SafeMath from "./SafeMath";

type WikiLinkRenderer = (target: string, label: string) => ReactNode;

function textContent(text: string): string {
  const entities: Record<string, string> = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
  };
  return text.replace(
    /&(?:lt|gt|amp);/g,
    (entity) => entities[entity] ?? entity,
  );
}

// Render a small Markdown subset as React text. No HTML, remote images or code execution.
function inline(
  text: string,
  wikiLink?: WikiLinkRenderer,
  math = false,
): ReactNode[] {
  const output: ReactNode[] = [];
  let cursor = 0;
  const pattern = math
    ? /\\[\\`*_[\]()|$]|\[\[([^\]\n|]+)(?:\|([^\]\n]+))?\]\]|\*\*((?:\\.|[^*])+)\*\*|`([^`]+)`|(?<!\\)\$(?!\$)((?:\\.|[^$\\\n])+)\$(?!\$)/g
    : /\\[\\`*_[\]()|$]|\[\[([^\]\n|]+)(?:\|([^\]\n]+))?\]\]|\*\*((?:\\.|[^*])+)\*\*|`([^`]+)`/g;
  for (const match of text.matchAll(pattern)) {
    output.push(textContent(text.slice(cursor, match.index)));
    output.push(
      match[0].startsWith("\\") ? (
        match[0].slice(1)
      ) : match[1] ? (
        <Fragment key={`w${match.index}`}>
          {wikiLink ? wikiLink(match[1], match[2] || match[1]) : match[0]}
        </Fragment>
      ) : match[3] ? (
        <strong key={`s${match.index}`}>
          {inline(match[3], wikiLink, math)}
        </strong>
      ) : match[4] ? (
        <code key={`c${match.index}`}>{match[4]}</code>
      ) : (
        <SafeMath key={`m${match.index}`} expression={match[5] ?? ""} />
      ),
    );
    cursor = match.index + match[0].length;
  }
  output.push(textContent(text.slice(cursor)));
  return output;
}

export default function SafeMarkdown({
  text,
  wikiLink,
  math = false,
}: {
  text: string;
  wikiLink?: WikiLinkRenderer;
  math?: boolean;
}) {
  const lines = text.split("\n");
  const result: ReactNode[] = [];
  let offset = 0;
  while (lines.length) {
    const line = lines.shift() ?? "";
    const key = `block-${offset}`;
    offset += line.length + 1;
    if (line.startsWith("```")) {
      const code: string[] = [];
      while (lines.length && !lines[0]?.startsWith("```")) {
        const row = lines.shift() ?? "";
        code.push(row);
        offset += row.length + 1;
      }
      const closing = lines.shift();
      offset += closing?.length ?? 0;
      result.push(
        <pre key={key}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
    } else if (math && /^\s*\$\$.*\$\$\s*$/.test(line)) {
      result.push(
        <SafeMath key={key} expression={line.trim().slice(2, -2)} display />,
      );
    } else if (
      math &&
      line.trim() === "$$" &&
      lines.some((row) => row.trim() === "$$")
    ) {
      const formula: string[] = [];
      while (lines.length && lines[0]?.trim() !== "$$") {
        const row = lines.shift() ?? "";
        formula.push(row);
        offset += row.length + 1;
      }
      offset += (lines.shift()?.length ?? 0) + 1;
      result.push(
        <SafeMath key={key} expression={formula.join("\n")} display />,
      );
    } else if (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[0] ?? "")) {
      const split = (row: string) => {
        const content = row.trim();
        const cells: string[] = [];
        let start = 0;
        for (const match of content.matchAll(
          /\\.|\[\[[^\]\n]+\]\]|`[^`]*`|\|/g,
        )) {
          if (match[0] === "|") {
            cells.push(content.slice(start, match.index).trim());
            start = match.index + 1;
          }
        }
        cells.push(content.slice(start).trim());
        if (content.startsWith("|")) cells.shift();
        if (start === content.length) cells.pop();
        return cells;
      };
      const headers = split(line);
      offset += (lines.shift()?.length ?? 0) + 1;
      const rows: Array<{ key: string; cells: string[] }> = [];
      while (lines[0]?.includes("|")) {
        const row = lines.shift() ?? "";
        rows.push({ key: `row-${offset}`, cells: split(row) });
        offset += row.length + 1;
      }
      const cells = (items: string[], tag: "th" | "td") => {
        let cellOffset = 0;
        return items.map((cell) => {
          const cellKey = `cell-${cellOffset}`;
          cellOffset += cell.length + 1;
          return tag === "th" ? (
            <th key={cellKey}>{inline(cell, wikiLink, math)}</th>
          ) : (
            <td key={cellKey}>{inline(cell, wikiLink, math)}</td>
          );
        });
      };
      result.push(
        <div className="agent-table" key={key}>
          <table>
            <thead>
              <tr>{cells(headers, "th")}</tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>{cells(row.cells, "td")}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    } else if (/^\s*[-*] /.test(line)) {
      const items: Array<{ key: string; text: string }> = [{ key, text: line }];
      while (/^\s*[-*] /.test(lines[0] ?? "")) {
        const row = lines.shift() ?? "";
        items.push({ key: `item-${offset}`, text: row });
        offset += row.length + 1;
      }
      result.push(
        <ul key={key}>
          {items.map((item) => (
            <li key={item.key}>
              {inline(item.text.replace(/^\s*[-*] /, ""), wikiLink, math)}
            </li>
          ))}
        </ul>,
      );
    } else if (/^#{1,4} /.test(line)) {
      result.push(
        <h3 key={key}>{inline(line.replace(/^#+ /, ""), wikiLink, math)}</h3>,
      );
    } else if (line.trim()) {
      result.push(<p key={key}>{inline(line, wikiLink, math)}</p>);
    }
  }
  return <div className="agent-markdown">{result}</div>;
}
