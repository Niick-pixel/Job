"""Cliente de IA: una única puerta de entrada a Claude con salidas estructuradas.

Todas las funciones de negocio piden un modelo Pydantic y reciben una
instancia validada, así el resto del código nunca parsea JSON a mano.
"""
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from ..config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def structured(self, *, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T: ...


class AnthropicLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None, effort: str | None = None):
        settings = get_settings()
        # Sin api_key explícita el SDK busca ANTHROPIC_API_KEY o un perfil de `ant auth login`.
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.llm_model
        self.effort = effort or settings.llm_effort

    def structured(self, *, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T:
        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": self.effort},
                # Si un clasificador de seguridad rechaza la petición, la API la
                # reintenta automáticamente en el modelo de respaldo recomendado.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("ANTHROPIC_API_KEY inválida o ausente") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Límite de peticiones alcanzado; reintenta en unos segundos") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Error de la API de Claude ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("No se pudo conectar con la API de Claude") from e

        if response.stop_reason == "refusal":
            raise LLMError("El modelo rechazó la petición")
        if response.stop_reason == "max_tokens":
            raise LLMError("Respuesta truncada: aumenta max_tokens")
        if response.parsed_output is None:
            raise LLMError("La respuesta no cumplió el esquema esperado")
        return response.parsed_output


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    """Dependencia FastAPI (sobrescribible en tests)."""
    global _llm
    if _llm is None:
        _llm = AnthropicLLM()
    return _llm
