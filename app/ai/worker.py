from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from contextlib import suppress

from app.ai.ai_db import connect, migrate, now, transaction
from app.ai.artifacts import parse_artifact, prompt
from app.ai.config import AIConfig, estimate_output_tokens
from app.ai.gateway import Gateway, ProviderChunk, ProviderError, ProviderResult
from app.ai.providers import provider_gateway
from app.ai.repository import add_event, claim, renew_lease


class StaleClaim(RuntimeError):
    """The lease was reclaimed; all output from this generation is discarded."""


class Worker:
    EVENT_COALESCE_CHARS = 32
    EVENT_COALESCE_SECONDS = 0.2

    def __init__(self, config: AIConfig, gateway: Gateway | None = None, owner: str | None = None):
        self.config = config
        self.gateway = gateway or provider_gateway(config)
        self.owner = owner or f"worker-{uuid.uuid4()}"

    async def run_once(self) -> bool:
        with transaction(self.config.db_path) as connection:
            run = claim(connection, self.owner, self.config.lease_seconds)
        if not run:
            return False
        try:
            with connect(self.config.db_path) as connection:
                snapshot_row = connection.execute(
                    "SELECT content_json FROM context_snapshots WHERE id=?",
                    (run["context_snapshot_id"],),
                ).fetchone()
                current = connection.execute(
                    "SELECT cancel_requested FROM runs WHERE id=?", (run["id"],)
                ).fetchone()
            if not snapshot_row or not current:
                raise RuntimeError("claimed run data is missing")
            if current["cancel_requested"]:
                self._cancel(run)
                return True
            snapshot = json.loads(snapshot_row["content_json"])
            request = json.loads(run["request_json"])
            system, user = prompt(run["kind"], snapshot, request)
            result = await self._generate_with_renewal(run, system, user)
            result = self._validated_result(result)
            content: str | dict
            if run["kind"] == "chat":
                content = result.text
            else:
                content = parse_artifact(run["kind"], result.text, snapshot)
            self._finalize(run, result, content)
        except StaleClaim:
            # A newer claim generation owns the run. Never mutate it.
            pass
        except ProviderError as exc:
            self._failure(run, exc.code, str(exc), exc.transient)
        except ValueError:
            self._failure(run, "invalid_artifact", "provider returned an invalid artifact", False)
        except Exception:
            # Per-claim boundary: normalize unexpected adapter/SQLite/finalization
            # failures without exposing exception text or stranding the run.
            self._failure(run, "internal_error", "AI run failed internally", False)
        return True

    @staticmethod
    def _validated_result(result: ProviderResult) -> ProviderResult:
        if not isinstance(result, ProviderResult):
            raise ProviderError("invalid_response", "provider returned an invalid response")
        if not isinstance(result.text, str) or not result.text.strip():
            raise ProviderError("invalid_response", "provider returned no usable text")
        return result

    async def _generate_with_renewal(self, run: dict, system: str, user: str) -> ProviderResult:
        stop = asyncio.Event()
        lost = asyncio.Event()
        renewer = asyncio.create_task(self._renew_loop(run, stop, lost))
        try:
            result = await self._generate(run, system, user)
            if lost.is_set() or not self._owns(run):
                raise StaleClaim
            return result
        finally:
            stop.set()
            renewer.cancel()
            with suppress(asyncio.CancelledError):
                await renewer

    async def _renew_loop(self, run: dict, stop: asyncio.Event, lost: asyncio.Event) -> None:
        interval = max(0.05, self.config.lease_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                with transaction(self.config.db_path) as connection:
                    renewed = renew_lease(
                        connection,
                        run["id"],
                        self.owner,
                        run["claim_generation"],
                        self.config.lease_seconds,
                    )
                if not renewed:
                    lost.set()
                    return

    def _owns(self, run: dict) -> bool:
        with connect(self.config.db_path) as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM runs WHERE id=? AND status='running' AND lease_owner=? "
                    "AND claim_generation=?",
                    (run["id"], self.owner, run["claim_generation"]),
                ).fetchone()
            )

    async def _generate(self, run: dict, system: str, user: str) -> ProviderResult:
        stream = getattr(self.gateway, "stream", None)
        if not callable(stream):
            result = await self.gateway.complete(
                system=system, user=user, max_tokens=self.config.max_output_tokens
            )
            result = self._validated_result(result)
            self._text_event(run, result.text)
            return result

        pieces: list[str] = []
        pending = ""
        last_flush = time.monotonic()
        final: ProviderResult | None = None
        async for chunk in stream(
            system=system, user=user, max_tokens=self.config.max_output_tokens
        ):
            if not isinstance(chunk, ProviderChunk) or not isinstance(chunk.text, str):
                raise ProviderError("invalid_response", "provider returned an invalid stream")
            if chunk.text:
                pieces.append(chunk.text)
                pending += chunk.text
            if pending and (
                len(pending) >= self.EVENT_COALESCE_CHARS
                or time.monotonic() - last_flush >= self.EVENT_COALESCE_SECONDS
                or chunk.result is not None
            ):
                self._text_event(run, pending)
                pending = ""
                last_flush = time.monotonic()
            if chunk.result is not None:
                final = self._validated_result(chunk.result)
        if pending:
            self._text_event(run, pending)
        text = "".join(pieces)
        if not text.strip():
            raise ProviderError("invalid_response", "provider returned no usable text")
        if final is None:
            return ProviderResult(text)
        if final.text == text:
            return final
        return ProviderResult(
            text, final.input_tokens, final.output_tokens, final.raw_finish_reason
        )

    def _text_event(self, run: dict, text: str) -> None:
        if not text:
            return
        with transaction(self.config.db_path) as connection:
            if not self._owns_in(connection, run):
                raise StaleClaim
            add_event(
                connection,
                run["id"],
                "text",
                {"text": text},
                run["claim_generation"],
            )

    def _owns_in(self, connection, run: dict) -> bool:
        return bool(
            connection.execute(
                "SELECT 1 FROM runs WHERE id=? AND status='running' AND lease_owner=? "
                "AND claim_generation=?",
                (run["id"], self.owner, run["claim_generation"]),
            ).fetchone()
        )

    def _finalize(self, run: dict, result: ProviderResult, content: str | dict) -> None:
        input_tokens = (
            result.input_tokens if result.input_tokens > 0 else run["estimated_input_tokens"]
        )
        output_tokens = (
            result.output_tokens
            if result.output_tokens > 0
            else estimate_output_tokens(result.text)
        )
        total = input_tokens + output_tokens
        with transaction(self.config.db_path) as connection:
            if not self._owns_in(connection, run):
                raise StaleClaim
            cancelled = connection.execute(
                "SELECT cancel_requested FROM runs WHERE id=?", (run["id"],)
            ).fetchone()["cancel_requested"]
            if cancelled:
                self._cancel_in(connection, run)
                return
            if run["kind"] == "chat":
                connection.execute(
                    "INSERT INTO messages(id,conversation_id,role,content,idempotency_key,"
                    "run_id,created_at) "
                    "VALUES(?,?, 'assistant', ?,NULL,?,?)",
                    (str(uuid.uuid4()), run["conversation_id"], content, run["id"], now()),
                )
            else:
                artifact_id = str(uuid.uuid4())
                version = connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 value FROM artifacts "
                    "WHERE scope=? AND scope_id=? AND kind=?",
                    (run["scope"], run["scope_id"], run["kind"]),
                ).fetchone()["value"]
                connection.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        run["scope"],
                        run["scope_id"],
                        run["kind"],
                        version,
                        run["schema_version"],
                        json.dumps(content),
                        run["id"],
                        run["context_snapshot_id"],
                        run["prompt_version"],
                        run["provider"],
                        run["model"],
                        now(),
                    ),
                )
                if run["cache_key"]:
                    connection.execute(
                        "INSERT OR REPLACE INTO cache_entries VALUES(?,?,?,NULL)",
                        (run["cache_key"], artifact_id, now()),
                    )
                if run["kind"] == "diagnosis":
                    for hypothesis in content["hypotheses"]:
                        hypothesis_id = str(uuid.uuid4())
                        connection.execute(
                            "INSERT INTO learning_hypotheses VALUES(?,?,?,?,?,?,?)",
                            (
                                hypothesis_id,
                                artifact_id,
                                hypothesis["type"],
                                hypothesis["status"],
                                hypothesis["confidence"],
                                hypothesis["statement"],
                                now(),
                            ),
                        )
                        for evidence in hypothesis["evidence"]:
                            connection.execute(
                                "INSERT INTO hypothesis_evidence VALUES(?,?)",
                                (hypothesis_id, evidence["id"]),
                            )
            connection.execute(
                "INSERT INTO usage_ledger VALUES(?,?,?,?,?,?,?,NULL,?)",
                (
                    str(uuid.uuid4()),
                    run["id"],
                    run["provider"],
                    run["model"],
                    input_tokens,
                    output_tokens,
                    total,
                    now(),
                ),
            )
            add_event(
                connection,
                run["id"],
                "usage",
                {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total,
                },
                run["claim_generation"],
            )
            updated = connection.execute(
                "UPDATE runs SET status='completed',lease_owner=NULL,lease_until=NULL,"
                "reserved_tokens=0,updated_at=?,completed_at=? WHERE id=? AND status='running' "
                "AND lease_owner=? AND claim_generation=?",
                (now(), now(), run["id"], self.owner, run["claim_generation"]),
            )
            if not updated.rowcount:
                raise StaleClaim
            add_event(
                connection,
                run["id"],
                "completed",
                {"status": "completed"},
                run["claim_generation"],
            )

    def _failure(self, run: dict, code: str, message: str, transient: bool) -> None:
        retry = transient and run["attempts"] < run["max_attempts"]
        try:
            with transaction(self.config.db_path) as connection:
                if not self._owns_in(connection, run):
                    return
                status = "queued" if retry else "failed"
                updated = connection.execute(
                    "UPDATE runs SET status=?,lease_owner=NULL,lease_until=NULL,error_code=?,"
                    "error_message=?,reserved_tokens=CASE WHEN ?='queued' "
                    "THEN reserved_tokens ELSE 0 END,"
                    "updated_at=? WHERE id=? AND status='running' AND lease_owner=? "
                    "AND claim_generation=?",
                    (
                        status,
                        code[:80],
                        message[:500],
                        status,
                        now(),
                        run["id"],
                        self.owner,
                        run["claim_generation"],
                    ),
                )
                if not updated.rowcount:
                    return
                if retry:
                    connection.execute(
                        "DELETE FROM run_events WHERE run_id=? AND event_type='text' "
                        "AND claim_generation=?",
                        (run["id"], run["claim_generation"]),
                    )
                add_event(
                    connection,
                    run["id"],
                    "retry" if retry else "failed",
                    {"code": code[:80]},
                    run["claim_generation"],
                )
        except Exception:
            # A persistent database outage cannot be repaired here; a transient
            # finalization error is handled by the second independent transaction.
            return

    def _cancel(self, run: dict) -> None:
        with transaction(self.config.db_path) as connection:
            if self._owns_in(connection, run):
                self._cancel_in(connection, run)

    def _cancel_in(self, connection, run: dict) -> None:
        updated = connection.execute(
            "UPDATE runs SET status='cancelled',lease_owner=NULL,lease_until=NULL,"
            "reserved_tokens=0,"
            "updated_at=?,completed_at=? WHERE id=? AND status='running' AND lease_owner=? "
            "AND claim_generation=?",
            (now(), now(), run["id"], self.owner, run["claim_generation"]),
        )
        if not updated.rowcount:
            raise StaleClaim
        add_event(
            connection,
            run["id"],
            "cancelled",
            {"status": "cancelled"},
            run["claim_generation"],
        )


async def serve(config: AIConfig, poll_seconds: float = 0.5) -> None:
    migrate(config.db_path)
    worker = Worker(config)
    while True:
        worked = await worker.run_once()
        if not worked:
            await asyncio.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = AIConfig.from_env()
    if not config.enabled:
        print("Community AI is disabled; worker not started.")
        return
    migrate(config.db_path)
    if args.once:
        asyncio.run(Worker(config).run_once())
    else:
        asyncio.run(serve(config))


if __name__ == "__main__":
    main()
