import type { BasemapProvider } from "./basemapCatalog";

export const tiandituMaxParallelImageRequests = 6;

export interface ImageRequestConcurrencyTarget {
  maxParallelImageRequests: number;
}

export interface BasemapRequestConcurrencyLease {
  update(provider: BasemapProvider): void;
  release(): void;
}

export function maxParallelImageRequestsForBasemap(
  provider: BasemapProvider,
  defaultLimit: number,
) {
  if (provider !== "tianditu") return defaultLimit;
  return Math.min(defaultLimit, tiandituMaxParallelImageRequests);
}

export function createBasemapRequestConcurrencyCoordinator(
  target: ImageRequestConcurrencyTarget,
) {
  let baselineLimit: number | null = null;
  const ownerProviders = new Map<symbol, BasemapProvider>();

  const applyEffectiveLimit = () => {
    if (baselineLimit === null) return;
    const effectiveLimit =
      ownerProviders.size === 0
        ? baselineLimit
        : Math.min(
            ...[...ownerProviders.values()].map((provider) =>
              maxParallelImageRequestsForBasemap(provider, baselineLimit!),
            ),
          );
    if (target.maxParallelImageRequests !== effectiveLimit) {
      target.maxParallelImageRequests = effectiveLimit;
    }
    if (ownerProviders.size === 0) baselineLimit = null;
  };

  return {
    acquire(provider: BasemapProvider): BasemapRequestConcurrencyLease {
      if (ownerProviders.size === 0) {
        baselineLimit = target.maxParallelImageRequests;
      }
      const owner = Symbol("basemap-request-concurrency-owner");
      let released = false;
      ownerProviders.set(owner, provider);
      applyEffectiveLimit();

      return {
        update(nextProvider) {
          if (released) return;
          ownerProviders.set(owner, nextProvider);
          applyEffectiveLimit();
        },
        release() {
          if (released) return;
          released = true;
          ownerProviders.delete(owner);
          applyEffectiveLimit();
        },
      };
    },
  };
}
