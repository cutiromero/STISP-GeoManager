import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";
import { expect, it, vi } from "vitest";
import MapPage from "./MapPage";

vi.mock("../contexts/AppContext", () => ({
  useAppContext: () => {
    throw new Error("对比链接不应挂载地理工作台");
  },
}));
vi.mock("../map/GeologyReviewWorkspace", () => ({
  default: (props: {
    workflowId: string;
    projectTagId: string | null;
    suggestionId: string | null;
  }) => <output aria-label="独立页参数">{JSON.stringify(props)}</output>,
}));

function Location() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <output aria-label="当前位置" data-navigation={navigationType}>
      {location.pathname + location.search + location.hash}
    </output>
  );
}

it.each(["suggest-age", "边界 / A&B"])(
  "旧链接直接替换为独立页，保留项目和定位参数 %s，不挂载工作台",
  async (suggestionId) => {
    render(
      <MemoryRouter
        initialEntries={[
          `/map?geologyCompare=review-workflow&projectTagId=3&suggestion=${encodeURIComponent(suggestionId)}#location`,
        ]}
      >
        <MapPage />
        <Location />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    const params = await screen.findByLabelText("独立页参数");
    expect(JSON.parse(params.textContent!)).toEqual({
      workflowId: "review-workflow",
      projectTagId: "3",
      suggestionId,
    });
    const location = screen.getByLabelText("当前位置");
    expect(location).toHaveAttribute("data-navigation", "REPLACE");
    const url = new URL(location.textContent!, window.location.origin);
    expect(url.searchParams.get("geologyReview")).toBe("review-workflow");
    expect(url.searchParams.has("geologyCompare")).toBe(false);
    expect(url.searchParams.get("projectTagId")).toBe("3");
    expect(url.searchParams.get("suggestion")).toBe(suggestionId);
    expect(url.hash).toBe("#location");
  },
);

it("新链接直接打开独立页并传递定位参数", async () => {
  render(
    <MemoryRouter
      initialEntries={[
        "/map?geologyReview=review-workflow&projectTagId=3&suggestion=suggest-age",
      ]}
    >
      <MapPage />
    </MemoryRouter>,
  );
  expect(
    JSON.parse((await screen.findByLabelText("独立页参数")).textContent!),
  ).toEqual({
    workflowId: "review-workflow",
    projectTagId: "3",
    suggestionId: "suggest-age",
  });
});
