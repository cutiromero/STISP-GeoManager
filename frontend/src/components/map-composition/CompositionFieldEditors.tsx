import { Input, InputNumber, Switch } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type {
  MapBounds,
  MapCompositionLayout,
} from "../../map-composition/layout";

export function TextEditor({
  label,
  value,
  multiline,
  onChange,
}: {
  label: string;
  value: MapCompositionLayout["title"];
  multiline?: boolean;
  onChange: (values: Partial<MapCompositionLayout["title"]>) => void;
}) {
  return (
    <div className="composition-text-editor">
      <Toggle
        label={label}
        checked={value.enabled}
        onChange={(enabled) => onChange({ enabled })}
      />
      {multiline ? (
        <Input.TextArea
          rows={2}
          value={value.text}
          onChange={(event) => onChange({ text: event.target.value })}
        />
      ) : (
        <Input
          value={value.text}
          onChange={(event) => onChange({ text: event.target.value })}
        />
      )}
    </div>
  );
}

export function BoundsEditor({
  value,
  onChange,
}: {
  value: MapBounds;
  onChange: (bounds: MapBounds) => void;
}) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const labels = english
    ? (["West", "South", "East", "North"] as const)
    : (["西", "南", "东", "北"] as const);
  return (
    <div className="composition-field-grid composition-bounds-grid">
      {labels.map((label, index) => (
        <Field key={label} label={label}>
          <InputNumber
            value={value[index]}
            step={0.01}
            onChange={(next) => {
              if (typeof next !== "number") return;
              const bounds = [...value] as MapBounds;
              bounds[index] = next;
              onChange(bounds);
            }}
          />
        </Field>
      ))}
    </div>
  );
}

export function BoxEditor({
  value,
  onChange,
}: {
  value: { xMm: number; yMm: number; widthMm: number; heightMm: number };
  onChange: (values: Partial<typeof value>) => void;
}) {
  const { i18n } = useTranslation();
  const english =
    i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
  const labels = {
    xMm: "X(mm)",
    yMm: "Y(mm)",
    widthMm: english ? "Width (mm)" : "宽(mm)",
    heightMm: english ? "Height (mm)" : "高(mm)",
  };
  return (
    <div className="composition-field-grid">
      {(["xMm", "yMm", "widthMm", "heightMm"] as const).map((key) => (
        <Field key={key} label={labels[key]}>
          <InputNumber
            min={0}
            value={value[key]}
            onChange={(next) =>
              typeof next === "number" && onChange({ [key]: next })
            }
          />
        </Field>
      ))}
    </div>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="composition-toggle">
      <span>{label}</span>
      <Switch size="small" checked={checked} onChange={onChange} />
    </label>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="composition-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
