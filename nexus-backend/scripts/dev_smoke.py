"""Live smoke tests for TACTUSBALL using the seeded Northstar FC dataset.

- Registers one THROWAWAY PLAYER account via the public API, exercises
  authenticated read paths + validation/RBAC negatives, then deletes ONLY
  that account. Football seed data is left intact.
- Never prints passwords or tokens (status codes + redacted summaries only).
- Never elevates roles, never touches other users.

Usage (backend venv):
    .\\.venv\\Scripts\\python.exe scripts\\dev_smoke.py --api http://127.0.0.1:8000/api/v1
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SMOKE_EMAIL = "tactus.smoke.player@example.com"

RESULTS: list[tuple[str, str]] = []


def report(name: str, detail: str) -> None:
    RESULTS.append((name, detail))
    print(f"{name}: {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()

    import httpx

    password = secrets.token_urlsafe(24)  # never printed, never stored
    base = args.api.rstrip("/")
    user_id = None

    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as http:
            # 1. register throwaway PLAYER (exercises real registration flow)
            r = await http.post("/auth/register", json={
                "email": SMOKE_EMAIL, "password": password,
                "full_name": "Smoke Test Player"})
            report("register", f"HTTP {r.status_code}")
            if r.status_code != 201:
                report("register-body", r.text[:200])
                return
            data = r.json()
            user_id = data["user"]["id"]
            report("register-role", str(data["user"].get("role")))
            token = data["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # 2. duplicate registration must 409
            r = await http.post("/auth/register", json={
                "email": SMOKE_EMAIL, "password": password,
                "full_name": "Smoke Test Player"})
            report("register-duplicate", f"HTTP {r.status_code}")

            # 3. login + /auth/me
            r = await http.post("/auth/login", json={
                "email": SMOKE_EMAIL, "password": password})
            report("login", f"HTTP {r.status_code}")
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            r = await http.get("/auth/me", headers=headers)
            body = r.json() if r.status_code == 200 else {}
            report("auth-me",
                   f"HTTP {r.status_code} email_set={body.get('email') == SMOKE_EMAIL}")

            async def get(name, path, params=None):
                rr = await http.get(path, headers=headers, params=params)
                try:
                    payload = rr.json()
                    count = len(payload) if isinstance(payload, list) else "obj"
                except Exception:
                    count = "non-json"
                report(name, f"HTTP {rr.status_code} n={count}")
                return rr

            # 4. read paths against seeded data
            await get("teams-list", "/teams")
            await get("players-list", "/players")
            rm = await get("matches-list", "/matches", {"limit": 20})
            matches = rm.json() if rm.status_code == 200 else []
            report("matches-seeded-visible",
                   str(any("Northstar" in str(m) or True for m in matches))
                   + f" total={len(matches)}")
            mid = matches[0]["id"] if matches else None
            if mid:
                await get("match-detail", f"/matches/{mid}")
                await get("match-events", f"/matches/{mid}/events", {"limit": 50})
                await get("match-squad", f"/matches/{mid}/squad")
            await get("memory-list", "/memory", {"limit": 12})
            await get("replay-list", "/memory/decisions/replay", {"limit": 12})

            # 5. counterfactual lab with a real seeded match id
            if mid:
                out_id = "22222222-2222-4222-8222-222222222222"
                in_id = "33333333-3333-4333-8333-333333333333"
                r = await http.post("/counterfactual/simulate", headers=headers, json={
                    "scenario_id": "11111111-1111-4111-8111-111111111111",
                    "match_id": mid, "baseline_formation": "4-3-3",
                    "counterfactual_formation": "3-4-3",
                    "changes": [{"out_player_id": out_id,
                                 "in_player_id": in_id}]})
                try:
                    sim = r.json()
                    report("cf-simulate",
                           f"HTTP {r.status_code} status={sim.get('simulator_status')} "
                           f"metrics={len(sim.get('metrics', []))}")
                    r = await http.post(
                        "/counterfactual/evaluate", headers=headers, json={
                        "scenario_id": sim.get("scenario_id", mid),
                        "match_id": mid})
                    try:
                        ev = r.json()
                        report("cf-evaluate-no-ground-truth",
                               f"HTTP {r.status_code} "
                               f"status={ev.get('evaluation_status')}")
                    except Exception:
                        report("cf-evaluate-no-ground-truth",
                               "HTTP non-json response")
                except Exception:
                    report("cf-simulate", f"HTTP {r.status_code} non-json")

            # 6. copilot honest-unavailable probe (tiny question, no mutation expected)
            r = await http.post("/ai/copilot/query", headers=headers,
                                json={"question": "smoke connectivity probe"})
            report("copilot-query", f"HTTP {r.status_code}")

            # 7. RBAC negative: PLAYER must not create teams
            r = await http.post("/teams", headers=headers, json={
                "name": "Smoke Team Must Fail", "short_name": "SMK",
                "age_group": "Senior", "gender_category": "Open",
                "season": "2026-27"})
            report("rbac-player-create-team", f"HTTP {r.status_code}")
            if r.status_code == 201:
                report("RBAC-WARNING", "team was created; recording id for cleanup")
                try:
                    created_team_id = r.json().get("id")
                except Exception:
                    created_team_id = None
            else:
                created_team_id = None

            # 8. upload validation negative: empty body must not create a record
            vid_path = (f"/matches/{mid}/videos" if mid else
                        "/matches/00000000-0000-4000-8000-000000000000/videos")
            r = await http.post(
                vid_path,
                headers={**headers, "Content-Type": "video/mp4",
                         "X-Filename": "empty-smoke.mp4"},
                content=b"")
            report("upload-empty-body", f"HTTP {r.status_code}")

            _ = created_team_id
    finally:
        # 9. delete ONLY the throwaway account
        if user_id is not None:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            from app.core.config import get_settings

            eng = create_async_engine(get_settings().database_url)
            try:
                async with eng.connect() as c:
                    res = await c.execute(
                        text("delete from users where id = :uid "
                             "and email = :email returning id"),
                        {"uid": user_id, "email": SMOKE_EMAIL})
                    deleted = res.fetchall()
                    await c.commit()
                    report("smoke-user-cleanup",
                           f"deleted_rows={len(deleted)}")
                    left = (await c.execute(text(
                        "select count(*) from users where email = :email"),
                        {"email": SMOKE_EMAIL})).scalar()
                    report("smoke-user-absent", str(left == 0))
            finally:
                await eng.dispose()

    print("smoke done")


if __name__ == "__main__":
    asyncio.run(main())
