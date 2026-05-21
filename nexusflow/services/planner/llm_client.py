from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from nexusflow.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def estimated_cost_usd(self) -> float:
        COST_PER_TOKEN: Dict[str, Dict[str, float]] = {
            "gpt-4o": {"in": 5.0 / 1_000_000, "out": 15.0 / 1_000_000},
            "gpt-4o-mini": {"in": 0.15 / 1_000_000, "out": 0.60 / 1_000_000},
            "gpt-3.5-turbo": {"in": 0.5 / 1_000_000, "out": 1.5 / 1_000_000},
        }
        pricing = COST_PER_TOKEN.get(self.model, {"in": 0.01 / 1000, "out": 0.03 / 1000})
        return (self.tokens_in * pricing["in"]) + (self.tokens_out * pricing["out"])


class LLMClient:
    """Async LLM client supporting OpenAI and OpenAI-compatible local providers."""

    def __init__(self) -> None:
        self._settings = get_settings().llm
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self._settings.provider in ("openai", "local"):
            from openai import AsyncOpenAI

            base_url = (
                self._settings.local_base_url
                if self._settings.provider == "local"
                else self._settings.openai_base_url
            )
            api_key = (
                "local-key"
                if self._settings.provider == "local"
                else self._settings.openai_api_key
            )
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self._settings.provider}")

        return self._client

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> str:
        """Return the response text for a completion request."""
        response = await self.complete_with_metadata(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        return response.content

    async def complete_with_metadata(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Full completion with token tracking and exponential backoff on rate limits."""
        resolved_model = model or (
            self._settings.local_model
            if self._settings.provider == "local"
            else self._settings.openai_model
        )

        client = await self._get_client()
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                usage = response.usage

                return LLMResponse(
                    content=content,
                    tokens_in=usage.prompt_tokens if usage else 0,
                    tokens_out=usage.completion_tokens if usage else 0,
                    model=resolved_model,
                    provider=self._settings.provider,
                )

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    delay = 2 ** attempt
                    logger.warning(
                        "LLM rate limited (attempt %d/%d), retrying in %ds",
                        attempt, max_retries, delay
                    )
                    await asyncio.sleep(delay)
                elif attempt == max_retries:
                    logger.error("LLM call failed after %d attempts: %s", max_retries, e)
                    raise
                else:
                    logger.warning("LLM call failed (attempt %d): %s", attempt, e)
                    await asyncio.sleep(1)

        raise RuntimeError("LLM client exhausted retries")
