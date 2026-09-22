import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { enUS, zhCN } from "./resources";

export const supportedLocales = ["zh-CN", "en-US"] as const;
export type AppLocale = (typeof supportedLocales)[number];

export const defaultLocale: AppLocale = "zh-CN";
export const localeStorageKey = "geomanager.locale";

export function normalizeLocale(value?: string | null): AppLocale {
  return value?.toLowerCase().startsWith("en") ? "en-US" : "zh-CN";
}

function storedLocale(): AppLocale {
  if (typeof window === "undefined") return defaultLocale;
  try {
    return normalizeLocale(window.localStorage.getItem(localeStorageKey));
  } catch {
    return defaultLocale;
  }
}

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources: {
      "zh-CN": zhCN,
      "en-US": enUS,
    },
    lng: storedLocale(),
    fallbackLng: defaultLocale,
    supportedLngs: supportedLocales,
    interpolation: { escapeValue: false },
    returnNull: false,
  });
}

export function currentLocale(): AppLocale {
  return normalizeLocale(i18n.resolvedLanguage ?? i18n.language);
}

export async function setLocale(locale: AppLocale) {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(localeStorageKey, locale);
    } catch {
      // Private browsing or a storage policy can block persistence.
    }
  }
  await i18n.changeLanguage(locale);
}

export default i18n;
