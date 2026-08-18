from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from atlas.config import Settings
from atlas.models import Answer


def should_review(answer: Answer) -> bool:
    return answer.refused or answer.confidence < 0.45 or not answer.citations


def append_review(settings: Settings, answer: Answer) -> None:
    settings.review_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(answer.question.encode()).hexdigest()[:12]
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "question_sha256_12": digest,
        "refused": answer.refused,
        "reason": answer.reason,
        "confidence": answer.confidence,
        "citations": answer.citations,
        "retrieved_ids": answer.retrieved_ids,
        "model": answer.model,
        "latency_ms": answer.latency_ms,
        "prompt_tokens": answer.prompt_tokens,
        "completion_tokens": answer.completion_tokens,
    }
    with settings.review_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
