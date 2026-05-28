"""litellm router — primary + single fallback per (tier, call_site)."""

from __future__ import annotations

import logging
import os
from typing import Any

import litellm
from pydantic import BaseModel, ValidationError

from shared_harness import llm_config
from shared_harness.cost_tracker import BudgetExceededError, check_budget, record_cost
from shared_harness.llm_parse import parse_model

logger = logging.getLogger(__name__)

_INFRA_ERRORS: tuple[type[BaseException], ...] = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.InternalServerError,
)


class AllProvidersFailed(Exception):
    """All LLM providers failed for this call."""


_fallback_disabled_runtime: bool = False


def reset_fallback_state() -> None:
    """Reset runtime fallback state (for tests)."""
    global _fallback_disabled_runtime
    _fallback_disabled_runtime = False


def _fallback_available(model: str) -> bool:
    if _fallback_disabled_runtime:
        return False
    if model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
        return False
    return True


def _provider_from_model(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else "unknown"


def _completion_kwargs(cfg: llm_config.TierConfig, tier: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if tier == 1 and cfg.reasoning_effort:
        kwargs["reasoning_effort"] = cfg.reasoning_effort
    return kwargs


def _estimate_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    return (tokens_in + tokens_out) * 0.000001


def _invoke(
    model: str,
    messages: list[dict[str, str]],
    tier: int,
    max_tokens: int,
    *,
    force_json: bool = False,
) -> tuple[str, int, int]:
    cfg = llm_config.resolve_tier(tier)
    extra = _completion_kwargs(cfg, tier)
    if force_json:
        extra["response_format"] = {"type": "json_object"}
    response = litellm.completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        **extra,
    )
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
    return content, tokens_in, tokens_out


def _attempt(
    *,
    model: str,
    messages: list[dict[str, str]],
    tier: int,
    call_site: str,
    attempt: str,
    run_id: str | None,
    task_type: str,
    max_tokens: int,
    schema: type[BaseModel] | None,
    force_json: bool = False,
) -> str | BaseModel:
    check_budget(run_id, task_type=task_type, before_call=True)
    raw, tin, tout = _invoke(model, messages, tier, max_tokens, force_json=force_json)
    record_cost(
        run_id=run_id,
        tier=tier,
        provider=_provider_from_model(model),
        model=model,
        call_site=call_site,
        attempt=attempt,
        tokens_in=tin,
        tokens_out=tout,
        usd=_estimate_usd(model, tin, tout),
    )
    check_budget(run_id, task_type=task_type)
    if schema is None:
        return raw
    return parse_model(raw, schema)


_MAX_PRIMARY_RETRIES = 2


def complete(
    *,
    tier: int,
    call_site: str,
    messages: list[dict[str, str]],
    schema: type[BaseModel] | None = None,
    run_id: str | None = None,
    task_type: str = "agent",
    max_tokens: int = 1024,
) -> str | BaseModel:
    cfg = llm_config.resolve_tier(tier)
    use_json_mode = schema is not None
    json_nudge = [{"role": "user", "content": "Respond with valid JSON only. No markdown fences."}]

    last_exc: Exception | None = None
    for attempt_num in range(_MAX_PRIMARY_RETRIES):
        msgs = messages if attempt_num == 0 else messages + json_nudge
        try:
            return _attempt(
                model=cfg.primary,
                messages=msgs,
                tier=tier,
                call_site=call_site,
                attempt="primary",
                run_id=run_id,
                task_type=task_type,
                max_tokens=max_tokens,
                schema=schema,
                force_json=use_json_mode or (attempt_num > 0),
            )
        except BudgetExceededError:
            raise
        except ValidationError as exc:
            last_exc = exc
            logger.warning(
                "Primary %s attempt %d/%d validation failed: %s",
                cfg.primary, attempt_num + 1, _MAX_PRIMARY_RETRIES, exc,
            )
            continue
        except _INFRA_ERRORS as exc:
            last_exc = exc
            logger.warning("Primary %s infra error: %s", cfg.primary, exc)
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("Primary %s unexpected error (%s): %s", cfg.primary, type(exc).__name__, exc)
            break

    if not llm_config.fallback_enabled() or not _fallback_available(cfg.fallback):
        raise AllProvidersFailed(
            f"Primary {cfg.primary} failed ({type(last_exc).__name__}: {last_exc}); "
            f"fallback={'disabled' if not llm_config.fallback_enabled() else 'unavailable'}"
        )

    try:
        return _attempt(
            model=cfg.fallback,
            messages=messages,
            tier=tier,
            call_site=call_site,
            attempt="fallback",
            run_id=run_id,
            task_type=task_type,
            max_tokens=max_tokens,
            schema=schema,
        )
    except BudgetExceededError:
        raise
    except Exception as exc:
        global _fallback_disabled_runtime
        if "402" in str(exc) or "Insufficient credits" in str(exc):
            _fallback_disabled_runtime = True
            logger.warning("Fallback auto-disabled (no credits): %s", exc)
        raise AllProvidersFailed(str(exc)) from exc
