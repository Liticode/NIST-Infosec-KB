from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from atlas.config import Settings
from atlas.fetch import html_to_text, load_json, load_source
from atlas.models import Record
from atlas.oscal import apply_baselines, parse_baseline_ids, parse_oscal_catalog

MAX_ESTIMATED_TOKENS = 4_000_000
MAX_ESTIMATED_BYTES = 500 * 1024 * 1024


@dataclass
class IngestReport:
    sources: int
    records: int
    by_namespace: dict[str, int]
    estimated_tokens: int
    estimated_bytes: int
    aborted: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "sources": self.sources,
            "records": self.records,
            "by_namespace": self.by_namespace,
            "estimated_tokens": self.estimated_tokens,
            "estimated_bytes": self.estimated_bytes,
            "aborted": self.aborted,
            "reason": self.reason,
        }


def load_manifest(settings: Settings) -> dict:
    return json.loads(settings.manifest_path.read_text())


def parse_ai_rmf(payload: dict, source: dict) -> list[Record]:
    records: list[Record] = []
    for item in payload.get("functions") or []:
        cid = str(item["id"])
        title = str(item.get("title") or cid)
        text = str(item.get("text") or title)
        family = cid.split("-")[0]
        records.append(
            Record(
                id=f"ai-rmf:{cid}",
                framework=source["framework"],
                control_id=cid,
                title=title,
                text=f"{cid}. {text}",
                family=family,
                version=str(source.get("version") or "1.0"),
                source_url=source["source_url"],
                namespace=source["namespace"],
                kind="outcome",
            )
        )
    return records


def parse_kev(payload: dict, source: dict) -> list[Record]:
    records: list[Record] = []
    version = str(payload.get("catalogVersion") or source.get("version") or "current")
    for item in payload.get("vulnerabilities") or []:
        cve = str(item.get("cveID") or "")
        if not cve:
            continue
        name = str(item.get("vulnerabilityName") or cve)
        desc = str(item.get("shortDescription") or "")
        action = str(item.get("requiredAction") or "")
        vendor = str(item.get("vendorProject") or "")
        product = str(item.get("product") or "")
        text = (
            f"{cve} {name}. Vendor {vendor} product {product}. {desc} "
            f"Required action: {action}. Date added {item.get('dateAdded', '')}. "
            f"Ransomware use: {item.get('knownRansomwareCampaignUse', '')}."
        )
        records.append(
            Record(
                id=f"cisa-kev:{cve}",
                framework="cisa-kev",
                control_id=cve,
                title=name,
                text=text,
                family=vendor or "kev",
                version=version,
                source_url=source["source_url"],
                namespace=source["namespace"],
                kind="kev",
                related_ids=["bod-22-01"],
            )
        )
    return records


def parse_directive(html: str, source: dict) -> list[Record]:
    text = html_to_text(html)
    if len(text) > 20000:
        text = text[:20000]
    return [
        Record(
            id="bod-22-01:body",
            framework="cisa-bod",
            control_id="BOD-22-01",
            title="BOD 22-01 Reducing the Significant Risk of Known Exploited Vulnerabilities",
            text=text or "CISA Binding Operational Directive 22-01 covering the Known Exploited Vulnerabilities catalog.",
            family="directive",
            version=str(source.get("version") or "22-01"),
            source_url=source["source_url"],
            namespace=source["namespace"],
            kind="directive",
            related_ids=["cisa-kev"],
        )
    ]


def build_records(settings: Settings, wave: int = 1) -> tuple[list[Record], IngestReport]:
    manifest = load_manifest(settings)
    sources = [s for s in manifest["sources"] if int(s.get("wave", 1)) <= wave]
    records: list[Record] = []
    baselines: dict[str, set[str]] = {}

    for source in sources:
        parser = source["parser"]
        if parser == "oscal_catalog":
            payload = load_json(settings, source["url"])
            records.extend(parse_oscal_catalog(payload, source))
        elif parser == "oscal_baseline":
            payload = load_json(settings, source["url"])
            baselines[source["baseline"]] = parse_baseline_ids(payload)
        elif parser == "ai_rmf_core":
            payload = load_json(settings, source["url"])
            records.extend(parse_ai_rmf(payload, source))
        elif parser == "cisa_kev":
            payload = load_json(settings, source["url"])
            records.extend(parse_kev(payload, source))
        elif parser == "html_directive":
            raw = load_source(settings, source["url"]).decode("utf-8", errors="replace")
            records.extend(parse_directive(raw, source))
        else:
            raise ValueError(f"unknown parser {parser}")

    if baselines:
        apply_baselines(records, baselines)
        # compact baseline documents so "is AC-2 in moderate?" is directly retrievable
        for name, ids in baselines.items():
            sample = ", ".join(sorted(ids)[:80])
            records.append(
                Record(
                    id=f"sp800-53b:{name}",
                    framework="sp800-53b",
                    control_id=f"BASELINE-{name.upper()}",
                    title=f"NIST SP 800-53B {name} baseline",
                    text=(
                        f"NIST SP 800-53B {name} baseline control identifiers include: {sample}. "
                        f"Total selected controls/enhancements: {len(ids)}."
                    ),
                    family="baseline",
                    version="5.2.0",
                    source_url="https://csrc.nist.gov/pubs/sp/800/53b/final",
                    namespace="sp800-53b",
                    kind="baseline",
                )
            )

    by_ns: dict[str, int] = defaultdict(int)
    tokens = 0
    for rec in records:
        by_ns[rec.namespace] += 1
        tokens += rec.estimated_tokens()
    est_bytes = sum(len(r.text.encode()) + 256 for r in records)
    aborted = tokens > MAX_ESTIMATED_TOKENS or est_bytes > MAX_ESTIMATED_BYTES
    reason = ""
    if tokens > MAX_ESTIMATED_TOKENS:
        reason = f"estimated tokens {tokens} exceed {MAX_ESTIMATED_TOKENS}"
    elif est_bytes > MAX_ESTIMATED_BYTES:
        reason = f"estimated bytes {est_bytes} exceed {MAX_ESTIMATED_BYTES}"
    report = IngestReport(
        sources=len(sources),
        records=len(records),
        by_namespace=dict(by_ns),
        estimated_tokens=tokens,
        estimated_bytes=est_bytes,
        aborted=aborted,
        reason=reason,
    )
    return records, report
