import importlib.resources
from mrprog.worker.steam_auto_trader import SteamAutoTrader


def main():
    saves_dir = str(importlib.resources.files("mrprog.worker").joinpath("saves"))
    SteamAutoTrader.copy_exe1_save(0, saves_dir)
    SteamAutoTrader.copy_exe2_save(0, saves_dir)
    SteamAutoTrader.copy_exe3_save(0, saves_dir)
    SteamAutoTrader.copy_exe4_save(0, saves_dir)
    SteamAutoTrader.copy_exe5_save(0, saves_dir)
    SteamAutoTrader.copy_exe6_save(0, saves_dir)


if __name__ == "__main__":
    main()
