from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import platform
import signal
import sys

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
from mmbn.gamedata.chip import Chip
from mrprog.utils import shell
from mrprog.utils.logging import install_logger
from mrprog.utils.trade import TradeRequest, TradeResponse
from nx.automation import image_processing
from nx.controller import Button, Controller, DPad

from mrprog.worker.auto_trade_base import AbstractAutoTrader

logger = logging.getLogger(__name__)

SUPPORTED_GAMES = {"switch": [3, 6], "steam": [6]}


# noinspection PyTypeChecker
class TradeWorker:
    mqtt_client: asyncio_mqtt.Client

    amqp_connection: AbstractRobustConnection
    trade_channel: AbstractChannel
    task_queue: AbstractQueue
    notification_queue: AbstractQueue
    loop: asyncio.AbstractEventLoop
    trade_exchange: AbstractExchange

    control_exchange: AbstractExchange
    control_channel: AbstractChannel
    control_queue: AbstractQueue

    def __init__(
        self, trader: AbstractAutoTrader, hostname: str, host: str, username: str, password: str, system: str, game: int
    ):
        self.trader = trader
        self.system = system
        self.game = game
        self.hostname = hostname

        self._amqp_connection_str = f"amqp://{username}:{password}@{host}/"
        self._mqtt_connection_info = (host, username, password)
        self._mqtt_update_task = None

        self.worker_id = hashlib.sha256(self.hostname.encode("utf-8")).hexdigest()
        self.loop = asyncio.get_running_loop()

        self.cached_messages = {}
        self.last_seen_id = 0

        self.trade_lock = asyncio.Lock()
        self.should_consume_queue = False

    async def handle_mqtt_updates(self) -> None:
        game_enabled = False
        worker_enabled = False
        trades_enabled = False
        self.should_consume_queue = False

        async with self.mqtt_client.messages() as messages:
            await self.mqtt_client.subscribe("bot/enabled")
            await self.mqtt_client.subscribe(f"game/{self.system}/{self.game}/enabled")
            await self.mqtt_client.subscribe(f"worker/{self.worker_id}/enabled")
            async for message in messages:
                self.cached_messages[message.topic] = message.payload
                if message.topic.matches(f"game/{self.system}/{self.game}/enabled"):
                    game_enabled = message.payload == b"1"
                elif message.topic.matches(f"worker/{self.worker_id}/enabled"):
                    worker_enabled = message.payload == b"1"
                elif message.topic.matches("bot/enabled"):
                    trades_enabled = message.payload == b"1"

                if self.should_consume_queue != (game_enabled and worker_enabled and trades_enabled):
                    self.should_consume_queue = game_enabled and worker_enabled and trades_enabled
                    if not self.should_consume_queue:
                        logger.info("Disabling task queue")
                        await self.task_queue.cancel(consumer_tag=f"{self.worker_id}_taskqueue")
                    else:
                        logger.info("Enabling task queue")
                        await self.task_queue.consume(
                            self.on_trade_request, no_ack=False, consumer_tag=f"{self.worker_id}_taskqueue"
                        )

    async def on_control_request(self, message: AbstractIncomingMessage) -> None:
        logger.info(f"Received control request: {message.body}")
        try:
            decoded_msg = message.body.decode("utf-8")
            if decoded_msg == "reset":
                logger.info("Attempting to acquire trade lock")
                async with self.trade_lock:
                    logger.info("Reloading save")
                    await self.trader.reload_save()
                    logger.info("Save reloaded")
                return
            inputs = decoded_msg.split(",")
            for input_str in inputs:
                input_info = input_str.split(" ")

                if len(input_info) == 3:
                    wait_ms = int(input_info[2])
                    hold_ms = int(input_info[1])
                elif len(input_info) == 2:
                    wait_ms = None
                    hold_ms = int(input_info[1])
                else:
                    wait_ms = None
                    hold_ms = 80

                try:
                    button = Button.from_str(input_info[0])
                    self.trader.controller.press_button(button, hold_ms, wait_ms)
                except KeyError:
                    dpad = DPad.from_str(input_info[0])
                    self.trader.controller.press_dpad(dpad, hold_ms, wait_ms)
            await self.trader.controller.wait_for_inputs()
        except Exception:
            logger.exception("Processing error for message %r", message)

    async def update_mqtt_info(self) -> None:
        interfaces = psutil.net_if_addrs()
        ip_address = None
        for interface in interfaces:
            for address in interfaces[interface]:
                if address.address.startswith("100."):
                    ip_address = address.address
                    break

        await self.mqtt_client.publish(
            topic=f"worker/{self.worker_id}/hostname", payload=self.hostname, qos=1, retain=True
        )
        await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/address", payload=ip_address, qos=1, retain=True)
        await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/system", payload=self.system, qos=1, retain=True)
        await self.mqtt_client.publish(
            topic=f"worker/{self.worker_id}/game", payload=str(self.game), qos=1, retain=True
        )
        git_versions = await shell.get_git_versions()
        await self.mqtt_client.publish(
            topic=f"worker/{self.worker_id}/version", payload=json.dumps(git_versions), qos=1, retain=True
        )
        await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/available", payload="1", qos=1, retain=True)

        await self.handle_mqtt_updates()

    async def run(self) -> None:
        while True:
            try:
                logger.info("Connecting to mqtt/amqp")
                mqtt_host, mqtt_user, mqtt_pass = self._mqtt_connection_info
                self.mqtt_client = asyncio_mqtt.Client(
                    hostname=mqtt_host,
                    username=mqtt_user,
                    password=mqtt_pass,
                    will=asyncio_mqtt.Will(topic=f"worker/{self.worker_id}/available", payload="0", qos=1, retain=True),
                    clean_session=False,
                    client_id=self.worker_id,
                )
                await self.mqtt_client.connect()

                self.amqp_connection = await aio_pika.connect_robust(
                    self._amqp_connection_str,
                    loop=self.loop,
                )
                self.trade_channel = await self.amqp_connection.channel()
                await self.trade_channel.set_qos(1)
                self.control_channel = await self.amqp_connection.channel()

                # Declare an exchange
                self.trade_exchange = await self.trade_channel.declare_exchange(
                    name="trade_requests", type=aio_pika.ExchangeType.TOPIC, durable=True
                )
                self.control_exchange = await self.control_channel.declare_exchange(
                    name="control_requests", type=aio_pika.ExchangeType.TOPIC, durable=True
                )

                # Declaring queues
                task_queue = await self.trade_channel.declare_queue(
                    name=f"{self.system}_bn{self.game}_task_queue", durable=True, arguments={"x-max-priority": 100}
                )
                await task_queue.bind(self.trade_exchange, routing_key=f"requests.{self.system}.bn{self.game}")
                self.task_queue = task_queue

                control_queue = await self.control_channel.declare_queue(name=f"control_queue_{self.worker_id[:8]}")
                await control_queue.bind(self.control_exchange, routing_key=f"control.{self.worker_id}")
                self.control_queue = control_queue
                await self.control_queue.consume(self.on_control_request, no_ack=True)

                self.notification_queue = await self.trade_channel.declare_queue(
                    name="trade_status_update", durable=True
                )

                logger.info("Going into mqtt update loop")
                await self.update_mqtt_info()
            except Exception as e:
                logger.exception(f"Exception in mqtt/amqp handlers", exc_info=e)

    async def on_trade_request(self, message: AbstractIncomingMessage) -> None:
        async with self.trade_lock:
            try:
                async with message.process(requeue=True, ignore_processed=True):
                    if not self.should_consume_queue:
                        logger.error(
                            f"Received message {message.correlation_id} even though task queue shouldn't be consumed!"
                        )
                        await message.nack(requeue=True)
                        return

                    if message.reply_to is None:
                        logger.error(f"Received message {message.correlation_id} without reply to! Ignoring")
                        await message.ack()
                        return

                    try:
                        request = TradeRequest.from_bytes(message.body)
                    except Exception:
                        logger.error(
                            f"Received message {message.correlation_id} that couldn't be deserialized! Ignoring: {message.body}"
                        )
                        await message.ack()
                        return
                    logger.info(f"Received request: {request.trade_id} - {request.trade_item}")
                    if self.last_seen_id > request.trade_id and not message.redelivered:
                        logger.info(f"Skipping message: {self.last_seen_id} > {request.trade_id}")
                        await message.ack()
                        return
                    elif self.last_seen_id < request.trade_id and not message.redelivered and message.priority == 0:
                        self.last_seen_id = request.trade_id

                    response = TradeResponse(
                        request, self.worker_id, TradeResponse.IN_PROGRESS, message=None, image=None
                    )
                    await self.trade_exchange.publish(
                        Message(
                            body=response.to_bytes(),
                            content_type="application/json",
                            correlation_id=message.correlation_id,
                        ),
                        routing_key=message.reply_to,
                    )

                    room_code_future = asyncio.Future()
                    if isinstance(request.trade_item, Chip):
                        trade_completed = asyncio.create_task(self.trader.trade_chip(request, room_code_future))
                    else:
                        trade_completed = asyncio.create_task(self.trader.trade_ncp(request, room_code_future))

                    logger.info("Waiting for room code")
                    try:
                        image_bytestring = await room_code_future
                        response = TradeResponse(
                            request,
                            self.worker_id,
                            TradeResponse.IN_PROGRESS,
                            message="Room code",
                            image=image_bytestring,
                        )
                        logger.info(f"Sending room code to {message.reply_to}")
                        await self.trade_exchange.publish(
                            Message(
                                body=response.to_bytes(),
                                content_type="application/json",
                                correlation_id=message.correlation_id,
                            ),
                            routing_key=message.reply_to,
                        )
                    except asyncio.CancelledError:
                        logger.warning("Room code future was cancelled")

                    trade_result, trader_message = await trade_completed

                    response = TradeResponse(request, self.worker_id, trade_result, message=trader_message)
                    logger.info(f"Sending finish message to {message.reply_to}")
                    await self.trade_exchange.publish(
                        Message(
                            body=response.to_bytes(),
                            content_type="application/json",
                            correlation_id=message.correlation_id,
                        ),
                        routing_key=message.reply_to,
                    )
                    if trade_result in [TradeResponse.SUCCESS, TradeResponse.CANCELLED, TradeResponse.USER_TIMEOUT]:
                        logger.warning(f"Trade finished: {trade_result, trader_message}")
                        await message.ack()
                    else:
                        logger.warning(f"Trade error: {trade_result, trader_message}")
                        await message.nack(requeue=True)

                    if trade_result == TradeResponse.CRITICAL_FAILURE:
                        logger.warning(f"Disabling worker: {trade_result, trader_message}")
                        await self.mqtt_client.publish(
                            topic=f"worker/{self.worker_id}/enabled", payload=0, qos=1, retain=True
                        )
                        logger.warning(f"Attempting to restart worker")
                        try:
                            if await self.trader.reset():
                                await self.mqtt_client.publish(
                                    topic=f"worker/{self.worker_id}/enabled", payload=1, qos=1, retain=True
                                )
                            else:
                                response = TradeResponse(
                                    request,
                                    self.worker_id,
                                    trade_result,
                                    message="Resetting failed. Worker requires attention.",
                                )
                                await self.trade_exchange.publish(
                                    Message(
                                        body=response.to_bytes(),
                                        content_type="application/json",
                                        correlation_id=message.correlation_id,
                                    ),
                                    routing_key=message.reply_to,
                                )
                        except NotImplementedError:
                            response = TradeResponse(
                                request,
                                self.worker_id,
                                trade_result,
                                message="Resetting not implemented. Worker requires attention.",
                            )
                            await self.trade_exchange.publish(
                                Message(
                                    body=response.to_bytes(),
                                    content_type="application/json",
                                    correlation_id=message.correlation_id,
                                ),
                                routing_key=message.reply_to,
                            )
            except Exception as e:
                logger.exception("Processing error for message %r", message)
                import traceback

                traceback.print_exc()
                await self.mqtt_client.publish(topic=f"worker/{self.worker_id}/enabled", payload=0, qos=1, retain=True)
                await message.nack(requeue=True)


