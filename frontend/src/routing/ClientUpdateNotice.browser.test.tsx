import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ClientUpdateNotice from "./ClientUpdateNotice";
import { moduleEntry } from "./clientBuild";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("identifies the loaded module without treating preload links as the entry", () => {
  const document = new DOMParser().parseFromString(
    '<link rel="modulepreload" href="/static/vendor.js"><script type="module" src="/static/current.js"></script>',
    "text/html",
  );
  expect(moduleEntry(document)).toBe("/static/current.js");
});

it("offers a safe refresh when the server has a different bundle", async () => {
  const original = document.querySelector.bind(document);
  const script = document.createElement("script");
  script.setAttribute("src", "/static/old.js");
  vi.spyOn(document, "querySelector").mockImplementation((selector) =>
    selector === 'script[type="module"][src]' ? script : original(selector),
  );
  vi.spyOn(window, "fetch").mockResolvedValue(
    new Response('<script type="module" src="/static/new.js"></script>', {
      status: 200,
      headers: { "Content-Type": "text/html" },
    }),
  );
  render(<ClientUpdateNotice />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "刷新使用新版" })).toBeVisible(),
  );
  expect(screen.getByText("刷新前请保留尚未发送的文字。")).toBeVisible();
});
