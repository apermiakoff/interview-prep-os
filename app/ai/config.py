from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import ParseResult, urlparse


class AIConfigError(ValueError):
    pass


def _secret(name: str) -> str | None:
    file_value = os.getenv(f"{name}_FILE")
    if file_value:
        try:
            return Path(file_value).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise AIConfigError(f"cannot read {name}_FILE") from exc
    return os.getenv(name) or None


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def resolved_addresses(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """Resolve every address, failing closed. Called at config and immediately pre-request."""
    try:
        return (ipaddress.ip_address(host),)
    except ValueError:
        try:
            records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except (socket.gaierror, OSError) as exc:
            raise AIConfigError("AI base URL host could not be resolved") from exc
    addresses = tuple({ipaddress.ip_address(record[4][0]) for record in records})
    if not addresses:
        raise AIConfigError("AI base URL host could not be resolved")
    return addresses


def _forbidden_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # is_global also excludes unspecified, reserved, multicast and documentation ranges.
    return not address.is_global


_CANONICAL_HOSTS = {"openai": "api.openai.com", "anthropic": "api.anthropic.com"}


def _parsed_base_url(value: str, *, provider: str, allowed_hosts: frozenset[str]) -> ParseResult:
    """Validate URL and exact-host policy without performing DNS."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AIConfigError("AI base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AIConfigError("credentials are forbidden in AI base URLs")
    host = parsed.hostname.lower()
    if host.endswith("."):
        raise AIConfigError("AI base URL hosts must be canonical exact names")
    canonical = _CANONICAL_HOSTS.get(provider)
    if canonical and (
        parsed.scheme != "https" or host != canonical or parsed.port not in {None, 443}
    ):
        raise AIConfigError(f"{provider} requires its canonical HTTPS host")
    if provider == "openai_compatible" and host not in allowed_hosts:
        raise AIConfigError("openai_compatible host is not in INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS")
    return parsed


def validate_base_url(
    value: str,
    *,
    provider: str,
    allow_private: bool,
    allowed_hosts: frozenset[str] = frozenset(),
) -> str:
    parsed = _parsed_base_url(value, provider=provider, allowed_hosts=allowed_hosts)
    host = parsed.hostname.lower()  # type: ignore[union-attr]
    addresses = resolved_addresses(host)
    if (
        provider != "ollama"
        and not allow_private
        and any(_forbidden_address(address) for address in addresses)
    ):
        raise AIConfigError("private or non-public AI base addresses are forbidden")
    return value.rstrip("/")


_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://127.0.0.1:11434",
}


REQUEST_PROTOCOL_OVERHEAD_TOKENS = 256


def estimate_tokens(*values: str) -> int:
    """Hard local input bound: all rendered UTF-8 bytes plus fixed protocol overhead."""
    return sum(len(value.encode("utf-8")) for value in values) + REQUEST_PROTOCOL_OVERHEAD_TOKENS


def estimate_output_tokens(value: str) -> int:
    """Conservative tokenizer-independent fallback when output usage is absent."""
    return max(1, len(value.encode("utf-8")))


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    provider: str
    model: str
    base_url: str
    api_key: str | None
    db_path: Path
    max_input_tokens: int
    max_output_tokens: int
    monthly_token_budget: int
    max_retries: int
    lease_seconds: int
    allow_private_base_url: bool
    allowed_base_hosts: frozenset[str]

    @classmethod
    def from_env(cls) -> AIConfig:
        enabled = _boolean("INTERVIEW_PREP_AI_ENABLED")
        provider = os.getenv("INTERVIEW_PREP_AI_PROVIDER", "ollama").lower()
        if provider not in {"openai", "anthropic", "openai_compatible", "ollama"}:
            raise AIConfigError("unsupported AI provider")
        raw_url = os.getenv("INTERVIEW_PREP_AI_BASE_URL") or _DEFAULT_URLS.get(provider)
        if not raw_url:
            if enabled:
                raise AIConfigError("INTERVIEW_PREP_AI_BASE_URL is required")
            raw_url = "https://disabled.invalid"
        allow_private = _boolean("INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL")
        allowed_hosts = frozenset(
            item.strip().lower()
            for item in os.getenv("INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS", "").split(",")
            if item.strip()
        )
        base_url = validate_base_url(
            raw_url,
            provider=provider,
            allow_private=allow_private,
            allowed_hosts=allowed_hosts,
        )
        api_key = _secret("INTERVIEW_PREP_AI_API_KEY")
        if enabled and provider in {"openai", "anthropic", "openai_compatible"} and not api_key:
            raise AIConfigError("AI provider API key is required")
        values = {
            "max_input_tokens": int(os.getenv("INTERVIEW_PREP_AI_MAX_INPUT_TOKENS", "12000")),
            "max_output_tokens": int(os.getenv("INTERVIEW_PREP_AI_MAX_OUTPUT_TOKENS", "2048")),
            "monthly_token_budget": int(
                os.getenv("INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET", "1000000")
            ),
            "max_retries": int(os.getenv("INTERVIEW_PREP_AI_MAX_RETRIES", "2")),
            "lease_seconds": int(os.getenv("INTERVIEW_PREP_AI_LEASE_SECONDS", "60")),
        }
        if any(value < 0 for value in values.values()) or values["lease_seconds"] < 1:
            raise AIConfigError("AI limits must be non-negative and lease must be positive")
        return cls(
            enabled=enabled,
            provider=provider,
            model=os.getenv("INTERVIEW_PREP_AI_MODEL", "llama3.2"),
            base_url=base_url,
            api_key=api_key,
            db_path=Path(os.getenv("INTERVIEW_PREP_AI_DB", "/ai-data/interview-prep-ai.db")),
            allow_private_base_url=allow_private,
            allowed_base_hosts=allowed_hosts,
            **values,
        )

    def resolve_request_address(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        """Resolve once immediately pre-request and return one validated address to pin."""
        parsed = _parsed_base_url(
            self.base_url, provider=self.provider, allowed_hosts=self.allowed_base_hosts
        )
        addresses = resolved_addresses(parsed.hostname or "")
        if (
            self.provider != "ollama"
            and not self.allow_private_base_url
            and any(_forbidden_address(address) for address in addresses)
        ):
            raise AIConfigError("private or non-public AI base addresses are forbidden")
        # IPv6 is supported by the gateway's bracketed literal connection URL.
        return sorted(addresses, key=lambda address: (address.version, int(address)))[0]

    def masked(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "credential_configured": bool(self.api_key),
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "monthly_token_budget": self.monthly_token_budget,
        }
