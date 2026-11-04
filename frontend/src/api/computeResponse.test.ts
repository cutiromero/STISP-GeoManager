import { describe, expect, it } from "vitest";
import {
  computeVersion,
  liveComputeTask,
} from "../agent/computeFlow.testFixtures";
import {
  assertAlgorithmList,
  assertCandidateList,
  assertComputeTask,
  assertComputeTaskList,
} from "./computeResponse";
import { ResponseFormatError } from "./responseDiagnostics";

const algorithm = () => ({
  id: 1,
  name: "NDVI",
  identifier: "ndvi",
  enabled: true,
  versions: [structuredClone(computeVersion)],
});

describe("compute response boundaries", () => {
  it("accepts complete algorithm manifests and genuine empty result lists", () => {
    const value = { items: [algorithm()], total: 1 };
    expect(() => assertAlgorithmList(value)).not.toThrow();
    expect(value.items[0]!.versions[0]).toEqual(computeVersion);
    expect(() => assertAlgorithmList({ items: [], total: 0 })).not.toThrow();
    expect(() => assertComputeTaskList({ items: [], total: 0 })).not.toThrow();
  });

  it.each([undefined, null, {}, [null]])(
    "rejects missing or malformed algorithm versions: %s",
    (versions) => {
      expect(() =>
        assertAlgorithmList({
          items: [{ ...algorithm(), versions }],
          total: 1,
        }),
      ).toThrow(ResponseFormatError);
    },
  );

  it.each(["inputs", "parameters", "outputs"])(
    "rejects invalid manifest %s before a form can render",
    (key) => {
      for (const bad of [null, {}, [null]]) {
        const value = algorithm();
        Object.assign(value.versions[0]!.manifest, { [key]: bad });
        expect(() => assertAlgorithmList({ items: [value], total: 1 })).toThrow(
          ResponseFormatError,
        );
      }
    },
  );

  it("checks nested enum/field options and candidate fields", () => {
    const value = algorithm();
    Object.assign(value.versions[0]!.manifest.parameters[0]!, {
      choices: [null],
    });
    expect(() => assertAlgorithmList({ items: [value], total: 1 })).toThrow(
      ResponseFormatError,
    );
    const candidate = {
      id: 10,
      name: "影像",
      kind: "raster",
      fields: [],
      geometryTypes: [],
    };
    expect(() =>
      assertCandidateList({ items: [candidate], total: 1 }),
    ).not.toThrow();
    expect(() =>
      assertCandidateList({
        items: [{ ...candidate, fields: null }],
        total: 1,
      }),
    ).toThrow(ResponseFormatError);
  });

  it("preserves complete computing and terminal task records", () => {
    for (const state of ["running", "succeeded"] as const) {
      const task = liveComputeTask(state);
      const before = structuredClone(task);
      expect(() => assertComputeTask(task)).not.toThrow();
      expect(task).toEqual(before);
    }
  });

  it.each(["inputs", "outputs"])(
    "rejects malformed task %s including null inner entries",
    (key) => {
      for (const bad of [undefined, null, {}, [null]])
        expect(() =>
          assertComputeTask({ ...liveComputeTask(), [key]: bad }),
        ).toThrow(ResponseFormatError);
    },
  );

  it("checks task version and output metadata before task cards are updated", () => {
    expect(() =>
      assertComputeTask({ ...liveComputeTask(), version: null }),
    ).toThrow(ResponseFormatError);
    const task = liveComputeTask("succeeded");
    Object.assign(task.outputs[0]!, { metadata: null });
    expect(() => assertComputeTask(task)).toThrow(ResponseFormatError);
  });
});
