from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Record:
    id: str
    framework: str
    control_id: str
    title: str
    text: str
    family: str
    version: str
    source_url: str
    namespace: str
    kind: str
    related_ids: list[str] = field(default_factory=list)
    in_low: bool = False
    in_moderate: bool = False
    in_high: bool = False
    in_privacy: bool = False

    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // 4)

    def pinecone_record(self) -> dict:
        return {
            "_id": self.id,
            "content": self.text,
            "framework": self.framework,
            "control_id": self.control_id,
            "title": self.title,
            "family": self.family,
            "version": self.version,
            "source_url": self.source_url,
            "kind": self.kind,
            "related_ids": self.related_ids[:40],
            "in_low": self.in_low,
            "in_moderate": self.in_moderate,
            "in_high": self.in_high,
            "in_privacy": self.in_privacy,
        }

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Hit:
    id: str
    score: float
    record: Record


@dataclass(slots=True)
class Answer:
    question: str
    text: str
    citations: list[str]
    confidence: float
    refused: bool
    reason: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    retrieved_ids: list[str]
