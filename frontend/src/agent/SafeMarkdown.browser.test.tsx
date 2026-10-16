import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SafeMarkdown from "./SafeMarkdown";

it("shows escaped catalog names exactly without splitting cells or creating markup", () => {
  const name =
    "haze1_ndvi|样区*A*`v1`[目录](修订)\\路径 <script>alert(1)</script> &lt;&gt;&amp;";
  const { container } = render(
    <SafeMarkdown
      text={
        "| 名称 | 类型 |\n|---|---|\n| haze1\\_ndvi\\|样区\\*A\\*\\`v1\\`\\[目录\\]\\(修订\\)\\\\路径 &lt;script&gt;alert(1)&lt;/script&gt; &amp;lt;&amp;gt;&amp;amp; | 栅格 |"
      }
    />,
  );
  const cells = container.querySelectorAll("tbody td");
  expect(cells).toHaveLength(2);
  expect(cells[0]?.textContent).toBe(name);
  expect(cells[1]?.textContent).toBe("栅格");
  expect(container.querySelector("script, img, a, strong, code")).toBeNull();
});

it("keeps Wiki links, bold, inline code and math working alongside escapes", () => {
  const wikiLink = vi.fn((target: string, label: string) => (
    <a href={`#${encodeURIComponent(target)}`}>{label}</a>
  ));
  const { container } = render(
    <SafeMarkdown
      math
      wikiLink={wikiLink}
      text={
        "| 知识 | 说明 |\n|---|---|\n| [[八宝山组|专家知识]] | **晚三叠世**和`name|value`，公式 $x_1+1$，原名 a\\_b |\n\n$$x^2$$\n\n```txt\n\\_literal &lt;tag&gt;\n```"
      }
    />,
  );
  expect(container.querySelectorAll("tbody td")).toHaveLength(2);
  expect(screen.getByRole("link", { name: "专家知识" })).toBeVisible();
  expect(wikiLink).toHaveBeenCalledWith("八宝山组", "专家知识");
  expect(container.querySelector("strong")?.textContent).toBe("晚三叠世");
  expect(container.querySelector("td code")?.textContent).toBe("name|value");
  expect(container.querySelectorAll(".katex")).toHaveLength(2);
  expect(container.querySelector("pre code")?.textContent).toBe(
    "\\_literal &lt;tag&gt;",
  );
  expect(container.querySelector("tbody")?.textContent).toContain("原名 a_b");
});

it("preserves escaped trailing pipes and paired backslashes in table names", () => {
  const { container } = render(
    <SafeMarkdown
      text={"名称 | 类型\n--- | ---\n尾部\\| | 栅格\n路径\\\\ | 表格"}
    />,
  );
  const cells = container.querySelectorAll("tbody td");
  expect([...cells].map((cell) => cell.textContent)).toEqual([
    "尾部|",
    "栅格",
    "路径\\",
    "表格",
  ]);
});
