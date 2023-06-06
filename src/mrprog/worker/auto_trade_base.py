from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
from abc import ABC, abstractmethod
from queue import Queue
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from mmbn.gamedata.bn3 import bn3_chip_list, bn3_ncp_list
from mmbn.gamedata.bn6 import bn6_chip_list, bn6_ncp_list
from mmbn.gamedata.chip import Chip, Sort
from mmbn.gamedata.navicust_part import NaviCustPart
from mrprog.utils.trade import TradeRequest, TradeResponse
from nx.automation import image_processing
from nx.automation.script import MatchArgs, Script
from nx.controller import Button, Controller, DPad

T = TypeVar("T")
logger = logging.getLogger(__file__)


MODULES: Dict[int, Any] = {3: (bn3_chip_list, bn3_ncp_list), 6: (bn6_chip_list, bn6_ncp_list)}

STARTING_NCP = {3: "SprArmor", 6: "SuprArmr"}


class Node(Generic[T]):
    def __init__(self, obj: T):
        self.obj = obj
        self.neighbors: Dict[Union[Button, DPad], Node[T]] = {}

    def add(self, node: "Node[T]", button: Union[Button, DPad]) -> "Node[T]":
        self.neighbors[button] = node
        return self

    def __repr__(self) -> str:
        return repr(self.obj)

    def __hash__(self) -> int:
        return hash(self.obj)

    def search(self, target: T) -> List[Tuple[Union[Button, DPad], "Node[T]"]]:
        if self.obj == target:
            return []

        visited = set()
        q: Queue[Tuple[Node[T], List[Union[Button, DPad]], List[Node[T]]]] = Queue()
        q.put((self, [], []))
        visited.add(self)

        shortest = None

        while not q.empty():
            node, path, visited_nodes = q.get()
            if node.obj == target and (shortest is None or len(shortest) > len(path)):
                shortest = list(zip(path, visited_nodes))
            for controller_input, neighbor in node.neighbors.items():
                if neighbor not in visited:
                    visited.add(neighbor)
                    q.put((neighbor, path + [controller_input], visited_nodes + [neighbor]))

        if shortest is not None:
            return shortest

        raise RuntimeError(f"Path from {str(self.obj)} to {str(target)} not found")


def build_input_graph(obj_list: List[T]) -> List[Node[T]]:
    nodes = [Node(obj) for obj in obj_list]
    for i in range(1, len(nodes) - 1):
        node = nodes[i]
        node.add(nodes[min((i + 8), len(nodes) - 1)], Button.R)
        node.add(nodes[max((i - 8), 0)], Button.L)
        node.add(nodes[(i + 1) % len(nodes)], DPad.Down)
        node.add(nodes[(i - 1) % len(nodes)], DPad.Up)

    start = nodes[0]
    end = nodes[-1]

    start.add(nodes[1], DPad.Down)
    start.add(end, DPad.Up)
    start.add(nodes[8], Button.R)
    start.add(end, Button.L)

    end.add(start, DPad.Down)
    end.add(nodes[-2], DPad.Up)
    end.add(start, Button.R)
    end.add(nodes[-9], Button.L)
    return nodes


