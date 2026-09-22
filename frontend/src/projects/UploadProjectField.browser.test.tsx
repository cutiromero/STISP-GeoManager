import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UploadProjectField } from "./UploadProjectField";

const state = vi.hoisted(() => ({
  projects: [{ id: 1, name: "公开", isActive: true }],
}));
vi.mock("./ProjectContext", () => ({ useProjectContext: () => state }));

function Field({ locked = false }: { locked?: boolean }) {
  const [value, setValue] = useState(1);
  return (
    <UploadProjectField value={value} onChange={setValue} locked={locked} />
  );
}
beforeEach(() => {
  state.projects = [{ id: 1, name: "公开", isActive: true }];
});
describe("upload destination", () => {
  it("starts with Default and only offers server-authorized tags", async () => {
    render(<Field />);
    expect(screen.getByText(/公开项目：所有人可访问/)).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "所属项目标签" }));
    expect(
      await screen.findByRole("option", { name: "公开" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "项目甲" }),
    ).not.toBeInTheDocument();
  });
  it("allows choosing an assigned private project and updates the access explanation", async () => {
    state.projects.push(
      { id: 2, name: "项目甲", isActive: true },
      { id: 3, name: "项目乙", isActive: true },
    );
    render(<Field />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "所属项目标签" }));
    await screen.findByText("项目乙", {
      selector: ".ant-select-item-option-content",
    });
    fireEvent.click(
      screen.getByText("项目乙", {
        selector: ".ant-select-item-option-content",
      }),
    );
    expect(screen.getByText(/仅该项目成员和超管可访问/)).toBeInTheDocument();
  });
  it("locks the destination while the selected file is being imported", () => {
    render(<Field locked />);
    expect(
      screen.getByRole("combobox", { name: "所属项目标签" }),
    ).toBeDisabled();
  });
});
