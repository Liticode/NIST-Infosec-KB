import json
from dataclasses import replace
from pathlib import Path

from atlas.answer import answer_question, validate_answer
from atlas.evaluate import run_eval
from atlas.config import settings
from atlas.ingest import parse_cpg_html, parse_cprt_80066, parse_kev
from atlas.models import Hit, Record
from atlas.oscal import parse_oscal_catalog
from atlas.retrieve import MemoryStore, Retriever
from atlas.review import should_review

FIXTURES = Path(__file__).parent / "fixtures"


def _records() -> list[Record]:
    catalog = json.loads((FIXTURES / "tiny_catalog.json").read_text())
    csf = json.loads((FIXTURES / "tiny_csf.json").read_text())
    kev = json.loads((FIXTURES / "tiny_kev.json").read_text())
    recs = parse_oscal_catalog(
        catalog,
        {
            "namespace": "sp800-53-r5",
            "framework": "sp800-53",
            "version": "5.2.0",
            "source_url": "https://csrc.nist.gov/example",
            "also_emit_assessment_namespace": "sp800-53a",
            "kind": "statement",
        },
    )
    recs.extend(
        parse_oscal_catalog(
            csf,
            {
                "namespace": "csf-2",
                "framework": "nist-csf",
                "version": "2.0",
                "source_url": "https://www.nist.gov/cyberframework",
                "kind": "outcome",
            },
        )
    )
    recs.extend(
        parse_kev(
            kev,
            {
                "namespace": "cisa-kev",
                "framework": "cisa-kev",
                "version": "test",
                "source_url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
            },
        )
    )
    return recs


def test_memory_retriever_finds_ac2_and_csf():
    cfg = settings()
    retriever = Retriever(MemoryStore(_records()), cfg)
    ac_hits = retriever.search("How would an auditor assess AC-2 account management?")
    assert any(hit.record.control_id.startswith("AC-2") for hit in ac_hits)
    csf_hits = retriever.search("organizational mission informs cybersecurity risk management")
    assert any(hit.record.control_id == "GV.OC-01" for hit in csf_hits)
    kev_hits = retriever.search("CVE-2024-0001 Example Widget")
    assert any(hit.record.control_id == "CVE-2024-0001" for hit in kev_hits)


def test_cpg_and_80066_parsers():
    cpg = parse_cpg_html(
        (FIXTURES / "tiny_cpg.html").read_text(),
        {
            "namespace": "cisa-cpg",
            "framework": "cisa-cpg",
            "version": "2.0",
            "source_url": "https://www.cisa.gov/cybersecurity-performance-goals-2-0-cpg-2-0",
            "kind": "outcome",
        },
    )
    ids = {r.control_id: r for r in cpg}
    assert "1.A" in ids
    assert "responsibilities" in ids["1.A"].text.lower()
    assert "1" in ids and ids["1"].kind == "function"

    hipaa = parse_cprt_80066(
        json.loads((FIXTURES / "tiny_cprt_66.json").read_text()),
        {
            "namespace": "sp800-66r2",
            "framework": "sp800-66",
            "version": "2.0.0",
            "source_url": "https://csrc.nist.gov/pubs/sp/800/66/r2/final",
        },
    )
    kinds = {r.kind for r in hipaa}
    assert "footnote" not in kinds
    activity = next(r for r in hipaa if r.kind == "activity")
    assert "generated, stored, and transmitted" in activity.text
    assert any(r.control_id.startswith("164.308") and r.kind == "implementation" for r in hipaa)


def test_missing_citation_is_refused():
    rec = Record(
        id="sp800-53-r5:ac-2:statement",
        framework="sp800-53",
        control_id="AC-2",
        title="Account Management",
        text="Define account types.",
        family="ac",
        version="5.2.0",
        source_url="https://example.invalid",
        namespace="sp800-53-r5",
        kind="statement",
    )
    hits = [Hit(id=rec.id, score=1.0, record=rec)]
    text, citations, _conf, refused, reason = validate_answer(
        {"answer": "Invented control ZZ-9", "citations": ["not-a-real-id"], "confidence": 0.9, "refusal": False},
        hits,
    )
    assert refused is True
    assert citations == []
    assert "citations" in reason
    assert text == ""


