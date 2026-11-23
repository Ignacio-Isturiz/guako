import json

import groq
from pydantic import BaseModel, SecretStr

from app.llm.base import BaseLLMProvider, RawCompletion
from app.llm.errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class GroqProvider(BaseLLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        temperature: float,
        timeout_seconds: float,
        max_retries: int = 2,
    ) -> None:
        super().__init__(max_retries=max_retries)
        self.model = model
        self._temperature = temperature
        # SDK-level retries are disabled: our own loop owns retry policy, and
        # SDK retries on 429 would hide quota errors and multiply latency.
        self._client = groq.Groq(api_key=api_key.get_secret_value(), timeout=timeout_seconds, max_retries=0)

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        # json_object guarantees valid JSON (syntax, not schema), so the
        # schema goes in the system message and Pydantic validates the result.
        schema = json.dumps(response_model.model_json_schema())
        system_message = (system + "\n\n" if system else "") + (
            "Respond ONLY with a JSON object matching this JSON schema:\n" + schema
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
        except groq.AuthenticationError as exc:
            raise LLMAuthError("Groq rejected the API key") from exc
        except groq.PermissionDeniedError as exc:
            raise LLMAuthError("Groq denied access") from exc
        except groq.RateLimitError as exc:
            raise LLMRateLimitError("Groq quota or rate limit exceeded") from exc
        except groq.APITimeoutError as exc:
            raise LLMTimeoutError("Groq timed out") from exc
        except groq.APIError as exc:
            raise LLMProviderError(f"Groq request failed: {type(exc).__name__}") from exc

        usage = response.usage
        return RawCompletion(
            text=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
