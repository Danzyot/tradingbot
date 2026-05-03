from __future__ import annotations

from loguru import logger
from pathlib import Path

from smc_bot.models.base import Signal, Setup


def setup_logging(log_dir: Path | str = "logs") -> None:
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    logger.add(
        log_path / "signals.log",
        filter=lambda record: "signal" in record["extra"],
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        rotation="1 day",
    )
    logger.add(
        log_path / "decisions.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        rotation="1 day",
    )


def log_signal(signal: Signal) -> None:
    logger.bind(signal=True).info(
        f"SIGNAL | {signal.direction.value.upper()} {signal.instrument} | "
        f"Model: {signal.model.value} | Entry: {signal.entry_price:.2f} | "
        f"SL: {signal.stop_loss:.2f} | TP1: {signal.tp1:.2f} | "
        f"R:R: {signal.rr_ratio:.2f} | Score: {signal.score} | "
        f"KZ: {signal.killzone} | Confluences: {signal.confluences}"
    )


def log_setup_created(setup: Setup) -> None:
    logger.info(
        f"SETUP CREATED | {setup.direction.value.upper()} | "
        f"Sweep: {setup.sweep_price:.2f} @ {setup.sweep_timestamp} | "
        f"Expires: {setup.expiry} | {setup.confluences}"
    )


def log_setup_expired(setup: Setup) -> None:
    logger.debug(f"SETUP EXPIRED | Sweep: {setup.sweep_price:.2f} @ {setup.sweep_timestamp}")


def log_filter_blocked(reason: str, timestamp) -> None:
    logger.debug(f"BLOCKED | {reason} @ {timestamp}")
