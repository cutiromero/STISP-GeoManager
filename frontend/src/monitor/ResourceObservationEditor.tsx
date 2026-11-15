import { Alert, Button, Input, Select, Space, Spin } from "antd";
import { useEffect, useState } from "react";
import { requestJson } from "../api/client";
import type {
  MonitoringResourceUsage,
  ResourceObservationProfile,
  ResourceObservationProfileUpdate,
} from "../api/generated/types.gen";

const scenes = [
  { value: "spartina", label: "互花米草" },
  { value: "wildfire", label: "野火" },
  { value: "landcover", label: "地表覆盖" },
] as const;
const purposes = [
  { value: "input", label: "原始输入" },
  { value: "result", label: "解译成果" },
  { value: "reference", label: "标准参考" },
  { value: "auxiliary", label: "辅助资料" },
];
export default function ResourceObservationEditor({
  resourceId,
}: {
  resourceId: number;
}) {
  const [profile, setProfile] = useState<ResourceObservationProfile>();
  const [form, setForm] = useState<ResourceObservationProfileUpdate>({});
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const endpoint = `/api/catalog/resources/${resourceId}/observation-metadata/`;
  const accept = (value: ResourceObservationProfile) => {
    setProfile(value);
    setForm({
      usages: value.usages,
      collectionKey: value.collectionKey,
      startsAt: value.period?.startsAt ?? null,
      endsAt: value.period?.endsAt ?? null,
      precision: value.period?.precision ?? "unknown",
    });
  };
  useEffect(() => {
    const controller = new AbortController();
    setProfile(undefined);
    setError(undefined);
    setSaved(false);
    void requestJson<ResourceObservationProfile>(endpoint, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) accept(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, [endpoint]);
  const change = (patch: ResourceObservationProfileUpdate) => {
    setSaved(false);
    setForm((old) => ({ ...old, ...patch }));
  };
  const save = async () => {
    setBusy(true);
    setError(undefined);
    try {
      accept(
        await requestJson<ResourceObservationProfile>(endpoint, {
          method: "PATCH",
          body: form,
        }),
      );
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-label="监测用途与时相" style={{ marginTop: 20 }}>
      <h3>监测用途与时相</h3>
      {error && <Alert type="error" title={error} />}
      {!profile ? (
        !error && <Spin />
      ) : (
        <Space vertical style={{ width: "100%" }}>
          {scenes.map((scene) => (
            <label key={scene.value}>
              {scene.label}
              <Select
                aria-label={`${scene.label}资料用途`}
                allowClear
                disabled={!profile.canEdit || busy}
                style={{ width: "100%" }}
                value={
                  form.usages?.find((row) => row.scene === scene.value)?.purpose
                }
                placeholder="未用于此场景"
                options={purposes}
                onChange={(
                  purpose: MonitoringResourceUsage["purpose"] | undefined,
                ) =>
                  change({
                    usages: [
                      ...(form.usages ?? []).filter(
                        (row) => row.scene !== scene.value,
                      ),
                      ...(purpose ? [{ scene: scene.value, purpose }] : []),
                    ],
                  })
                }
              />
            </label>
          ))}
          <label>
            资料集合标识
            <Input
              aria-label="资料集合标识"
              disabled={!profile.canEdit || busy}
              value={form.collectionKey}
              onChange={(event) =>
                change({ collectionKey: event.target.value })
              }
              placeholder="同一监测系列使用相同标识"
            />
          </label>
          <label>
            时间精度
            <Select
              aria-label="时间精度"
              disabled={
                !profile.canEdit || busy || profile.family === "seasfire"
              }
              style={{ width: "100%" }}
              value={form.precision}
              options={[
                { value: "unknown", label: "未登记" },
                { value: "day", label: "日" },
                { value: "month", label: "月" },
                { value: "year", label: "年" },
                { value: "interval", label: "时段" },
              ]}
              onChange={(precision) =>
                change({
                  precision,
                  ...(precision === "unknown"
                    ? { startsAt: null, endsAt: null }
                    : {}),
                })
              }
            />
          </label>
          {form.precision !== "unknown" && (
            <Space wrap>
              <label>
                观测开始
                <Input
                  type="date"
                  aria-label="观测开始"
                  disabled={
                    !profile.canEdit || busy || profile.family === "seasfire"
                  }
                  value={form.startsAt ?? ""}
                  onChange={(event) =>
                    change({ startsAt: event.target.value || null })
                  }
                />
              </label>
              <label>
                观测结束
                <Input
                  type="date"
                  aria-label="观测结束"
                  disabled={
                    !profile.canEdit || busy || profile.family === "seasfire"
                  }
                  value={form.endsAt ?? ""}
                  onChange={(event) =>
                    change({ endsAt: event.target.value || null })
                  }
                />
              </label>
            </Space>
          )}
          {profile.family === "seasfire" && <p>观测时间取自原生时间坐标。</p>}
          {form.precision === "month" && (
            <p>月精度使用月初至月末，例如 2026-03-01 至 2026-03-31。</p>
          )}
          {profile.canEdit && (
            <Button type="primary" loading={busy} onClick={() => void save()}>
              保存用途与时相
            </Button>
          )}
          {saved && <span role="status">已保存</span>}
        </Space>
      )}
    </section>
  );
}
