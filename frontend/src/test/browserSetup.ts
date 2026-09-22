import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { setLocale } from "../i18n";

afterEach(async () => {
  cleanup();
  await setLocale("zh-CN");
});

class MockResizeObserver {
  observe() {
    return undefined;
  }
  unobserve() {
    return undefined;
  }
  disconnect() {
    return undefined;
  }
}

if (!("ResizeObserver" in window)) {
  Object.defineProperty(window, "ResizeObserver", {
    writable: true,
    configurable: true,
    value: MockResizeObserver,
  });
}

if (!("matchMedia" in window)) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

if (!("scrollTo" in window)) {
  Object.defineProperty(window, "scrollTo", {
    writable: true,
    configurable: true,
    value: () => undefined,
  });
}

if (!("createObjectURL" in URL)) {
  Object.defineProperty(URL, "createObjectURL", {
    writable: true,
    configurable: true,
    value: () => "blob:test",
  });
}

if (!("revokeObjectURL" in URL)) {
  Object.defineProperty(URL, "revokeObjectURL", {
    writable: true,
    configurable: true,
    value: () => undefined,
  });
}
