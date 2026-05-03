from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from smc_bot.data.candle import Candle


class CISDDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class CISD:
    direction: CISDDirection
    price: float
    timestamp: datetime
    timeframe: str
    broken_candle_open: float


class CISDDetector:
    def __init__(self, timeframe: str = "1m"):
        self._timeframe = timeframe
        self._candles: list[Candle] = []
        self._cisds: list[CISD] = []

    @property
    def cisds(self) -> list[CISD]:
        return self._cisds

    @property
    def last_cisd(self) -> CISD | None:
        return self._cisds[-1] if self._cisds else None

    def update(self, candle: Candle) -> list[CISD]:
        self._candles.append(candle)
        new_cisds: list[CISD] = []

        if len(self._candles) < 2:
            return new_cisds

        current = self._candles[-1]

        for i in range(len(self._candles) - 2, max(len(self._candles) - 20, -1), -1):
            prior = self._candles[i]

            if prior.is_bearish and current.body_high > prior.open:
                cisd = CISD(
                    direction=CISDDirection.BULLISH,
                    price=current.close,
                    timestamp=current.timestamp,
                    timeframe=self._timeframe,
                    broken_candle_open=prior.open,
                )
                new_cisds.append(cisd)
                self._cisds.append(cisd)
                break

        for i in range(len(self._candles) - 2, max(len(self._candles) - 20, -1), -1):
            prior = self._candles[i]

            if prior.is_bullish and current.body_low < prior.open:
                cisd = CISD(
                    direction=CISDDirection.BEARISH,
                    price=current.close,
                    timestamp=current.timestamp,
                    timeframe=self._timeframe,
                    broken_candle_open=prior.open,
                )
                new_cisds.append(cisd)
                self._cisds.append(cisd)
                break

        return new_cisds
