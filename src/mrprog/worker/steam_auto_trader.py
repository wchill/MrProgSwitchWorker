import asyncio
import importlib.resources
import os
import pkgutil
import signal
from typing import Tuple, List, Optional, Callable

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
        save_dir_vol_1 = steam.get_vol1_save_directory(steamid_32)
        save_dir_vol_2 = steam.get_vol2_save_directory(steamid_32)
        os.makedirs(save_dir_vol_1, exist_ok=True)
        os.makedirs(save_dir_vol_2, exist_ok=True)

        if game == 1:
            cls.copy_exe1_save(steamid_32, save_dir_vol_1)
        elif game == 2:
            cls.copy_exe2_save(steamid_32, save_dir_vol_1)
        elif game == 3:
            cls.copy_exe3_save(steamid_32, save_dir_vol_1)
        elif game == 4:
            cls.copy_exe4_save(steamid_32, save_dir_vol_2)
        elif game == 5:
            cls.copy_exe5_save(steamid_32, save_dir_vol_2)
        elif game == 6:
            cls.copy_exe6_save(steamid_32, save_dir_vol_2)

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
        config_file = config_template.format(dll_path=str(importlib.resources.files("mrprog.worker").joinpath("support_files/XInputReportInjector.dll")))
        appdata = os.getenv('LOCALAPPDATA')
        profile_dir_1 = os.path.join(appdata, "Programs", "Special K", "Profiles")
        profile_dir_2 = os.path.join("C:", "Program Files", "Special K", "Profiles")

        for vol in ["1", "2"]:
            for output_file in ["custom_SpecialK.ini", "custom_dxgi.ini"]:
                for profile_dir in [profile_dir_1, profile_dir_2]:
                    game_profile_dir = os.path.join(profile_dir, f"Mega Man Battle Network Legacy Collection Vol {vol}")
                    os.makedirs(game_profile_dir, exist_ok=True)
                    output_path = os.path.join(game_profile_dir, output_file)
                    with open(output_path, "w") as f:
                        f.write(config_file)
                        print(f"Installed Special K config to {output_path}")

    @classmethod
    def copy_exe1_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe1_save_0.bin"], None, lambda _: 0xBC)

    @classmethod
    def copy_exe2_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe2j_save_0.bin"], None, lambda _: 0x104)

    @classmethod
    def copy_exe3_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe3w_save_0.bin", "exe3b_save_0.bin"], None, lambda _: 0xE0)

    @classmethod
    def copy_exe4_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe4r_save_0.bin", "exe4b_save_0.bin"], 1, lambda save_data: save_data.index(b"Exe4") + 12)

    @classmethod
    def copy_exe5_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe5b_save_0.bin", "exe5k_save_0.bin"], 1, lambda _: 0x1FC0)

    @classmethod
    def copy_exe6_save(cls, steamid_32: int, output_dir: str) -> None:
        cls.copy_save(steamid_32, output_dir, ["exe6f_save_0.bin", "exe6g_save_0.bin"], 1, lambda _: 0x1960)

    @classmethod
    def copy_save(cls, steamid_32: int, output_dir: str, save_names: List[str], xor_byte_offset: Optional[int], id_offset_func: Callable[[bytes], int]) -> None:
        steam_id_bytes = steamid_32.to_bytes(4, "little")

        for save_name in save_names:
            try:
                encrypted = pkgutil.get_data("mrprog.worker", f"saves/{save_name}")

                if xor_byte_offset is None:
                    xor_byte = 0
                else:
                    xor_byte = encrypted[xor_byte_offset]

                print(f"xor byte {xor_byte}")
                decrypted = cls.array_xor(encrypted, xor_byte)

                id_offset = id_offset_func(decrypted)
                print(f"Using ID offset: {hex(id_offset)}")
                print(f"Loaded save with SteamID {int.from_bytes(decrypted[id_offset:id_offset+4], 'little')}")

                for i, b in enumerate(steam_id_bytes):
                    decrypted[id_offset + i] = b

                encrypted_updated = cls.array_xor(decrypted, xor_byte)

                path = os.path.join(output_dir, save_name)
                with open(path, "wb") as f:
                    f.write(encrypted_updated)
                    print(f"Copied save with SteamID {steamid_32} to {path}")
            except FileNotFoundError:
                pass

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
