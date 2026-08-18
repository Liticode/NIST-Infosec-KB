from __future__ import annotations

import time
from collections.abc import Iterable

from atlas.config import Settings
from atlas.models import Record

BATCH = 90


class PineconeStore:
    def __init__(self, settings: Settings):
        from pinecone import Pinecone

        if not settings.pinecone_ready:
            raise RuntimeError("PINECONE_API_KEY is not set")
        self.settings = settings
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self._ensure_index()
        self.index = self.pc.Index(settings.index_name)

    def _ensure_index(self) -> None:
        if self.pc.has_index(self.settings.index_name):
            return
        self.pc.create_index_for_model(
            name=self.settings.index_name,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": "llama-text-embed-v2",
                "field_map": {"text": "content"},
            },
        )

    def upsert(self, records: Iterable[Record]) -> int:
        grouped: dict[str, list[Record]] = {}
        for record in records:
            grouped.setdefault(record.namespace, []).append(record)
        count = 0
        for namespace, items in grouped.items():
            for start in range(0, len(items), BATCH):
                batch = [item.pinecone_record() for item in items[start : start + BATCH]]
                self.index.upsert_records(namespace, batch)
                count += len(batch)
                time.sleep(0.15)
        return count

    def search(
        self,
        query: str,
        namespace: str,
        top_k: int = 8,
        filter: dict | None = None,
        rerank: bool = False,
    ) -> list[dict]:
        body: dict = {
            "top_k": top_k,
            "inputs": {"text": query},
        }
        if filter:
            body["filter"] = filter
        kwargs: dict = {"namespace": namespace, "query": body}
        if rerank:
            kwargs["rerank"] = {
                "model": "bge-reranker-v2-m3",
                "top_n": min(5, top_k),
                "rank_fields": ["content"],
            }
        result = self.index.search(**kwargs)
        hits = result.get("result", {}).get("hits") or result.get("matches") or []
        out = []
        for hit in hits:
            fields = getattr(hit, "fields", None) or hit.get("fields") or hit.get("metadata") or {}
            score = getattr(hit, "score", None)
            if score is None:
                score = hit.get("score") or hit.get("_score") or 0.0
            hid = getattr(hit, "_id", None) or hit.get("_id") or hit.get("id") or fields.get("control_id")
            out.append({"id": hid, "score": float(score or 0), "fields": fields})
        return out
