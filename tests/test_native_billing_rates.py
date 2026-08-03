from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class NativeBillingRatesTest(unittest.TestCase):
    def test_native_client_displays_one_to_one_recharge_packages(self):
        source = CLIENT.read_text(encoding="utf-8")

        self.assertIn("PACKAGES = [(6, 6), (30, 30), (68, 68), (128, 128), (298, 298), (648, 648)]", source)
        self.assertIn('QLabel("选择充值金额(1 元 = 1 云豆)")', source)

    def test_native_client_local_prices_use_one_yundou_per_yuan(self):
        source = CLIENT.read_text(encoding="utf-8")

        self.assertIn('"product_video": 5.57', source)
        self.assertIn('"copywriting": 0.24', source)
        self.assertIn('"digital_human": 9.81', source)


if __name__ == "__main__":
    unittest.main()
