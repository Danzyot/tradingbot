from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import json


@dataclass
class NewsEvent:
    title: str
    timestamp: datetime
    currency: str = "USD"
    impact: str = "high"


class NewsFilter:
    def __init__(
        self,
        buffer_before_minutes: int = 5,
        buffer_after_minutes: int = 5,
        events: list[NewsEvent] | None = None,
    ):
        self._buffer_before = timedelta(minutes=buffer_before_minutes)
        self._buffer_after = timedelta(minutes=buffer_after_minutes)
        self._events: list[NewsEvent] = events or []

    @property
    def events(self) -> list[NewsEvent]:
        return self._events

    def add_event(self, event: NewsEvent) -> None:
        self._events.append(event)

    def load_from_json(self, path: Path) -> None:
        with open(path) as f:
            data = json.load(f)
        for item in data:
            self._events.append(
                NewsEvent(
                    title=item["title"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    currency=item.get("currency", "USD"),
                    impact=item.get("impact", "high"),
                )
            )

    def is_blocked(self, timestamp: datetime) -> bool:
        for event in self._events:
            if event.impact != "high":
                continue
            if event.currency != "USD":
                continue
            start = event.timestamp - self._buffer_before
            end = event.timestamp + self._buffer_after
            if start <= timestamp <= end:
                return True
        return False

    def next_event(self, timestamp: datetime) -> NewsEvent | None:
        future = [e for e in self._events if e.timestamp > timestamp and e.impact == "high"]
        if future:
            return min(future, key=lambda e: e.timestamp)
        return None
