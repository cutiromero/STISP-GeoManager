import { describe, expect, it } from "vitest";
import {
  createBasemapRequestConcurrencyCoordinator,
  maxParallelImageRequestsForBasemap,
  tiandituMaxParallelImageRequests,
} from "./basemapRequestConcurrency";

describe("basemapRequestConcurrency", () => {
  it("limits Tianditu owners while leaving Mapbox owners at baseline", () => {
    expect(maxParallelImageRequestsForBasemap("tianditu", 16)).toBe(
      tiandituMaxParallelImageRequests,
    );
    expect(maxParallelImageRequestsForBasemap("mapbox", 16)).toBe(16);
  });

  it("does not increase an existing stricter host limit", () => {
    expect(maxParallelImageRequestsForBasemap("tianditu", 4)).toBe(4);
  });

  it("keeps the strictest active owner until that owner releases", () => {
    const target = { maxParallelImageRequests: 16 };
    const coordinator = createBasemapRequestConcurrencyCoordinator(target);
    const tianditu = coordinator.acquire("tianditu");
    const mapbox = coordinator.acquire("mapbox");

    expect(target.maxParallelImageRequests).toBe(6);
    mapbox.release();
    expect(target.maxParallelImageRequests).toBe(6);
    tianditu.release();
    expect(target.maxParallelImageRequests).toBe(16);
  });

  it("updates an owner across switches and releases idempotently", () => {
    const target = { maxParallelImageRequests: 16 };
    const coordinator = createBasemapRequestConcurrencyCoordinator(target);
    const first = coordinator.acquire("mapbox");
    const second = coordinator.acquire("tianditu");

    first.update("tianditu");
    second.update("mapbox");
    expect(target.maxParallelImageRequests).toBe(6);

    first.release();
    first.release();
    expect(target.maxParallelImageRequests).toBe(16);
    second.release();
    expect(target.maxParallelImageRequests).toBe(16);
  });

  it("recaptures a stricter or newer baseline for each ownership epoch", () => {
    const target = { maxParallelImageRequests: 4 };
    const coordinator = createBasemapRequestConcurrencyCoordinator(target);
    const first = coordinator.acquire("tianditu");

    expect(target.maxParallelImageRequests).toBe(4);
    first.release();
    target.maxParallelImageRequests = 12;

    const second = coordinator.acquire("tianditu");
    expect(target.maxParallelImageRequests).toBe(6);
    second.release();
    expect(target.maxParallelImageRequests).toBe(12);
  });
});
