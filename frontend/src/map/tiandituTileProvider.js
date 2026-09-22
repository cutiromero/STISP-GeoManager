const defaultMinStartIntervalMs = 100;
const defaultMaxConcurrentRequests = 6;
const defaultMinConcurrentRequests = 2;
const defaultMaxAdaptiveStartIntervalMs = 600;
const defaultRecoverySuccessThreshold = 16;
const defaultMaxRetries = 2;
const defaultBaseRetryDelayMs = 1_000;
const defaultMaxRetryDelayMs = 10_000;
const defaultMaxRetryAfterMs = 120_000;
const defaultMaxInlineRetryAfterMs = 10_000;
const defaultTransientRetryDelayMs = 250;
const defaultRequestTimeoutMs = 10_000;
const defaultFailureWindowMs = 15_000;
const defaultFailureWindowMaxSamples = 12;
const defaultFailureWindowMinSamples = 8;
const defaultFailureWindowMinFailures = 3;
const defaultFailureRateThreshold = 0.5;
const defaultConsecutiveFailureThreshold = 3;
const defaultNodeFailureThreshold = 2;
const defaultNodeCircuitCooldownMs = 30_000;
const maxErrorBodyCharacters = 4_096;
// Tianditu browser keys validate the request source. Send only the platform
// origin across sites, never the current path or query string.
const tiandituReferrerPolicy = "strict-origin-when-cross-origin";
const tiandituNodePattern = /^t([0-7])\.tianditu\.gov\.cn$/i;
const tiandituSourcePathPattern = /^\/(vec|cva|img|cia)_w\/wmts$/i;
const tiandituAttribution = "© 天地图";
const tiandituDefaultMaxZoom = 18;
const tiandituImageryReliableMaxZoom = 16;
const credentialServiceCodes = new Set(["301007", "301018"]);
const credentialConfirmationServiceCodes = new Set(["301018"]);

export class TiandituTileHttpError extends Error {
  constructor(response, attempts, options = {}) {
    const {
      failureKind = "permanent",
      failureReason = null,
      failureWindow = null,
      layer = null,
      node = null,
      retryAfterMs = null,
      serviceCode = null,
    } = options;
    const statusText = safeHttpStatusText(response.status, response.statusText);
    const details = [
      `HTTP ${response.status}${statusText ? ` ${statusText}` : ""}`,
      serviceCode ? `service code ${serviceCode}` : null,
      failureKind,
      failureReason,
      failureWindow
        ? `${failureWindow.failureCount}/${failureWindow.sampleCount} failed (${Math.round(failureWindow.failureRate * 100)}%)`
        : null,
    ].filter(Boolean);
    super(`Tianditu tile request failed (${details.join("; ")})`);
    this.name = "TiandituTileHttpError";
    this.provider = "tianditu";
    // Mapbox GL intentionally converts status=404 into a detail-free
    // sourcedata event. Preserve the upstream status separately and expose a
    // neutral status so the structured failure window reaches the main thread.
    const exposedStatus = response.status === 404 ? 0 : response.status;
    this.status = exposedStatus;
    this.statusCode = exposedStatus;
    this.upstreamStatus = response.status;
    this.attempts = attempts;
    this.failureKind = failureKind;
    this.failureReason = failureReason;
    this.failureWindow = failureWindow;
    this.layer = layer;
    this.node = node;
    this.retryAfterMs = retryAfterMs;
    this.retryable =
      failureKind === "rate-limit" || failureKind === "transient";
    this.retryExhausted = this.retryable;
    this.businessCode = serviceCode;
    this.serviceCode = serviceCode;
  }
}

