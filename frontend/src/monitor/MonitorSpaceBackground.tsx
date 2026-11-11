import { memo } from "react";

const stars = Array.from({ length: 320 }, (_, id) => ({
  id: `distant-star-${id}`,
  x: (id * 733.137 + 73) % 2000,
  y: (id * 347.731 + 31) % 1200,
  radius: id % 29 === 0 ? 1.65 : id % 7 === 0 ? 1.05 : 0.65,
  opacity: 0.3 + (id % 9) * 0.075,
  color: id % 17 === 0 ? "#ffe5c5" : id % 5 === 0 ? "#b6d8ff" : "#ecf2ff",
}));

export default memo(function MonitorSpaceBackground() {
  return (
    <div className="monitor-space-background" aria-hidden="true">
      <svg
        className="monitor-space-stars"
        viewBox="0 0 2000 1200"
        preserveAspectRatio="xMidYMid slice"
      >
        {stars.map((star) => (
          <circle
            key={star.id}
            cx={star.x}
            cy={star.y}
            r={star.radius}
            opacity={star.opacity}
            fill={star.color}
          />
        ))}
      </svg>
    </div>
  );
});
