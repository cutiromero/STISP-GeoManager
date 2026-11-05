import { beforeEach, expect, it, vi } from "vitest";
import {
  geologicalColor,
  previewSuggestions,
  queryReviewMap,
  reviewBounds,
  reviewLegend,
  reviewResourceIds,
  reviewSuggestionIndex,
  colorReviewMap,
} from "./geologyReviewData";
import {
  afterReviewMap,
  beforeReviewMap,
  reviewQuery,
  reviewDifferences,
  reviewWorkflow,
} from "./geologyReview.testFixtures";
const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../api/client", () => ({ requestJson: request }));
beforeEach(() => request.mockReset());

it("对比与讲解使用资源按name分类配色，图例显示单元名称", () => {
  const data = structuredClone(beforeReviewMap);
  colorReviewMap(data, {
    symbolization: {
      renderer: {
        type: "uniqueValue",
        field: "name",
        classes: [{ value: "八宝山组", label: "八宝山组", color: "#123456" }],
        defaultClass: { color: "#abcdef" },
      },
    },
  });
  expect(data.features[0]!.properties.fill_color).toBe("#123456");
  expect(data.features[1]!.properties.fill_color).toBe("#abcdef");
  expect(reviewLegend(data).map((item) => item.name)).toEqual([
    "八宝山组",
    "第四系",
  ]);
});

it.each(["LineString", "Point"] as const)(
  "讲解页读取%s成果的分类符号化，不仅处理具名面",
  async (type) => {
    const data = structuredClone(beforeReviewMap);
    data.features = [
      {
        ...data.features[0]!,
        geometry:
          type === "Point"
            ? { type, coordinates: [98.4, 35.6] }
            : {
                type,
                coordinates: [
                  [98.4, 35.6],
                  [98.45, 35.62],
                ],
              },
        properties: { state: "keep" },
      },
    ];
    request
      .mockResolvedValueOnce(reviewQuery(201, data))
      .mockResolvedValueOnce({
        defaultVisualization: {
          symbolization: {
            renderer: {
              type: "uniqueValue",
              field: "state",
              classes: [{ value: "keep", color: "#416fa4" }],
            },
          },
        },
      });
    const result = await queryReviewMap(201, { mixed: true, loadStyle: true });
    expect(result.features[0]!.properties.fill_color).toBe("#416fa4");
    expect(result.features[0]!.properties._review_classification_field).toBe(
      "state",
    );
    expect(request.mock.calls[1]![0]).toBe(
      "/api/catalog/resources/201/profile/",
    );
  },
);

it("loads the primary pair concurrently with display-only geometry", async () => {
  let finishFirst = (_value: ReturnType<typeof reviewQuery>) => {};
  request
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    )
    .mockResolvedValueOnce(reviewQuery(201, afterReviewMap));
  const first = queryReviewMap(101, { displayGeometry: true });
  const second = queryReviewMap(201, { displayGeometry: true });
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(request.mock.calls[0]![1].body.displayGeometry).toBe(true);
  finishFirst(reviewQuery(101, beforeReviewMap));
  expect(await first).toEqual(beforeReviewMap);
  expect(await second).toEqual(afterReviewMap);
  expect(request).toHaveBeenCalledTimes(2);
});

it("最多同时传输两张显示图层，第三张等待空闲名额", async () => {
  let finishFirst = (_value: ReturnType<typeof reviewQuery>) => {};
  let finishSecond = (_value: ReturnType<typeof reviewQuery>) => {};
  request
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSecond = resolve;
        }),
    )
    .mockResolvedValueOnce(reviewQuery(301, beforeReviewMap));
  const pending = [
    queryReviewMap(101, { displayGeometry: true }),
    queryReviewMap(201, { displayGeometry: true }),
    queryReviewMap(301, { displayGeometry: true }),
  ];
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  finishFirst(reviewQuery(101, beforeReviewMap));
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(3));
  finishSecond(reviewQuery(201, afterReviewMap));
  await Promise.all(pending);
});

it("其他地质检查入口保持原精度和串行查询行为", async () => {
  let finishFirst = (_value: ReturnType<typeof reviewQuery>) => {};
  request
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    )
    .mockResolvedValueOnce(reviewQuery(201, afterReviewMap));
  const first = queryReviewMap(101);
  const second = queryReviewMap(201);
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  expect(request.mock.calls[0]![1].body.displayGeometry).toBeUndefined();
  finishFirst(reviewQuery(101, beforeReviewMap));
  await Promise.all([first, second]);
});

