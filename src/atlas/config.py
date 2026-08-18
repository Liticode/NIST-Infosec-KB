from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    root: Path
    cache_dir: Path
    review_path: Path
    manifest_path: Path
    eval_path: Path
    index_name: str
    xai_model: str
    pinecone_api_key: str
    xai_api_key: str
    nvd_api_key: str
    rerank: bool
    max_live_queries: int

    @property
    def pinecone_ready(self) -> bool:
        return bool(self.pinecone_api_key)

    @property
    def xai_ready(self) -> bool:
        return bool(self.xai_api_key)


def settings() -> Settings:
    load_env()
    cache = Path(os.environ.get("ATLAS_CACHE_DIR", ROOT / "data" / "cache"))
    if not cache.is_absolute():
        cache = ROOT / cache
    review = Path(os.environ.get("ATLAS_REVIEW_PATH", ROOT / "review" / "queue.jsonl"))
    if not review.is_absolute():
        review = ROOT / review
    return Settings(
        root=ROOT,
        cache_dir=cache,
        review_path=review,
        manifest_path=ROOT / "data" / "manifest.json",
        eval_path=ROOT / "eval" / "questions.json",
        index_name=os.environ.get("ATLAS_INDEX_NAME", "public-control-atlas"),
        xai_model=os.environ.get("ATLAS_XAI_MODEL", "grok-4.6"),
        pinecone_api_key=os.environ.get("PINECONE_API_KEY", "").strip(),
        xai_api_key=os.environ.get("XAI_API_KEY", "").strip(),
        nvd_api_key=os.environ.get("NVD_API_KEY", "").strip(),
        rerank=os.environ.get("ATLAS_RERANK", "0") in {"1", "true", "True"},
        max_live_queries=int(os.environ.get("ATLAS_MAX_LIVE_QUERIES", "50")),
    )
