from typing import Callable, Tuple, Optional
from unittest.mock import MagicMock

from mrprog.utils.trade import TradeResponse
from mrprog.worker.auto_trade_base import AbstractAutoTrader
from nx.automation.script import MatchArgs
from nx.controller import Controller


class MockController(Controller):
    def __init__(self):
        super().__init__(MagicMock())

    async def wait_for_inputs(self):
        pass


class MockAutoTrader(AbstractAutoTrader):
    def __init__(self, game: int):
        super().__init__(MockController(), game)

    async def wait(self, wait_time: int = 0) -> None:
        pass

    async def reset(self) -> bool:
        pass

    @staticmethod
    async def wait_for_text(
        matcher: Callable[[str], bool],
        top_left: Tuple[int, int],
        size: Tuple[int, int],
        timeout: Optional[float],
        invert: bool = True,
    ) -> bool:
        return True

    @staticmethod
    async def wait_for_match(*matchers: MatchArgs, timeout: Optional[float]) -> Tuple[int, Optional[str]]:
        return TradeResponse.SUCCESS, ""
