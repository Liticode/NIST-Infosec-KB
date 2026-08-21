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

## Quick start (auditor walkthrough)

You need **Git** and **Python 3.12 or newer**. Check with `python3 --version`. You do **not** need API keys to clone, run tests, or try a local question.

### 1. Clone and make a virtual environment

A virtual environment (`.venv`) is a project-local Python install so this tool’s packages do not mix with the rest of your machine. Create it once; **activate it in every new terminal** before you run commands.

```bash
git clone https://github.com/Liticode/NIST-Infosec-KB.git
cd NIST-Infosec-KB
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# Windows:  .venv\Scripts\activate
pip install -e ".[dev]"
```

Your prompt should show `(.venv)`. To leave it later: `deactivate`. Do not copy someone else’s `.venv` or `.env`.

### 2. `.env` — only if you want live Pinecone or Grok

Copy the template. The real `.env` is gitignored and must never be committed.

```bash
cp .env.example .env
```

| Variable | Required? | What it does |
|---|---|---|
| *(none)* | No | `pytest` and extractive `query` work with no keys. |
| `PINECONE_API_KEY` | Only for a cloud index | Upserts the catalog into **your** free [Pinecone Starter](https://app.pinecone.io) index. Stay on Starter; do not start the Standard trial. |
| `XAI_API_KEY` | Only for Grok answers | Lets `query` write a cited answer from retrieved passages. Without it, you still get citations plus an extractive quote. |

Open `.env` in a text editor and paste keys on the right-hand side of `PINECONE_API_KEY=` and/or `XAI_API_KEY=` with no quotes. Leave a line blank if you are not using that service.

### 3. Prove it works (no keys)

**Network note:** `pytest` is fully offline. `atlas ingest` (with or without `--dry-run`) downloads allowlisted HTTPS catalogs from NIST/CISA unless they are already in `data/cache/`. `--dry-run` only skips the Pinecone upsert. On a locked-down network you will get a clear runtime error pointing you back to `pytest`.

```bash
pytest                            # automated tests; no network
python -m atlas ingest --dry-run  # needs HTTPS (or cache); does not upsert
python -m atlas query "How would an auditor assess AC-2 account management?"
python -m atlas eval              # extractive by default; never sends refusal probes to an LLM
```

A good result includes `citations` (record IDs) and `refused: false`. Refusal means retrieved passages do not support the question (wrong control/framework, out-of-scope cue such as ISO 27001 / PCI / a patient id pattern, or answer text that is not in the citations). Extractive mode will not quote an unrelated hit. `python -m atlas eval` fails if expected refusals are missed.

### 4. Optional: live Pinecone + Grok

After keys are in `.env`:

```bash
python -m atlas ingest
python -m atlas query "How would an auditor assess AC-2 account management?"
python -m atlas query "What does NIST SP 800-171 requirement 03.01.01 require for account management?"
python -m atlas eval
# optional: python -m atlas eval --use-llm   # answerable items only; must_refuse stays extractive
```

`ingest` (without `--dry-run`) writes to Pinecone only when `PINECONE_API_KEY` is set; otherwise it uses an in-memory index that lasts for that process only.

### 5. Ask your AI to help you configure it

You do not have to set this up by hand. After you clone the repo, open the folder in the assistant you already use (Claude, ChatGPT, Copilot, Cursor, Gemini, and so on) so it can **read the files**. Then paste the prompt below.

Tell it to look at `README.md`, `.env.example`, `pyproject.toml`, and `src/atlas/` before it suggests commands. Do **not** paste API keys into the chat; put keys only in local `.env`.

```text
I cloned this Public Control Atlas repository.
I am a semi-technical auditor, not a Python specialist. Please read this repo
(README.md, .env.example, pyproject.toml, src/atlas/) and help me get it working
on my machine.

Do this:
1. Check that I have Git and Python 3.12+.
2. Create/activate a project venv (.venv) and pip install -e ".[dev]".
3. Run pytest (offline). Then, if I have HTTPS access, run
   python -m atlas ingest --dry-run (downloads NIST/CISA catalogs; does not
   upsert). Then a sample python -m atlas query about AC-2. Explain
   citations vs refused. Remind me that --dry-run still needs network unless
   data/cache/ is already populated.
4. Configuration: the only API key needed for a live cloud index is
   PINECONE_API_KEY (free Pinecone Starter at https://app.pinecone.io).
   Stay on Starter; do not start the Standard trial. Copy .env.example to
   .env if we use a key; never commit .env. XAI_API_KEY is optional (Grok
   prose). Do not make me create extra vendor accounts.
5. Suggest use options: local no-key demo vs live Pinecone ingest + query.
   Give me copy-paste commands for my OS. Eval defaults to extractive;
   --use-llm is optional and must never send must_refuse probes to a vendor.

Constraints: do not ingest ISO, PCI, HITRUST, CIS, SCF, PHI, or client files.
Do not print or store secrets. Do not change code unless I ask.
```

If the assistant cannot see the repo, attach or `@`-mention the project folder first. A useful first result is: venv created, tests green, and either a local query or a one-line instruction for where to paste a Pinecone Starter key.

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
- SP 800-66r2 is public NIST/HIPAA Security Rule guidance, not patient records. The corpus has no ePHI. Grounding refuses some out-of-scope patterns (for example a `patient <id>` cue that is not in the passages); it is not a general privacy filter. Do not paste real ePHI or client secrets into `atlas query`.

## License

Code: [MIT](LICENSE). Catalogs: U.S. government works; see [NOTICE](NOTICE) and [SOURCES.md](SOURCES.md).
