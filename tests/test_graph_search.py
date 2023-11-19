import itertools
from typing import Dict

import pytest

from mmbn.gamedata.chip import Chip, Sort
from mmbn.gamedata.chip_list import ChipList
from mmbn.gamedata.navicust_part import NaviCustPart
from mmbn.gamedata.ncp_list import NcpList
from mock_auto_trader import MockAutoTrader


GAMES = [3, 4, 5, 6]


class TestGraphSearch:
    @pytest.fixture(scope="session")
    def traders(self):
        return {game: MockAutoTrader(game) for game in GAMES}

    @pytest.mark.parametrize("game,chip",
                             itertools.chain.from_iterable([[(game, chip) for chip in ChipList(game).tradable_chips] for game in GAMES]))
    def test_chip_graph_search(self, game: int, traders: Dict[int, MockAutoTrader], chip: Chip):
        traders[game].calculate_chip_inputs(chip)

    @pytest.mark.parametrize("game,ncp",
                             itertools.chain.from_iterable([[(game, ncp) for ncp in NcpList(game).tradable_parts] for game in GAMES]))
    def test_ncp_graph_search(self, game: int, traders: Dict[int, MockAutoTrader], ncp: NaviCustPart):
        traders[game].calculate_ncp_inputs(ncp)
