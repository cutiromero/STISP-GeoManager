import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LoginBackground from "./LoginBackground";
import "../styles.css";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function activeImage(container: HTMLElement) {
  const slide = container.querySelector<HTMLElement>(
    ".login-background-slide.is-active",
  );
  return slide?.style.backgroundImage;
}

describe("login background motion", () => {
  it("continues rotating all three images and loops without changing the cover", async () => {
    vi.useFakeTimers();
    const { container } = render(<LoginBackground />);
    const initial = activeImage(container);
    const images = [initial];
    for (let index = 0; index < 3; index += 1) {
      await act(() => vi.advanceTimersByTime(9000));
      images.push(activeImage(container));
    }
    expect(new Set(images)).toHaveProperty("size", 3);
    expect(images[3]).toBe(initial);
    const effects = container.querySelector<HTMLElement>(
      ".login-background-carousel",
    )!;
    expect(getComputedStyle(effects, "::before").animationIterationCount).toBe(
      "infinite, infinite",
    );
    expect(getComputedStyle(effects, "::after").animationIterationCount).toBe(
      "infinite",
    );
  });

  it("pauses hidden pages and resumes rotation when the page is visible", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const { container } = render(<LoginBackground />);
    const initial = activeImage(container);
    hidden.mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTime(30000));
    expect(activeImage(container)).toBe(initial);
    const effects = container.querySelector<HTMLElement>(
      ".login-background-carousel",
    )!;
    expect(getComputedStyle(effects, "::after").animationPlayState).toBe(
      "paused",
    );
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(() => vi.advanceTimersByTime(9000));
    expect(activeImage(container)).not.toBe(initial);
    expect(getComputedStyle(effects, "::after").animationPlayState).toBe(
      "running",
    );
  });

  it("honors the system motion preference and responds when it changes", async () => {
    vi.useFakeTimers();
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    vi.spyOn(preference, "matches", "get").mockReturnValue(true);
    vi.spyOn(window, "matchMedia").mockReturnValue(preference);
    const { container } = render(<LoginBackground />);
    const initial = activeImage(container);
    expect(container.firstElementChild).toHaveAttribute(
      "data-animated",
      "false",
    );
    await act(() => vi.advanceTimersByTime(30000));
    expect(activeImage(container)).toBe(initial);
    vi.spyOn(preference, "matches", "get").mockReturnValue(false);
    act(() => preference.dispatchEvent(new Event("change")));
    await act(() => vi.advanceTimersByTime(9000));
    expect(activeImage(container)).not.toBe(initial);
  });
});
