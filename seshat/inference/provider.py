"""Provider-agnostic LLM interface.

"local" talks to an Ollama server (fully local, the default per Seshat.md §4);
"api" talks to any OpenAI-compatible chat-completions endpoint for users who
prefer quality over privacy. Both are stdlib-only (urllib), so no SDK deps.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from seshat.config import SeshatConfig

OLLAMA_DEFAULT_URL = "http://localhost:11434"
TIMEOUT_SECONDS = 600  # an 8B model on a busy consumer box can be slow


class GenerationError(Exception):
    """Raised when the provider is unreachable or returns garbage."""


class LLMProvider(Protocol):
    model_version: str

    def generate(self, prompt: str) -> str: ...


def _post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise GenerationError(f"LLM request to {url} failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GenerationError(f"LLM at {url} returned invalid JSON: {exc}") from exc


class OllamaProvider:
    def __init__(self, model: str, base_url: str = "") -> None:
        self._model = model
        self._base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
        self.model_version = f"ollama/{model}"

    def generate(self, prompt: str) -> str:
        result = _post_json(
            f"{self._base_url}/api/generate",
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
        )
        if "response" not in result:
            raise GenerationError(f"Unexpected Ollama response: {result.get('error', result)}")
        return result["response"]


class OpenAICompatProvider:
    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        if not base_url:
            raise GenerationError(
                "provider = \"api\" needs a base_url in seshat.toml [inference] "
                "or the SESHAT_API_BASE environment variable."
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_version = f"api/{model}"

    def generate(self, prompt: str) -> str:
        result = _post_json(
            f"{self._base_url}/chat/completions",
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
        )
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerationError(f"Unexpected API response: {result}") from exc


def get_provider(config: SeshatConfig) -> LLMProvider:
    inference = config.inference
    if inference.provider == "local":
        return OllamaProvider(inference.model, inference.base_url)
    return OpenAICompatProvider(
        inference.model,
        inference.base_url or os.environ.get("SESHAT_API_BASE", ""),
        os.environ.get("SESHAT_API_KEY", ""),
    )
