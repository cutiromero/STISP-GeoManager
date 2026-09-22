import tiandituMapWorldLogo from "../assets/tianditu-map-world.svg";
import type { BasemapProvider } from "../map/basemapCatalog";
import { useTranslation } from "react-i18next";

interface Props {
  provider: BasemapProvider;
}

export default function TiandituAttributionBadge({ provider }: Props) {
  const { t } = useTranslation();
  if (provider !== "tianditu") return null;

  return (
    <aside
      className="tianditu-attribution-badge"
      aria-label={t("map.tiandituAttribution")}
    >
      <a
        href="https://www.tianditu.gov.cn/"
        target="_blank"
        rel="noopener noreferrer"
        aria-label={t("map.visitTianditu")}
      >
        <img
          src={tiandituMapWorldLogo}
          alt={t("map.tiandituLogoAlt")}
          width={112}
          height={60}
          draggable={false}
        />
        <span>{t("map.tiandituService")}</span>
      </a>
    </aside>
  );
}