export class TiandituFailureWindow {
  constructor({
    windowMs = defaultFailureWindowMs,
    maxSamples = defaultFailureWindowMaxSamples,
    minSamples = defaultFailureWindowMinSamples,
    minFailures = defaultFailureWindowMinFailures,
    failureRateThreshold = defaultFailureRateThreshold,
    consecutiveFailureThreshold = defaultConsecutiveFailureThreshold,
    now = () => Date.now(),
  } = {}) {
    this.windowMs = Math.max(1, windowMs);
    this.maxSamples = Math.max(1, Math.floor(maxSamples));
    this.minSamples = Math.max(1, Math.floor(minSamples));
    this.minFailures = Math.max(1, Math.floor(minFailures));
    this.failureRateThreshold = Math.min(1, Math.max(0, failureRateThreshold));
    this.consecutiveFailureThreshold = Math.max(
      1,
      Math.floor(consecutiveFailureThreshold),
    );
    this.now = now;
    this.events = [];
    this.consecutiveFailures = 0;
  }

  recordSuccess() {
    const now = this.now();
    this.prune(now);
    this.events.push({ failed: false, timestamp: now });
    this.trimToMaxSamples();
    this.recomputeConsecutiveFailures();
    return this.snapshot(now);
  }

  recordFailure({ countsTowardConsecutive = true } = {}) {
    const now = this.now();
    this.prune(now);
    this.events.push({
      countsTowardConsecutive,
      failed: true,
      timestamp: now,
    });
    this.trimToMaxSamples();
    this.recomputeConsecutiveFailures();
    return this.snapshot(now);
  }

  snapshot(now = this.now()) {
    this.prune(now);
    const sampleCount = this.events.length;
    const failureCount = this.events.reduce(
      (count, event) => count + Number(event.failed),
      0,
    );
    const failureRate = sampleCount === 0 ? 0 : failureCount / sampleCount;
    return {
      consecutiveFailures: this.consecutiveFailures,
      failureCount,
      failureRate,
      sampleCount,
      tripped:
        this.consecutiveFailures >= this.consecutiveFailureThreshold ||
        (sampleCount >= this.minSamples &&
          failureCount >= this.minFailures &&
          failureRate >= this.failureRateThreshold),
      windowMs: this.windowMs,
    };
  }

  prune(now) {
    const cutoff = now - this.windowMs;
    while (this.events[0]?.timestamp < cutoff) this.events.shift();
    this.recomputeConsecutiveFailures();
  }

  trimToMaxSamples() {
    const excess = this.events.length - this.maxSamples;
    if (excess > 0) this.events.splice(0, excess);
    this.recomputeConsecutiveFailures();
  }

  recomputeConsecutiveFailures() {
    let count = 0;
    for (let index = this.events.length - 1; index >= 0; index -= 1) {
      if (
        !this.events[index].failed ||
        this.events[index].countsTowardConsecutive === false
      ) {
        break;
      }
      count += 1;
    }
    this.consecutiveFailures = count;
  }
}

export class TiandituNodeCircuitBreaker {
  constructor({
    failureThreshold = defaultNodeFailureThreshold,
    failureWindowMs = defaultFailureWindowMs,
    cooldownMs = defaultNodeCircuitCooldownMs,
    now = () => Date.now(),
  } = {}) {
    this.failureThreshold = Math.max(1, Math.floor(failureThreshold));
    this.failureWindowMs = Math.max(1, failureWindowMs);
    this.cooldownMs = Math.max(1, cooldownMs);
    this.now = now;
    this.nodes = new Map();
  }

  route(rawUrl, attempt = 0, excludedNodes = new Set()) {
    const parsed = parseTiandituUrl(rawUrl);
    if (!parsed) return { available: true, node: null, url: rawUrl };
    const now = this.now();
    const startIndex = (parsed.index + Math.max(0, attempt)) % 8;
    for (let offset = 0; offset < 8; offset += 1) {
      const candidateIndex = (startIndex + offset) % 8;
      const candidateNode = `t${candidateIndex}`;
      if (excludedNodes.has(candidateNode)) continue;
      if (this.isOpen(candidateNode, now)) continue;
      parsed.url.hostname = `${candidateNode}.tianditu.gov.cn`;
      return {
        available: true,
        node: candidateNode,
        url: parsed.url.toString(),
      };
    }
    return { available: false, node: null, url: null };
  }

