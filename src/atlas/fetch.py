from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from atlas.config import Settings

ALLOWED_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "www.cisa.gov",
    "cisa.gov",
    "nvd.nist.gov",
    "services.nvd.nist.gov",
    "csrc.nist.gov",
    "www.nist.gov",
    "nvlpubs.nist.gov",
    "doi.org",
}

MAX_REDIRECTS = 8
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def assert_allowed_url(url: str) -> None:
    if url.startswith("local:"):
        return
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refusing non-https URL: {url}")
    host = (parsed.hostname or "").lower()
    if not host or host not in ALLOWED_HOSTS:
        raise ValueError(f"URL host not on allowlist: {host}")


def resolve_redirect(current: str, location: str) -> str:
    if not (location or "").strip():
        raise ValueError("redirect with empty Location")
    nxt = urljoin(current, location.strip())
    assert_allowed_url(nxt)
    return nxt


def cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    suffix = Path(urlparse(url).path).name or "download"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", suffix)[:80]
    return cache_dir / f"{digest}-{safe}"


def resolve_local(settings: Settings, spec: str) -> Path:
    rel = spec.removeprefix("local:")
    candidate = Path(rel)
    if not rel or candidate.is_absolute() or rel.startswith(("/", "\\")):
        raise ValueError("local: path must be relative to the repository")
    root = settings.root.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"local: path escapes the repository: {rel}") from exc
    if not path.is_file():
        raise ValueError(f"local: not a file: {rel}")
    return path


def _http_get(url: str, timeout: float) -> bytes:
    assert_allowed_url(url)
    headers = {"User-Agent": "public-control-atlas/0.1 (+https://github.com/Liticode/NIST-Infosec-KB)"}
    current = url
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            for _ in range(MAX_REDIRECTS):
                assert_allowed_url(current)
                response = client.get(current)
                if response.is_redirect:
                    current = resolve_redirect(str(response.url), response.headers.get("location") or "")
                    continue
                response.raise_for_status()
                return response.content
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Network fetch failed for {url}. "
            "ingest (including --dry-run) needs HTTPS access to allowlisted hosts "
            "(raw.githubusercontent.com, csrc.nist.gov, www.cisa.gov, …). "
            "For an offline check with no network, run: pytest"
        ) from exc
    raise ValueError(f"too many redirects fetching {url}")


def load_source(settings: Settings, url: str, timeout: float = 60.0) -> bytes:
    if url.startswith("local:"):
        return resolve_local(settings, url).read_bytes()
    assert_allowed_url(url)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_path(settings.cache_dir, url)
    if dest.exists():
        return dest.read_bytes()
    body = _http_get(url, timeout)
    dest.write_bytes(body)
    return body


def load_json(settings: Settings, url: str) -> dict | list:
    raw = load_source(settings, url)
    return json.loads(raw)


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub(" ", text).strip()
