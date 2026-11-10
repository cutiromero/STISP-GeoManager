import {
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  type FormInstance,
} from "antd";
import type { ReactNode } from "react";
import type {
  ComputeCandidate,
  ComputeManifest,
  ComputeParameterSpec,
} from "../api/generated/types.gen";
import { useComputeText } from "./ui";
import "./ComputeAlgorithmFields.css";

export type ComputeFieldValues = {
  inputs?: Record<string, number>;
  parameters?: Record<string, unknown>;
};

export function resetLinkedComputeParameters(
  form: FormInstance,
  manifest: ComputeManifest,
  changed: ComputeFieldValues,
) {
  for (const inputKey of Object.keys(changed.inputs ?? {})) {
    for (const parameter of manifest.parameters) {
      if (
        parameter.input === inputKey &&
        (parameter.type === "band" || parameter.type === "field")
      )
        form.setFieldValue(["parameters", parameter.key], undefined);
    }
  }
}

export function ComputeParameterControl({
  parameter,
  candidate,
  value,
  checked,
  onChange,
  id,
}: {
  parameter: ComputeParameterSpec;
  candidate?: Pick<ComputeCandidate, "fields" | "bands">;
  value?: unknown;
  checked?: boolean;
  onChange?: (value: unknown) => void;
  id?: string;
}) {
  const ui = useComputeText();
  if (parameter.type === "boolean")
    return (
      <Switch
        id={id}
        checked={checked}
        onChange={onChange}
        checkedChildren={ui("开启", "On")}
        unCheckedChildren={ui("关闭", "Off")}
      />
    );
  if (["band", "field", "enum"].includes(parameter.type)) {
    const options: { value: string | number; label: string }[] =
      parameter.type === "band"
        ? Array.from({ length: candidate?.bands ?? 0 }, (_, index) => ({
            value: index + 1,
            label: ui(`第 ${index + 1} 波段`, `Band ${index + 1}`),
          }))
        : (parameter.type === "field"
            ? (candidate?.fields ?? [])
            : (parameter.choices ?? [])
          ).map((entry) => ({ value: entry, label: ui(entry) }));
    return (
      <Select
        id={id}
        value={value as string | number | undefined}
        onChange={onChange}
        showSearch
        optionFilterProp="label"
        options={options}
        disabled={parameter.type !== "enum" && !candidate}
        placeholder={
          parameter.type !== "enum" && !candidate
            ? ui("请先选择输入数据", "Choose input data first")
            : ui("请选择", "Select")
        }
        aria-label={ui(parameter.label)}
      />
    );
  }
  if (parameter.type === "integer" || parameter.type === "number")
    return (
      <InputNumber
        id={id}
        value={typeof value === "number" ? value : null}
        onChange={onChange}
        min={parameter.min}
        max={parameter.max}
        precision={parameter.type === "integer" ? 0 : undefined}
        placeholder={ui("请输入数值", "Enter a value")}
      />
    );
  return (
    <Input
      id={id}
      value={typeof value === "string" ? value : ""}
      maxLength={2000}
      onChange={(event) => onChange?.(event.target.value)}
      placeholder={ui("请输入", "Enter text")}
    />
  );
}

function FieldSection({
  number,
  title,
  detail,
  children,
}: {
  number: string;
  title: string;
  detail?: string;
  children: ReactNode;
}) {
  return (
    <section className="compute-field-section" aria-label={title}>
      <div className="compute-field-heading">
        <span aria-hidden="true">{number}</span>
        <h3>{title}</h3>
        {detail && <small>{detail}</small>}
      </div>
      {children}
    </section>
  );
}

