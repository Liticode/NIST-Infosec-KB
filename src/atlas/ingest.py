from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass

from atlas.config import Settings
from atlas.fetch import html_to_text, load_json, load_source
from atlas.models import Record
from atlas.oscal import apply_baselines, parse_baseline_ids, parse_oscal_catalog

DEFAULT_WAVE = 2
MAX_ESTIMATED_TOKENS = 4_000_000
MAX_ESTIMATED_BYTES = 500 * 1024 * 1024

_HIPAA_CITE = re.compile(r"(\d{3}\.\d{3}(?:\([^)]+\))*)")
_CPG_DT = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.I | re.S)
_CPG_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_CPG_ID = re.compile(r"\((\d+(?:\.[A-Z])?)\)\s*$")


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


def parse_cpg_html(html: str, source: dict) -> list[Record]:
    records: list[Record] = []
    version = str(source.get("version") or "2.0")
    namespace = source["namespace"]
    source_url = source["source_url"]
    seen: set[str] = set()

    for raw_title, raw_body in _CPG_DT.findall(html):
        title = html_to_text(raw_title)
        body = html_to_text(raw_body)
        match = _CPG_ID.search(title)
        cid = match.group(1) if match else title
        if match:
            title = title[: match.start()].strip()
        if cid in seen:
            continue
        seen.add(cid)
        family = cid.split(".")[0] if "." in cid else cid
        records.append(
            Record(
                id=f"{namespace}:{cid}",
                framework=source["framework"],
                control_id=cid,
                title=title or cid,
                text=f"{cid} {title}. {body}".strip(),
                family=family,
                version=version,
                source_url=source_url,
                namespace=namespace,
                kind=source.get("kind") or "outcome",
            )
        )

    for raw in _CPG_H2.findall(html):
        heading = html_to_text(raw)
        match = _CPG_ID.search(heading)
        if not match:
            continue
        cid = match.group(1)
        if "." in cid or cid in seen:
            continue
        seen.add(cid)
        title = heading[: match.start()].strip() or heading
        records.append(
            Record(
                id=f"{namespace}:fn-{cid}",
                framework=source["framework"],
                control_id=cid,
                title=title,
                text=f"CISA CPG 2.0 {title} function ({cid}).",
                family=cid,
                version=version,
                source_url=source_url,
                namespace=namespace,
                kind="function",
            )
        )
    return records


def _hipaa_cite(identifier: str) -> str:
    match = _HIPAA_CITE.search(identifier or "")
    return match.group(1) if match else identifier


def parse_cprt_80066(payload: dict, source: dict) -> list[Record]:
    block = ((payload.get("response") or {}).get("elements") or payload)
    elements = block.get("elements") or []
    rels = block.get("relationships") or []
    by_id = {str(item.get("element_identifier") or ""): item for item in elements}
    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}
    for rel in rels:
        src = str(rel.get("source_element_identifier") or "")
        dest = str(rel.get("dest_element_identifier") or "")
        if src and dest:
            children.setdefault(src, []).append(dest)
            parents.setdefault(dest, []).append(src)

    records: list[Record] = []
    version = str(source.get("version") or "2.0.0")
    namespace = source["namespace"]
    source_url = source["source_url"]
    emit_types = {
        "security_rule": "safeguard",
        "standard": "standard",
        "imp_spec": "implementation",
        "key_activity": "activity",
        "sample_question": "assessment",
    }
    for item in elements:
        etype = str(item.get("element_type") or "")
        if etype not in emit_types:
            continue
        eid = str(item.get("element_identifier") or "")
        if not eid:
            continue
        title = str(item.get("title") or eid)
        text = str(item.get("text") or "").strip()
        if etype == "key_activity":
            desc = []
            for child_id in children.get(eid, []):
                child = by_id.get(child_id) or {}
                if child.get("element_type") == "description" and child.get("text"):
                    desc.append(str(child["text"]).strip())
            text = " ".join(desc)
        if not text:
            text = title
        cite = _hipaa_cite(eid)
        related = [cite] if cite and cite != eid else []
        related.extend(parents.get(eid, [])[:12])
        records.append(
            Record(
                id=f"{namespace}:{eid}",
                framework=source["framework"],
                control_id=cite,
                title=title,
                text=f"{cite} {title}. {text}",
                family=cite.split("(")[0] if cite else "hipaa",
                version=version,
                source_url=source_url,
                namespace=namespace,
                kind=emit_types[etype],
                related_ids=related[:40],
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


def build_records(settings: Settings, wave: int = DEFAULT_WAVE) -> tuple[list[Record], IngestReport]:
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
        elif parser == "html_cpg":
            raw = load_source(settings, source["url"]).decode("utf-8", errors="replace")
            records.extend(parse_cpg_html(raw, source))
        elif parser == "cprt_80066":
            payload = load_json(settings, source["url"])
            records.extend(parse_cprt_80066(payload, source))
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
