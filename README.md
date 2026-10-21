# AI Corporations & Products Dashboard

MIS 556 Group Assignment 1. A RAG + agent-powered dashboard on Google, OpenAI, Anthropic, Nvidia and Apple, for an enterprise AI buyer/investor.

**Start here:** open `START HERE - Team Guide.docx` (one folder up) for what to do and how to run this.

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python validate_data.py --dir data/sample   # check the mock data (should say OK)
streamlit run app/main.py                   # open the dashboard (starts on sample data)
```

## The core (Reid): RAG, agents, refresh
```bash
pip install -r requirements-core.txt
python -m pytest tests -q                # 71 offline tests, free
python refresh.py --sample               # collectors -> validate -> index -> verify -> change log
python refresh.py --collect              # same on REAL data (needs .env, see .env.example)
python -m rag ask "Which model is cheapest?" --sample
```
- **Real data pipeline** (needs `.env` with the OpenAI key and `SEC_USER_AGENT`): `python -m collectors.filings` (SEC documents) → `python -m collectors.prices` → `python -m collectors.financials_from_releases` (LLM extraction, guarded) → `python refresh.py` (validate, index, verify, SEC XBRL cross-check). Or all in one: `python refresh.py --collect`.
- **No API key:** everything runs offline (hashing embedder, keyword routing, extractive answers) so it can be tested for free. With `OPENAI_API_KEY` in `.env` it switches to real embeddings and LLM answers automatically.
- **Spending cap:** `MAX_USD_PER_RUN` in `.env`; every API call is metered and stops at the cap.
- **How it works:** `rag/` = chunk, embed, hybrid search (vectors + BM25 fused with RRF, company boost, metadata filters), cited answers. `agents/` = LangGraph: Supervisor routes to Researcher (RAG), Analyst (pandas tools), Verifier (checks numbers against the cited documents), Writer.

## Layout
```
contract.py          data contract (columns, allowed values): the single source of truth
validate_data.py     checks your CSVs; run before every push
data/
  financials.csv  stock_prices.csv  token_pricing.csv  partnerships.csv
  sources/sources_A.csv  sources_B.csv  sources_R.csv     one file per owner
  raw/<Company>/                                           documents the RAG reads
  sample/                                                  MOCK data for building and testing
collectors/          re-runnable data scripts: prices.py, filings.py (baseline by Reid; Manny extends)
tabs/                one file per dashboard tab (teammates: financials, stock, pricing, partnerships)
rag/  agents/  app/  refresh.py  tests/    Reid's core
docs/                plan, role cards, insights
```

## Rules in one line each
- **No source, no row.** Every value has a `source_id` pointing at a page you opened.
- Real data goes in `data/`; `data/sample/` is fake and never mixes with it.
- Own branch, pull request, Reid merges. `python validate_data.py` must pass first.
- No keys in git. Use `.env` (copy `.env.example`).
- Using an AI assistant is fine. Give it `docs/TEAM_PLAN.md`, your role card, `contract.py` and `validate_data.py`, and never let it supply facts from memory.