  recordSuccess(node) {
    if (!node) return;
    const state = this.nodes.get(node);
    if (!state) return;
    if (state.openUntil > this.now()) return;
    this.nodes.delete(node);
  }

  recordFailure(node) {
    if (!node) return;
    const now = this.now();
    const previous = this.nodes.get(node);
    const failures =
      previous && now - previous.lastFailureAt <= this.failureWindowMs
        ? previous.failures + 1
        : 1;
    this.nodes.set(node, {
      failures,
      lastFailureAt: now,
      openUntil: failures >= this.failureThreshold ? now + this.cooldownMs : 0,
    });
  }

  isOpen(node, now = this.now()) {
    const state = this.nodes.get(node);
    if (!state) return false;
    if (state.openUntil > now) return true;
    if (state.openUntil > 0) this.nodes.delete(node);
    return false;
  }
}

export class RequestStartScheduler {
  constructor({
    minStartIntervalMs = defaultMinStartIntervalMs,
    maxConcurrentRequests = defaultMaxConcurrentRequests,
    minConcurrentRequests = defaultMinConcurrentRequests,
    maxAdaptiveStartIntervalMs = defaultMaxAdaptiveStartIntervalMs,
    recoverySuccessThreshold = defaultRecoverySuccessThreshold,
    now = () => Date.now(),
    setTimer = (callback, delayMs) => setTimeout(callback, delayMs),
    clearTimer = (timerId) => clearTimeout(timerId),
  } = {}) {
    this.baseMinStartIntervalMs = Math.max(0, minStartIntervalMs);
    this.minStartIntervalMs = this.baseMinStartIntervalMs;
    this.baseMaxConcurrentRequests = Math.max(1, maxConcurrentRequests);
    this.maxConcurrentRequests = this.baseMaxConcurrentRequests;
    this.minConcurrentRequests = Math.min(
      this.baseMaxConcurrentRequests,
      Math.max(1, minConcurrentRequests),
    );
    this.maxAdaptiveStartIntervalMs = Math.max(
      this.baseMinStartIntervalMs,
      maxAdaptiveStartIntervalMs,
    );
    this.recoverySuccessThreshold = Math.max(
      1,
      Math.floor(recoverySuccessThreshold),
    );
    this.now = now;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.queue = [];
    this.activeRequests = 0;
    this.nextStartAt = 0;
    this.timerId = null;
    this.successfulRequestsSinceRateLimit = 0;
    this.rateLimitPenaltyUntil = 0;
  }

  schedule(run, signal) {
    return new Promise((resolve, reject) => {
      if (signal.aborted) {
        reject(createAbortError());
        return;
      }

      const job = {
        run,
        signal,
        resolve,
        reject,
        state: "queued",
        onAbort: null,
      };
      job.onAbort = () => {
        if (job.state !== "queued") return;
        job.state = "cancelled";
        const index = this.queue.indexOf(job);
        if (index >= 0) this.queue.splice(index, 1);
        reject(createAbortError());
        this.drain();
      };
      signal.addEventListener("abort", job.onAbort, { once: true });
      this.queue.push(job);
      this.drain();
    });
  }

  deferFor(delayMs) {
    const deferredStartAt = this.now() + Math.max(0, delayMs);
    if (deferredStartAt <= this.nextStartAt) return;
    this.nextStartAt = deferredStartAt;
    if (this.timerId !== null) {
      this.clearTimer(this.timerId);
      this.timerId = null;
    }
    this.drain();
  }

