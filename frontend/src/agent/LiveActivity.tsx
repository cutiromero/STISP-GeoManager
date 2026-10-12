import { CheckOutlined, PauseOutlined } from "@ant-design/icons";
import type { LiveActivity as Activity } from "./agentActivity";

export function ActivityMark({ state }: { state: Activity["state"] }) {
  return (
    <span className={`agent-activity-mark is-${state}`} aria-hidden="true">
      {state === "complete" ? (
        <CheckOutlined />
      ) : state === "waiting" ? (
        <PauseOutlined />
      ) : (
        <span />
      )}
    </span>
  );
}

export default function LiveActivity({
  activity,
  title,
  compact = false,
}: {
  activity: Activity;
  title?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={`agent-activity ${compact ? "is-compact " : ""}is-${activity.state}`}
      data-activity-state={activity.state}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <ActivityMark state={activity.state} />
      <div className="agent-activity-copy">
        {title && (
          <strong className="agent-activity-title" title={title}>
            {title}
          </strong>
        )}
        <span className="agent-activity-label">{activity.label}</span>
        {!compact && activity.detail && <p>{activity.detail}</p>}
      </div>
      {activity.state === "working" && (
        <span className="agent-activity-track" aria-hidden="true" />
      )}
    </div>
  );
}
