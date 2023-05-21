from __future__ import annotations

import argparse
import asyncio
import logging
import platform
from typing import Tuple

import aio_pika
import asyncio_mqtt
import psutil
from aio_pika import Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractIncomingMessage,
    AbstractQueue,
    AbstractRobustConnection,
)
from auto_trader import AutoTrader
from mmbn.gamedata.chip import Chip
from mrprog.utils.logging import install_logger
from mrprog.utils.trade import TradeRequest, TradeResponse
from nx.automation import image_processing
from nx.controller import Button, Controller
from nx.controller.sinks import SocketSink

logger = logging.getLogger(__name__)

SUPPORTED_GAMES = {"switch": [3, 6], "steam": [6]}


# noinspection PyTypeChecker
class TradeWorker:
    mqtt_client: asyncio_mqtt.Client

    amqp_connection: AbstractRobustConnection
    channel: AbstractChannel
    task_queue: AbstractQueue
    notification_queue: AbstractQueue
    loop: asyncio.AbstractEventLoop
    exchange: AbstractExchange

    trader: AutoTrader
    controller: Controller

    def __init__(
        self, controller_server: Tuple[str, int], host: str, username: str, password: str, system: str, game: int
    ):
        # TODO: Handle BN3, Steam
        self.controller_server = controller_server
        self.system = system
        self.game = game
        self.sink = None
        self.socket = None

        self._amqp_connection_str = f"amqp://{username}:{password}@{host}/"
        self._mqtt_connection_info = (host, username, password)
        self._mqtt_update_task = None

        self.worker_id = f"{hash(platform.node()):x}"

    async def handle_mqtt_updates(self) -> None:
        async with self.mqtt_client.messages() as messages:
            await self.mqtt_client.subscribe(f"enabled/{self.system}/{self.game}")
            async for message in messages:
                if message.topic.matches(f"enabled/{self.system}/{self.game}"):
                    enabled = bool(message.body)
                    if not enabled:
                        await self.task_queue.cancel(consumer_tag=self.worker_id)
                    else:
                        await self.task_queue.consume(self.on_trade_request, no_ack=False, consumer_tag=self.worker_id)

    async def update_mqtt_info(self) -> None:
        interfaces = psutil.net_if_addrs()
        ip_address = None
        for interface in interfaces:
            for address in interfaces[interface]:
                if address.address.startswith("100."):
                    ip_address = address.address
                    break

        await self.mqtt_client.publish(
            topic=f"worker/{self.worker_id}/hostname", payload=platform.node(), qos=1, retain=True
        )
        await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/address", payload=ip_address, qos=1, retain=True)
        await self.mqtt_client.publish(
            topic=f"worker/{self.worker_id}/game", payload=f"{self.system}.bn{self.game}", qos=1, retain=True
        )
        await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/available", payload="1", qos=1, retain=True)

        self._mqtt_update_task = self.loop.create_task(self.handle_mqtt_updates())

    async def run(self) -> None:
        self.sink = SocketSink(self.controller_server[0], self.controller_server[1])
        self.socket = await self.sink.connect()
        self.controller = Controller(self.socket)

        self.trader = AutoTrader(self.controller, self.game)

        # Let the screen pop up if needed
        self.controller.press_button(Button.Nothing, wait_ms=2000)
        await self.controller.wait_for_inputs()
        if (
            image_processing.run_tesseract_line(image_processing.capture(), (1000, 1000), (460, 460))
            == "Controller Not Connecting"
        ):
            print("Found controller connect screen, connecting")
            self.controller.press_button(Button.L + Button.R, hold_ms=100, wait_ms=2000)
            self.controller.press_button(Button.A, hold_ms=100, wait_ms=2000)
            await self.controller.wait_for_inputs()

        mqtt_host, mqtt_user, mqtt_pass = self._mqtt_connection_info
        self.mqtt_client = asyncio_mqtt.Client(
            hostname=mqtt_host,
            username=mqtt_user,
            password=mqtt_pass,
            will=asyncio_mqtt.Will(topic=f"worker/{self.worker_id}/available", payload="0", qos=1, retain=True),
            clean_session=True,
        )
        await self.mqtt_client.connect()

        self.amqp_connection = await aio_pika.connect_robust(
            self._amqp_connection_str,
            loop=self.loop,
        )
        self.channel = await self.amqp_connection.channel()

        # Declare an exchange
        self.exchange = await self.channel.declare_exchange(
            name="trade_requests",
            type=aio_pika.ExchangeType.TOPIC,
        )

        # Declaring queues
        task_queue = await self.channel.declare_queue(
            name=f"{self.system}_bn{self.game}_task_queue", durable=True, arguments={"x-max-priority": 100}
        )
        await task_queue.bind(self.exchange, routing_key=f"requests.{self.system}.bn{self.game}")
        self.task_queue = task_queue

        self.notification_queue = await self.channel.declare_queue(name="trade_status_update", durable=True)
        await self.update_mqtt_info()

    async def on_trade_request(self, message: AbstractIncomingMessage) -> None:
        try:
            async with message.process(requeue=False):
                assert message.reply_to is not None

                request = TradeRequest.from_bytes(message.body)
                print(f"Received request: {request.trade_id}")

                room_code_future = asyncio.Future()
                if isinstance(request.trade_item, Chip):
                    trade_completed = self.trader.trade_chip(request, room_code_future)
                else:
                    trade_completed = self.trader.trade_ncp(request, room_code_future)

                try:
                    image_bytestring = await room_code_future
                    response = TradeResponse(
                        request, self.worker_id, TradeResponse.IN_PROGRESS, message="Room code", image=image_bytestring
                    )
                    print(f"Sending room code to {message.reply_to}")
                    await self.exchange.publish(
                        Message(
                            body=response.to_bytes(),
                            content_type="application/json",
                            correlation_id=message.correlation_id,
                        ),
                        routing_key=message.reply_to,
                    )
                except asyncio.CancelledError:
                    trade_result, trader_message = await trade_completed
                    response = TradeResponse(request, self.worker_id, trade_result, message=trader_message)
                    await self.exchange.publish(
                        Message(
                            body=response.to_bytes(),
                            content_type="application/json",
                            correlation_id=message.correlation_id,
                        ),
                        routing_key=message.reply_to,
                    )
                    if trade_result in [TradeResponse.SUCCESS, TradeResponse.CANCELLED, TradeResponse.USER_TIMEOUT]:
                        await message.ack()
                    else:
                        await message.nack(requeue=True)
                    return

                response = TradeResponse(
                    request, self.worker_id, TradeResponse.IN_PROGRESS, message="Room code", image=image_bytestring
                )
                print(f"Sending room code to {message.reply_to}")
                await self.exchange.publish(
                    Message(
                        body=response.to_bytes(),
                        content_type="application/json",
                        correlation_id=message.correlation_id,
                    ),
                    routing_key=message.reply_to,
                )

                trade_result, trader_message = await trade_completed

                response = TradeResponse(request, self.worker_id, trade_result, message=trader_message)
                print(f"Sending finish message to {message.reply_to}")
                await self.exchange.publish(
                    Message(
                        body=response.to_bytes(),
                        content_type="application/json",
                        correlation_id=message.correlation_id,
                    ),
                    routing_key=message.reply_to,
                )
                if trade_result in [TradeResponse.SUCCESS, TradeResponse.CANCELLED, TradeResponse.USER_TIMEOUT]:
                    await message.ack()
                else:
                    await message.nack(requeue=True)
        except Exception:
            logging.exception("Processing error for message %r", message)
            await message.nack(requeue=True)

    async def process_trade_queue(self):
        async with self.task_queue.iterator() as qiterator:
            message: AbstractIncomingMessage
            async for message in qiterator:
                try:
                    async with message.process(requeue=False):
                        assert message.reply_to is not None

                        request = TradeRequest.from_bytes(message.body)
                        print(f"Received request: {request.trade_id}")

                        room_code_future = asyncio.Future()
                        if isinstance(request.trade_item, Chip):
                            trade_completed = self.trader.trade_chip(request, room_code_future)
                        else:
                            trade_completed = self.trader.trade_ncp(request, room_code_future)

                        try:
                            image_bytestring = await room_code_future
                            response = TradeResponse(
                                request,
                                self.worker_id,
                                TradeResponse.IN_PROGRESS,
                                message="Room code",
                                image=image_bytestring,
                            )
                            print(f"Sending room code to {message.reply_to}")
                            await self.exchange.publish(
                                Message(
                                    body=response.to_bytes(),
                                    content_type="application/json",
                                    correlation_id=message.correlation_id,
                                ),
                                routing_key=message.reply_to,
                            )
                        except asyncio.CancelledError:
                            trade_result, trader_message = await trade_completed
                            response = TradeResponse(request, self.worker_id, trade_result, message=trader_message)
                            await self.exchange.publish(
                                Message(
                                    body=response.to_bytes(),
                                    content_type="application/json",
                                    correlation_id=message.correlation_id,
                                ),
                                routing_key=message.reply_to,
                            )
                            continue

                        response = TradeResponse(
                            request,
                            self.worker_id,
                            TradeResponse.IN_PROGRESS,
                            message="Room code",
                            image=image_bytestring,
                        )
                        print(f"Sending room code to {message.reply_to}")
                        await self.exchange.publish(
                            Message(
                                body=response.to_bytes(),
                                content_type="application/json",
                                correlation_id=message.correlation_id,
                            ),
                            routing_key=message.reply_to,
                        )

                        response = TradeResponse(request, self.worker_id, TradeResponse.SUCCESS, message="OK")
                        print(f"Sending finish message to {message.reply_to}")
                        await self.exchange.publish(
                            Message(
                                body=response.to_bytes(),
                                content_type="application/json",
                                correlation_id=message.correlation_id,
                            ),
                            routing_key=message.reply_to,
                        )
                        print("Request complete")
                except Exception:
                    logging.exception("Processing error for message %r", message)


async def main():
    parser = argparse.ArgumentParser(prog="Mr. Prog Trade Worker", description="Trade worker process for Mr. Prog")
    parser.add_argument("--host")  # positional argument
    parser.add_argument("--username")  # option that takes a value
    parser.add_argument("--password")
    parser.add_argument("--platform")
    parser.add_argument("--game", type=int)
    parser.parse_args()

    install_logger(parser.host, parser.username, parser.password)
    worker = TradeWorker(
        ("127.0.0.1", 3000), parser.host, parser.username, parser.password, parser.platform, parser.game
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
