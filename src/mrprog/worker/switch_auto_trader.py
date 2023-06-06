from .auto_trade_base import AbstractAutoTrader


class SwitchAutoTrader(AbstractAutoTrader):
    async def reload_save(self):
        # Home screen
        await self.home(wait_time=1000)

        # Cloud save menu
        await self.plus(wait_time=1000)
        await self.a()

        # Select correct profile
        await self.down()
        await self.a(wait_time=500)

        # TODO: Wait for "Download Save Data"
        await self.wait(5000)
        await self.down()
        await self.a()

        # TODO: Wait for "Close the software"
        await self.wait(1000)
        await self.a(wait_time=5000)

        # Select "download save"
        await self.up()
        await self.a()

        # TODO: Wait for "Download complete.
        await self.wait(20000)
        await self.home()

        # TODO: Wait for "Select a user."
        await self.wait(2000)
        await self.a(wait_time=2000)
        await self.a()

        # TODO: Wait for "PRESS ANY BUTTON"
        for _ in range(60):
            await self.a(wait_time=1000)

        # TODO: Wait for "PRESS + BUTTON"
        await self.plus(wait_time=500)
        await self.a(wait_time=5000)

        await self.plus(wait_time=1000)
        await self.up()
        await self.up(wait_time=500)
        await self.a(wait_time=3000)
