import asyncio
import importlib.resources
import os
import pkgutil
import signal
from typing import Tuple

from nx.automation import image_processing
from nx.controller import Controller
from nx.controller.sinks.windows_named_pipe_sink import (
    PipeWrapper,
    WindowsNamedPipeSink,
)

from mrprog.worker.auto_trade_base import AbstractAutoTrader


class SteamAutoTrader(AbstractAutoTrader):
    def __init__(self, pipe_wrapper: PipeWrapper, game: int):
        self.controller = Controller(pipe_wrapper)
        self.pipe_wrapper = pipe_wrapper
        super().__init__(self.controller, game)

    @classmethod
    async def create(cls, game: int) -> "SteamAutoTrader":
        cls.install_specialk_config()

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

    @classmethod
    async def _init_sink(cls, game: int) -> Tuple[PipeWrapper, bool]:
        from windows.automation import steam

        steamid_32 = steam.get_logged_in_user_steamid32()
        cls.copy_exe6_save(steamid_32)

        if game in [1, 2, 3]:
            image_processing.WIN_WINDOW_NAME = "MegaMan_BattleNetwork_LegacyCollection_Vol1"
            process_name = steam.get_vol1_exe_path()
        else:
            image_processing.WIN_WINDOW_NAME = "MegaMan_BattleNetwork_LegacyCollection_Vol2"
            process_name = steam.get_vol2_exe_path()

        sink = WindowsNamedPipeSink(process_name)
        return sink.connect_to_pipe()

    @classmethod
    def install_specialk_config(cls) -> None:
        config_template = importlib.resources.files("mrprog.worker").joinpath("support_files/custom_SpecialK.ini").read_text()
        config_file = config_template.format(dll_path=importlib.resources.files("mrprog.worker").joinpath("support_files/XInputReportInjector.dll").name)
        appdata = os.getenv('LOCALAPPDATA')
        profile_dir = os.path.join(appdata, "Programs", "Special K", "Profiles")

        for vol in ["1", "2"]:
            for output_file in ["custom_SpecialK.ini", "custom_dxgi.ini"]:
                game_profile_dir = os.path.join(profile_dir, f"Mega Man Battle Network Legacy Collection Vol {vol}")
                output_path = os.path.join(game_profile_dir, output_file)
                with open(output_path, "w") as f:
                    f.write(config_file)
                    print(f"Installed Special K config to {output_path}")

    @classmethod
    def copy_exe3_save(cls, steamid_32: int) -> None:
        from windows.automation import steam

        steam_id_bytes = steamid_32.to_bytes(4, "little")

        save_names = ["exe3w_save_0.bin"]

        for save_name in save_names:
            save_data = bytearray(pkgutil.get_data("mrprog.worker", f"saves/{save_name}"))

            for i, b in enumerate(steam_id_bytes):
                save_data[0xE0 + i] = b

            path = os.path.join(steam.get_vol1_save_directory(steamid_32), save_name)
            with open(path, "wb") as f:
                f.write(save_data)
                print(f"Copied save to {path}")

    @classmethod
    def copy_exe6_save(cls, steamid_32: int) -> None:
        from windows.automation import steam

        steam_id_bytes = steamid_32.to_bytes(4, "little")

        save_names = ["exe6f_save_0.bin", "exe6g_save_0.bin"]

        for save_name in save_names:
            encrypted = pkgutil.get_data("mrprog.worker", f"saves/{save_name}")
            xor_byte = encrypted[1]
            decrypted = cls.array_xor(encrypted, xor_byte)

            for i, b in enumerate(steam_id_bytes):
                decrypted[6496 + i] = b

            encrypted_updated = cls.array_xor(decrypted, xor_byte)
            path = os.path.join(steam.get_vol1_save_directory(steamid_32), save_name)
            with open(path, "wb") as f:
                f.write(encrypted_updated)
                print(f"Copied save to {path}")

    async def _navigate_menus_after_reset(self) -> bool:
        for _ in range(45):
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

    @staticmethod
    def array_xor(b1, xor):
        result = bytearray(b1)
        for i in range(len(b1)):
            result[i] ^= xor
        return result
