export function moduleEntry(document: Document): string {
  const src = document
    .querySelector<HTMLScriptElement>('script[type="module"][src]')
    ?.getAttribute("src");
  return src ? new URL(src, window.location.origin).pathname : "";
}
