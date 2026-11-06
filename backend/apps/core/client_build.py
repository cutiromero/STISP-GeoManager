"""Detect stale browser bundles at workflow mutation boundaries."""

from html.parser import HTMLParser
from urllib.parse import urlsplit

from django.conf import settings


class EntryParser(HTMLParser):
    entry = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("type") == "module" and values.get("src"):
            self.entry = urlsplit(values["src"]).path


def current_entry():
    for path in (
        settings.FRONTEND_DIST / "index.html",
        settings.STATIC_ROOT / "index.html",
    ):
        if path.is_file():
            parser = EntryParser()
            parser.feed(path.read_text(encoding="utf-8"))
            return parser.entry
    return None


def current_browser(request):
    # API clients keep their documented defaults. Browser release compatibility
    # is a UX guard, never an authentication or authorization boundary.
    if settings.DEBUG or not request.headers.get("Sec-Fetch-Mode"):
        return True
    entry = current_entry()
    return entry is None or request.headers.get("X-App-Entry") == entry
