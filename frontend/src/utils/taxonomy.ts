import type { DataSchemaCatalogNode, DataSchemaSummary } from "../types";
import { currentLocale } from "../i18n";

const englishTaxonomy: Record<string, { name: string; description: string }> = {
  spatial: {
    name: "Geographic data",
    description: "Data with parsed geographic coordinates.",
  },
  non_spatial: {
    name: "Non-geographic data",
    description: "Tables, documents and images without geographic coordinates.",
  },
};
export const fallbackTaxonomyTree: DataSchemaCatalogNode[] = [
  taxonomyLeaf(
    "spatial",
    "地理数据",
    "具有地理坐标信息的矢量、栅格和坐标表格。",
  ),
  taxonomyLeaf(
    "non_spatial",
    "非地理数据",
    "没有地理坐标信息的表格、文档、图片等资料。",
  ),
];

export interface TaxonomySelectOption {
  value: string;
  label: string;
  disabled?: boolean;
  children?: TaxonomySelectOption[];
}

export function taxonomyTree(
  schema: DataSchemaSummary | null | undefined,
): DataSchemaCatalogNode[] {
  const tree = schema?.catalogTree.length
    ? schema.catalogTree
    : fallbackTaxonomyTree;
  return currentLocale() === "en-US" ? localizeTaxonomyNodes(tree) : tree;
}

function localizeTaxonomyNodes(
  nodes: DataSchemaCatalogNode[],
  parentPath: string[] = [],
): DataSchemaCatalogNode[] {
  return nodes.map((node) => {
    const copy =
      englishTaxonomy[node.code] ?? englishTaxonomy[node.categoryCode];
    const name = copy?.name ?? node.name;
    const path = [...parentPath, name];
    return {
      ...node,
      name,
      description: copy?.description ?? node.description,
      path,
      children: localizeTaxonomyNodes(node.children, path),
    };
  });
}

export function taxonomySelectOptions(
  schema: DataSchemaSummary | null | undefined,
): TaxonomySelectOption[] {
  return taxonomyTree(schema).map(toSelectOption);
}

export function taxonomyLeafOptions(
  schema: DataSchemaSummary | null | undefined,
): Array<{ value: string; label: string }> {
  return flattenTaxonomy(taxonomyTree(schema))
    .filter((node) => node.selectable)
    .map((node) => ({
      value: node.categoryCode,
      label: node.path.join(" / "),
    }));
}

export function flattenTaxonomy(
  nodes: DataSchemaCatalogNode[],
): DataSchemaCatalogNode[] {
  return nodes.flatMap((node) => [node, ...flattenTaxonomy(node.children)]);
}

export function findTaxonomyNode(
  nodes: DataSchemaCatalogNode[],
  categoryCode: string | null | undefined,
): DataSchemaCatalogNode | null {
  if (!categoryCode) return null;
  for (const node of nodes) {
    if (node.categoryCode === categoryCode || node.code === categoryCode) {
      return node;
    }
    const child = findTaxonomyNode(node.children, categoryCode);
    if (child) return child;
  }
  return null;
}

function taxonomyLeaf(
  code: string,
  name: string,
  description: string,
): DataSchemaCatalogNode {
  return {
    code,
    name,
    categoryCode: code,
    selectable: true,
    description,
    path: [name],
    domainType: null,
    spatialClass: null,
    children: [],
  };
}

function toSelectOption(node: DataSchemaCatalogNode): TaxonomySelectOption {
  return {
    value: node.categoryCode,
    label: node.name,
    disabled: !node.selectable,
    children: node.children.length
      ? node.children.map(toSelectOption)
      : undefined,
  };
}
