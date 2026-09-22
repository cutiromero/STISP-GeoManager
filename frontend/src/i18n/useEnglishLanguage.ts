import { useTranslation } from "react-i18next";

/** Reactive language helper for screens that still keep their two labels inline. */
export function useEnglishLanguage() {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage?.toLowerCase().startsWith("en") ?? false;
}

export function localText(
  english: boolean,
  chinese: string,
  englishText: string,
) {
  return english ? englishText : chinese;
}
