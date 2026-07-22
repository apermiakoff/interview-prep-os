from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.ai.config import AIConfig, AIConfigError


@dataclass(frozen=True)
class ProviderResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw_finish_reason: str | None = None


@dataclass(frozen=True)
class ProviderChunk:
    """Normalized text delta or final usage/result metadata."""

    text: str = ""
    result: ProviderResult | None = None


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


class Gateway(Protocol):
    async def complete(self, *, system: str, user: str, max_tokens: int) -> ProviderResult: ...

    def stream(
        self, *, system: str, user: str, max_tokens: int
    ) -> AsyncIterator[ProviderChunk]: ...


class HTTPGateway:
    # Safe complete-response fallback is explicit for every built-in protocol.
    # Provider-specific streaming can be added without changing the worker contract.
    streaming_mode = "complete-only"

    def __init__(self, config: AIConfig):
        self.config = config

    def _pinned_endpoint(self, suffix: str, address: object) -> tuple[str, str, str]:
        parsed = urlsplit(self.config.base_url)
        hostname = parsed.hostname or ""
        default_port = 443 if parsed.scheme == "https" else 80
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None and parsed.port != default_port:
            host_header = f"{host_header}:{parsed.port}"
        literal = str(address)
        literal = f"[{literal}]" if ":" in literal else literal
        if parsed.port is not None:
            literal = f"{literal}:{parsed.port}"
        path = f"{parsed.path.rstrip('/')}/{suffix.lstrip('/')}"
        return urlunsplit((parsed.scheme, literal, path, "", "")), host_header, hostname

    async def complete(self, *, system: str, user: str, max_tokens: int) -> ProviderResult:
        # Resolve and enforce target policy immediately before every request and
        # before constructing any credential-bearing headers.
        try:
            address = self.config.resolve_request_address()
        except AIConfigError as exc:
            raise ProviderError("target_rejected", "provider target rejected") from exc
        provider = self.config.provider
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if provider == "anthropic":
            headers.update(
                {"x-api-key": self.config.api_key or "", "anthropic-version": "2023-06-01"}
            )
            endpoint, host_header, sni_hostname = self._pinned_endpoint("messages", address)
            body: dict[str, Any] = {
                "model": self.config.model,
                "system": system,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": user}],
            }
        elif provider == "ollama":
            endpoint, host_header, sni_hostname = self._pinned_endpoint("api/chat", address)
            body = {
                "model": self.config.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {"num_predict": max_tokens},
            }
        else:
            headers["Authorization"] = f"Bearer {self.config.api_key or ''}"
            endpoint, host_header, sni_hostname = self._pinned_endpoint("chat/completions", address)
            body = {
                "model": self.config.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        try:
            headers["Host"] = host_header
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    extensions={"sni_hostname": sni_hostname},
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            transient = (
                exc.response.status_code in {408, 409, 429} or exc.response.status_code >= 500
            )
            raise ProviderError(
                f"http_{exc.response.status_code}", "provider request failed", transient=transient
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("transport", "provider transport error", transient=True) from exc
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                "invalid_response", "provider returned an invalid response"
            ) from exc
        try:
            if provider == "anthropic":
                text = "".join(
                    item["text"] for item in payload["content"] if item.get("type") == "text"
                )
                usage = payload.get("usage", {})
                result = ProviderResult(
                    text,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    payload.get("stop_reason"),
                )
            elif provider == "ollama":
                usage = payload
                result = ProviderResult(
                    payload["message"]["content"],
                    usage.get("prompt_eval_count", 0),
                    usage.get("eval_count", 0),
                    payload.get("done_reason"),
                )
            else:
                usage = payload.get("usage", {})
                choice = payload["choices"][0]
                result = ProviderResult(
                    choice["message"]["content"],
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    choice.get("finish_reason"),
                )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "invalid_response", "provider returned an invalid response"
            ) from exc
        if not isinstance(result.text, str) or not result.text.strip():
            raise ProviderError("invalid_response", "provider returned no usable text")
        return result

    async def stream(
        self, *, system: str, user: str, max_tokens: int
    ) -> AsyncIterator[ProviderChunk]:
        result = await self.complete(system=system, user=user, max_tokens=max_tokens)
        if result.text:
            yield ProviderChunk(text=result.text)
        yield ProviderChunk(result=result)