  recordRateLimit(delayMs) {
    const now = this.now();
    const normalizedDelayMs = Math.max(0, delayMs);
    const isExistingBurst = now < this.rateLimitPenaltyUntil;
    this.rateLimitPenaltyUntil = Math.max(
      this.rateLimitPenaltyUntil,
      now + normalizedDelayMs,
    );
    this.successfulRequestsSinceRateLimit = 0;

    if (!isExistingBurst) {
      const doubledIntervalMs =
        this.minStartIntervalMs > 0 ? this.minStartIntervalMs * 2 : 1;
      this.minStartIntervalMs = Math.min(
        this.maxAdaptiveStartIntervalMs,
        Math.max(this.baseMinStartIntervalMs, doubledIntervalMs),
      );
      this.maxConcurrentRequests = Math.max(
        this.minConcurrentRequests,
        Math.ceil(this.maxConcurrentRequests / 2),
      );
    }

    this.deferFor(normalizedDelayMs);
  }

  recordSuccess() {
    if (this.now() < this.rateLimitPenaltyUntil) return;
    if (
      this.minStartIntervalMs === this.baseMinStartIntervalMs &&
      this.maxConcurrentRequests === this.baseMaxConcurrentRequests
    ) {
      this.successfulRequestsSinceRateLimit = 0;
      this.rateLimitPenaltyUntil = 0;
      return;
    }

    this.successfulRequestsSinceRateLimit += 1;
    if (this.successfulRequestsSinceRateLimit < this.recoverySuccessThreshold) {
      return;
    }

    this.successfulRequestsSinceRateLimit = 0;
    this.minStartIntervalMs = Math.max(
      this.baseMinStartIntervalMs,
      Math.ceil(this.minStartIntervalMs / 2),
    );
    this.maxConcurrentRequests = Math.min(
      this.baseMaxConcurrentRequests,
      this.maxConcurrentRequests + 1,
    );
    if (
      this.minStartIntervalMs === this.baseMinStartIntervalMs &&
      this.maxConcurrentRequests === this.baseMaxConcurrentRequests
    ) {
      this.rateLimitPenaltyUntil = 0;
    }
    this.drain();
  }

  drain() {
    if (this.timerId !== null) return;
    if (this.activeRequests >= this.maxConcurrentRequests) return;

    while (this.queue.length > 0 && this.queue[0].state !== "queued") {
      this.queue.shift();
    }
    const job = this.queue[0];
    if (!job) return;

    const waitMs = Math.max(0, this.nextStartAt - this.now());
    if (waitMs > 0) {
      this.timerId = this.setTimer(() => {
        this.timerId = null;
        this.drain();
      }, waitMs);
      return;
    }

    this.queue.shift();
    job.state = "active";
    if (job.onAbort) {
      job.signal.removeEventListener("abort", job.onAbort);
    }
    this.activeRequests += 1;
    this.nextStartAt = this.now() + this.minStartIntervalMs;

    Promise.resolve()
      .then(() => {
        if (job.signal.aborted) throw createAbortError();
        return job.run();
      })
      .then(job.resolve, job.reject)
      .finally(() => {
        job.state = "settled";
        this.activeRequests -= 1;
        this.drain();
      });

    this.drain();
  }

  dispose() {
    if (this.timerId !== null) {
      this.clearTimer(this.timerId);
      this.timerId = null;
    }
    for (const job of this.queue.splice(0)) {
      job.state = "cancelled";
      if (job.onAbort) {
        job.signal.removeEventListener("abort", job.onAbort);
      }
      job.reject(createAbortError());
    }
  }
}

export function parseRetryAfterMs(value, now = Date.now()) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.ceil(seconds * 1_000);
  }
  const retryAt = Date.parse(value);
  if (!Number.isFinite(retryAt)) return null;
  return Math.max(0, retryAt - now);
}

