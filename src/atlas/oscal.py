from __future__ import annotations

import re
from collections.abc import Iterable

from atlas.models import Record

_INSERT_RE = re.compile(r"\{\{\s*insert:\s*param,\s*([^}]+)\s*\}\}")


_PAREN_ID = re.compile(r"^(.+?)\s+\(([^)]+)\)\s*$")


def _label(node: dict) -> str:
    raw = ""
    for prop in node.get("props") or []:
        if prop.get("name") == "label" and prop.get("class") != "zero-padded":
            raw = str(prop.get("value") or "")
            break
    if not raw:
        raw = str(node.get("id") or "")
    # "Account Management (03.01.01)" / "Define Security Requirements (PO.1)" -> public ID
    match = _PAREN_ID.match(raw)
    if match and re.search(r"[\d.]", match.group(2)):
        return match.group(2)
    return raw


def _param_map(control: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for param in control.get("params") or []:
        pid = str(param.get("id") or "")
        label = param.get("label") or param.get("guidelines", {}).get("prose") or pid
        if isinstance(label, dict):
            label = label.get("prose") or pid
        out[pid] = str(label)
        out[pid.replace("_", "-")] = str(label)
    return out


def _fill(text: str, params: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return params.get(key, params.get(key.replace("_", "-"), f"[{key}]"))

    return _INSERT_RE.sub(repl, text)


def _collect_prose(parts: Iterable[dict], names: set[str], params: dict[str, str]) -> list[str]:
    chunks: list[str] = []
    for part in parts:
        name = part.get("name")
        if name in names and part.get("prose"):
            chunks.append(_fill(str(part["prose"]), params))
        chunks.extend(_collect_prose(part.get("parts") or [], names, params))
    return chunks


def _related_ids(node: dict) -> list[str]:
    out: list[str] = []
    for link in node.get("links") or []:
        href = str(link.get("href") or "")
        rel = str(link.get("rel") or "")
        if rel in {"related", "incorporated_into", "reference"} and href.startswith("#"):
            out.append(href[1:])
    return out


def parse_oscal_catalog(payload: dict, source: dict) -> list[Record]:
    catalog = payload.get("catalog") or payload
    metadata = catalog.get("metadata") or {}
    version = source.get("version") or metadata.get("version") or ""
    source_url = source["source_url"]
    framework = source["framework"]
    statement_ns = source["namespace"]
    assess_ns = source.get("also_emit_assessment_namespace")
    records: list[Record] = []

    def walk(nodes: list[dict], family: str) -> None:
        for node in nodes:
            cid = str(node.get("id") or "")
            title = str(node.get("title") or cid)
            label = _label(node) or cid
            params = _param_map(node)
            parts = node.get("parts") or []
            statement = _collect_prose(parts, {"statement", "item", "example", "guidance"}, params)
            assessment = _collect_prose(
                parts,
                {"assessment-objective", "assessment-method", "assessment-objects"},
                params,
            )
            related = _related_ids(node)
            if statement:
                records.append(
                    Record(
                        id=f"{statement_ns}:{cid}:statement",
                        framework=framework,
                        control_id=label,
                        title=title,
                        text=f"{label} {title}. " + " ".join(statement),
                        family=family,
                        version=str(version),
                        source_url=source_url,
                        namespace=statement_ns,
                        kind=source.get("kind") or "statement",
                        related_ids=related,
                    )
                )
            if assess_ns and assessment:
                records.append(
                    Record(
                        id=f"{assess_ns}:{cid}:assessment",
                        framework=str(source.get("assessment_framework") or assess_ns),
                        control_id=label,
                        title=f"Assessment procedures for {label}",
                        text=f"Assessment for {label} {title}. " + " ".join(assessment),
                        family=family,
                        version=str(version),
                        source_url=source_url,
                        namespace=assess_ns,
                        kind="assessment",
                        related_ids=[cid, *related],
                    )
                )
            walk(node.get("controls") or [], family)

    for group in catalog.get("groups") or []:
        family = str(group.get("id") or group.get("title") or "")
        walk(group.get("controls") or [], family)
        # some catalogs put controls only at group.controls
    if not catalog.get("groups") and catalog.get("controls"):
        walk(catalog.get("controls") or [], "")
    return records


def parse_baseline_ids(payload: dict) -> set[str]:
    profile = payload.get("profile") or payload
    ids: set[str] = set()
    for imported in profile.get("imports") or []:
        for block in imported.get("include-controls") or []:
            for cid in block.get("with-ids") or []:
                ids.add(str(cid).lower())
    return ids


def apply_baselines(records: list[Record], membership: dict[str, set[str]]) -> None:
    for record in records:
        key = record.control_id.lower().replace(" ", "")
        alt = key.replace("-0", "-")
        candidates = {record.control_id.lower(), key, alt, key.replace(".", "-")}
        # OSCAL baseline ids look like ac-2 / ac-2.1
        oscal = record.id.split(":")[1] if ":" in record.id else record.control_id
        candidates.add(oscal.lower())
        if candidates & membership.get("low", set()):
            record.in_low = True
        if candidates & membership.get("moderate", set()):
            record.in_moderate = True
        if candidates & membership.get("high", set()):
            record.in_high = True
        if candidates & membership.get("privacy", set()):
            record.in_privacy = True
