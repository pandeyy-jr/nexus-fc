# NEXUS FC Backend

Phase 04 extends the backend foundation with authentication, role-based authorization, squad management, training history, operational availability, and player development records. Public registration creates a `PLAYER`; admins manage user roles and account activation. Medical records, injury prediction, performance analytics, tactical AI, and frontend functionality are not implemented.

## Requirements and local setup

- Python 3.12+
- Docker Desktop with Compose, or PostgreSQL 16

From this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `JWT_SECRET_KEY` to a private random value of at least 32 characters. Keep `.env` local; it is ignored by Git. For a local PostgreSQL container, start the database with `docker compose up -d db`. Apply migrations and start the API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Or use the API and database containers together:

```powershell
docker compose up --build
```

The API listens on `http://localhost:8000`; OpenAPI documentation is at `/docs`.

## Configuration

Configuration is read from environment variables or `.env`:

- `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`
- `DATABASE_URL`
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- `CORS_ORIGINS`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` for Compose

The JWT secret must be at least 32 characters. CORS origins default to an empty list. Never commit real credentials.

## Roles and registration

The supported roles are `HEAD_COACH`, `ASSISTANT_COACH`, `ANALYST`, `SPORTS_SCIENTIST`, `MEDICAL_STAFF`, `SCOUT`, `PLAYER`, `DIRECTOR`, and `ADMIN`. Stored role names are constrained to this set. Public registration always assigns `PLAYER`; registration rejects unknown extra fields, including a client-supplied `role`.

Passwords must be 12 to 128 characters and are hashed with Argon2 through `pwdlib`. Passwords and token values are not logged or returned. User responses omit password hashes.

## Authentication and authorization

Register and login return an OAuth2-style bearer token response. Send the token on protected requests with `Authorization: Bearer <access_token>`.

Authentication verifies the token, resolves the user from the database, and rejects inactive or missing users. Authorization then checks the current database role for the operation. Missing, malformed, expired, or inactive-user tokens return `401 Unauthorized`. An authenticated user without the required role receives `403 Forbidden`.

### API routes

- `GET /api/v1/health`
- `GET /api/v1/health/db`
- `GET /api/v1/info`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me` (authenticated)
- `GET /api/v1/users` (admin; supports `limit` and `offset`)
- `GET /api/v1/users/{user_id}` (admin)
- `PATCH /api/v1/users/{user_id}/status` (admin)
- `PATCH /api/v1/users/{user_id}/role` (admin)
- `GET /api/v1/players`
- `POST /api/v1/players`
- `GET /api/v1/players/{player_id}`
- `PATCH /api/v1/players/{player_id}`
- `DELETE /api/v1/players/{player_id}`
- `GET /api/v1/staff`
- `POST /api/v1/staff`
- `GET /api/v1/staff/{staff_id}`
- `PATCH /api/v1/staff/{staff_id}`
- `DELETE /api/v1/staff/{staff_id}`
- `GET /api/v1/teams`
- `POST /api/v1/teams`
- `GET /api/v1/teams/{team_id}`
- `PATCH /api/v1/teams/{team_id}`
- `DELETE /api/v1/teams/{team_id}`
- `GET /api/v1/teams/{team_id}/players?include_history=false`
- `POST /api/v1/teams/{team_id}/players/{player_id}`
- `PATCH /api/v1/teams/{team_id}/players/{player_id}`
- `DELETE /api/v1/teams/{team_id}/players/{player_id}` (ends the current membership)
- `GET /api/v1/training/sessions`
- `POST /api/v1/training/sessions`
- `GET /api/v1/training/sessions/{session_id}`
- `PATCH /api/v1/training/sessions/{session_id}`
- `DELETE /api/v1/training/sessions/{session_id}` (only when it has no participation records)
- `GET /api/v1/training/sessions/{session_id}/players`
- `POST /api/v1/training/sessions/{session_id}/players`
- `PATCH /api/v1/training/sessions/{session_id}/players/{player_id}`
- `DELETE /api/v1/training/sessions/{session_id}/players/{player_id}`
- `GET /api/v1/players/{player_id}/training`
- `GET /api/v1/players/{player_id}/availability`
- `GET /api/v1/players/{player_id}/availability/current`
- `POST /api/v1/players/{player_id}/availability`
- `PATCH /api/v1/players/{player_id}/availability/{availability_id}`
- `DELETE /api/v1/players/{player_id}/availability/{availability_id}` (ends the period)
- `GET /api/v1/players/{player_id}/development/goals`
- `POST /api/v1/players/{player_id}/development/goals`
- `GET /api/v1/players/{player_id}/development/goals/{goal_id}`
- `PATCH /api/v1/players/{player_id}/development/goals/{goal_id}`
- `DELETE /api/v1/players/{player_id}/development/goals/{goal_id}` (cancels and retains history)
- `GET /api/v1/players/{player_id}/development/assessments`
- `POST /api/v1/players/{player_id}/development/assessments`
- `GET /api/v1/players/{player_id}/development/assessments/{assessment_id}`
- `PATCH /api/v1/players/{player_id}/development/assessments/{assessment_id}`

