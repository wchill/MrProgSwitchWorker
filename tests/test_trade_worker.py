import asyncio
import json
from unittest.mock import MagicMock

from mock_auto_trader import MockAutoTrader
from mrprog.utils.trade import TradeRequest, TradeResponse
from nx.automation import image_processing


class TestTradeWorker:
    async def test_chip_trade(self, monkeypatch):
        monkeypatch.setattr(image_processing, "capture", MagicMock())
        monkeypatch.setattr(image_processing, "crop_to_bounding_box", MagicMock())
        monkeypatch.setattr(image_processing, "convert_image_to_png_bytestring", MagicMock())
        monkeypatch.setattr(image_processing, "run_tesseract_line", lambda *args: "1/15")

        trader = MockAutoTrader(6)
        payload = json.dumps({"user_name": "wchill", "user_id": 0, "channel_id": 0, "system": "steam", "game": 6, "trade_id": 0, "trade_item": {"py/object": "mmbn.gamedata.bn6.bn6_chip.BN6Chip", "name": "AirHocky", "chip_id": "051", "code": {"py/reduce": [{"py/type": "mmbn.gamedata.chip.Code"}, {"py/tuple": [12]}]}, "atk": 60, "element": {"py/reduce": [{"py/type": "mmbn.gamedata.bn6.bn6_chip.BN6Element"}, {"py/tuple": [10]}]}, "mb": 19, "chip_type": 1, "description": "Bounce the puck off walls"}, "priority": 0})
        request = TradeRequest.from_json(payload)
        room_code_future = asyncio.Future()

        trade_completed = asyncio.create_task(trader.trade_chip(request, room_code_future))
        image_bytestring = await room_code_future
        assert image_bytestring is not None

        trade_result, trader_message = await trade_completed

        assert trade_result == TradeResponse.SUCCESS
