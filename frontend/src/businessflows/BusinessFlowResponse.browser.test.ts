import { afterEach, expect, it, vi } from "vitest";
import { businessFlowsApi } from "../api/businessFlows";
import { resetProjectSession, setActiveProject } from "../projects/session";
import { endBrowserSession } from "../auth/browserSession";
import { businessFlowRun, geologyDetail } from "./businessFlow.testFixtures";

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  vi.unstubAllGlobals();
  resetProjectSession();
  endBrowserSession(false);
});
it("rejects successful HTML and incomplete definitions instead of passing them to the graph", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response("<!doctype html><title>unexpected</title>", {
          headers: { "Content-Type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(
        new Response("<!doctype html><title>unexpected</title>", {
          headers: { "Content-Type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(json({ items: null, canManage: false }))
      .mockResolvedValueOnce(
        json({
          ...geologyDetail,
          version: {
            ...geologyDetail.version,
            definition: {
              ...geologyDetail.version!.definition,
              inputRequirements: [{ key: "broken" }],
            },
          },
        }),
      ),
  );
  await expect(businessFlowsApi.list()).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  await expect(businessFlowsApi.list()).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  await expect(businessFlowsApi.detail(1)).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
});
it("binds a create to the current project and preserves a typed immutable definition", async () => {
  setActiveProject("3");
  const fetch = vi.fn().mockResolvedValue(json(geologyDetail));
  vi.stubGlobal("fetch", fetch);
  await expect(
    businessFlowsApi.create({
      code: "geology_reasoning",
      name: "地质综合推理",
      definition: geologyDetail.version!.definition,
    }),
  ).resolves.toEqual(geologyDetail);
  const request = fetch.mock.calls[0]?.[0] as Request;
  expect(request.headers.get("X-Project-Id")).toBe("3");
  expect(request.method).toBe("POST");
  const body = await request.json();
  expect(body.definition.nodes[2].review.human).toBe(true);
  expect(body.definition.adapter).toBe("geology_generic");
});
it("rejects a mismatched detail and a malformed run actor state", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        json({ ...geologyDetail, flow: { ...geologyDetail.flow, id: 2 } }),
      )
      .mockResolvedValueOnce(
        json({
          id: "flow-run",
          status: "running",
          revision: 1,
          definitionSnapshot: geologyDetail.version!.definition,
          nodes: [
            {
              nodeId: "apply",
              status: "running",
              attempt: 1,
              human: { required: true, status: "pending" },
              executor: {},
              reviewer: { status: "pending" },
            },
          ],
          events: [],
        }),
      ),
  );
  await expect(businessFlowsApi.detail(1)).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  await expect(businessFlowsApi.run("flow-run")).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
});

it("rejects a well formed response belonging to a different requested workflow", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json(businessFlowRun({ id: "other-run" }))),
  );
  await expect(businessFlowsApi.run("expected-run")).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  await expect(businessFlowsApi.pause("expected-run")).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
});

it("rejects malformed recovery and trace payloads before rendering nested fields", async () => {
  const run = businessFlowRun();
  Object.assign(run.nodes[0]!, {
    contextRecovery: { nodeId: "analyse", level: 0 },
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(json(run))
      .mockResolvedValueOnce(
        json({
          nodeId: "analyse",
          title: "节点",
          requests: [{ id: "broken" }],
          actions: [],
          historical: false,
          nextOffset: null,
        }),
      ),
  );
  await expect(businessFlowsApi.run(run.id)).rejects.toMatchObject({
    name: "ResponseFormatError",
  });
  await expect(
    businessFlowsApi.nodeTrace(run.id, "analyse"),
  ).rejects.toMatchObject({ name: "ResponseFormatError" });
});
