from __future__ import annotations

import argparse
import json
import sys

from atlas.answer import answer_question
from atlas.config import settings
from atlas.ingest import DEFAULT_WAVE, build_records
from atlas.review import append_review, should_review


def _store(cfg, records):
    if cfg.pinecone_ready:
        from atlas.index import PineconeStore

        return PineconeStore(cfg)
    print(
        "PINECONE_API_KEY not set in project .env; using in-memory MemoryStore",
        file=sys.stderr,
    )
    from atlas.retrieve import MemoryStore

    store = MemoryStore(records)
    return store


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = settings()
    print(
        "Note: ingest downloads allowlisted HTTPS catalogs (NIST/CISA). "
        "--dry-run skips Pinecone upsert only; it still needs network unless sources are already cached. "
        "Offline proof with no network: pytest",
        file=sys.stderr,
    )
    try:
        records, report = build_records(cfg, wave=args.wave)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2))
    if report.aborted:
        print(report.reason, file=sys.stderr)
        return 2
    if args.dry_run:
        return 0
    store = _store(cfg, records)
    count = store.upsert(records)
    print(json.dumps({"upserted": count, "backend": type(store).__name__}))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from atlas.retrieve import Retriever

    cfg = settings()
    records = []
    if not cfg.pinecone_ready:
        try:
            records, report = build_records(cfg, wave=DEFAULT_WAVE)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if report.aborted:
            print(report.reason, file=sys.stderr)
            return 2
    store = _store(cfg, records)
    retriever = Retriever(store, cfg)
    namespaces = args.namespace.split(",") if args.namespace else None
    hits = retriever.search(args.question, namespaces=namespaces, top_k=args.top_k, kind=args.kind)
    answer = answer_question(cfg, args.question, hits)
    if should_review(answer):
        append_review(cfg, answer)
    print(
        json.dumps(
            {
                "answer": answer.text,
                "citations": answer.citations,
                "confidence": answer.confidence,
                "refused": answer.refused,
                "reason": answer.reason,
                "model": answer.model,
                "latency_ms": answer.latency_ms,
                "prompt_tokens": answer.prompt_tokens,
                "completion_tokens": answer.completion_tokens,
                "retrieved": [
                    {
                        "id": hit.record.id,
                        "control_id": hit.record.control_id,
                        "score": hit.score,
                        "namespace": hit.record.namespace,
                    }
                    for hit in hits
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from atlas.evaluate import run_eval
    from atlas.retrieve import Retriever

    cfg = settings()
    questions = json.loads(cfg.eval_path.read_text())
    records, report = build_records(cfg, wave=DEFAULT_WAVE)
    if report.aborted:
        print(report.reason, file=sys.stderr)
        return 2
    store = _store(cfg, records)
    retriever = Retriever(store, cfg)
    if args.use_llm and cfg.xai_ready:
        print(
            "Note: --use-llm sends answerable eval questions to the configured LLM. "
            "must_refuse probes stay extractive and are never sent.",
            file=sys.stderr,
        )
    summary, code = run_eval(
        questions,
        retriever,
        cfg,
        min_hit_rate=args.min_hit_rate,
        min_refuse_rate=args.min_refuse_rate,
        use_llm=args.use_llm,
    )
    summary["ingest"] = report.to_dict()
    print(json.dumps(summary, indent=2))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Public Control Atlas CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Download, normalize, and optionally upsert")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--wave", type=int, default=DEFAULT_WAVE)
    ingest.set_defaults(func=cmd_ingest)

    query = sub.add_parser("query", help="Retrieve and answer a question")
    query.add_argument("question")
    query.add_argument("--namespace", default="")
    query.add_argument("--kind", default="")
    query.add_argument("--top-k", type=int, default=5)
    query.set_defaults(func=cmd_query)

    ev = sub.add_parser("eval", help="Run the offline evaluation set")
    ev.add_argument("--min-hit-rate", type=float, default=0.8)
    ev.add_argument("--min-refuse-rate", type=float, default=1.0)
    ev.add_argument(
        "--use-llm",
        action="store_true",
        help="Use XAI_API_KEY for answerable items only; must_refuse probes stay extractive",
    )
    ev.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
