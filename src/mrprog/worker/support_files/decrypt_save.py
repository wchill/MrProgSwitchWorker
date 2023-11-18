import importlib.resources
import os

from mrprog.worker.steam_auto_trader import SteamAutoTrader


def main():
    from windows.automation import steam

    steamid_32 = steam.get_logged_in_user_steamid32()
    save_dir_vol_1 = steam.get_vol1_save_directory(steamid_32)
    save_dir_vol_2 = steam.get_vol2_save_directory(steamid_32)

    with open(os.path.join(save_dir_vol_2, "exe4b_save_1.bin"), "rb") as f1:
        with open(os.path.join(save_dir_vol_2, "exe4b_save_1.decrypted"), "wb") as f2:
            save = f1.read()
            f2.write(SteamAutoTrader.array_xor(save, save[1]))


if __name__ == "__main__":
    main()
