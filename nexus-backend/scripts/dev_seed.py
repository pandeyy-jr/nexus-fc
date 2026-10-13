"""Development-only illustrative seed data for TACTUSBALL smoke testing.

Fictional club dataset (Northstar FC) created through the existing service
layer, so all validation, relationships, and transactions apply.

Safety properties:
- Runs only when --target-database matches the connected database name.
- Idempotent: existing rows are found by natural key and reused, never
  overwritten. Re-running is safe.
- Never touches users/roles, never migrates, never drops/truncates.
- Never creates administrators or bypasses RBAC. Match/event writes act
  as the operator's own ADMIN account (--admin-email), so created_by
  provenance stays truthful.
- --cleanup deletes ONLY rows found by the same natural keys, in reverse
  FK order. Anything not matching the seed keys is left alone.

Usage (from nexus-backend/, project venv):
    .\\.venv\\Scripts\\python.exe scripts\\dev_seed.py --target-database DB
    .\\.venv\\Scripts\\python.exe scripts\\dev_seed.py --target-database DB --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

MARKER = "[SEED DEMO] Illustrative fixture for smoke testing only."

PLAYERS = [
    # (slug, first, last, dob, preferred, secondary, squad_number)
    ("gk-01", "Arjun", "Mehta", "1996-03-14", "GK", None, 1),
    ("cb-01", "Kabir", "Rao", "1998-07-02", "CB", "DM", 2),
    ("cb-02", "Dev", "Patel", "1999-11-30", "CB", None, 4),
    ("lb-01", "Ishaan", "Verma", "2000-01-19", "LB", "LWB", 3),
    ("rb-01", "Nikhil", "Bose", "1997-05-25", "RB", None, 5),
    ("dm-01", "Rohan", "Iyer", "1998-09-08", "DM", "CM", 6),
    ("cm-01", "Aditya", "Nair", "2001-02-11", "CM", None, 8),
    ("am-01", "Vikram", "Shah", "1999-06-17", "AM", "RW", 10),
    ("lw-01", "Karan", "Malhotra", "2000-12-03", "LW", "ST", 11),
    ("st-01", "Sanjay", "Kulkarni", "1997-08-22", "ST", "CF", 9),
]

STARTERS = {"gk-01", "cb-01", "cb-02", "lb-01", "rb-01", "dm-01", "cm-01"}
CAPTAIN = "cb-01"
SUB_MINUTES = {"am-01": (60, 90, 30), "lw-01": (65, 90, 25), "st-01": (70, 90, 20)}


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed illustrative Northstar FC data.")
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--admin-email", default="adi260807@gmail.com")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            actual = (await conn.execute(text("select current_database()"))).scalar()
        print(f"target_database={actual}")
        if actual != args.target_database:
            print("ABORT: connected database does not match --target-database")
            return
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            if args.cleanup:
                await cleanup(session)
            else:
                await seed(session, args.admin_email)
    finally:
        await engine.dispose()


async def seed(session, admin_email: str) -> None:
    from app.repositories import (
        match_catalog,
        matches,
        memberships,
        users,
    )
    from app.repositories import (
        players as player_repo,
    )
    from app.repositories import (
        teams as team_repo,
    )
    from app.schemas.match_catalog import (
        CompetitionCreate,
        OpponentCreate,
        VenueCreate,
    )
    from app.schemas.match_events import (
        MatchEventCreate,
        MatchParticipationCreate,
        MatchSquadCreate,
    )
    from app.schemas.matches import MatchCreate
    from app.schemas.memberships import MembershipCreate
    from app.schemas.players import PlayerCreate
    from app.schemas.teams import TeamCreate
    from app.services import match_catalog as catalog_svc
    from app.services import matches as matches_svc
    from app.services import memberships as memberships_svc
    from app.services import players as players_svc
    from app.services import teams as teams_svc

    admin = await users.get_by_email(session, admin_email)
    if admin is None:
        print(f"ABORT: admin account {admin_email} not found")
        return
    print(f"actor={admin.email} (writes attributed to operator account)")

    created = {"total": 0}
    skipped = {"total": 0}

    def mark(was_created: bool, label: str) -> None:
        if was_created:
            created["total"] += 1
            print(f"created {label}")
        else:
            skipped["total"] += 1

    # --- catalog ---
    comps = await match_catalog.list_competitions(session, 100, 0)
    comp = next((c for c in comps if c.name == "Demo Development League"
                 and c.season == "2026-27"), None)
    if comp is None:
        comp = await catalog_svc.create_competition(session, CompetitionCreate(
            name="Demo Development League", short_name="DDL",
            competition_type="LEAGUE", season="2026-27"))
        mark(True, "competition Demo Development League")
    else:
        mark(False, "competition Demo Development League")

    opps = await match_catalog.list_opponents(session, 100, 0)
    opp = next((o for o in opps if o.name == "Riverside United"), None)
    if opp is None:
        opp = await catalog_svc.create_opponent(session, OpponentCreate(
            name="Riverside United", short_name="RUFC"))
        mark(True, "opponent Riverside United")
    else:
        mark(False, "opponent Riverside United")

    venues = await match_catalog.list_venues(session, 100, 0)
    venue = next((v for v in venues if v.name == "Northstar Training Ground"), None)
    if venue is None:
        venue = await catalog_svc.create_venue(session, VenueCreate(
            name="Northstar Training Ground", capacity=1500))
        mark(True, "venue Northstar Training Ground")
    else:
        mark(False, "venue Northstar Training Ground")

    # --- team ---
    all_teams = await team_repo.list_teams(session)
    team = next((t for t in all_teams if t.name == "Northstar FC"
                 and t.season == "2026-27"), None)
    if team is None:
        team = await teams_svc.create_team(session, TeamCreate(
            name="Northstar FC", short_name="NFC", age_group="Senior",
            gender_category="Open", season="2026-27"))
        mark(True, "team Northstar FC")
    else:
        mark(False, "team Northstar FC")

    # --- players + memberships ---
    existing_players = await player_repo.list_players(session)
    player_by_key = {(p.first_name, p.last_name, str(p.date_of_birth)): p
                     for p in existing_players}
    player_ids: dict[str, object] = {}
    for slug, first, last, dob, pref, sec, number in PLAYERS:
        key = (first, last, dob)
        player = player_by_key.get(key)
        if player is None:
            player = await players_svc.create_player(session, PlayerCreate(
                first_name=first, last_name=last,
                date_of_birth=date.fromisoformat(dob),
                preferred_position=pref, secondary_position=sec,
                squad_number=number))
            mark(True, f"player {first} {last}")
        else:
            mark(False, f"player {first} {last}")
        player_ids[slug] = player.id
        current = await memberships.get_current(session, team.id, player.id)
        if current is None:
            await memberships_svc.create_membership(
                session, team.id, player.id,
                MembershipCreate(joined_at=dt("2026-07-01T00:00:00+00:00")))
            mark(True, f"membership {slug}")
        else:
            mark(False, f"membership {slug}")

    # --- matches ---
    existing_matches = await matches.list_matches(session, None, None, None,
                                                  None, None, 100, 0)
    match_ids: dict[str, object] = {}

    def find_match(opponent_id, scheduled):
        for m in existing_matches:
            if (m.team_id == team.id and m.opponent_id == opponent_id
                    and m.scheduled_at == scheduled):
                return m
        return None

    sched_done = dt("2026-10-04T15:00:00+00:00")
    m1 = find_match(opp.id, sched_done)
    if m1 is None:
        m1 = await matches_svc.create_match(session, MatchCreate(
            team_id=team.id, opponent_id=opp.id, competition_id=comp.id,
            venue_id=venue.id, scheduled_at=sched_done,
            actual_start_at=dt("2026-10-04T15:02:00+00:00"),
            actual_end_at=dt("2026-10-04T16:47:00+00:00"),
            home_away="HOME", status="COMPLETED", matchday=1,
            season="2026-27", home_score=2, away_score=1,
            notes=f"{MARKER} League opener vs Riverside United."), admin)
        mark(True, "match 2026-10-04 vs Riverside United")
    else:
        mark(False, "match 2026-10-04 vs Riverside United")
    match_ids["done"] = m1.id

    sched_next = dt("2026-10-18T15:00:00+00:00")
    m2 = find_match(opp.id, sched_next)
    if m2 is None:
        m2 = await matches_svc.create_match(session, MatchCreate(
            team_id=team.id, opponent_id=opp.id, competition_id=comp.id,
            venue_id=venue.id, scheduled_at=sched_next,
            home_away="HOME", status="SCHEDULED", matchday=2,
            season="2026-27",
            notes=f"{MARKER} Upcoming league fixture."), admin)
        mark(True, "match 2026-10-18 vs Riverside United")
    else:
        mark(False, "match 2026-10-18 vs Riverside United")
    match_ids["next"] = m2.id

    # --- squads + participations (completed match) ---
    squad_rows = await matches.list_squad(session, m1.id)
    squad_by_player = {s.player_id: s for s in squad_rows}
    for slug, _f, _l, _d, _p, _s, number in PLAYERS:
        pid = player_ids[slug]
        row = squad_by_player.get(pid)
        if row is None:
            row = await matches_svc.add_squad_player(session, m1.id, MatchSquadCreate(
                player_id=pid,
                squad_status="STARTER" if slug in STARTERS else "SUBSTITUTE",
                shirt_number=number,
                starting=slug in STARTERS,
                captain=(slug == CAPTAIN)))
            mark(True, f"squad {slug} (completed match)")
        else:
            mark(False, f"squad {slug} (completed match)")
        minutes = (0, 90, 90) if slug in STARTERS else SUB_MINUTES.get(slug)
        if minutes is not None:
            part = await matches.get_participation(session, row.id)
            if part is None:
                await matches_svc.create_participation(
                    session, m1.id, pid, MatchParticipationCreate(
                        started_at_minute=minutes[0], ended_at_minute=minutes[1],
                        minutes_played=minutes[2]))
                mark(True, f"participation {slug}")
            else:
                mark(False, f"participation {slug}")

    # --- squad (upcoming match, no participations) ---
    squad_rows2 = await matches.list_squad(session, m2.id)
    squad_by_player2 = {s.player_id: s for s in squad_rows2}
    for slug, _f, _l, _d, _p, _s, number in PLAYERS:
        pid = player_ids[slug]
        if pid not in squad_by_player2:
            await matches_svc.add_squad_player(session, m2.id, MatchSquadCreate(
                player_id=pid, squad_status="SELECTED", shirt_number=number))
            mark(True, f"squad {slug} (upcoming match)")
        else:
            mark(False, f"squad {slug} (upcoming match)")

    # --- events (completed match only; illustrative, schema-validated) ---
    existing_events = await matches.list_events(session, m1.id, 100, 0)
    wanted = [
        ("KICK_OFF", 0, "NEUTRAL", None, None, "Illustrative kick-off marker."),
        ("GOAL", 23, "HOME", "st-01", "am-01", "Illustrative goal."),
        ("YELLOW_CARD", 55, "HOME", "dm-01", None, "Illustrative booking."),
        ("FULL_TIME", 90, "NEUTRAL", None, None, "Illustrative full-time marker."),
    ]
    for etype, minute, side, scorer, assist, desc in wanted:
        pid = player_ids[scorer] if scorer else None
        aid = player_ids[assist] if assist else None
        dup = any(e.event_type.value == etype and e.minute == minute
                  and e.player_id == pid for e in existing_events)
        if dup:
            mark(False, f"event {etype} {minute}'")
            continue
        await matches_svc.create_event(session, m1.id, MatchEventCreate(
            side=side, player_id=pid, assist_player_id=aid,
            event_type=etype, minute=minute, description=desc), admin)
        mark(True, f"event {etype} {minute}'")

    print(f"seed done: created={created['total']} skipped={skipped['total']}")


async def cleanup(session) -> None:

    from app.repositories import (
        match_catalog,
        matches,
        memberships,
    )
    from app.repositories import (
        players as player_repo,
    )
    from app.repositories import (
        teams as team_repo,
    )

    removed = {"total": 0}

    async def drop(obj, label: str) -> None:
        await session.delete(obj)
        removed["total"] += 1
        print(f"removed {label}")

    # resolve seed rows by the same natural keys used at creation
    all_matches = await matches.list_matches(session, None, None, None,
                                             None, None, 200, 0)
    seed_matches = [m for m in all_matches
                    if (m.notes or "").startswith(MARKER)]
    for m in seed_matches:
        for e in await matches.list_events(session, m.id, 500, 0):
            await drop(e, f"event {e.id}")
        for s in await matches.list_squad(session, m.id):
            part = await matches.get_participation(session, s.id)
            if part is not None:
                await drop(part, f"participation {part.id}")
            await drop(s, f"squad row {s.id}")
        await drop(m, f"match {m.id}")

    all_teams = await team_repo.list_teams(session)
    team = next((t for t in all_teams if t.name == "Northstar FC"
                 and t.season == "2026-27"), None)
    if team is not None:
        for mem in await memberships.list_for_team(session, team.id, False):
            await drop(mem, f"membership {mem.id}")
        await drop(team, "team Northstar FC")

    existing_players = await player_repo.list_players(session)
    wanted_names = {(f, ln) for _, f, ln, _, _, _, _ in PLAYERS}
    for p in existing_players:
        if (p.first_name, p.last_name) in wanted_names:
            await drop(p, f"player {p.first_name} {p.last_name}")

    for c in await match_catalog.list_competitions(session, 100, 0):
        if c.name == "Demo Development League" and c.season == "2026-27":
            await drop(c, "competition Demo Development League")
    for o in await match_catalog.list_opponents(session, 100, 0):
        if o.name == "Riverside United":
            await drop(o, "opponent Riverside United")
    for v in await match_catalog.list_venues(session, 100, 0):
        if v.name == "Northstar Training Ground":
            await drop(v, "venue Northstar Training Ground")

    await session.commit()
    print(f"cleanup done: removed={removed['total']}")


if __name__ == "__main__":
    asyncio.run(main())
