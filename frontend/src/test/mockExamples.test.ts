import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

type MockExamples = Record<string, Record<string, unknown>>;

function loadExamples(): MockExamples {
  const examplesDir = resolve(process.cwd(), "../mock/prism/examples");
  return readdirSync(examplesDir)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .reduce<MockExamples>((examples, file) => {
      const fileExamples = JSON.parse(
        readFileSync(resolve(examplesDir, file), "utf8"),
      ) as MockExamples;
      for (const key of Object.keys(fileExamples)) {
        expect(examples[key], `duplicate mock target: ${key}`).toBeUndefined();
      }
      return { ...examples, ...fileExamples };
    }, {});
}

function response<T>(
  examples: MockExamples,
  operation: string,
  status = "200",
) {
  return examples[operation]?.[status] as T;
}

function arrayById<T extends { id: number | string }>(items: T[]) {
  return new Map(items.map((item) => [item.id, item]));
}

describe("Prism mock example business consistency", () => {
  const examples = loadExamples();

  it("keeps registered user roles aligned with effective permissions", () => {
    const register = response<{
      user: {
        roles: string[];
        permissions: { canUploadData: boolean };
        effectivePermissions: string[];
      };
      roleApplication: { status: string };
    }>(examples, "POST /api/auth/register/");

    expect(register.user.permissions.canUploadData).toBe(false);
    expect(register.user.effectivePermissions).not.toContain(
      "catalog.add_dataresource",
    );
    expect(register.user.roles).toContain("普通用户");
    expect(register.user.roles).not.toContain("游客");
    expect(register.roleApplication.status).toBe("pending");
  });

  it("links raster resources, map layers, and raster datasets by shared ids", () => {
    const resources = response<{
      items: Array<{ id: number | string; code: string; dataType: string }>;
    }>(examples, "GET /api/catalog/resources/").items;
    const layers = response<{
      items: Array<{
        id: number | string;
        code: string;
        layerType: string;
        dataResourceId?: number;
      }>;
    }>(examples, "GET /api/layers/").items;
    const datasets = response<{
      items: Array<{
        id: number;
        code: string;
        dataResourceId: number;
        mapLayerId: number;
        bandCount: number;
      }>;
    }>(examples, "GET /api/raster/datasets/").items;
    const resourcesById = arrayById(resources);
    const layersById = arrayById(layers);

    for (const dataset of datasets) {
      const resource = resourcesById.get(dataset.dataResourceId);
      const layer = layersById.get(dataset.mapLayerId);
      expect(resource?.dataType).toBe("raster");
      expect(resource?.code).toBe(dataset.code);
      expect(layer?.layerType).toBe("raster");
      expect(layer?.dataResourceId).toBe(dataset.dataResourceId);
      expect(dataset.bandCount).toBeGreaterThan(0);
    }
  });

  it("keeps vector resource profile and query result counts consistent", () => {
    const profile = response<{
      resource: { id: number; itemCount: number };
      featureCount: number;
      bounds: number[];
    }>(examples, "GET /api/catalog/resources/{id}/profile/");
    const query = response<{
      resourceId: number;
      totalCount: number;
      returnedCount: number;
      geojson: { features: unknown[] };
    }>(examples, "POST /api/catalog/resources/{id}/query/");

    expect(profile.resource.itemCount).toBe(profile.featureCount);
    expect(query.resourceId).toBe(profile.resource.id);
    expect(query.totalCount).toBe(profile.featureCount);
    expect(query.returnedCount).toBe(query.geojson.features.length);
    expect(profile.bounds).toHaveLength(4);
  });
});
