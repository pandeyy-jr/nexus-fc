import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi import status as http_status

from app.ai.copilot.models import CopilotRequest, CopilotResponse
from app.ai.copilot.openai_provider import build_copilot_provider
from app.ai.copilot.provider import ModelProvider, ModelProviderUnavailable
from app.ai.copilot.registry import build_default_registry
from app.ai.copilot.service import CopilotService
from app.api.dependencies import CurrentUser, SessionDependency
from app.core.config import get_settings
from app.core.rate_limit import (
    RateLimiter,
    build_copilot_rate_limiter,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Request-scoped rate limiter (built once at startup)
_copilot_rate_limiter: RateLimiter | None = None


def get_copilot_rate_limiter() -> RateLimiter:
    """Get or create the copilot rate limiter."""
    global _copilot_rate_limiter
    if _copilot_rate_limiter is None:
        _copilot_rate_limiter = build_copilot_rate_limiter()
    return _copilot_rate_limiter


def get_copilot_provider() -> ModelProvider:
    """Model provider seam. Builds the configured OpenAI-compatible
    adapter; without credentials requests fail closed with 503.
    Tests override this dependency with a deterministic fake."""
    try:
        return build_copilot_provider(get_settings())
    except ModelProviderUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Copilot model provider is not configured",
        ) from exc


@router.post("/copilot/query", response_model=CopilotResponse)
async def post_copilot_query(
    request: Request,
    response: Response,
    body: CopilotRequest,
    session: SessionDependency,
    actor: CurrentUser,
    provider: Annotated[ModelProvider, Depends(get_copilot_provider)],
    rate_limiter: Annotated[RateLimiter, Depends(get_copilot_rate_limiter)],
) -> CopilotResponse:
    """Governed Copilot question answering. The actor comes from JWT;
    the request carries no role, identity, permissions, or context.
    All tool execution flows through the registry with that actor, and
    budgets/grounding are enforced by the service."""
    # Rate limit by authenticated actor (server-derived identity)
    rate_key = f"copilot:{actor.id}"
    rate_limiter.check_limit(rate_key)

    # Request ID for traceability - server-generated for trust
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id

    logger.info(
        "copilot request started",
        extra={
            "request_id": request_id,
            "actor_id": str(actor.id),
            "actor_role": actor.role.name,
            "question_len": len(body.question),
        },
    )

    try:
        service = CopilotService(build_default_registry(), provider)
        result = await service.ask(session, actor, body)
        rate_limiter.record_hit(rate_key)

        logger.info(
            "copilot request completed",
            extra={
                "request_id": request_id,
                "actor_id": str(actor.id),
                "actor_role": actor.role.name,
                "tool_calls": result.tool_call_count,
                "tools_used": result.tools_used,
                "grounded": result.grounded,
                "error": result.error or "",
            },
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "copilot request failed",
            extra={
                "request_id": request_id,
                "actor_id": str(actor.id),
                "actor_role": actor.role.name,
                "error_category": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error",
        ) from exc
