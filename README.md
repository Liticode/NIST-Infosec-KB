# Public Control Atlas

Cited retrieval over **public NIST and CISA catalogs**, on **Pinecone Starter**, with **Grok** answers that refuse when the evidence is missing.

This is a portfolio and training project. It is not an official NIST or CISA tool, and it is not legal, audit, or compliance advice.

## What it demonstrates

A hiring manager can clone the repo, run tests with no API keys, and (with a free Pinecone key) watch the same patterns used in assurance work:

1. Ingest **machine-readable** government catalogs (OSCAL JSON, CISA KEV), not mystery PDFs.
2. Store them in a Pinecone serverless index with **namespaces per framework** and **metadata filters** (family, kind, baseline flags).
3. Ask questions such as “how would an auditor test AC-2?” or “is AC-2 in the moderate baseline?”
4. Return **control IDs + source URLs**. No citation that exists in the retrieved set → **refuse**.
5. Route low-confidence results to a JSONL **human-review queue**.
6. Record latency and token estimates **without** logging the raw question.

```
ingest official JSON  →  normalize by control  →  Pinecone namespaces
        ↑                                              ↓
   allowlisted URLs                            retrieve + optional rerank
                                                       ↓
                                         Grok answers only from passages
                                                       ↓
                                      cite / refuse / review queue
```

## Corpus

| Namespace | Source | Wave | What it unlocks |
|---|---|---|---|
| `csf-2` | NIST CSF 2.0 OSCAL | 1 | Outcomes such as GV.OC-01 |
| `sp800-53-r5` | NIST SP 800-53 Rev. 5.2.0 | 1 | Control statements |
| `sp800-53a` | Same catalog (embedded 800-53A) | 1 | Assessment objectives and methods |
| `sp800-53b` | NIST SP 800-53B profiles | 1 | Low / moderate / high / privacy membership |
| `ai-rmf` | NIST AI RMF 1.0 core titles | 1 | Responsible-AI vocabulary |
| `cisa-kev` | CISA KEV JSON | 1 | Exploited CVEs |
| `bod-22-01` | CISA BOD 22-01 | 1 | Why KEV remediations are obligatory for FCEB |
| `sp800-171-r3` | NIST SP 800-171 Rev. 3 OSCAL | 2 | CUI requirements such as 03.01.01 |
| `sp800-171a` | Same catalog (embedded 800-171A) | 2 | Assessment objectives for CUI requirements |
| `sp800-218` | NIST SP 800-218 SSDF 1.1 OSCAL | 2 | Practices such as PO.1 |
| `cisa-cpg` | CISA CPG 2.0 | 2 | Cross-sector goals such as 1.A |
| `sp800-66r2` | NIST SP 800-66 Rev. 2 CPRT JSON | 2 | HIPAA Security Rule standards and 800-66 activities |

All of that stays inside Pinecone **Starter** (2 GB, 5M embedding tokens). See [SOURCES.md](SOURCES.md).

ISO 27001, PCI-DSS, HITRUST, CIS, and SCF mappings are **intentionally absent**. Those texts are not public-domain.

## Quick start

Python 3.12+. Clone from GitHub (do not copy a local venv or `.env`):

```bash
git clone https://github.com/Liticode/NIST-Infosec-KB.git
cd NIST-Infosec-KB
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env         # add keys when you have them
pytest                       # no network, no keys
python -m atlas ingest --dry-run
```

Live upsert and Grok answers need keys in `.env`:

```bash
PINECONE_API_KEY=...
XAI_API_KEY=...
python -m atlas ingest
python -m atlas query "How would an auditor assess AC-2 account management?"
python -m atlas eval
```

Without keys, `ingest` (not `--dry-run`) and `query` use an in-memory lexical index and an extractive fallback so the CLI still works offline.

## Pinecone Starter notes

- Create an account at [app.pinecone.io](https://app.pinecone.io) and stay on **Starter**.
- Do **not** start the Standard trial unless you want a $50/month minimum later.
- Indexes are AWS `us-east-1` only.
- This project uses `create_index_for_model` + `upsert_records` + `search` (integrated `llama-text-embed-v2`).
- Re-embed only when a source version changes.

## Cost

| Item | Expected |
|---|---|
| Pinecone Starter | $0 if you stay under included storage / units |
| Pinecone embeddings / rerank | $0 on Starter included quotas |
| xAI Grok 4.6 answers | about $5–15 for build + eval; a few dollars a month for light demo use |
| GitHub Actions | $0 on a public repo |

## Project layout

```
src/atlas/          CLI, ingest, OSCAL/KEV parsers, retrieve, answer, review
data/manifest.json  Allowlisted official URLs
data/ai_rmf_core.json
eval/questions.json
tests/              Fake retriever + citation tests (no secrets)
```

## Limitations

- Starter has no RBAC, no backups, no uptime SLA.
- Models can still err; refusal reduces fabrication, it does not eliminate it.
- Baseline flags come from official 800-53B profiles, not from a commercial crosswalk.
- AI RMF Wave 1 is the official core function/category titles, not the full playbook.
- SP 800-66r2 is public NIST/HIPAA Security Rule guidance, not patient records. Queries about a named person's ePHI are refused.

## License

Code: [MIT](LICENSE). Catalogs: U.S. government works; see [NOTICE](NOTICE) and [SOURCES.md](SOURCES.md).