def test_extractive_answer_cites_retrieved_id():
    cfg = replace(settings(), xai_api_key="")
    retriever = Retriever(MemoryStore(_records()), cfg)
    hits = retriever.search("AC-2 account management")
    answer = answer_question(cfg, "What is AC-2?", hits)
    assert answer.refused is False
    assert answer.citations
    assert answer.citations[0] in {h.record.id for h in hits}


def test_no_hits_refused_and_queued():
    cfg = settings()
    answer = answer_question(cfg, "What is ISO 27001 A.5.23?", [])
    assert answer.refused is True
    assert should_review(answer) is True


def test_extractive_refuses_unrelated_hit():
    rec = Record(
        id="sp800-53-r5:ac-2:statement",
        framework="sp800-53",
        control_id="AC-2",
        title="Account Management",
        text="Define and document the types of accounts allowed.",
        family="ac",
        version="5.2.0",
        source_url="https://example.invalid",
        namespace="sp800-53-r5",
        kind="statement",
    )
    hits = [Hit(id=rec.id, score=0.4, record=rec)]
    cfg = replace(settings(), xai_api_key="")
    iso = answer_question(cfg, "Quote the exact ISO 27001:2022 Annex A control text for A.5.23.", hits)
    assert iso.refused is True
    phi = answer_question(cfg, "What ePHI did patient 123456 have at Example Community Hospital last Tuesday?", hits)
    assert phi.refused is True
    ok = answer_question(cfg, "What does NIST SP 800-53 AC-2 require for account management?", hits)
    assert ok.refused is False
    assert "AC-2" in ok.text


def test_invented_control_in_cited_answer_is_refused():
    rec = Record(
        id="sp800-53-r5:ac-2:statement",
        framework="sp800-53",
        control_id="AC-2",
        title="Account Management",
        text="Define account types.",
        family="ac",
        version="5.2.0",
        source_url="https://example.invalid",
        namespace="sp800-53-r5",
        kind="statement",
    )
    hits = [Hit(id=rec.id, score=1.0, record=rec)]
    _text, _cites, _conf, refused, reason = validate_answer(
        {
            "answer": "AC-2 requires ZZ-9 widget rotation and quantum passwords.",
            "citations": ["sp800-53-r5:ac-2:statement"],
            "confidence": 0.9,
            "refusal": False,
        },
        hits,
        question="What does AC-2 require?",
    )
    assert refused is True
    assert "not supported" in reason or "identifiers" in reason


def test_eval_fails_when_must_refuse_is_missed():
    cfg = replace(settings(), xai_api_key="")
    recs = _records()
    retriever = Retriever(MemoryStore(recs), cfg)
    questions = [
        {
            "id": "ac2-search",
            "question": "What does NIST SP 800-53 AC-2 require for account management?",
            "expected_controls": ["AC-2"],
            "must_refuse": False,
        },
        {
            "id": "unsupported-iso",
            "question": "Quote the exact ISO 27001:2022 Annex A control text for A.5.23.",
            "expected_controls": [],
            "must_refuse": True,
        },
    ]
    summary, code = run_eval(questions, retriever, cfg, min_hit_rate=0.8, min_refuse_rate=1.0)
    assert summary["refuse_rate"] == 1.0
    assert code == 0
    iso_row = next(r for r in summary["rows"] if r["id"] == "unsupported-iso")
    assert iso_row["refused"] is True
    missed, missed_code = run_eval(
        [
            {
                "id": "mislabeled-refuse",
                "question": "What does NIST SP 800-53 AC-2 require for account management?",
                "expected_controls": ["AC-2"],
                "must_refuse": True,
            }
        ],
        retriever,
        cfg,
        min_hit_rate=0.0,
        min_refuse_rate=1.0,
    )
    assert missed["refuse_rate"] == 0.0
    assert missed_code == 1
    live, live_code = run_eval(
        [
            {
                "id": "unsupported-iso",
                "question": "Quote the exact ISO 27001:2022 Annex A control text for A.5.23.",
                "expected_controls": [],
                "must_refuse": True,
            }
        ],
        retriever,
        settings(),  # may include XAI_API_KEY in the environment
        min_hit_rate=0.0,
        min_refuse_rate=1.0,
        use_llm=True,
    )
    assert live_code == 0
    assert live["rows"][0]["refused"] is True
    assert live["rows"][0]["model"] in {"none", "extractive"}
