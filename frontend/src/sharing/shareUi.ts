import { useEnglishLanguage, localText } from "../i18n/useEnglishLanguage";

export const invitationsChanged = "stisp:share-invitations-changed";
export function notifyInvitationsChanged() {
  window.dispatchEvent(new Event(invitationsChanged));
}

export function useShareText() {
  const english = useEnglishLanguage();
  return (zh: string, en: string) => localText(english, zh, en);
}

export function safeSharePath(value: string): string | null {
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin) return null;
  if (!["/map", "/compute"].includes(url.pathname)) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}
