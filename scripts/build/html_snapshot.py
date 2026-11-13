"""Snapshot a documentation website into one zip, politely, for a reproducible build.

The zip holds every page linked from the start page under the same base URL (HTML only,
no images or styles) at its path below the base, plus `manifest.json` with the URL,
SHA-256 and fetch date of each page. Builds read the zip, never the live site, so a rebuild
gives the same notes until someone takes a new snapshot on purpose.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

AGENT = "astro-kb-builder/1 (documentation snapshot; one request at a time)"
HREF = re.compile(r'href="([^"#]+)(?:#[^"]*)?"')


def page_path(url: str, base: str) -> str:
    """Path of a page inside the zip: 'Data_analysis/chap_cu4nss/index.html' etc."""
    rel = url[len(base):]
    return (rel + "index.html") if (rel == "" or rel.endswith("/")) else rel


def fetch(url: str, tries: int = 3) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError("unreachable")


def snapshot(start: str, out: Path, delay: float = 0.5) -> dict:
    """Crawl the pages linked from `start` (one level: the start page is the full table of
    contents) and from them, staying below `start`'s folder. Writes `out` (zip)."""
    base = start if start.endswith("/") else start.rsplit("/", 1)[0] + "/"
    todo, seen, pages = [start], set(), {}
    while todo:
        url = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        data = fetch(url)
        pages[page_path(url, base)] = (url, data)
        if len(pages) % 50 == 0:
            print(f"  {len(pages)} pages", file=sys.stderr)
        for href in HREF.findall(data.decode("utf-8", "replace")):
            nxt = urljoin(url, href)
            p = urlparse(nxt)
            if p.scheme in ("http", "https") and nxt.startswith(base) and nxt not in seen \
                    and (nxt.endswith("/") or nxt.endswith(".html")) and "?" not in nxt:
                todo.append(nxt)
        time.sleep(delay)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {"start": start, "base": base, "fetched": when, "agent": AGENT,
                "pages": {path: {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                          for path, (url, data) in sorted(pages.items())}}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for path, (_, data) in sorted(pages.items()):
            z.writestr(path, data)
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    tmp.rename(out)
    return manifest


def read(zpath: Path) -> tuple[dict, dict[str, bytes]]:
    """(manifest, {path: html bytes}) of a snapshot zip."""
    with zipfile.ZipFile(zpath) as z:
        manifest = json.loads(z.read("manifest.json"))
        return manifest, {p: z.read(p) for p in manifest["pages"]}


if __name__ == "__main__":
    m = snapshot(sys.argv[1], Path(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 0.5)
    print(f"{len(m['pages'])} pages -> {sys.argv[2]}")
