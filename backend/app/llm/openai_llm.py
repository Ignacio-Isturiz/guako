import json

import openai
from pydantic import BaseModel, SecretStr

from app.llm.base import BaseLLMProvider, RawCompletion
from app.llm.errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.providers.util import retry_after_seconds

# Reasoning-family models only accept the default temperature.
_FIXED_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat completions with JSON output. Paid: tracked against the spending cap by the router."""

    name = "openai"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        temperature: float,
        timeout_seconds: float,
        max_retries: int = 2,
        client: openai.OpenAI | None = None,
    ) -> None:
        super().__init__(max_retries=max_retries)
        self.model = model
        self._temperature = temperature
        # SDK-level retries are off: our own loop owns retry policy, and a hidden retry on 429 would
        # hide quota errors from the router and multiply latency.
        self._client = client or openai.OpenAI(api_key=api_key.get_secret_value(), timeout=timeout_seconds, max_retries=0)

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        schema = json.dumps(response_model.model_json_schema())
        system_message = (system + "\n\n" if system else "") + (
            "Respond ONLY with a JSON object matching this JSON schema:\n" + schema
        )
        options = {} if self.model.startswith(_FIXED_TEMPERATURE_PREFIXES) else {"temperature": self._temperature}
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                **options,
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise LLMAuthError("OpenAI rejected the API key or denied access") from exc
        except openai.RateLimitError as exc:
            # "insufficient_quota" = the account is out of credit: waiting a minute will not help.
            out_of_credit = getattr(exc, "code", None) == "insufficient_quota"
            raise LLMRateLimitError(
                "OpenAI quota or rate limit exceeded", retry_after=retry_after_seconds(exc), quota=out_of_credit
            ) from exc
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI timed out") from exc
        except openai.APIError as exc:
            raise LLMProviderError(f"OpenAI request failed: {type(exc).__name__}") from exc

        usage = response.usage
        return RawCompletion(
            text=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
