from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import (
    ASSISTANT_PLAYER_FIELDS,
    PLAYER_DELETE_ROLES,
    PLAYER_UPDATE_ROLES,
    PLAYER_VIEW_ROLES,
)
from app.core.roles import RoleName
from app.db.models.player import Player
from app.db.models.user import User
from app.repositories import players
from app.schemas.players import PlayerCreate, PlayerUpdate


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


async def list_players(session: AsyncSession, actor: User) -> list[Player]:
    if actor.role.name == RoleName.PLAYER:
        return await players.list_players(session, user_id=actor.id)
    if actor.role.name not in PLAYER_VIEW_ROLES:
        raise _forbidden()
    return await players.list_players(session)


async def get_player(session: AsyncSession, player_id: UUID, actor: User) -> Player:
    player = await players.get_by_id(session, player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if actor.role.name == RoleName.PLAYER:
        if player.user_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
            )
    elif actor.role.name not in PLAYER_VIEW_ROLES:
        raise _forbidden()
    return player


async def _validate_player_user(
    session: AsyncSession, user_id: UUID | None, current_player_id: UUID | None = None
) -> None:
    if user_id is None:
        return
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.role.name != RoleName.PLAYER:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="A player profile can only link to a PLAYER account",
        )
    existing = await players.get_by_user_id(session, user_id)
    if existing is not None and existing.id != current_player_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is already linked to a player profile",
        )


async def create_player(session: AsyncSession, payload: PlayerCreate) -> Player:
    await _validate_player_user(session, payload.user_id)
    data = payload.model_dump()
    if data["profile_photo_url"] is not None:
        data["profile_photo_url"] = str(data["profile_photo_url"])
    player = Player(**data)
    session.add(player)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player profile conflicts with an existing record",
        ) from exc
    await session.refresh(player)
    return player


async def update_player(
    session: AsyncSession, player_id: UUID, payload: PlayerUpdate, actor: User
) -> Player:
    if actor.role.name not in PLAYER_UPDATE_ROLES:
        raise _forbidden()
    changed_fields = payload.model_fields_set
    if actor.role.name == RoleName.ASSISTANT_COACH and not changed_fields.issubset(
        ASSISTANT_PLAYER_FIELDS
    ):
        raise _forbidden()

    player = await players.get_by_id(session, player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )

    data = payload.model_dump(exclude_unset=True)
    preferred_position = data.get("preferred_position", player.preferred_position)
    secondary_position = data.get("secondary_position", player.secondary_position)
    if secondary_position is not None and secondary_position == preferred_position:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Secondary position must differ from preferred position",
        )
    if "user_id" in data:
        await _validate_player_user(
            session, data["user_id"], current_player_id=player.id
        )
    if "profile_photo_url" in data and data["profile_photo_url"] is not None:
        data["profile_photo_url"] = str(data["profile_photo_url"])
    for field, value in data.items():
        setattr(player, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player profile conflicts with an existing record",
        ) from exc
    await session.refresh(player)
    return player


async def delete_player(session: AsyncSession, player_id: UUID) -> None:
    player = await players.get_by_id(session, player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if await players.has_memberships(
        session, player_id
    ) or await players.has_phase04_records(session, player_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player profiles with historical records cannot be deleted",
        )
    await session.delete(player)
    await session.commit()


def can_delete_player(actor: User) -> bool:
    return actor.role.name in PLAYER_DELETE_ROLES
