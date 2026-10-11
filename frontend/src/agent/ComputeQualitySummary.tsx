import { DownloadOutlined } from "@ant-design/icons";
import { Alert, Button, Collapse } from "antd";
import { useEffect, useState } from "react";
import { computeApi, downloadComputeFile } from "../api/compute";
import type { ComputePreview, ComputeTask } from "../api/generated/types.gen";
import { useComputeText } from "../compute/ui";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
const metricLabels: Record<string, [string, string]> = {
  totalFeatures: ["检查要素", "Features checked"],
  validAfter: ["修复后有效", "Valid after repair"],
  needsReview: ["需要审核", "Needs review"],
  failed: ["修复失败", "Repair failures"],
  maxAreaChangePct: [
    "面积变化审核阈值（%）",
    "Area change review threshold (%)",
  ],
};
const isTrue = (value: unknown) =>
  value === true || ["true", "1"].includes(String(value).toLowerCase());

export default function ComputeQualitySummary({ task }: { task: ComputeTask }) {
  const ui = useComputeText();
  const reports = [
    ...new Map(
      task.outputs.flatMap((output) => {
        const quality = record(output.metadata.qualityCheck);
        return ["passed", "needs_review"].includes(String(quality.status))
          ? [[JSON.stringify(quality), quality] as const]
          : [];
      }),
    ).values(),
  ];
  const needsReview = reports.some(
    (quality) => quality.status === "needs_review",
  );
  const logOutput = task.outputs.find(
    (output) => output.key === "repair_log" && !output.expired,
  );
  const auditOutput = task.outputs.find(
    (output) =>
      output.key === "repair_audit" && !output.expired && output.downloadUrl,
  );
  const [preview, setPreview] = useState<ComputePreview>();
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    if (!needsReview || !logOutput) return;
    let disposed = false;
    setPreview(undefined);
    setError("");
    void computeApi.preview(logOutput.id).then(
      (value) => {
        if (!disposed) setPreview(value);
      },
      (reason: unknown) => {
        if (!disposed)
          setError(
            reason instanceof Error
              ? reason.message
              : ui("审核记录暂时无法读取", "Unable to read review records"),
          );
      },
    );
    return () => {
      disposed = true;
    };
  }, [task.id, needsReview, logOutput?.id]);
  if (!reports.length) return null;
  const rows =
    preview?.rows.map((values) =>
      Object.fromEntries(
        preview.columns.map((key, index) => [key, values[index]]),
      ),
    ) ?? [];
  const reviewRows = rows.filter((row) => isTrue(row.needs_review));
  const totalRows = preview?.metadata.rows;
  const partial = typeof totalRows === "number" && totalRows > rows.length;
  const download = async () => {
    if (!auditOutput || downloading) return;
    setDownloading(true);
    setError("");
    try {
      await downloadComputeFile(auditOutput.downloadUrl, auditOutput.fileName);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : ui("下载暂时失败", "Download failed"),
      );
    } finally {
      setDownloading(false);
    }
  };
  return (
    <section
      className="agent-quality-summary"
      aria-label={ui("实际质量检查", "Actual quality checks")}
    >
      {reports.map((quality) => {
        const metrics = record(quality.metrics);
        return (
          <Alert
            key={JSON.stringify(quality)}
            showIcon
            type={quality.status === "needs_review" ? "warning" : "info"}
            title={
              quality.status === "needs_review"
                ? ui("候选结果需要审核", "Candidate results need review")
                : ui("算法质量检查已通过", "Algorithm quality checks passed")
            }
            description={
              <>
                <p>
                  {typeof quality.summary === "string" ? quality.summary : ""}
                </p>
                <dl className="agent-quality-metrics">
                  {Object.entries(metricLabels).flatMap(([key, label]) =>
                    typeof metrics[key] === "number"
                      ? [
                          <div key={key}>
                            <dt>{ui(...label)}</dt>
                            <dd>{String(metrics[key])}</dd>
                          </div>,
                        ]
                      : [],
                  )}
                </dl>
              </>
            }
          />
        );
      })}
      {needsReview && logOutput && (
        <Collapse
          size="small"
          defaultActiveKey={["review"]}
          items={[
            {
              key: "review",
              label: ui(
                "核对修复原因与降维片段",
                "Review repair reasons and dimensional fragments",
              ),
              children: (
                <div className="agent-quality-details">
                  {reviewRows.length ? (
                    reviewRows.map((row) => (
                      <article key={JSON.stringify(row)}>
                        <strong>
                          {ui(
                            `记录第 ${String(row.repair_row)} 项`,
                            `Record ${String(row.repair_row)}`,
                          )}
                        </strong>
                        {Boolean(row.review_reasons) && (
                          <p>{String(row.review_reasons)}</p>
                        )}
                        {row.non_polygon_parts !== undefined && (
                          <span>
                            {ui(
                              "非面／降维片段",
                              "Non-polygon or lower-dimensional fragments",
                            )}
                            ：{String(row.non_polygon_parts)}
                          </span>
                        )}
                        {Boolean(row.candidate_type) && (
                          <span>
                            {ui("完整候选形态", "Complete candidate geometry")}
                            ：{String(row.candidate_type)}
                          </span>
                        )}
                      </article>
                    ))
                  ) : (
                    <p>
                      {preview
                        ? ui(
                            "当前预览中未发现需审核行，请结合完整审核包核对。",
                            "No review rows appear in this preview. Check the full audit package.",
                          )
                        : ui(
                            "正在读取实际修复记录…",
                            "Reading actual repair records…",
                          )}
                    </p>
                  )}
                  {partial && (
                    <p>
                      {ui(
                        `已显示前 ${rows.length} 条记录，完整记录请下载审核包。`,
                        `Showing the first ${rows.length} records. Download the audit package for all records.`,
                      )}
                    </p>
                  )}
                </div>
              ),
            },
          ]}
        />
      )}
      {auditOutput && (
        <Button
          icon={<DownloadOutlined aria-hidden="true" />}
          size="small"
          loading={downloading}
          onClick={() => void download()}
        >
          {ui(
            "下载完整候选与审核包",
            "Download full candidate and audit package",
          )}
        </Button>
      )}
      {error && <Alert type="error" title={error} />}
    </section>
  );
}