it("完成后的建议入口按对象及修改类型定位，区分同一图斑的两项修改", () => {
  const workflow = reviewWorkflow(true);
  expect(
    reviewSuggestionIndex(workflow, reviewDifferences, "suggest-age"),
  ).toBe(1);
  expect(
    reviewSuggestionIndex(workflow, reviewDifferences, "suggest-gap"),
  ).toBe(0);
  expect(
    reviewSuggestionIndex(
      workflow,
      previewSuggestions(workflow),
      "suggest-age",
    ),
  ).toBe(1);
  expect(reviewSuggestionIndex(workflow, reviewDifferences, "missing")).toBe(
    -1,
  );
});

it("只取真实算子 corrected 和 changes_map 的资源，不把CSV当差异图", () => {
  expect(reviewResourceIds(reviewWorkflow())).toEqual({
    before: 101,
    after: null,
    differences: null,
  });
  const workflow = reviewWorkflow(true);
  expect(reviewResourceIds(workflow)).toEqual({
    before: 101,
    after: 201,
    differences: 202,
  });
  workflow.plan.stages = [
    {
      identifier: "geology-map-correct",
      outputs: [{ key: "changes", resourceId: 999 }],
    },
  ];
  expect(reviewResourceIds(workflow)).toEqual({
    before: 101,
    after: null,
    differences: null,
  });
});
it("拒绝截断、错误资源和非面查询，保留权限错误", async () => {
  const response = reviewQuery(101, beforeReviewMap);
  request.mockResolvedValueOnce({ ...response, limitExceeded: true });
  await expect(queryReviewMap(101)).rejects.toThrow("超过双图预览范围");
  request.mockResolvedValueOnce({ ...response, totalCount: 3 });
  await expect(queryReviewMap(101)).rejects.toThrow("返回不完整");
  request.mockResolvedValueOnce({ ...response, resourceId: 201 });
  await expect(queryReviewMap(101)).rejects.toThrow("返回不完整");
  request.mockResolvedValueOnce({
    ...response,
    geojson: {
      type: "FeatureCollection",
      features: [
        {
          ...beforeReviewMap.features[0],
          geometry: { type: "Point", coordinates: [98, 35] },
        },
        beforeReviewMap.features[1],
      ],
    },
  });
  await expect(queryReviewMap(101)).rejects.toThrow("完整的面图件");
  const denied = Object.assign(new Error("无权查看此资源"), { status: 403 });
  request.mockRejectedValueOnce(denied);
  await expect(queryReviewMap(101)).rejects.toBe(denied);
});
it("建议预览保持真实范围，批准后仅返回所选建议且不写数据", () => {
  const workflow = reviewWorkflow();
  const all = previewSuggestions(workflow);
  expect(all.features).toHaveLength(2);
  expect(all.features[0]!.geometry).toEqual(
    workflow.modificationReview!.suggestions[0]!.preview,
  );
  workflow.modificationReview!.approvedSuggestionIds = ["suggest-age"];
  const selected = previewSuggestions(workflow);
  expect(selected.features).toHaveLength(1);
  expect(selected.features[0]!.properties).toMatchObject({
    suggestion_id: "suggest-age",
    status: "已批准",
  });
  expect(request).not.toHaveBeenCalled();
});
it("按稳定class区分类别，前后颜色一致且边界使用WGS84", () => {
  const legend = reviewLegend(beforeReviewMap, afterReviewMap);
  expect(legend.map((item) => item.key)).toEqual(["5", "9"]);
  expect(legend[0]!.color).toBe(geologicalColor(5));
  const sameNames = structuredClone(beforeReviewMap);
  sameNames.features[1]!.properties.name = "八宝山组";
  expect(reviewLegend(sameNames)).toHaveLength(2);
  expect(geologicalColor("invalid")).toBe("#d4dce5");
  expect(reviewBounds(beforeReviewMap)).toEqual([98.4, 35.6, 98.45, 35.62]);
  expect(reviewBounds({ type: "FeatureCollection", features: [] })).toBeNull();
});
