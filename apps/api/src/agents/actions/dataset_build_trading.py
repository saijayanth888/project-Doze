"""``dataset.build_trading`` — orchestrate Stage 1 + Stage 2 of the trading-bot
data pipeline for a single track, then read ``curator_result.json`` to determine
success.

This action is the Sunday workflow's entry point. It does NOT train — it only
ensures the curated Arrow shard + test-set JSONL exist and meet the N_MIN gate.
The downstream ``evolution.start`` step handles training; the per-action
``condition: {last_action_status: ok}`` gate ensures it only fires when the
data pipeline succeeds.

Execution model
---------------
1. Validate ``track_id`` is one of the 6 trading tracks. Reject early if not.
2. Probe ``TRADEBOT_DATABASE_URL`` connectivity via ``SELECT 1``. If unreachable,
   return ``status="error"`` with ``reason="tradebot_db_unreachable"``. This
   prevents silent subprocess failures when the trading-bot Postgres is down.
3. Subprocess: ``python3 /app/trading-bot/scripts/modelforge_ingest.py
   --role-filter <track_id> --since <ingest_date>``.
4. Subprocess: ``python3 /app/trading-bot/scripts/modelforge_curate.py
   --role-filter <track_id>``.
5. Read ``<dgx_train_root>/datasets/<track_id>/curator_result.json``. If the file
   is missing OR ``status != "ok"``, return ``status="error"`` with the curator
   stderr captured.
6. On success: return ``status="ok"`` with ``records_count``, ``test_set_path``,
   ``curated_path``, ``track_id``.

Failure modes
-------------
* ``tradebot_db_unreachable`` — connectivity probe failed. Operator must check
  the trading-bot Postgres container.
* ``ingest_failed`` — subprocess exited non-zero. ``ingest_stderr`` in output.
* ``curate_failed`` — subprocess exited non-zero. ``curate_stderr`` in output.
* ``curator_result_missing`` — curator_result.json not found after both stages.
* ``curator_result_insufficient_data`` — curator returned ``insufficient_data``
  (N_MIN gate not met). Normal production state for new tracks.
* ``curator_result_error`` — curator returned ``error`` (datasets lib missing,
  disk error, etc.). Check ``curate_stderr`` for root cause.

Container setup
---------------
The trading-bot scripts live at ``/app/trading-bot/scripts/`` via a read-only
bind-mount: ``~/Documents/trading-bot/scripts:/app/trading-bot/scripts:ro``.
The env block MUST include ``TRADEBOT_DATABASE_URL``.
Both ``pandas`` and ``psycopg2-binary`` must be installed (they are in
``requirements.txt``). ``asyncpg`` is already present.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from services.automation_engine.actions import Action, ActionResult, register_action

logger = logging.getLogger("modelforge.automation.actions.dataset_build_trading")

# Canonical set of trading track IDs. Keep in sync with modelforge_curate.py::ALL_ROLES.
_VALID_TRACK_IDS: frozenset[str] = frozenset({
    "trading-reflector",
    "trading-bull",
    "trading-bear",
    "trading-arbiter",
    "trading-regime-tagger",
    "trading-indicator-selector",
})

_INGEST_SCRIPT = "/app/trading-bot/scripts/modelforge_ingest.py"
_CURATE_SCRIPT = "/app/trading-bot/scripts/modelforge_curate.py"


def _probe_db(db_url: str) -> bool:
    """Execute ``SELECT 1`` against *db_url* synchronously via psycopg2.

    Returns ``True`` when reachable. Never raises — caller interprets ``False``
    as unreachable and surfaces ``tradebot_db_unreachable``.
    """
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError:
        logger.error("[build-trading] psycopg2 not installed — cannot probe DB")
        return False
    try:
        conn = psycopg2.connect(db_url, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True
    except Exception as exc:
        logger.warning("[build-trading] DB probe failed: %s", exc)
        return False


class BuildTradingDataset(Action):
    """Orchestrate Stage 1 (ingest) + Stage 2 (curate) for one trading track.

    On success, ``output`` carries the curator_result.json fields the downstream
    ``evolution.start`` action needs (``test_set_path``, ``records_count``,
    ``curated_path``, ``track_id``).
    """

    kind = "dataset.build_trading"
    label = "Build Trading Dataset"
    description = (
        "Run modelforge_ingest + modelforge_curate for one trading track. "
        "Reads curator_result.json to determine success / failure. "
        "Chain with evolution.start using condition={last_action_status: ok} "
        "to ensure training only fires when data meets the N_MIN gate."
    )
    schema = [
        {
            "name": "track_id",
            "type": "select",
            "label": "Track ID",
            "required": True,
            "options": sorted(_VALID_TRACK_IDS),
            "help": "One of the 6 trading track IDs. Must match a role in modelforge_curate.py::ALL_ROLES.",
        },
        {
            "name": "ingest_date",
            "type": "string",
            "label": "Ingest date",
            "default": "yesterday",
            "help": "ISO date (YYYY-MM-DD), 'yesterday', or 'all'. Passed as --since to modelforge_ingest.py.",
        },
        {
            "name": "dgx_train_root",
            "type": "string",
            "label": "DGX train root",
            "default": "/app/data/dgx-train",
            "help": "Root of the .dgx-train layout (bind-mounted from host ~/Documents/.dgx-train).",
        },
        {
            "name": "decisions_md_path",
            "type": "string",
            "label": "decisions.md path (optional)",
            "default": "",
            "help": "Override the default decisions.md path passed to modelforge_ingest.py via --decisions-md.",
        },
        {
            "name": "llm_calls_path",
            "type": "string",
            "label": "llm-calls.jsonl path (optional)",
            "default": "",
            "help": "Override the default llm-calls.jsonl path passed to modelforge_ingest.py via --llm-calls.",
        },
    ]

    async def execute(self, *, config, context, engine):  # noqa: ARG002
        track_id = str(config.get("track_id") or "").strip()
        ingest_date = str(config.get("ingest_date") or "yesterday").strip()
        dgx_train_root = str(config.get("dgx_train_root") or "/app/data/dgx-train").strip()
        decisions_md_path = str(config.get("decisions_md_path") or "").strip()
        llm_calls_path = str(config.get("llm_calls_path") or "").strip()

        # 1. Validate track_id early — reject before touching disk or network.
        if track_id not in _VALID_TRACK_IDS:
            return ActionResult(
                status="error",
                error="invalid_track_id",
                message=(
                    f"track_id={track_id!r} is not one of the 6 valid trading tracks: "
                    f"{sorted(_VALID_TRACK_IDS)}"
                ),
                output={"track_id": track_id, "valid_track_ids": sorted(_VALID_TRACK_IDS)},
            )

        # 2. DB connectivity probe — fail fast rather than produce opaque
        #    subprocess errors when the trading-bot Postgres is unreachable.
        db_url = os.environ.get("TRADEBOT_DATABASE_URL", "").strip()
        if db_url:
            if not _probe_db(db_url):
                return ActionResult(
                    status="error",
                    error="tradebot_db_unreachable",
                    message=(
                        f"Cannot connect to TRADEBOT_DATABASE_URL={db_url!r}. "
                        "Check that the trading-bot Postgres container is running "
                        "and reachable from this container (host.docker.internal port 5434)."
                    ),
                    output={"track_id": track_id, "db_url": db_url},
                )
        else:
            logger.warning(
                "[build-trading] TRADEBOT_DATABASE_URL not set — skipping DB probe. "
                "modelforge_ingest.py will proceed without bootstrap decisions data.",
            )

        # 3. Stage 1: ingest.
        ingest_argv = [
            "python3", _INGEST_SCRIPT,
            "--role-filter", track_id,
            "--since", ingest_date,
        ]
        if decisions_md_path:
            ingest_argv += ["--decisions-md", decisions_md_path]
        if llm_calls_path:
            ingest_argv += ["--llm-calls", llm_calls_path]
        ingest_env = {**os.environ, "DGX_TRAIN_ROOT": dgx_train_root}

        logger.info("[build-trading] running ingest: %s", " ".join(ingest_argv))
        try:
            ingest_proc = subprocess.run(
                ingest_argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                env=ingest_env,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(
                status="error",
                error="ingest_timeout",
                message=f"modelforge_ingest.py timed out after 300s for track_id={track_id!r}",
                output={"track_id": track_id},
            )
        except Exception as exc:
            return ActionResult(
                status="error",
                error="ingest_spawn_failed",
                message=f"Failed to launch modelforge_ingest.py: {exc}",
                output={"track_id": track_id},
            )

        if ingest_proc.returncode != 0:
            return ActionResult(
                status="error",
                error="ingest_failed",
                message=(
                    f"modelforge_ingest.py exited {ingest_proc.returncode} for track_id={track_id!r}"
                ),
                output={
                    "track_id": track_id,
                    "ingest_returncode": ingest_proc.returncode,
                    "ingest_stdout": ingest_proc.stdout[-2000:] if ingest_proc.stdout else "",
                    "ingest_stderr": ingest_proc.stderr[-2000:] if ingest_proc.stderr else "",
                },
            )

        logger.info(
            "[build-trading] ingest ok (rc=0) for track=%s. stdout: %s",
            track_id, (ingest_proc.stdout or "").strip()[-500:],
        )

        # 4. Stage 2: curate.
        curate_argv = [
            "python3", _CURATE_SCRIPT,
            "--role-filter", track_id,
        ]
        curate_env = {**os.environ, "DGX_TRAIN_ROOT": dgx_train_root}

        logger.info("[build-trading] running curate: %s", " ".join(curate_argv))
        try:
            curate_proc = subprocess.run(
                curate_argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
                env=curate_env,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(
                status="error",
                error="curate_timeout",
                message=f"modelforge_curate.py timed out after 600s for track_id={track_id!r}",
                output={"track_id": track_id},
            )
        except Exception as exc:
            return ActionResult(
                status="error",
                error="curate_spawn_failed",
                message=f"Failed to launch modelforge_curate.py: {exc}",
                output={"track_id": track_id},
            )

        if curate_proc.returncode != 0:
            return ActionResult(
                status="error",
                error="curate_failed",
                message=(
                    f"modelforge_curate.py exited {curate_proc.returncode} for track_id={track_id!r}"
                ),
                output={
                    "track_id": track_id,
                    "curate_returncode": curate_proc.returncode,
                    "curate_stdout": curate_proc.stdout[-2000:] if curate_proc.stdout else "",
                    "curate_stderr": curate_proc.stderr[-2000:] if curate_proc.stderr else "",
                },
            )

        logger.info(
            "[build-trading] curate ok (rc=0) for track=%s. stdout: %s",
            track_id, (curate_proc.stdout or "").strip()[-500:],
        )

        # 5. Read curator_result.json — this is the authoritative success signal.
        curator_result_path = Path(dgx_train_root) / "datasets" / track_id / "curator_result.json"
        if not curator_result_path.is_file():
            return ActionResult(
                status="error",
                error="curator_result_missing",
                message=(
                    f"curator_result.json not found at {curator_result_path} after successful "
                    f"ingest + curate for track_id={track_id!r}. Check curate logs."
                ),
                output={
                    "track_id": track_id,
                    "expected_path": str(curator_result_path),
                    "curate_stdout": curate_proc.stdout[-1000:] if curate_proc.stdout else "",
                    "curate_stderr": curate_proc.stderr[-1000:] if curate_proc.stderr else "",
                },
            )

        try:
            with curator_result_path.open("r", encoding="utf-8") as fh:
                result = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return ActionResult(
                status="error",
                error="curator_result_unreadable",
                message=f"Failed to read {curator_result_path}: {exc}",
                output={"track_id": track_id, "curator_result_path": str(curator_result_path)},
            )

        curator_status = str(result.get("status") or "").strip()
        if curator_status != "ok":
            accept_count = int(result.get("accept_count") or 0)
            reject_reasons = result.get("reject_reasons") or {}
            common_output = {
                "track_id": track_id,
                "curator_status": curator_status,
                "accept_count": accept_count,
                "reject_count": int(result.get("reject_count") or 0),
                "reject_reasons": reject_reasons,
                "records_count": accept_count,  # convenience alias
            }
            if curator_status == "insufficient_data":
                # Insufficient data is a DESIGNED outcome of the data gate — not
                # an error. Returning ``status="skipped"`` lets the workflow
                # runner continue to subsequent conditional steps (e.g.
                # ``notify.slack`` gated on ``last_action_status=skipped``) so
                # the Sunday workflow can send a fail-loud Slack alert without
                # the runner halting at this step. Returning ``status="error"``
                # here previously caused the runner to break the action loop,
                # which silenced the downstream insufficient-data Slack ping.
                return ActionResult(
                    status="skipped",
                    message=(
                        f"Insufficient data for {track_id}: "
                        f"accept_count={accept_count}, "
                        f"reject_reasons={reject_reasons}. "
                        f"N_MIN gate held. No training will fire."
                    ),
                    output=common_output,
                )
            # Genuine errors (unparseable curator_result.json, curator process
            # crash with non-ok-non-insufficient_data status) still halt.
            return ActionResult(
                status="error",
                error="curator_result_error",
                message=(
                    f"Curator returned unexpected status={curator_status!r} for "
                    f"track_id={track_id!r}. accept_count={accept_count}, "
                    f"reject_reasons={reject_reasons}."
                ),
                output=common_output,
            )

        # 6. Success.
        accept_count = int(result.get("accept_count") or 0)
        test_set_path = result.get("test_set_path") or ""
        out_path = result.get("out_path") or ""
        output = {
            "track_id": track_id,
            "records_count": accept_count,
            "test_set_path": test_set_path,
            "curated_path": out_path,
            "reject_count": int(result.get("reject_count") or 0),
            "test_set_count": int(result.get("test_set_count") or 0),
            "curator_result_path": str(curator_result_path),
        }
        logger.info(
            "[build-trading] dataset build OK track=%s records=%d test=%d",
            track_id, accept_count, int(result.get("test_set_count") or 0),
        )
        return ActionResult(
            status="ok",
            message=(
                f"Dataset built for {track_id}: "
                f"{accept_count} train records, "
                f"{int(result.get('test_set_count') or 0)} test records."
            ),
            output=output,
        )


# Self-register with the central registry. This MUST be at the bottom
# of the module (after BuildTradingDataset is bound).
try:  # pragma: no cover -- the import side-effect IS the test
    register_action(BuildTradingDataset)
except Exception as _exc:  # pragma: no cover
    logger.warning(
        "[build-trading] self-registration failed: %s", _exc,
    )


__all__ = ["BuildTradingDataset"]
