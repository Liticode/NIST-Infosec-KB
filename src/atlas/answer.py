from __future__ import annotations

import json
import re
import time
from collections.abc import Callable

import httpx

from atlas.config import Settings
from atlas.models import Answer, Hit

SYSTEM = """You answer only from the retrieved public catalog passages.
Return JSON with keys: answer (string), citations (array of retrieved record ids), confidence (0-1 number), refusal (boolean), reason (string).
If the passages do not contain enough evidence, set refusal true and do not invent controls, baselines, or CVEs.
Every citation must be one of the provided record ids. Quote control IDs that appear in the passages.
This is not legal, audit, or compliance advice.
"""


def _passages(hits: list[Hit]) -> str:
    blocks = []
    for hit in hits:
        rec = hit.record
        blocks.append(
            f"ID: {rec.id}\ncontrol_id: {rec.control_id}\nkind: {rec.kind}\n"
            f"baseline_moderate: {rec.in_moderate}\nsource: {rec.source_url}\n{rec.text[:1800]}"
        )
    return "\n\n---\n\n".join(blocks)


def parse_model_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    return json.loads(text)


def validate_answer(payload: dict, hits: list[Hit]) -> tuple[str, list[str], float, bool, str]:
    allowed = {hit.record.id for hit in hits} | {hit.record.control_id for hit in hits}
    allowed_l = {a.lower() for a in allowed}
    citations = [str(c) for c in payload.get("citations") or []]
    valid = []
    for cite in citations:
        if cite in allowed or cite.lower() in allowed_l:
            valid.append(cite)
    refused = bool(payload.get("refusal"))
    text = str(payload.get("answer") or "").strip()
    confidence = float(payload.get("confidence") or 0)
    reason = str(payload.get("reason") or "")
    if not hits:
        return "", [], 0.0, True, "no retrieved passages"
    if not refused and not valid:
        return "", [], 0.0, True, "answer lacked citations that exist in retrieved context"
    if not refused and not text:
        return "", valid, 0.0, True, "empty answer"
    return text, valid, confidence, refused, reason


def grok_complete(settings: Settings, prompt: str) -> tuple[str, int, int, int]:
    started = time.perf_counter()
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.xai_model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
    elapsed = int((time.perf_counter() - started) * 1000)
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage") or {}
    return (
        content,
        elapsed,
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
    )


def extractive_fallback(hits: list[Hit]) -> dict:
    if not hits:
        return {
            "answer": "",
            "citations": [],
            "confidence": 0.0,
            "refusal": True,
            "reason": "no retrieved passages",
        }
    top = hits[0].record
    return {
        "answer": f"{top.control_id}: {top.text[:600]}",
        "citations": [top.id],
        "confidence": 0.35,
        "refusal": False,
        "reason": "extractive fallback (no XAI_API_KEY)",
    }


def answer_question(
    settings: Settings,
    question: str,
    hits: list[Hit],
    completer: Callable[[Settings, str], tuple[str, int, int, int]] | None = None,
) -> Answer:
    if not hits:
        return Answer(
            question=question,
            text="",
            citations=[],
            confidence=0.0,
            refused=True,
            reason="no retrieved passages",
            model="none",
            latency_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            retrieved_ids=[],
        )
    prompt = (
        f"Question: {question}\n\nRetrieved passages:\n{_passages(hits)}\n\n"
        "Respond with JSON only."
    )
    model = "extractive"
    raw = ""
    latency = 0
    p_tok = 0
    c_tok = 0
    if completer is not None:
        raw, latency, p_tok, c_tok = completer(settings, prompt)
        model = "custom"
        payload = parse_model_json(raw)
    elif settings.xai_ready:
        raw, latency, p_tok, c_tok = grok_complete(settings, prompt)
        model = settings.xai_model
        payload = parse_model_json(raw)
    else:
        payload = extractive_fallback(hits)
    text, citations, confidence, refused, reason = validate_answer(payload, hits)
    return Answer(
        question=question,
        text=text,
        citations=citations,
        confidence=confidence,
        refused=refused,
        reason=reason,
        model=model,
        latency_ms=latency,
        prompt_tokens=p_tok,
        completion_tokens=c_tok,
        retrieved_ids=[h.record.id for h in hits],
    )
