from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

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

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def assert_allowed_url(url: str) -> None:
    if url.startswith("local:"):
        return
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError(f"refusing non-http URL: {url}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"URL host not on allowlist: {host}")


def cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    suffix = Path(urlparse(url).path).name or "download"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", suffix)[:80]
    return cache_dir / f"{digest}-{safe}"


def resolve_local(settings: Settings, spec: str) -> Path:
    rel = spec.removeprefix("local:")
    path = Path(rel)
    if not path.is_absolute():
        path = settings.root / path
    return path


def load_source(settings: Settings, url: str, timeout: float = 60.0) -> bytes:
    if url.startswith("local:"):
        return resolve_local(settings, url).read_bytes()
    path = Path(url)
    if path.exists():
        return path.read_bytes()
    assert_allowed_url(url)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_path(settings.cache_dir, url)
    if dest.exists():
        return dest.read_bytes()
    headers = {"User-Agent": "public-control-atlas/0.1 (portfolio demo; +https://github.com)"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
        return response.content


def load_json(settings: Settings, url: str) -> dict | list:
    raw = load_source(settings, url)
    return json.loads(raw)


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub(" ", text).strip()
