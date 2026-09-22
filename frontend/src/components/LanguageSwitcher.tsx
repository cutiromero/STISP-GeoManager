import { GlobalOutlined } from "@ant-design/icons";
import { Button, Dropdown } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { currentLocale, setLocale, type AppLocale } from "../i18n";

interface LanguageSwitcherProps {
  compact?: boolean;
  className?: string;
}

export default function LanguageSwitcher({
  compact = false,
  className,
}: LanguageSwitcherProps) {
  const { t, i18n } = useTranslation();
  const locale = currentLocale();
  const items: MenuProps["items"] = [
    {
      key: "zh-CN",
      label: t("language.chinese"),
      disabled: locale === "zh-CN",
    },
    {
      key: "en-US",
      label: t("language.english"),
      disabled: locale === "en-US",
    },
  ];

  async function changeLanguage({ key }: { key: string }) {
    await setLocale(key as AppLocale);
  }

  return (
    <Dropdown
      menu={{ items, onClick: changeLanguage }}
      placement="bottomRight"
      trigger={["click"]}
    >
      <Button
        className={className}
        type="text"
        icon={<GlobalOutlined />}
        aria-label={t("language.switchTo")}
        title={t("language.switchTo")}
      >
        {compact ? null : i18n.resolvedLanguage?.startsWith("en") ? "EN" : "中"}
      </Button>
    </Dropdown>
  );
}
