from __future__ import annotations

import re
from collections import Counter

from atlas.config import Settings
from atlas.index import PineconeStore
from atlas.models import Hit, Record

_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{1,}", re.I)

DEFAULT_NAMESPACES = (
    "csf-2",
    "sp800-53-r5",
    "sp800-53a",
    "sp800-53b",
    "ai-rmf",
    "cisa-kev",
    "bod-22-01",
)


class MemoryStore:
    """Deterministic lexical retriever for tests and offline dry runs."""

    def __init__(self, records: list[Record] | None = None):
        self.records = list(records or [])

    def upsert(self, records: list[Record]) -> int:
        by_id = {r.id: r for r in self.records}
        for record in records:
            by_id[record.id] = record
        self.records = list(by_id.values())
        return len(records)

    def search(
        self,
        query: str,
        namespace: str,
        top_k: int = 8,
        filter: dict | None = None,
        rerank: bool = False,
    ) -> list[dict]:
        del rerank
        q = Counter(_TOKEN.findall(query.lower()))
        scored: list[tuple[float, Record]] = []
        for record in self.records:
            if record.namespace != namespace:
                continue
            if filter and not _match_filter(record, filter):
                continue
            tokens = Counter(_TOKEN.findall(f"{record.control_id} {record.title} {record.text}".lower()))
            overlap = sum((q & tokens).values())
            if record.control_id.lower() in query.lower():
                overlap += 8
            if overlap <= 0:
                continue
            scored.append((float(overlap), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = []
        for score, record in scored[:top_k]:
            hits.append({"id": record.id, "score": score, "fields": record.pinecone_record()})
        return hits


def _match_filter(record: Record, filter: dict) -> bool:
    fields = record.pinecone_record()
    for key, cond in filter.items():
        value = fields.get(key)
        if isinstance(cond, dict):
            if "$eq" in cond and value != cond["$eq"]:
                return False
            if "$in" in cond and value not in cond["$in"]:
                return False
        elif value != cond:
            return False
    return True


def record_from_fields(fields: dict, fallback_id: str) -> Record:
    related = fields.get("related_ids") or []
    if isinstance(related, str):
        related = [related]
    return Record(
        id=str(fields.get("_id") or fallback_id),
        framework=str(fields.get("framework") or ""),
        control_id=str(fields.get("control_id") or ""),
        title=str(fields.get("title") or ""),
        text=str(fields.get("content") or fields.get("text") or ""),
        family=str(fields.get("family") or ""),
        version=str(fields.get("version") or ""),
        source_url=str(fields.get("source_url") or ""),
        namespace=str(fields.get("namespace") or ""),
        kind=str(fields.get("kind") or ""),
        related_ids=[str(x) for x in related],
        in_low=bool(fields.get("in_low")),
        in_moderate=bool(fields.get("in_moderate")),
        in_high=bool(fields.get("in_high")),
        in_privacy=bool(fields.get("in_privacy")),
    )


class Retriever:
    def __init__(self, store: MemoryStore | PineconeStore, settings: Settings):
        self.store = store
        self.settings = settings

    def search(
        self,
        query: str,
        namespaces: list[str] | None = None,
        top_k: int = 5,
        kind: str | None = None,
    ) -> list[Hit]:
        namespaces = namespaces or list(DEFAULT_NAMESPACES)
        filt = {"kind": {"$eq": kind}} if kind else None
        hits: list[Hit] = []
        for namespace in namespaces:
            raw = self.store.search(
                query=query,
                namespace=namespace,
                top_k=top_k,
                filter=filt,
                rerank=self.settings.rerank,
            )
            for item in raw:
                fields = item.get("fields") or {}
                fields.setdefault("namespace", namespace)
                rec = record_from_fields(fields, str(item.get("id")))
                if not rec.namespace:
                    rec.namespace = namespace
                hits.append(Hit(id=rec.id, score=float(item.get("score") or 0), record=rec))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[: max(top_k, 8)]