class AbstractAutoTrader(Script, ABC):
    def __init__(self, controller: Controller, game: int):
        super().__init__(controller)
        self.game = game

        chip_list, ncp_list = MODULES[game]
        ncp_nothing = ncp_list.NOTHING
        all_parts = ncp_list.TRADABLE_PARTS
        tradable_chip_order = chip_list.TRADABLE_CHIP_ORDER

        self.root_chip_node = self.build_all_chip_input_graphs(tradable_chip_order)
        self.root_ncp_node = self.build_ncp_input_graph(all_parts, ncp_nothing)

    @staticmethod
    def build_all_chip_input_graphs(tradable_chip_order) -> Node[Chip]:
        graphs = [build_input_graph(tradable_chip_order[sort]) for sort in Sort]
        id_root = graphs[0][0]
        abcde_root = graphs[1][0]
        code_root = graphs[2][0]
        atk_root = graphs[3][0]
        element_root = graphs[4][0]
        no_root = graphs[5][0]
        mb_root = graphs[6][0]

        id_root.add(abcde_root, Button.Plus)
        abcde_root.add(code_root, Button.Plus)
        code_root.add(atk_root, Button.Plus)
        atk_root.add(element_root, Button.Plus)
        element_root.add(no_root, Button.Plus)
        no_root.add(mb_root, Button.Plus)
        mb_root.add(id_root, Button.Plus)
        return id_root

    @staticmethod
    def build_ncp_input_graph(ncp_list, ncp_nothing) -> Node[NaviCustPart]:
        ncp_graph = build_input_graph(ncp_list + [ncp_nothing])
        return ncp_graph[0]

    def calculate_chip_inputs(self, chip: Chip) -> List[Tuple[Union[Button, DPad], Node[Chip]]]:
        return self.root_chip_node.search(chip)

    def calculate_ncp_inputs(self, ncp: NaviCustPart) -> List[Tuple[Union[Button, DPad], Node[NaviCustPart]]]:
        result = self.root_ncp_node.search(ncp)
        return result

    @abstractmethod
    async def reload_save(self):
        # TODO: Implement
        pass

    async def navigate_to_chip_trade_screen(self) -> bool:
        # navigate to trade screen
        # Trade
        await self.down()
        await self.a()

        # Private Trade
        await self.down()
        await self.a()

        # Create Room
        await self.a()

        # Chip Trade
        await self.a()

        # Next
        await self.a()

        logger.debug("Waiting for chip select")
        return await self.wait_for_text(lambda ocr_text: ocr_text == "Sort : ID", (1054, 205), (162, 48), 10)

    async def navigate_to_ncp_trade_screen(self) -> bool:
        # navigate to trade screen
        # Trade
        await self.down()
        await self.a()

        # Private Trade
        await self.down()
        await self.a()

        # Create Room
        await self.a()

        # Program Trade
        await self.down()
        await self.a()

        # Next
        await self.a()

        logger.info("Waiting for ncp select")
        return await self.wait_for_text(
            lambda ocr_text: ocr_text == STARTING_NCP[self.game], (1080, 270), (200, 60), timeout=10, invert=False
        )

    """
    def check_lowest_chip_qty(self) -> int:
        self.navigate_to_trade_screen()
        self.repeat(self.plus, 5)
        self.repeat(self.up, 2)
        _, frame = self.capture.read()
        image_processing.run_tesseract_line(frame, top_left, size, invert)
    """

    @staticmethod
    def check_for_cancel(
        trade_cancelled: multiprocessing.Event, cancel_trade_for_user_id: multiprocessing.Value, user_id: int
    ) -> bool:
        cancel_lock = cancel_trade_for_user_id.get_lock()

        cancel_lock.acquire()
        if cancel_trade_for_user_id.value == user_id:
            cancel_trade_for_user_id.value = 0
            trade_cancelled.set()
            cancel_lock.release()
            return True
        trade_cancelled.set()
        cancel_lock.release()
        return False

    def handle_trade_failed(self) -> MatchArgs:
        async def handler() -> Tuple[int, Optional[str]]:
            await self.wait(1000)
            await self.a(wait_time=1000)
            return TradeResponse.RETRYING, "The trade failed. Retrying."

        return lambda text: text == "The guest has already left.", handler, (660, 440), (620, 50), True

    def handle_communication_error(self) -> MatchArgs:
        async def handler() -> Tuple[int, Optional[str]]:
            logger.warning("Communication error, restarting trade")
            await self.wait(1000)
            await self.a(wait_time=1000)
            return TradeResponse.RETRYING, "There was a communication error. Retrying."

        return lambda text: text == "A communication error occurred.", handler, (660, 440), (620, 50), True

    def handle_guest_already_left(self) -> MatchArgs:
        async def handler() -> Tuple[int, Optional[str]]:
            await self.wait(12000)
            await self.b(wait_time=1000)
            await self.a(wait_time=1000)
            return TradeResponse.CANCELLED, "User left the room, trade cancelled."

        return lambda text: text == "The trade failed.", handler, (800, 400), (335, 65), True

    def handle_trade_complete(self) -> MatchArgs:
        async def handler() -> Tuple[int, Optional[str]]:
            await self.a(wait_time=1000)
            if await self.wait_for_text(lambda ocr_text: ocr_text == "NETWORK", (55, 65), (225, 50), 10):
                logger.debug("Back at main menu")
                await self.wait(2000)
                return TradeResponse.SUCCESS, None
            else:
                return (
                    TradeResponse.CRITICAL_FAILURE,
                    "I think the trade was successful, but something broke.",
                )

        return lambda text: text == "Trade complete!", handler, (815, 440), (310, 55), True

    async def trade(
        self,
        trade_request: TradeRequest,
        navigate_func: Callable[[], Awaitable[bool]],
        input_tuples: List[Tuple[Union[Button, DPad], Node[T]]],
        room_code_future: asyncio.Future,
    ) -> Tuple[int, Optional[str]]:
        try:
            logger.info(f"Trading {trade_request.trade_item}")

            success = await navigate_func()
            if not success:
                room_code_future.cancel()
                return TradeResponse.CRITICAL_FAILURE, "Unable to open trade screen."

            for controller_input, selected_chip in input_tuples:
                if isinstance(controller_input, DPad):
                    self.controller.press_dpad(controller_input)
                else:
                    self.controller.press_button(controller_input)

            """
            if self.check_for_cancel(trade_cancelled, cancel_trade_for_user_id, discord_context.user_id):
                self.repeat(self.b, 5, wait_time=200)
                self.up()
                return TradeResult.Cancelled, "Trade cancelled by user."
            """

            await self.a()
            await self.a()

            logger.debug("Searching for room code")
            if not await self.wait_for_text(
                lambda ocr_text: ocr_text.startswith("Room Code:"), (1242, 89), (365, 54), 15
            ):
                room_code_future.cancel()
                return TradeResponse.CRITICAL_FAILURE, "Unable to retrieve room code."

            frame = image_processing.capture(convert=True)
            room_code_image = image_processing.crop_to_bounding_box(frame, (1242, 89), (400, 80), invert=True)
            image_bytestring = image_processing.convert_image_to_png_bytestring(room_code_image)

            # Send room code back to consumer
            room_code_future.set_result(image_bytestring)
            await asyncio.sleep(0)

            start_time = time.time()
            logger.debug("Waiting 180s for user")
            while time.time() < start_time + 180:
                await asyncio.sleep(1)
                """
                if self.check_for_cancel(trade_cancelled, discord_context.user_id):
                    self.b(wait_time=1000)
                    self.a(wait_time=1000)
                    logger.info("Cancelling trade because user didn't respond within 180 seconds")
                    return TradeResult.Cancelled, "Trade cancelled by user."
                """

                result = await self.match(self.handle_guest_already_left(), self.handle_communication_error())
                if result is not None:
                    return result

                text = image_processing.run_tesseract_line(image_processing.capture(), (785, 123), (160, 60))
                if text == "1/15":
                    logger.debug("User joined lobby")
                    await self.wait(500)
                    await self.a(wait_time=1000)

                    result = await self.match(self.handle_guest_already_left())
                    if result is not None:
                        return result

                    await self.a()

                    result = await self.match(self.handle_guest_already_left())
                    if result is not None:
                        return result

                    logger.debug("User completed trade")

                    try:
                        return await self.wait_for_match(
                            self.handle_guest_already_left(),
                            self.handle_trade_failed(),
                            self.handle_trade_complete(),
                            timeout=30,
                        )
                    except TimeoutError:
                        return TradeResponse.CRITICAL_FAILURE, "Trade failed due to an unexpected state."

            await self.b(wait_time=1000)
            await self.a(wait_time=1000)
            return TradeResponse.USER_TIMEOUT, "Trade cancelled due to timeout."
        except Exception as e:
            room_code_future.cancel()
            return TradeResponse.CRITICAL_FAILURE, f"Trade failed due to an error: {e}"

    async def trade_chip(
        self, trade_request: TradeRequest, room_code_future: asyncio.Future
    ) -> Tuple[int, Optional[str]]:
        return await self.trade(
            trade_request,
            self.navigate_to_chip_trade_screen,
            self.calculate_chip_inputs(trade_request.trade_item),
            room_code_future,
        )

    async def trade_ncp(
        self, trade_request: TradeRequest, room_code_future: asyncio.Future
    ) -> Tuple[int, Optional[str]]:
        return await self.trade(
            trade_request,
            self.navigate_to_ncp_trade_screen,
            self.calculate_ncp_inputs(trade_request.trade_item),
            room_code_future,
        )
