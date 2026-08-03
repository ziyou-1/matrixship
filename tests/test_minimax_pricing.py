import unittest

from backend.utils.minimax_pricing import published_unit_price


class MiniMaxH3PricingHoldTest(unittest.TestCase):
    def test_h3_price_is_unresolved_and_never_invented(self):
        self.assertIsNone(
            published_unit_price(
                model="MiniMax-H3",
                mode="video_generation",
                duration=4,
                resolution="768P",
            )
        )

    def test_unknown_h3_price_is_also_unresolved(self):
        self.assertIsNone(
            published_unit_price(
                model="MiniMax-H3",
                mode="video_generation",
                duration=15,
                resolution="2K",
            )
        )


if __name__ == "__main__":
    unittest.main()
