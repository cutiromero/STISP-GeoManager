import type {
  MonitoringSourceCatalog,
  MonitoringSourceTimePage,
  ResourceListItem,
} from "../api/generated/types.gen";
export function sourceCatalog(
  scene: "spartina" | "wildfire",
  resources: ResourceListItem[],
): MonitoringSourceCatalog {
  const assets = resources.map((resource, index) => ({
    resource,
    metadata: {
      resourceId: resource.id,
      resourceVersion: resource.updatedAt,
      family: scene === "wildfire" ? "seasfire" : "multitemporal_features",
      collectionKey: "registered-series",
      period: {
        startsAt: `2026-0${1 + index * 3}-01`,
        endsAt: `2026-0${1 + index * 3}-28`,
        precision: "month" as const,
      },
      sourceSchema:
        scene === "wildfire"
          ? {
              kind: "native_cube" as const,
              timeCount: 2001,
              bounds: [-180, -90, 180, 90],
            }
          : {
              kind: "raster" as const,
              bands: 16,
              bounds: [121.8, 31.1, 122, 31.4],
            },
      indexVersion: "real-source-v1",
      usages: [{ scene, purpose: "input" as const }],
      canEdit: true,
    },
    collectionLabel: "登记监测系列",
    years:
      scene === "wildfire"
        ? [{ year: 2026, count: 46, validProducts: ["gwis_ba" as const] }]
        : [],
  }));
  return {
    projectId: 13,
    scene,
    assets,
    hasMoreSources: false,
    nextOffset: null,
    collections: [
      {
        key: "registered-series",
        label: "登记监测系列",
        count: resources.length,
        startsAt: "2026-01-01",
        endsAt: "2026-12-31",
      },
    ],
    method: {
      definitionId: 2,
      versionId: 21,
      operatorVersionId: 97,
      title: "监测任务",
      goal: "处理所选资料",
      inputs: (scene === "wildfire"
        ? ["cube"]
        : ["march", "august", "december"]
      ).map((key) => ({
        key,
        label: key,
        kind: "raster",
        required: true,
        bandCount: scene === "wildfire" ? null : 16,
        minBands: 0,
        dtypes: [],
        nativeCube: scene === "wildfire",
      })),
      parameters: [],
      inputRequirements: [],
    },
    inputSets:
      scene === "wildfire"
        ? []
        : [
            {
              id: "dynamic-2026",
              collectionKey: "registered-series",
              label: "2026-01 / 2026-04 / 2026-07",
              startsAt: "2026-01-01",
              endsAt: "2026-07-31",
              inputs: Object.fromEntries(
                resources.map((row, index) => [
                  ["march", "august", "december"][index]!,
                  row.id,
                ]),
              ),
              periods: assets.map((row) => row.metadata.period),
              resources,
            },
          ],
  };
}
export const sourceTimes: MonitoringSourceTimePage = {
  resourceId: 1475,
  indexVersion: "real-source-v1",
  nextOrdinal: null,
  items: [
    {
      id: 11,
      ordinal: 2000,
      date: "2026-12-27",
      endDate: "2026-12-31",
      validProducts: ["gwis_ba"],
    },
  ],
};
