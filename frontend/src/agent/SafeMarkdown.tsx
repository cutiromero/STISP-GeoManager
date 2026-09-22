import type { ReactNode } from "react";

// Render a small Markdown subset as React text. No HTML, remote images or code execution.
function inline(text: string): ReactNode[] {
  const output: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(/\*\*([^*]+)\*\*|`([^`]+)`/g)) {
    output.push(text.slice(cursor, match.index));
    output.push(
      match[1] ? (
        <strong key={`s${match.index}`}>{match[1]}</strong>
      ) : (
        <code key={`c${match.index}`}>{match[2]}</code>
      ),
    );
    cursor = match.index + match[0].length;
  }
  output.push(text.slice(cursor));
  return output;
}

export default function SafeMarkdown({ text }: { text: string }) {
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
    } else if (line.includes("|") && /^\s*\|?\s*:?-{3,}/.test(lines[0] ?? "")) {
      const split = (row: string) =>
        row
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => c.trim());
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
            <th key={cellKey}>{inline(cell)}</th>
          ) : (
            <td key={cellKey}>{inline(cell)}</td>
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
    } else if (/^#{1,4} /.test(line)) {
      result.push(<h3 key={key}>{inline(line.replace(/^#+ /, ""))}</h3>);
    } else if (line.trim()) {
      result.push(<p key={key}>{inline(line)}</p>);
    }
  }
  return <div className="agent-markdown">{result}</div>;
}
