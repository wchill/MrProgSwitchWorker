import asyncio
import os
import signal
from typing import Tuple

from mrprog.worker.auto_trade_base import AbstractAutoTrader
from nx.controller import Controller
from nx.automation import image_processing
from nx.controller.sinks.windows_named_pipe_sink import PipeWrapper, WindowsNamedPipeSink


class SteamAutoTrader(AbstractAutoTrader):
    def __init__(self, pipe_wrapper: PipeWrapper, game: int):
        controller = Controller(pipe_wrapper)
        self.pipe_wrapper = pipe_wrapper
        super().__init__(controller, game)

    @classmethod
    async def create(cls, game: int) -> "SteamAutoTrader":
        sink, process_exists = await cls._init_sink(game)
        trader = cls(sink, game)
        if process_exists:
            print("Process already exists, skipping navigation")
            return trader
        else:
            print("Attempting to navigate menus")
            if await trader._navigate_menus_after_reset():
                return trader
            raise RuntimeError("Unable to properly reset: did not end up in network menu.")

    @staticmethod
    async def _init_sink(game: int) -> Tuple[PipeWrapper, bool]:
        from windows.automation import steam

        if game in [1, 2, 3]:
            image_processing.WIN_WINDOW_NAME = "MegaMan_BattleNetwork_LegacyCollection_Vol1"
            process_name = steam.get_vol1_exe_path()
        else:
            image_processing.WIN_WINDOW_NAME = "MegaMan_BattleNetwork_LegacyCollection_Vol2"
            process_name = steam.get_vol2_exe_path()

        sink = WindowsNamedPipeSink(process_name)
        return sink.connect_to_pipe()

    async def _navigate_menus_after_reset(self) -> bool:
        for _ in range(60):
            await self.a(wait_time=1000)

        # TODO: Wait for "PRESS + BUTTON"
        await self.plus(wait_time=500)
        await self.a(wait_time=5000)

        await self.plus(wait_time=1000)
        await self.up()
        await self.up(wait_time=500)
        await self.a(wait_time=3000)

        return await self.wait_for_text(lambda ocr_text: ocr_text == "NETWORK", (55, 65), (225, 50), 10)

    async def reset(self) -> bool:
        try:
            print(f"Attempting to kill process {self.pipe_wrapper.process_id}")
            os.kill(self.pipe_wrapper.process_id, signal.SIGTERM)
        except OSError:
            pass

        print(f"Sleeping for 10 seconds to let Steam finish cloud sync")
        await asyncio.sleep(10)

        print("Reinitializing sink")
        sink, _ = await self._init_sink(self.game)
        self.pipe_wrapper = sink
        self.controller = Controller(sink)
        return await self._navigate_menus_after_reset()
