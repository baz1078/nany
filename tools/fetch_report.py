"""Fetch a hosted Inspectagram report page and return its visible text.

Self-contained (stdlib only) — deliberately not imported from the Lot7
backend (inspection-ai-backend/utils.py) so Nany has no cross-repo
dependency. If the upstream scraper changes, port fixes over manually.
"""

import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse


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
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError("Link must start with http:// or https://")

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NannyBot/1.0)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or 'utf-8'
        html = resp.read().decode(charset, errors='replace')

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
    return text.strip()
