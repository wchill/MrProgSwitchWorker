import pytest

from mmbn.gamedata.bn3 import bn3_chip_list, bn3_ncp_list
from mmbn.gamedata.bn6 import bn6_chip_list, bn6_ncp_list
from mmbn.gamedata.chip import Chip
from mmbn.gamedata.navicust_part import NaviCustPart
from mock_auto_trader import MockAutoTrader


class TestGraphSearch:
    @pytest.mark.parametrize("game,chip",
                             [(3, chip) for chip in bn3_chip_list.TRADABLE_CHIPS] + [(6, chip) for chip in bn6_chip_list.TRADABLE_CHIPS])
    def test_chip_graph_search(self, game: int, chip: Chip):
        trader = MockAutoTrader(game)
        trader.calculate_chip_inputs(chip)

    @pytest.mark.parametrize("game,ncp",
                             [(3, ncp) for ncp in bn3_ncp_list.TRADABLE_PARTS] + [(6, ncp) for ncp in bn6_ncp_list.TRADABLE_PARTS])
    def test_ncp_graph_search(self, game: int, ncp: NaviCustPart):
        trader = MockAutoTrader(game)
        trader.calculate_ncp_inputs(ncp)
