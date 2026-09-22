import type { DataDomainType } from "../types";

export type ImportAccessScopeId = number | "__self__";

export interface ImportFormValues {
  name: string;
  domainType?: DataDomainType;
  categoryCode?: string;
  importMode: "geographic" | "table";
  longitudeColumn?: string;
  latitudeColumn?: string;
  accessGroupIds: ImportAccessScopeId[];
}

export function normalizeImportValues(
  values: Partial<ImportFormValues>,
): Partial<ImportFormValues> {
  const name = values.name?.trim();
  const importMode = values.importMode;
  return {
    name,
    domainType: values.domainType,
    categoryCode: values.categoryCode,
    importMode,
    longitudeColumn: values.longitudeColumn || undefined,
    latitudeColumn: values.latitudeColumn || undefined,
    accessGroupIds: values.accessGroupIds ?? [],
  };
}