export default function ComputeAlgorithmFields({
  manifest,
  candidates,
  values,
  loading = false,
  onSearch,
  searchControls,
}: {
  manifest: ComputeManifest;
  candidates: ComputeCandidate[];
  values?: ComputeFieldValues;
  loading?: boolean;
  onSearch?: (keyword: string) => void;
  searchControls?: ReactNode;
}) {
  const ui = useComputeText();
  const form = Form.useFormInstance();
  const fieldValues: ComputeFieldValues = values ?? form.getFieldsValue(true);
  const selected = Object.fromEntries(
    Object.entries(fieldValues.inputs ?? {}).map(([key, id]) => [
      key,
      candidates.find((candidate) => candidate.id === id),
    ]),
  );
  const kindText = (kind: string) =>
    ({
      raster: ui("栅格影像", "Raster"),
      vector: ui("矢量数据", "Vector"),
      table: ui("数据表", "Table"),
      image: ui("图片", "Image"),
      report: ui("报告", "Report"),
      archive: ui("文件包", "Archive"),
    })[kind] ?? kind;
  const defaultText = (parameter: ComputeParameterSpec) => {
    const value = parameter.default;
    if (typeof value === "boolean")
      return value ? ui("开启", "On") : ui("关闭", "Off");
    if (parameter.type === "band" && typeof value === "number")
      return ui(`第 ${value} 波段`, `Band ${value}`);
    return ui(String(value));
  };
  return (
    <div className="compute-algorithm-fields">
      <FieldSection
        number="01"
        title={ui("输入数据", "Input data")}
        detail={ui("当前项目", "Current project")}
      >
        {searchControls}
        <div className="compute-field-grid">
          {manifest.inputs.map((input) => {
            const candidate = selected[input.key];
            return (
              <Form.Item
                key={input.key}
                name={["inputs", input.key]}
                label={ui(input.label)}
                rules={[
                  {
                    required: input.required,
                    message: ui("请选择输入数据", "Select input data"),
                  },
                ]}
                extra={
                  <span className="compute-field-context">
                    <span>{kindText(input.kind)}</span>
                    {candidate?.bands ? (
                      <span>
                        {ui(
                          `${candidate.bands} 波段`,
                          `${candidate.bands} bands`,
                        )}
                      </span>
                    ) : null}
                    {candidate?.crs && <span>{candidate.crs}</span>}
                    {input.minBands !== undefined && (
                      <span>
                        {ui(
                          `至少 ${input.minBands} 波段`,
                          `At least ${input.minBands} bands`,
                        )}
                      </span>
                    )}
                  </span>
                }
              >
                <Select
                  showSearch
                  onSearch={onSearch}
                  loading={loading}
                  optionFilterProp="label"
                  placeholder={ui("选择要处理的数据", "Choose data to process")}
                  aria-label={ui(input.label)}
                  options={candidates
                    .filter((candidate) => candidate.kind === input.kind)
                    .map((candidate) => ({
                      value: candidate.id,
                      label: `${candidate.name}${candidate.bands ? ui(` / ${candidate.bands} 波段`, ` / ${candidate.bands} bands`) : ""}`,
                      disabled:
                        input.minBands !== undefined &&
                        candidate.bands < input.minBands,
                    }))}
                />
              </Form.Item>
            );
          })}
        </div>
        {manifest.inputs.length === 0 && (
          <p className="compute-field-note">
            {ui(
              "此算法无需输入数据。",
              "This algorithm requires no input data.",
            )}
          </p>
        )}
      </FieldSection>
      <FieldSection number="02" title={ui("算法参数", "Algorithm parameters")}>
        <div className="compute-field-grid">
          {manifest.parameters.map((parameter) => {
            if (
              parameter.when &&
              fieldValues.parameters?.[String(parameter.when.key)] !==
                parameter.when.equals
            )
              return null;
            const candidate = parameter.input
              ? selected[parameter.input]
              : undefined;
            const linkedInput = manifest.inputs.find(
              (input) => input.key === parameter.input,
            );
            const validate = async (_rule: unknown, value: unknown) => {
              const currentCandidate = parameter.input
                ? candidates.find(
                    (item) =>
                      item.id ===
                      form.getFieldValue(["inputs", parameter.input]),
                  )
                : undefined;
              if (value === undefined || value === null || value === "") {
                if (parameter.required)
                  throw new Error(
                    ui("请补充此参数", "Complete this parameter"),
                  );
                return;
              }
              if (["number", "integer", "band"].includes(parameter.type)) {
                if (
                  typeof value !== "number" ||
                  !Number.isFinite(value) ||
                  (parameter.type !== "number" && !Number.isInteger(value))
                )
                  throw new Error(ui("请输入有效数字", "Enter a valid number"));
                if (
                  (parameter.min !== undefined && value < parameter.min) ||
                  (parameter.max !== undefined && value > parameter.max)
                )
                  throw new Error(
                    ui(
                      "数值超出允许范围",
                      "Value is outside the allowed range",
                    ),
                  );
              }
              if (parameter.type === "boolean" && typeof value !== "boolean")
                throw new Error(ui("请选择开启或关闭", "Choose on or off"));
              if (
                ["string", "enum", "field"].includes(parameter.type) &&
                (typeof value !== "string" || value.length > 2000)
              )
                throw new Error(ui("请输入有效文本", "Enter valid text"));
              if (
                parameter.type === "enum" &&
                (typeof value !== "string" ||
                  !parameter.choices?.includes(value))
              )
                throw new Error(
                  ui("请从可用选项中选择", "Choose an available option"),
                );
              if (
                parameter.type === "band" &&
                (!currentCandidate ||
                  typeof value !== "number" ||
                  value < 1 ||
                  value > currentCandidate.bands)
              )
                throw new Error(
                  ui(
                    "请重新选择当前数据的波段",
                    "Select a band from the current data",
                  ),
                );
              if (
                parameter.type === "field" &&
                (!currentCandidate ||
                  typeof value !== "string" ||
                  !currentCandidate.fields.includes(value))
              )
                throw new Error(
                  ui(
                    "请重新选择当前数据的字段",
                    "Select a field from the current data",
                  ),
                );
            };
            return (
              <Form.Item
                key={parameter.key}
                name={["parameters", parameter.key]}
                label={ui(parameter.label)}
                required={parameter.required}
                valuePropName={
                  parameter.type === "boolean" ? "checked" : "value"
                }
                preserve={false}
                rules={[{ validator: validate }]}
                extra={
                  <div className="compute-parameter-help">
                    {parameter.help && <span>{ui(parameter.help)}</span>}
                    <span className="compute-field-context">
                      {linkedInput && (
                        <span>
                          {ui("关联：", "Input: ")}
                          {ui(linkedInput.label)}
                        </span>
                      )}
                      {parameter.default !== undefined && (
                        <span>
                          {ui("默认参考：", "Default reference: ")}
                          {defaultText(parameter)}
                        </span>
                      )}
                      {parameter.min !== undefined &&
                      parameter.max !== undefined ? (
                        <span>
                          {ui("范围：", "Range: ")}
                          {parameter.min} – {parameter.max}
                        </span>
                      ) : parameter.min !== undefined ? (
                        <span>≥ {parameter.min}</span>
                      ) : (
                        parameter.max !== undefined && (
                          <span>≤ {parameter.max}</span>
                        )
                      )}
                    </span>
                  </div>
                }
              >
                <ComputeParameterControl
                  parameter={parameter}
                  candidate={candidate}
                />
              </Form.Item>
            );
          })}
        </div>
        {manifest.parameters.length === 0 && (
          <p className="compute-field-note">
            {ui(
              "此算法无需额外参数。",
              "This algorithm requires no additional parameters.",
            )}
          </p>
        )}
      </FieldSection>
      <FieldSection number="03" title={ui("结果概览", "Result overview")}>
        <div className="compute-output-chips">
          {manifest.outputs.map((output) => (
            <span key={output.key}>
              <strong>{ui(output.label)}</strong>
              <small>{kindText(output.kind)}</small>
            </span>
          ))}
        </div>
        <p className="compute-field-note">
          {ui(
            "计算完成后可查看结果，或存入当前项目的“计算结果”分类。",
            "When complete, view results or import them into this project’s “Compute results” category.",
          )}
        </p>
      </FieldSection>
    </div>
  );
}
