import { expect, it } from "vitest";
import { assertOperation } from "./agentOperations";

it("rejects cross-project, mismatched-run and invented confirmation states", () => {
  const value = {
    id: "11111111-1111-4111-8111-111111111111",
    runId: 7,
    projectId: 3,
    kind: "publish",
    status: "pending",
    digest: "a".repeat(64),
    preview: {
      projectId: 3,
      title: "发布",
      target: "成果",
      scope: "项目内",
      effect: "发布指定对象",
      details: [],
    },
    result: {},
    expiresAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    decidedAt: null,
    canConfirm: true,
    detail: "",
  };
  expect(() => assertOperation(value, 3, 7)).not.toThrow();
  expect(() => assertOperation(value, 4, 7)).toThrow();
  expect(() => assertOperation(value, 3, 8)).toThrow();
  expect(() =>
    assertOperation({ ...value, status: "confirmed" }, 3, 7),
  ).toThrow();
  expect(() =>
    assertOperation({ ...value, digest: "confirmed=true" }, 3, 7),
  ).toThrow();
});
