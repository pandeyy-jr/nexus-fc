# NEXUS FC

**The Evidence-Driven AI Operating System for a Football Club**

NEXUS FC helps football clubs make better-informed decisions by connecting
operational data, match evidence, and club memory under strict governance.
A core principle is binding: **AI supports human decision-making; it never
autonomously makes medical, selection, substitution, coaching, or
disciplinary decisions.** Every AI output stays a recommendation; the human
act of deciding remains separate and auditable.

## Repository layout

```
Football OS/
├── AGENTS.md               # Engineering constitution for coding agents
├── .gitignore
├── README.md               # This file
└── nexus-backend/          # FastAPI backend, AI layers, tests
    ├── app/
    │   ├── api/            # HTTP endpoints, auth dependencies
    │   ├── schemas/        # Pydantic contracts
    │   ├── services/       # Business logic and governance choke points
    │   ├── repositories/   # Database access only
    │   ├── db/             # SQLAlchemy models, async engine
    │   ├── core/           # Settings, security, roles, memory enums
    │   └── ai/             # Copilot, vision, tactics (ML foundations)
    ├── alembic/            # Schema migrations
    ├── tests/              # pytest suites
    ├── Dockerfile, docker-compose.yml
    └── README.md           # Backend setup and API documentation
```

## Architecture

Backend layers (strict, one-directional):

```
API (app/api) → schemas (app/schemas) → services (app/services)
  → repositories (app/repositories) → database (PostgreSQL)
```

AI layers:

```
vision/ → tactics/ → Club Memory → retrieval → RAG / AI Copilot
```

- **PostgreSQL is the authoritative source of truth.**
- Vector stores (Qdrant) are **derived indexes only** — never canonical
  records, never an authorization authority.
- Tactical ML modules (`app/ai/tactics/`: state, encoding, transformer,
  graph, GNN, fusion, events, evaluation) are **untrained foundation code**.

## Current capabilities

- **Phases 01–07 — Foundations:** domain model, authentication, role-based
  authorization, squad/training/availability operations, video and vision
  processing foundations, tactical intelligence modules.
- **Phase 08 — Club Memory:** memory and evidence records, provenance,
  sensitivity-based governance, redaction, retention expiry (fail closed),
  REST API, governed retrieval, indexing boundary, Qdrant adapter, governed
  vector retrieval that resolves hits back to PostgreSQL before disclosure.
- **Phases 09A–09F — AI Copilot:** governed retrieval integration,
  grounded answer pipeline, deterministic claim/grounding verification
  (no LLM in the verifier), OpenAI-compatible HTTP provider gateway
  (no vendor SDK), fail-closed provider configuration, rate limiting,
  server-generated request IDs, and audit logging.
- **Phases 10A–10C — Decision Replay:** immutable decision replay records,
  read-only chronological reconstruction that separates decision-time
  evidence from later outcomes, AI recommendation vs. human decision kept
  distinct, outcome linking with before/at/after temporal classification,
  provenance preservation, and no hindsight judgment of decisions.

## AI layers

- **Vision:** frame extraction, detection, tracking, observation contracts.
- **Tactics:** tracking-state encoding, temporal and graph models, GNN and
  fusion modules, event extraction, evaluation harnesses — all explicitly
  **untrained**; synthetic fixtures prove plumbing only, never quality.
- **Club Memory:** governed, provenance-preserving long-term club knowledge.
- **Retrieval:** the mandatory choke point for AI reads; payload metadata is
  never trusted for authorization.
- **RAG / AI Copilot:** evidence-backed answers with citations and
  deterministic grounding checks; LLM providers are unconfigured by default
  and fail closed with `503` until a real provider is supplied.

## Technology stack

- Python 3.12+, FastAPI, Pydantic, SQLAlchemy (async), Alembic
- PostgreSQL 16 (production target), SQLite (focused tests only)
- Qdrant (derived vector index), httpx (provider gateway)
- Docker / Docker Compose, pytest, Ruff
- Argon2 password hashing (`pwdlib`), OAuth2 bearer JWT authentication

## Security and governance principles

- Authentication on every API boundary; RBAC enforced from the server-side
  `User.role`, never client-supplied roles; IDOR and cross-actor access
  prevented server-side.
- PostgreSQL is authoritative; vector hits resolve to database records
  before per-actor governance applies. Redacted memories stay stored for
  audit but are never retrievable — not even by `ADMIN`.
- NULL confidence means unknown and is never invented; provenance
  (`source_type`/`source_id`) is immutable.
- No secrets in the repository: `.env` is ignored, `.env.example` carries
  placeholders only.
- AI outputs preserve source, timestamps, model/version, and evidence
  references; recommendations are never presented as decisions.

## Development status

- Phases 01–10C are implemented in this repository.
- RAG/AI Copilot real-world validation, trained tactical models, and live
  Qdrant server integration remain future work — vector integration is
  verified only where explicitly reported, and no model quality claims are
  made anywhere in this repository.
- No production deployment, dataset, user, or partnership claims are made.

## Testing status

Verified locally with Python 3.13:

- Full suite: **550 passed, 3 skipped, 5 pre-existing failures** —
  2 vector-store tests requiring `qdrant-client` (not installed locally)
  and 3 match-endpoint tests with a pre-existing `UUID` JSON-serialization
  issue in the test payload. None involve Phase 09/10 code.
- Phase 10 (10A + 10B + 10C): **52 passed**.
- Broader relevant regression set (governance, memory, auth, RAG, copilot):
  **200 passed, 0 failures**.
- `ruff check` and `ruff format --check` are clean for the Phase 09D–10C
  files; older phase files carry pre-existing lint debt.

Run the suite from `nexus-backend/`:

```powershell
python -m pytest tests/ -q
```

## Getting started

See **[nexus-backend/README.md](nexus-backend/README.md)** for local setup,
configuration, roles, API routes, and Docker instructions. Copy
`nexus-backend/.env.example` to `nexus-backend/.env` and set
`JWT_SECRET_KEY` to a private random value of at least 32 characters.
