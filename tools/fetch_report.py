"""Fetch a hosted Inspectagram report page and return its visible text.

Self-contained (stdlib only) — deliberately not imported from the Lot7
backend (inspection-ai-backend/utils.py) so Nany has no cross-repo
dependency. If the upstream scraper changes, port fixes over manually.
"""

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse


class BadLink(ValueError):
    """The link isn't a readable report. The message is written for the person who pasted it."""


SHARE_HINT = "In Inspectagram, publish your report, tap Share, copy the link, and paste it here."


def check_link(url):
    """Reject links that can never be a report before any work is done. Raises BadLink."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.netloc:
        raise BadLink("That doesn't look like a link. " + SHARE_HINT)
    if "inspectagram" not in p.netloc.lower():
        raise BadLink("That doesn't look like an Inspectagram report link. " + SHARE_HINT)
    if re.match(r"^/reports/[0-9]+", p.path):
        raise BadLink("That looks like your editor link, which Nani can't open. " + SHARE_HINT)


def fetch_report_text(url, timeout=20, include_anchors=True):
    """Return the visible text of a hosted inspection report page.

    include_anchors=True emits each element's `id` (or the more precise
    `data-page-anchor` when present) inline as "[ANCHOR:<id>]" so findings
    can be tagged with a deep link back to {url}#{id}. Inspectagram uses
    #page-XX anchors on page containers and #cell_<hash> anchors on
    individual findings (confirmed against real report exports).

    Icon alt text (severity icons, legend icons) is emitted inline as
    "[alt text]" since severity is conveyed visually, not in body text.
    """
    check_link(url)
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError("Link must start with http:// or https://")

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NannyBot/1.0)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            html = resp.read().decode(charset, errors='replace')
            if 'sign_in' in resp.geturl():  # redirected to the login page: an editor link in disguise
                raise BadLink("That link needs an Inspectagram login, which Nani can't use. " + SHARE_HINT)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise BadLink("That link needs an Inspectagram login, which Nani can't use. " + SHARE_HINT)
        if exc.code == 404:
            raise BadLink("Nani couldn't find that report. Check the link. " + SHARE_HINT)
        raise

    class _Extractor(HTMLParser):
        _SKIP = {'script', 'style', 'head', 'noscript', 'svg'}
        _BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5',
                  'h6', 'section', 'article', 'td', 'th', 'header', 'footer'}

        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip_depth = 0

        def handle_starttag(self, tag, attrs):
            attrs_d = dict(attrs)
            if tag in self._SKIP:
                self._skip_depth += 1
            elif tag == 'img' and self._skip_depth == 0:
                # Inspectagram serves the inspector's own photos from /data/
                # and its stock library graphics (legend icons, chapter
                # pages, "example" pictures) from /global/ - the only way to
                # tell a real photo from a stock placeholder in the scrape.
                src = attrs_d.get('src') or ''
                if '/global/' in src:
                    self.parts.append(' [STOCK-IMAGE] ')
                elif '/data/' in src:
                    self.parts.append(' [PHOTO] ')
                alt = attrs_d.get('alt')
                if alt and alt.strip():
                    self.parts.append(' [' + alt.strip() + '] ')
            elif tag in self._BLOCK:
                self.parts.append('\n')

            if include_anchors and self._skip_depth == 0:
                anchor_id = attrs_d.get('data-page-anchor') or attrs_d.get('id')
                if anchor_id and anchor_id.strip():
                    self.parts.append(' [ANCHOR:' + anchor_id.strip() + '] ')

        def handle_endtag(self, tag):
            if tag in self._SKIP and self._skip_depth > 0:
                self._skip_depth -= 1
            elif tag in self._BLOCK:
                self.parts.append('\n')

        def handle_data(self, data):
            if self._skip_depth == 0:
                t = data.strip()
                if t:
                    self.parts.append(t + ' ')

    p = _Extractor()
    p.feed(html)
    text = ''.join(p.parts)
    text = re.sub(r'\n[ \t]*(\n[ \t]*)+', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = text.strip()
    if len(text) < 1000:  # real reports run to tens of thousands of characters
        raise BadLink("Nani couldn't find a report on that page. " + SHARE_HINT)
    return text
