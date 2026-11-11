const stars = Array.from({ length: 150 }, (_, id) => ({
  id: `star-${id}`,
  x: (id * 137.508 + 43) % 1000,
  y: (id * 73.371 + 29) % 800,
  radius: id % 13 === 0 ? 1.5 : 0.55,
  opacity: 0.18 + (id % 7) * 0.1,
}));

export default function MonitorOrbitScene({ center }: { center: number[] }) {
  return (
    <div className="monitor-orbital-scene" aria-hidden="true">
      <svg
        className="monitor-starfield"
        viewBox="0 0 1000 800"
        preserveAspectRatio="none"
      >
        {stars.map((star) => (
          <circle
            key={star.id}
            cx={star.x}
            cy={star.y}
            r={star.radius}
            opacity={star.opacity}
          />
        ))}
      </svg>
      <div className="monitor-planet-aura" />
      <div className="monitor-orbit monitor-orbit-equator">
        <i />
        <b />
      </div>
      <div className="monitor-orbit monitor-orbit-polar">
        <i />
        <b />
      </div>
      <div className="monitor-orbit-reticle" />
      <div className="monitor-orbit-platform" />
      <span className="monitor-coordinate monitor-coordinate-north">
        {Math.abs(center[1] ?? 0).toFixed(2)}°{" "}
        {(center[1] ?? 0) < 0 ? "S" : "N"} /{" "}
        {Math.abs(center[0] ?? 0).toFixed(2)}°{" "}
        {(center[0] ?? 0) < 0 ? "W" : "E"}
      </span>
      <span className="monitor-coordinate monitor-coordinate-south">
        EARTH OBSERVATION · LIVE MONITORING
      </span>
    </div>
  );
}
