import importlib.resources
from mrprog.worker.steam_auto_trader import SteamAutoTrader


def main():
    from windows.automation import steam

    steamid_32 = steam.get_logged_in_user_steamid32()
    save_dir_vol_1 = steam.get_vol1_save_directory(steamid_32)
    save_dir_vol_2 = steam.get_vol2_save_directory(steamid_32)

    # SteamAutoTrader.copy_exe1_save(steamid_32, save_dir_vol_1)
    # SteamAutoTrader.copy_exe2_save(steamid_32, save_dir_vol_1)
    # SteamAutoTrader.copy_exe3_save(steamid_32, save_dir_vol_1)
    SteamAutoTrader.copy_exe4_save(steamid_32, save_dir_vol_2)
    SteamAutoTrader.copy_exe5_save(steamid_32, save_dir_vol_2)
    # SteamAutoTrader.copy_exe6_save(steamid_32, save_dir_vol_2)


if __name__ == "__main__":
    main()
