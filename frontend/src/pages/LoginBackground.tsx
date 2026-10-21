import { useEffect, useState } from "react";
import digitalCity from "../assets/spatiotemporal/digital-city.png";
import digitalEarth from "../assets/spatiotemporal/digital-earth.png";
import dataLayers from "../assets/spatiotemporal/data-layers.png";

const backgrounds = [digitalCity, digitalEarth, dataLayers];
const rotationIntervalMs = 9000;
const transitionDurationMs = 1600;

export default function LoginBackground() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [outgoingIndex, setOutgoingIndex] = useState<number | null>(null);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const animated = visible && !reducedMotion;

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(preference.matches);
    const updateVisibility = () => setVisible(!document.hidden);
    preference.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => {
      preference.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);

  useEffect(() => {
    if (!animated) return;
    const timer = window.setTimeout(() => {
      setOutgoingIndex(activeIndex);
      setActiveIndex((activeIndex + 1) % backgrounds.length);
    }, rotationIntervalMs);
    return () => window.clearTimeout(timer);
  }, [activeIndex, animated]);

  useEffect(() => {
    if (outgoingIndex === null) return;
    const timer = window.setTimeout(
      () => setOutgoingIndex(null),
      transitionDurationMs,
    );
    return () => window.clearTimeout(timer);
  }, [outgoingIndex]);

  return (
    <div
      className="login-background-carousel"
      aria-hidden="true"
      data-animated={animated}
    >
      {backgrounds.map((background, index) => (
        <div
          className={[
            "login-background-slide",
            index === activeIndex ? "is-active" : "",
            index === outgoingIndex ? "is-outgoing" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          key={background}
          style={{ backgroundImage: `url("${background}")` }}
        />
      ))}
    </div>
  );
}
