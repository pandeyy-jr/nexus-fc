# NEXUS FC — Engineering Constitution

Binding rules for coding agents working in this repository.
Backend lives in `nexus-backend/`; all paths below are relative to it.

## 1. Project purpose

NEXUS FC is an evidence-driven AI operating system for a football club.
Core principle: **AI supports human decision-making; it never autonomously
makes medical, selection, substitution, coaching, or disciplinary decisions.**

## 2. Architecture

Backend layers:

```
API (app/api) → schemas (app/schemas) → services (app/services)
  → repositories (app/repositories) → database (app/db, PostgreSQL)
```

AI layers (`app/ai`):

```
vision/ → tactics/ → Club Memory → retrieval → future RAG/AI Copilot
```

- **PostgreSQL is the authoritative source of truth.**
- Vector stores such as Qdrant are **derived indexes only** — they never
  become canonical records and never authorize disclosure.
- Tactical ML (`tactics/`: state, encoding, transformer, graph, GNN,
  fusion, events, evaluation) is currently **untrained foundation code**.

## 3. Service boundaries

- **Repositories**: database access only. No transaction ownership unless
  the existing convention explicitly requires it.
- **Services**: business logic, transaction ownership (commit/rollback),
  and DTO/public-contract boundaries. Never expose ORM objects.
- **API**: authentication, authorization, request/response handling.
  Never bypass services; never import repositories directly.
- **AI**: must use governed service boundaries
  (`memory_governance`, `memory_retrieval`). Must not directly query
  restricted tables for retrieval/RAG purposes.

## 4. Club Memory rules

- Memory provenance must never be silently lost. `source_type`/`source_id`
  are immutable — no update path may rewrite them.
- Human decisions and AI recommendations are different concepts. An
  AI-generated record must never be represented as a human decision;
  `created_by` (recorder) and `decision_maker` (decider) stay separate.
- Confidence: **NULL means unknown. Never invent confidence values.**
- Redacted memories stay stored (row preserved) for audit/provenance but
  must not be retrievable — not even by ADMIN.
- Expired memories fail closed; expiry never auto-deletes rows.
- Governance runs **before** information enters any RAG/AI context.

## 5. Retrieval rule

Future AI retrieval MUST go through the governed retrieval service.

Never: `AI → raw PostgreSQL`, `AI → raw Qdrant`.
Correct: `AI → governed retrieval → authoritative memory/evidence`.

Vector payload metadata is never authoritative for authorization:
hits resolve to PostgreSQL records, then per-actor governance applies.
Agents operate under a governed user context — no AI bypass exists.

## 6. AI/ML integrity

Never fabricate: model accuracy, evaluation metrics, training results,
confidence, football intelligence, ground-truth performance.
- Untrained models are explicitly described as **untrained**.
- Synthetic fixtures are for testing only; they prove plumbing, never quality.
- No Recall@K/Precision@K without ground-truth relevance labels.
- Real-world performance requires real data and evaluation.

## 7. Provenance

AI outputs preserve: source, source ID, match/video/frame/time where
available, model/version, timestamp, evidence references.
Prefer evidence-backed outputs over unsupported summaries.

## 8. Security baseline

Always: enforce authentication; enforce RBAC from server-side `User.role`
(never client-supplied roles); prevent IDOR; validate input; reject
unknown fields where the schema demands it; protect secrets via
environment (placeholders only in `.env.example`); never log
credentials/tokens/sensitive player information; avoid leaking internal
exceptions (map to explicit HTTP errors); least privilege; protect file
uploads (type/size/signature checks); rate-limit public API boundaries;
verify authorization server-side; fail closed for restricted data.

## 9. Database rules

- Schema changes via Alembic only; test upgrade/downgrade/re-upgrade
  when the environment permits.
- UUID primary keys, `ondelete` FK discipline (RESTRICT vs CASCADE is a
  deliberate per-relation decision), CHECK constraints, indexes.
- Never silently change existing semantics.
- PostgreSQL is the production target. SQLite is acceptable for focused
  tests only — it does not enforce FK pragmas, so DB-level referential
  behavior must be verified on PostgreSQL semantics.

## 10. Testing rules

For every implementation slice: add focused tests; run neighboring
regression tests; run Ruff on changed files; run the formatter; test
failure paths and authorization boundaries.
- Do not fix unrelated pre-existing failures unless instructed.
- Never weaken a test to make it pass.
- Never claim a test/integration passed unless it actually ran.

## 11. Architecture rule

Prefer: small interfaces, explicit contracts, composition, dependency
inversion (Protocols for backends/providers), deterministic behavior,
replaceable infrastructure.
Avoid: unnecessary abstractions, giant service classes, duplicated
business rules, framework leakage, premature optimization,
speculative infrastructure.

## 12. Phase discipline

Do not implement future phases unless explicitly requested. Do not
silently redesign previous phases. If a requirement conflicts with an
existing architectural contract: **STOP and report the conflict** rather
than breaking the contract.

## 13. Data privacy

Player performance, availability, wellness, tracking and related data
may be sensitive. No medical diagnoses or medical-record functionality
unless explicitly scoped and governed. PLAYER-role access is never a
wildcard. Do not expose player information broadly by default.

## 14. AI agent safety

Future AI agents operate under a governed user context; cannot bypass
RBAC; cannot mutate critical domain state except through an explicit
authorized service; cannot represent generated content as human-authored
evidence; must preserve provenance; must distinguish recommendation
(a suggestion) from decision (a human act).

## 15. Production quality

Optimize for correctness, security, maintainability, observability,
testability, explainability, reproducibility — not for "feature exists."

## 16. Coding agent behavior

Before editing: inspect the smallest relevant file set; understand
conventions; avoid broad rewrites. During: smallest coherent change;
reuse abstractions; no duplicated logic. After: focused tests,
relevant regressions, Ruff, format, and report exactly what was
verified (commands run, counts, pre-existing failures left alone).

## 17. Frontend design rules

When a frontend is built: no purple/blue gradients, gradient hero text,
emoji headings, excessive glassmorphism, rainbow/neon styling, generic
three-card layouts, fake testimonials/metrics, purposeless animation,
low-contrast dark UI, or buzzword marketing copy. Prioritize information
hierarchy, real data, useful/loading/error/empty states, responsive
accessible layouts, clear navigation, professional analytics aesthetics.

## 18. Security check before release

Remove test data; verify no committed secrets; test admin routes,
unauthorized access, IDOR, input validation, file uploads, API errors;
remove debug logging; test mobile layouts, slow networks,
failure/recovery paths; attempt to break critical workflows.

## 19. Decision replay principle

Preserve what was known **at the time** of a decision. Never use future
outcomes to rewrite historical context. Separate: information available
then, AI recommendation then, human decision then, eventual outcome.

## 20. Current status

- Phases 01–07: complete foundations (domain, vision, tactical intelligence).
- Phase 08 Club Memory: domain, repository/service, governance, redaction,
  REST, retrieval, indexing boundary, Qdrant adapter, governed vector
  retrieval — built; RAG/AI Copilot remain future layers.
- Qdrant/vectors are derived infrastructure; live-server integration is
  verified only where explicitly reported.
- Real football model validation remains future work.
