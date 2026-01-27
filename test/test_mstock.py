import os
import unittest

from dotenv import load_dotenv
from openalgo import api as OAClient

# Load environment variables from .env file
load_dotenv()


class TestMstockBroker(unittest.TestCase):
    def setUp(self):
        """Set up for the test case."""
        # The test assumes that the OpenAlgo server is running and
        # the user is already logged into the mstock broker.
        self.api_key = os.getenv(
            "OPENALGO_API_KEY", "3bb8d260915ff680a7258108c0483b9eb7675ced31309a36f5846366943ee9fa"
        )
        self.client = OAClient(api_key=self.api_key, host="http://127.0.0.1:5000")

    def test_place_order(self):
        """Test placing a simple order."""
        # This test requires an active mstock session in the OpenAlgo server
        order_response = self.client.placeorder(
            strategy="TEST",
            symbol="TCS",
            exchange="NSE",
            price_type="MARKET",
            product="MIS",
            action="BUY",
            quantity=1,
        )
        self.assertEqual(order_response.get("status"), "success")
        self.assertIn("orderid", order_response)

    def test_get_positions(self):
        """Test retrieving positions."""
        positions_response = self.client.positionbook()
        self.assertEqual(positions_response.get("status"), "success")

    def test_get_holdings(self):
        """Test retrieving holdings."""
        holdings_response = self.client.holdings()
        self.assertEqual(holdings_response.get("status"), "success")

    def test_get_funds(self):
        """Test retrieving funds."""
        funds_response = self.client.funds()
        self.assertEqual(funds_response.get("status"), "success")


if __name__ == "__main__":
    unittest.main()