## Squad domain

Players have a non-medical operational status (`ACTIVE`, `INACTIVE`, `SUSPENDED`), controlled preferred/secondary positions, optional physical profile fields, and an optional unique link to an existing `PLAYER` user. A player profile can exist without a login. Linked user accounts are never embedded in player responses.

Staff profiles reference an existing non-player `User`; creating a staff profile does not create an account. Teams are club-defined records with name, short name, age group, gender category, season, and active state.

Player-team assignments are stored as `PlayerTeamMembership` records with UTC join/leave timestamps and constrained squad statuses (`ACTIVE`, `INACTIVE`, `LOANED`, `RELEASED`). Ending a membership sets `left_at` and marks the history row `INACTIVE`; it does not delete it. A partial unique index prevents more than one current membership for a player/team pair. Profiles or teams with membership history cannot be deleted, preserving the historical record. Player accounts see only teams where their linked player profile is currently assigned; within those rosters they see only their own membership rows, including history when requested.

## Domain access rules

- `ADMIN` and `DIRECTOR` can create, view, update, and delete player/team profiles; they can manage staff profiles and memberships.
- `HEAD_COACH` can create, view, and update players, create/update teams, manage staff profiles, and manage memberships; deletion of players/teams is reserved for `ADMIN` and `DIRECTOR`.
- `ASSISTANT_COACH` can view players and teams, update the permitted football-profile fields (position, squad number, dominant foot, height, and weight), and manage memberships. They cannot change identity, account links, or player status.
- `ANALYST`, `SPORTS_SCIENTIST`, `MEDICAL_STAFF`, and `SCOUT` can read player, staff, and team profiles.
- `PLAYER` can only list/view their own linked player profile, see teams and roster history associated with their own profile, and cannot modify profiles, staff, teams, or memberships.

Management routes require authentication. A valid user without the required role receives `403`; missing or invalid credentials receive `401`. Player access to another player's profile/team is concealed with `404`. Create/update schemas reject unknown fields and invalid enums; optional nullable fields may be cleared only where the domain allows it.

No medical records or diagnoses, injury prediction, player performance analytics, training intelligence, scouting intelligence, tactical AI, match intelligence, or video/vision features are implemented in this phase.

## Training, availability, and development

Training sessions belong to a team and record planned session details. Participation is unique per session/player. Adding a participant requires a player-team membership that overlaps the session date; historical memberships therefore work for past sessions but do not authorize attendance after a player has left that team. A session with participation history cannot be deleted. Training loads are descriptive club-defined values from 0 to 1000, not injury indicators or recommendations. Planned intensity is a 1-to-10 planning field, not a measured medical value.

Availability is operational only (`AVAILABLE`, `LIMITED`, `UNAVAILABLE`) and has constrained reason categories. Notes must contain operational restrictions only. Availability periods use UTC timestamps; overlapping periods are rejected, and the current endpoint returns `null` when no explicit period is active. `DELETE` ends an active/future period rather than removing its history. This domain does not contain diagnoses, treatment plans, medication, or clinical notes.

Development goals use controlled category, status, and priority values. Assessments are human-authored records attributed to the authenticated assessor. New assessments append to the history; editing a specific assessment does not replace other entries. Deleting a goal marks it `CANCELLED` so its assessment history remains available.

