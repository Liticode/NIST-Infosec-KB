from __future__ import annotations

from dataclasses import replace

from atlas.answer import answer_question
from atlas.config import Settings
from atlas.retrieve import Retriever


def run_eval(
    questions: list[dict],
    retriever: Retriever,
    cfg: Settings,
    min_hit_rate: float = 0.8,
    min_refuse_rate: float = 1.0,
    use_llm: bool = False,
) -> tuple[dict, int]:
    """Score the eval set.

    By default answers are extractive only (no remote LLM). `must_refuse` items never
    call an LLM even when use_llm=True, so refusal probes are not sent to a vendor.
    """
    rows = []
    hits_ok = 0
    answerable = 0
    refused_ok = 0
    must_refuse_n = 0
    extractive_cfg = replace(cfg, xai_api_key="")
    for item in questions:
        hits = retriever.search(item["question"], top_k=5)
        retrieved_ids = [h.record.id for h in hits]
        retrieved_controls = {h.record.control_id.lower() for h in hits}
        expected = [str(x).lower() for x in item.get("expected_controls") or []]
        in_top = False
        if expected:
            answerable += 1
            in_top = any(
                exp in retrieved_controls or any(exp in rid.lower() for rid in retrieved_ids) for exp in expected
            )
            hits_ok += int(in_top)
        # Refusal probes and default eval stay extractive so prompts never leave the machine.
        cfg_ans = extractive_cfg if (item.get("must_refuse") or not use_llm) else cfg
        answer = answer_question(cfg_ans, item["question"], hits)
        if item.get("must_refuse"):
            must_refuse_n += 1
            refused_ok += int(answer.refused)
        rows.append(
            {
                "id": item["id"],
                "in_top": in_top,
                "refused": answer.refused,
                "reason": answer.reason,
                "citations": answer.citations,
                "model": answer.model,
            }
        )
    hit_rate = (hits_ok / answerable) if answerable else 0.0
    refuse_rate = (refused_ok / must_refuse_n) if must_refuse_n else 1.0
    summary = {
        "retrieval_hit_rate": hit_rate,
        "answerable": answerable,
        "hits_ok": hits_ok,
        "must_refuse": must_refuse_n,
        "unsupported_refused": refused_ok,
        "refuse_rate": refuse_rate,
        "use_llm": use_llm,
        "rows": rows,
        "backend": type(retriever.store).__name__,
    }
    code = 0
    if answerable and hit_rate < min_hit_rate:
        code = 1
    if must_refuse_n and refuse_rate < min_refuse_rate:
        code = 1
    return summary, code