def signal_handler(sig, frame, worker: TradeWorker):
    logger.warning(f"Received {sig} {frame}, waiting for trade lock...")
    loop = asyncio.get_running_loop()
    fut = asyncio.run_coroutine_threadsafe(worker.trade_lock.acquire(), loop)
    fut.result()
    logger.warning("Exiting due to signal")
    exit(0)


async def init_switch_worker(game: int) -> AbstractAutoTrader:
    from nx.controller.sinks import SocketSink

    from mrprog.worker.switch_auto_trader import SwitchAutoTrader

    sink = SocketSink("127.0.0.1", 3000)
    socket = await sink.connect()
    controller = Controller(socket)

    # Let the screen pop up if needed
    controller.press_button(Button.Nothing, wait_ms=2000)
    await controller.wait_for_inputs()
    if (
        image_processing.run_tesseract_line(image_processing.capture(), (1000, 1000), (460, 460))
        == "Controller Not Connecting"
    ):
        logger.info("Found controller connect screen, connecting")
        controller.press_button(Button.L + Button.R, hold_ms=100, wait_ms=2000)
        controller.press_button(Button.A, hold_ms=100, wait_ms=2000)
        await controller.wait_for_inputs()

    return SwitchAutoTrader(controller, game)


async def init_steam_worker(game: int) -> AbstractAutoTrader:
    from nx.controller.sinks import WindowsNamedPipeSink

    from mrprog.worker.steam_auto_trader import SteamAutoTrader

    sink = WindowsNamedPipeSink()
    pipe = sink.connect_to_pipe()
    controller = Controller(pipe)

    return SteamAutoTrader(controller, game)


async def main():
    trader_init_functions = {"switch": init_switch_worker, "steam": init_steam_worker}

    parser = argparse.ArgumentParser(prog="Mr. Prog Trade Worker", description="Trade worker process for Mr. Prog")
    parser.add_argument("--host", required=True)  # positional argument
    parser.add_argument("--username", required=True)  # option that takes a value
    parser.add_argument("--password", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--game", type=int, required=True)
    parser.add_argument("--hostname", required=False)
    args = parser.parse_args()

    install_logger(args.host, args.username, args.password)

    trader = await trader_init_functions[args.platform](args.game)
    worker = TradeWorker(
        trader, args.hostname or platform.node(), args.host, args.username, args.password, args.platform, args.game
    )
    await worker.run()


if __name__ == "__main__":
    if sys.platform.lower() == "win32" or os.name.lower() == "nt":
        # only import if platform/os is win32/nt, otherwise "WindowsSelectorEventLoopPolicy" is not present
        from asyncio import WindowsSelectorEventLoopPolicy, set_event_loop_policy

        # set the event loop
        set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