### Phase 04 access rules

- `ADMIN`, `DIRECTOR`, and `HEAD_COACH` can manage sessions, participation, and development records. `ASSISTANT_COACH` can also manage these coaching records.
- `ANALYST` and `SPORTS_SCIENTIST` can read training records. Sports scientists may update participation load/duration fields only; they cannot create/delete participation or change attendance and notes.
- `ADMIN`, `DIRECTOR`, `HEAD_COACH`, and `ASSISTANT_COACH` can read operational availability. `ADMIN`, `DIRECTOR`, `HEAD_COACH`, and `MEDICAL_STAFF` can record/update/end it. The medical role receives no automatic access to training or development data.
- `ANALYST` and `SCOUT` can read development goals and assessments; `SPORTS_SCIENTIST` and `MEDICAL_STAFF` do not inherit that access.
- `PLAYER` accounts can read only the training, availability, goals, and assessments of their linked player profile. They cannot modify official records or create assessments.

The authenticated user is assigned as session creator, availability recorder, goal creator, and assessment author by the server. Those attribution fields cannot be set or impersonated through request bodies.

Example training-session request:

```powershell
$session = @{
	team_id = "<team-uuid>"
	session_date = "2026-10-01"
	start_time = "10:00:00"
	end_time = "11:30:00"
	session_type = "TECHNICAL"
	objective = "Passing patterns"
	planned_intensity = 6
	planned_duration_minutes = 90
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/training/sessions -Headers $headers -ContentType "application/json" -Body $session
```

Rate limiting is not configured in this backend; apply it at the API gateway/reverse proxy as a production hardening step. There are no uploads or payment/webhook endpoints in this phase.

Example requests in PowerShell:

```powershell
$body = @{ email = "player@example.com"; full_name = "Alex Player"; password = "secure-password-123" } | ConvertTo-Json
$registered = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/register -ContentType "application/json" -Body $body
$token = $registered.access_token
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/me -Headers $headers
```

An administrator may update another account using a JSON body such as `{"is_active":false}` at `/api/v1/users/{user_id}/status`, or `{"role":"ANALYST"}` at `/api/v1/users/{user_id}/role`. Admins cannot deactivate themselves or change their own role, preventing accidental self-lockout; the last active admin cannot be removed.

## Database migrations

The initial migration creates the user and role tables and seeds the supported roles. Phase 02 migration `0002_user_profile` backfills existing users' `full_name` from their email, adds `updated_at`, and constrains the role catalog. Phase 03 migrations `0003_squad_domain` and `0004_distinct_positions` create the squad domain and prevent duplicate player positions. Phase 04 migration `0005_phase04_domains` adds training, participation, availability, goal, and assessment tables. Downgrade Phase 04 with `alembic downgrade 0004_distinct_positions`; prior migration history remains intact.

```powershell
alembic upgrade head
alembic downgrade 0004_distinct_positions
```

## Tests and lint

Tests use isolated in-memory SQLite and do not access the configured development database.

```powershell
pytest
ruff check .
ruff format --check .
```

The current test suite covers Phase 01 health/auth, Phase 02 RBAC, Phase 03 squad management, and Phase 04 training, operational availability, development history, authorization, and player self-access.

## Club Memory RAG

- `POST /api/v1/memory/rag/query` answers a question from governed Club Memory. Every request passes authenticated user → governed retrieval → context builder → LLM provider → deterministic claim verification.
- Retrieval only returns memories the caller is authorized to see; redacted, expired, and unauthorized memories never enter LLM context. No production LLM provider is configured: requests fail closed with `503` until one is wired (tests override the provider dependency with a deterministic fake).
- When retrieval yields no usable evidence, the endpoint honestly returns an empty answer with grounding status `INSUFFICIENT_EVIDENCE` instead of generating fallback content.
- Production rate limiting remains a deployment concern: no rate-limit mechanism exists in this codebase yet.

Not implemented: medical records, injury prediction, performance prediction, match intelligence, computer vision, tactical AI, production LLM/vector-search integrations, AI agents, and counterfactual simulation. The RAG query endpoint exists with deterministic claim verification but has no production LLM provider wired.

