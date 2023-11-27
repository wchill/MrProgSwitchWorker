from mrprog.worker.auto_trade_base import AbstractAutoTrader


class SwitchAutoTrader(AbstractAutoTrader):
    async def reset(self) -> bool:
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
        for _ in range(50):
            await self.a(wait_time=1000)

        # TODO: Wait for "PRESS + BUTTON"
        await self.plus(wait_time=500)
        await self.a(wait_time=5000)

        # Handle the "continue/start new game" prompt in 4
        if self.game == 4:
            await self.a(wait_time=5000)

        await self.plus(wait_time=1000)
        await self.up()
        await self.up(wait_time=500)
        await self.a(wait_time=3000)

        return await self.wait_for_text(lambda ocr_text: ocr_text == "NETWORK", (55, 65), (225, 50), 10)
