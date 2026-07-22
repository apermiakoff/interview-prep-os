#!/usr/bin/env python3
"""Configure the local community stack without exposing credentials in argv or env."""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

PROVIDERS = {"ollama", "openai", "anthropic", "openai_compatible"}
DEFAULT_URLS = {
    "ollama": "http://host.docker.internal:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Create .env.community and a mode-0600 AI secret")
    value.add_argument("--non-interactive", action="store_true")
    value.add_argument("--enable-ai", action="store_true")
    value.add_argument("--provider", choices=sorted(PROVIDERS))
    value.add_argument("--model")
    value.add_argument("--base-url")
    key_source = value.add_mutually_exclusive_group()
    key_source.add_argument(
        "--api-key-file",
        type=Path,
        help="read the API key from this file (use '-' to read stdin); never pass a key in argv",
    )
    key_source.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="read the API key from stdin",
    )
    value.add_argument("--monthly-token-budget", type=int, default=100_000)
    value.add_argument("--port", type=int, default=8765)
    value.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return value


def _single_line(name: str, value: str) -> str:
    if any(character in value for character in "\r\n\0"):
        raise ValueError(f"{name} must be a single line")
    return value


def _read_key(args: argparse.Namespace) -> str | None:
    if args.api_key_stdin or args.api_key_file == Path("-"):
        key = sys.stdin.read()
    elif args.api_key_file is not None:
        source = args.api_key_file.expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError("--api-key-file must be a regular file, not a symlink")
        key = source.read_text(encoding="utf-8")
    else:
        return None
    key = key.removesuffix("\n").removesuffix("\r")
    if not key:
        raise ValueError("API key input is empty")
    return _single_line("API key", key)


def _atomic_write(path: Path, content: str, mode: int) -> None:
    """Replace a configuration file without a world-readable creation window."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        temporary.unlink(missing_ok=True)


def configure(args: argparse.Namespace) -> tuple[Path, Path]:
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("--root must be an existing directory")
    enabled = args.enable_ai
    provider = args.provider
    model = args.model
    base_url = args.base_url
    key = _read_key(args)
    if not args.non_interactive:
        enabled = input("Enable optional AI? [y/N] ").strip().lower() in {"y", "yes"}
        if enabled:
            provider = input("Provider (ollama/openai/anthropic/openai_compatible): ").strip()
            model = input("Model: ").strip()
            base_url = input(f"Base URL [{DEFAULT_URLS.get(provider, '')}]: ").strip() or None
            if provider != "ollama":
                key = getpass.getpass("API key (stored only in a mode-0600 file): ")
    provider = provider or "ollama"
    if provider not in PROVIDERS:
        raise ValueError("unsupported provider")
    if enabled and not model:
        raise ValueError("--model is required when AI is enabled")
    model = _single_line("model", model or "")
    base_url = base_url or DEFAULT_URLS.get(provider)
    if enabled and not base_url:
        raise ValueError("--base-url is required for openai_compatible")
    base_url = _single_line("base URL", base_url or "https://disabled.invalid")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL may not contain credentials, query, or fragment")
    if provider == "openai" and base_url.rstrip("/") != DEFAULT_URLS["openai"]:
        raise ValueError("OpenAI uses canonical https://api.openai.com/v1")
    if provider == "anthropic" and base_url.rstrip("/") != DEFAULT_URLS["anthropic"]:
        raise ValueError("Anthropic uses canonical https://api.anthropic.com/v1")
    if args.monthly_token_budget < 1:
        raise ValueError("monthly token budget must be positive")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")

    secret_dir = root / ".community-secrets"
    if secret_dir.is_symlink():
        raise ValueError(".community-secrets may not be a symlink")
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    if not secret_dir.is_dir():
        raise ValueError(".community-secrets must be a directory")
    os.chmod(secret_dir, 0o700)
    secret_path = secret_dir / "ai_api_key"
    if secret_path.is_symlink():
        raise ValueError("AI secret destination may not be a symlink")

    # Reconfiguration without a new key preserves the existing credential. This prevents
    # an ordinary core-only setup/update from silently destroying a configured AI key.
    existing_key: str | None = None
    if secret_path.exists():
        if not stat.S_ISREG(secret_path.stat().st_mode):
            raise ValueError("AI secret destination must be a regular file")
        existing_key = secret_path.read_text(encoding="utf-8")
    effective_key = key if key is not None else existing_key
    if enabled and provider != "ollama" and not effective_key:
        raise ValueError("an API key is required; use --api-key-file or --api-key-stdin")

    if key is not None or existing_key is None:
        _atomic_write(secret_path, key or "", 0o600)
    else:
        os.chmod(secret_path, 0o600)

    allowed_host = parsed.hostname if provider == "openai_compatible" else ""
    private = provider in {"ollama", "openai_compatible"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
    }
    env_path = root / ".env.community"
    lines = [
        f"INTERVIEW_PREP_PORT={args.port}",
        f"INTERVIEW_PREP_AI_ENABLED={'true' if enabled else 'false'}",
        f"INTERVIEW_PREP_AI_PROVIDER={provider}",
        f"INTERVIEW_PREP_AI_MODEL={model}",
        f"INTERVIEW_PREP_AI_BASE_URL={base_url.rstrip('/')}",
        "INTERVIEW_PREP_AI_API_KEY_FILE=./.community-secrets/ai_api_key",
        f"INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET={args.monthly_token_budget}",
        f"INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL={'true' if private else 'false'}",
        f"INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS={allowed_host}",
        "INTERVIEW_PREP_ALLOWED_HOSTS=",
        "INTERVIEW_PREP_ALLOWED_ORIGINS=",
    ]
    _atomic_write(env_path, "\n".join(lines) + "\n", 0o600)
    return env_path, secret_path


def main() -> int:
    args = parser().parse_args()
    try:
        env_path, secret_path = configure(args)
    except (OSError, UnicodeError, ValueError) as exc:
        parser().error(str(exc))
    profile = " --profile ai" if args.enable_ai else ""
    print(f"Created {env_path} and protected secret file {secret_path} (key not displayed).")
    print("Ollama is not bundled; Docker reaches a host installation via host.docker.internal.")
    print(
        f"Next: docker compose --env-file {env_path} "
        f"-f compose.community.yaml{profile} up -d --build"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
