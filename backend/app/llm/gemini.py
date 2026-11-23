from google import genai
from google.genai import errors, types
from pydantic import BaseModel, SecretStr

from app.llm.base import BaseLLMProvider, RawCompletion
from app.llm.errors import (
    LLMAuthError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

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
        # google-genai expects the timeout in milliseconds.
        self._client = genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    def _complete(self, prompt: str, system: str | None, response_model: type[BaseModel]) -> RawCompletion:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            response_mime_type="application/json",
            response_schema=response_model,
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise LLMAuthError("Gemini rejected the API key") from exc
            if exc.code == 429:
                raise LLMRateLimitError("Gemini quota or rate limit exceeded") from exc
            raise LLMProviderError(f"Gemini request failed with status {exc.code}") from exc
        except errors.APIError as exc:
            if exc.code == 504:
                raise LLMTimeoutError("Gemini timed out") from exc
            raise LLMProviderError(f"Gemini request failed with status {exc.code}") from exc
        except Exception as exc:  # httpx timeouts / network errors are not APIError
            if "timeout" in type(exc).__name__.lower():
                raise LLMTimeoutError("Gemini timed out") from exc
            raise LLMProviderError(f"Gemini call failed: {type(exc).__name__}") from exc

        usage = response.usage_metadata
        return RawCompletion(
            text=response.text or "",
            prompt_tokens=usage.prompt_token_count if usage else None,
            completion_tokens=usage.candidates_token_count if usage else None,
        )