export function abortableDelay(delayMs, signal) {
  if (signal.aborted) return Promise.reject(createAbortError());
  return new Promise((resolve, reject) => {
    const timerId = setTimeout(
      () => {
        signal.removeEventListener("abort", handleAbort);
        resolve();
      },
      Math.max(0, delayMs),
    );
    const handleAbort = () => {
      clearTimeout(timerId);
      reject(createAbortError());
    };
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

const sharedScheduler = new RequestStartScheduler();
const sharedFailureWindow = new TiandituFailureWindow();
const sharedNodeCircuitBreaker = new TiandituNodeCircuitBreaker();

export class TiandituTileProvider {
  constructor(_sourceOptions = {}, dependencies = {}) {
    this.scheduler = dependencies.scheduler ?? sharedScheduler;
    this.fetchImpl =
      dependencies.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.maxRetries = dependencies.maxRetries ?? defaultMaxRetries;
    this.baseRetryDelayMs =
      dependencies.baseRetryDelayMs ?? defaultBaseRetryDelayMs;
    this.maxRetryDelayMs =
      dependencies.maxRetryDelayMs ?? defaultMaxRetryDelayMs;
    this.maxRetryAfterMs = finiteNonNegativeNumber(
      dependencies.maxRetryAfterMs,
      defaultMaxRetryAfterMs,
    );
    this.maxInlineRetryAfterMs = finiteNonNegativeNumber(
      dependencies.maxInlineRetryAfterMs,
      defaultMaxInlineRetryAfterMs,
    );
    this.transientRetryDelayMs =
      dependencies.transientRetryDelayMs ?? defaultTransientRetryDelayMs;
    this.requestTimeoutMs = Math.max(
      1,
      dependencies.requestTimeoutMs ?? defaultRequestTimeoutMs,
    );
    this.now = dependencies.now ?? (() => Date.now());
    this.delay = dependencies.delay ?? abortableDelay;
    this.failureWindow = dependencies.failureWindow ?? sharedFailureWindow;
    this.nodeCircuit = dependencies.nodeCircuit ?? sharedNodeCircuitBreaker;
    this.random = dependencies.random ?? Math.random;
  }

  async load({ request } = {}) {
    const source = parseTiandituSourceMetadataRequest(request?.url);
    if (!source) {
      // Do not include the URL because it carries the browser-visible key.
      throw new Error("Tianditu source metadata request is invalid");
    }

    return {
      tilejson: "3.0.0",
      tiles: tiandituTiles(source.layer, source.key),
      tileSize: 256,
      minzoom: 0,
      // img_w returns HTTP-200 placeholder tiles from z17 in the platform
      // coverage area. This cap makes Mapbox GL overscale real z16 imagery.
      maxzoom:
        source.layer === "img"
          ? tiandituImageryReliableMaxZoom
          : tiandituDefaultMaxZoom,
      attribution: tiandituAttribution,
      scheme: "xyz",
    };
  }

  async loadTile(_tile, { request, signal }) {
    let retryAfterMs = null;
    let nodeAttempt = 0;
    let fetchAttempts = 0;
    let stickyRateLimitRequest = null;
    const attemptedNodes = new Set();

    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      const routedRequest =
        stickyRateLimitRequest ??
        this.nodeCircuit.route(request.url, nodeAttempt, attemptedNodes);
      if (!routedRequest.available) {
        const failureWindow = this.failureWindow.recordFailure();
        throw new TiandituTileHttpError(
          syntheticFailureResponse("Circuit Open"),
          fetchAttempts,
          {
            failureKind: "transient",
            failureReason: "circuit-open",
            failureWindow,
            layer: tiandituLayer(request.url),
            node: null,
          },
        );
      }
      if (routedRequest.node) attemptedNodes.add(routedRequest.node);

      let result;
      try {
        result = await this.scheduler.schedule(
          () =>
            withRequestTimeout(
              async (requestSignal) => {
                fetchAttempts += 1;
                const response = await this.fetchImpl(
                  routedRequest.url,
                  requestInit(request, requestSignal),
                );
                return {
                  response,
                  data: response.ok ? await response.arrayBuffer() : null,
                  errorDetails: response.ok
                    ? null
                    : await readTiandituErrorDetails(response),
                };
              },
              signal,
              this.requestTimeoutMs,
            ),
          signal,
        );
      } catch (error) {
        if (isAbortFailure(error, signal)) throw error;
        stickyRateLimitRequest = null;
        this.nodeCircuit.recordFailure(routedRequest.node);
        nodeAttempt += 1;
        const retryDelayMs = retryDelayForFailure("transient", attempt, this);
        if (attempt >= this.maxRetries) {
          const failureWindow = this.failureWindow.recordFailure();
          throw new TiandituTileHttpError(
            syntheticFailureResponse("Network Error"),
            fetchAttempts,
            {
              failureKind: "transient",
              failureReason: isRequestTimeoutFailure(error)
                ? "request-timeout"
                : "network-error",
              failureWindow,
              layer: tiandituLayer(routedRequest.url),
              node: routedRequest.node,
            },
          );
        }
        this.scheduler.deferFor(retryDelayMs);
        await this.delay(retryDelayMs, signal);
        continue;
      }

      const { response, data, errorDetails } = result;
      if (signal.aborted) throw createAbortError();

      if (response.ok) {
        this.nodeCircuit.recordSuccess(routedRequest.node);
        this.failureWindow.recordSuccess();
        this.scheduler.recordSuccess();
        return {
          data,
          expires: response.headers.get("expires") ?? undefined,
          cacheControl: response.headers.get("cache-control") ?? undefined,
        };
      }

      retryAfterMs = parseRetryAfterMs(
        response.headers.get("retry-after"),
        this.now(),
      );
      const failureKind = classifyTiandituFailure(response, errorDetails);
      const isMissingTile = response.status === 404;
      if (failureKind === "transient" && !isMissingTile) {
        this.nodeCircuit.recordFailure(routedRequest.node);
        nodeAttempt += 1;
      } else if (isMissingTile) {
        nodeAttempt += 1;
      }

      const shouldConfirmCredentialFailure =
        failureKind === "credentials" &&
        credentialConfirmationServiceCodes.has(
          errorDetails?.serviceCode ?? "",
        ) &&
        attempt < Math.min(1, this.maxRetries);
      if (shouldConfirmCredentialFailure) {
        const confirmationDelayMs = retryDelayForFailure(
          "transient",
          attempt,
          this,
        );
        this.scheduler.deferFor(confirmationDelayMs);
        await this.delay(confirmationDelayMs, signal);
        continue;
      }

      if (failureKind === "credentials" || failureKind === "permanent") {
        const failureWindow = forceTrip(this.failureWindow.recordFailure());
        throw new TiandituTileHttpError(response, attempt + 1, {
          failureKind,
          failureWindow,
          layer: tiandituLayer(routedRequest.url),
          node: routedRequest.node,
          retryAfterMs,
          serviceCode: errorDetails?.serviceCode ?? null,
        });
      }

      const exponentialDelay = retryDelayForFailure(failureKind, attempt, this);
      const retryDelayMs =
        retryAfterMs === null
          ? exponentialDelay
          : Math.min(retryAfterMs, this.maxRetryAfterMs);
      const retryAfterRequiresBackgroundCooldown =
        failureKind === "rate-limit" &&
        retryAfterMs !== null &&
        retryAfterMs > this.maxInlineRetryAfterMs;
      if (failureKind === "rate-limit") {
        stickyRateLimitRequest = routedRequest;
        this.scheduler.recordRateLimit(retryDelayMs);
      } else {
        stickyRateLimitRequest = null;
      }
      const retryLimit =
        response.status === 403 || isMissingTile
          ? Math.min(1, this.maxRetries)
          : this.maxRetries;
      if (attempt >= retryLimit || retryAfterRequiresBackgroundCooldown) {
        const recordedWindow = this.failureWindow.recordFailure({
          countsTowardConsecutive: !isMissingTile,
        });
        const failureWindow =
          failureKind === "rate-limit"
            ? forceTrip(recordedWindow)
            : recordedWindow;
        throw new TiandituTileHttpError(response, attempt + 1, {
          failureKind,
          failureReason: isMissingTile ? "missing-tile" : null,
          failureWindow,
          layer: tiandituLayer(routedRequest.url),
          node: routedRequest.node,
          retryAfterMs:
            failureKind === "rate-limit" ? retryDelayMs : retryAfterMs,
          serviceCode: errorDetails?.serviceCode ?? null,
        });
      }
      if (failureKind !== "rate-limit" && !isMissingTile) {
        this.scheduler.deferFor(retryDelayMs);
      }
      await this.delay(retryDelayMs, signal);
    }

    throw new Error("Unreachable Tianditu tile retry state");
  }
}

function parseTiandituSourceMetadataRequest(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const pathLayer = url.pathname.match(tiandituSourcePathPattern)?.[1];
    const queryLayer = url.searchParams.get("LAYER")?.toLowerCase();
    const layer = pathLayer?.toLowerCase();
    if (
      url.protocol !== "https:" ||
      !tiandituNodePattern.test(url.hostname) ||
      !layer ||
      queryLayer !== layer ||
      !url.searchParams.has("tk")
    ) {
      return null;
    }
    return { key: url.searchParams.get("tk") ?? "", layer };
  } catch {
    return null;
  }
}

function tiandituTiles(layer, key) {
  const encodedKey = encodeURIComponent(key);
  return Array.from(
    { length: 8 },
    (_, index) =>
      `https://t${index}.tianditu.gov.cn/${layer}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${encodedKey}`,
  );
}

async function readTiandituErrorDetails(response) {
  if (typeof response.text !== "function") {
    return { credentialHint: false, serviceCode: null };
  }
  const contentLength = Number(response.headers.get("content-length"));
  if (
    Number.isFinite(contentLength) &&
    contentLength > maxErrorBodyCharacters
  ) {
    return { credentialHint: false, serviceCode: null };
  }
  try {
    const body = (await response.text()).slice(0, maxErrorBodyCharacters);
    return {
      credentialHint: hasCredentialFailureHint(body),
      serviceCode: extractServiceCode(body),
    };
  } catch {
    return { credentialHint: false, serviceCode: null };
  }
}

function classifyTiandituFailure(response, details) {
  if (response.status === 429) return "rate-limit";
  if (response.status === 401) return "credentials";
  if (response.status === 404) return "transient";
  if (response.status === 403) {
    if (
      details?.credentialHint ||
      credentialServiceCodes.has(details?.serviceCode ?? "")
    ) {
      return "credentials";
    }
    return "transient";
  }
  if (
    response.status === 408 ||
    response.status === 425 ||
    response.status >= 500
  ) {
    return "transient";
  }
  return "permanent";
}

function retryDelayForFailure(failureKind, attempt, provider) {
  if (failureKind === "rate-limit") {
    return Math.min(
      provider.baseRetryDelayMs * 2 ** attempt,
      provider.maxRetryDelayMs,
    );
  }
  const baseDelay = Math.min(
    provider.transientRetryDelayMs * 2 ** attempt,
    provider.maxRetryDelayMs,
  );
  const jitter = 0.75 + Math.min(1, Math.max(0, provider.random())) * 0.5;
  return Math.max(1, Math.round(baseDelay * jitter));
}

function finiteNonNegativeNumber(value, fallback) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : fallback;
}

function parseTiandituUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    if (url.protocol !== "https:") return null;
    const match = tiandituNodePattern.exec(url.hostname);
    if (!match) return null;
    return { index: Number(match[1]), url };
  } catch {
    return null;
  }
}

function tiandituLayer(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const pathLayer = url.pathname.match(/\/(vec|cva|img|cia)_w(?:\/|$)/i)?.[1];
    const queryLayer = url.searchParams.get("LAYER");
    const layer = (pathLayer ?? queryLayer ?? "").toLowerCase();
    return layer === "vec" ||
      layer === "cva" ||
      layer === "img" ||
      layer === "cia"
      ? layer
      : null;
  } catch {
    return null;
  }
}

function extractServiceCode(body) {
  try {
    const parsed = JSON.parse(body);
    const jsonCode = findServiceCode(parsed);
    if (jsonCode) return jsonCode;
  } catch {
    // Non-JSON WAF and service responses are handled by the bounded text probe.
  }
  const labelledCode = body.match(
    /(?:error\s*code|errcode|code|错误码|状态码)["'\s:=]+([A-Za-z0-9_.-]{3,32})/i,
  )?.[1];
  if (labelledCode) return sanitizeServiceCode(labelledCode);
  const xmlCode = body.match(
    /<(?:code|errorCode|status|statusCode)>\s*([A-Za-z0-9_.-]{1,32})\s*<\//i,
  )?.[1];
  if (xmlCode) return sanitizeServiceCode(xmlCode);
  return sanitizeServiceCode(body.match(/\b(\d{6})\b/)?.[1] ?? null);
}

function findServiceCode(value, depth = 0) {
  if (value == null || depth > 3) return null;
  if (typeof value !== "object") return null;
  const record = value;
  for (const key of ["code", "errorCode", "errcode", "status", "statusCode"]) {
    const code = sanitizeServiceCode(record[key]);
    if (code) return code;
  }
  for (const nested of Object.values(record)) {
    const code = findServiceCode(nested, depth + 1);
    if (code) return code;
  }
  return null;
}

function sanitizeServiceCode(value) {
  const normalized =
    typeof value === "number"
      ? String(value)
      : typeof value === "string"
        ? value.trim()
        : "";
  return /^[A-Za-z0-9_.-]{1,32}$/.test(normalized) ? normalized : null;
}

function hasCredentialFailureHint(body) {
  return /(?:invalid|expired|unauthori[sz]ed).{0,24}(?:key|token)|(?:key|token).{0,24}(?:invalid|expired)|white\s*list|whitelist|(?:密钥|令牌|鉴权).{0,16}(?:无效|失效|过期|失败|不匹配)|(?:域名|来源|refer+er).{0,16}(?:白名单|不匹配|未授权|非法)/i.test(
    body,
  );
}

function forceTrip(snapshot) {
  return { ...snapshot, tripped: true };
}

function syntheticFailureResponse(statusText) {
  return { status: 0, statusText };
}

function safeHttpStatusText(status, statusText) {
  const knownStatusTexts = {
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    408: "Request Timeout",
    425: "Too Early",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
  };
  if (
    status === 0 &&
    (statusText === "Circuit Open" || statusText === "Network Error")
  ) {
    return statusText;
  }
  return knownStatusTexts[status] ?? "";
}

function isAbortFailure(error, signal) {
  return signal.aborted || error?.name === "AbortError";
}

function isRequestTimeoutFailure(error) {
  return error?.name === "TiandituTileTimeoutError";
}

async function withRequestTimeout(run, signal, timeoutMs) {
  if (signal.aborted) throw createAbortError();
  const controller = new AbortController();
  const handleAbort = () => controller.abort();
  signal.addEventListener("abort", handleAbort, { once: true });
  let timedOut = false;
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(createRequestTimeoutError());
    }, timeoutMs);
  });

  try {
    return await Promise.race([run(controller.signal), timeout]);
  } catch (error) {
    if (signal.aborted) throw createAbortError();
    if (timedOut && !isRequestTimeoutFailure(error)) {
      throw createRequestTimeoutError();
    }
    throw error;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
    signal.removeEventListener("abort", handleAbort);
  }
}

function createRequestTimeoutError() {
  const error = new Error("Tianditu tile request timed out");
  error.name = "TiandituTileTimeoutError";
  return error;
}

function requestInit(request, signal) {
  return {
    signal,
    headers: request.headers,
    method: request.method,
    body: request.body,
    credentials: request.credentials,
    referrerPolicy: tiandituReferrerPolicy,
  };
}

function createAbortError() {
  if (typeof DOMException === "function") {
    return new DOMException("The operation was aborted", "AbortError");
  }
  const error = new Error("The operation was aborted");
  error.name = "AbortError";
  return error;
}

export default TiandituTileProvider;
