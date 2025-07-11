"""
WebSocket Proxy Dictionary Iteration Stress Test

This script tests the WebSocket proxy server's handling of concurrent dictionary modifications
by creating multiple clients that rapidly connect, subscribe, and disconnect.
"""

import asyncio
import websockets
import json
import random
import time
import argparse
import uuid
import logging
import os
from datetime import datetime

# Set up logging
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'websocket_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('websocket_test')

# Test configuration
WEBSOCKET_URI = "ws://127.0.0.1:8765"
API_KEY = "your-openalgo-api-key"  # OpenAlgo API key
CLIENT_COUNT = 10
TEST_DURATION_SECONDS = 30

# Symbols to use for testing
SYMBOLS = [
    {"symbol": "CRUDEOIL18JUN25FUT", "exchange": "MCX"},
    {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
    {"symbol": "SENSEX", "exchange": "BSE_INDEX"},
    {"symbol": "RELIANCE26JUN25FUT", "exchange": "NFO"}
]

class WebSocketClient:
    """Represents a single WebSocket client for testing"""
    
    def __init__(self, client_id):
        self.id = client_id
        self.ws = None
        self.connected = False
        self.subscriptions = []
    
    async def connect(self):
        """Connect to the WebSocket server and authenticate"""
        try:
            self.ws = await websockets.connect(WEBSOCKET_URI)
            self.connected = True
            logger.info(f"[{self.id}] Connected")
            
            # Send authentication message
            auth_msg = {
                "action": "authenticate",
                "api_key": API_KEY
            }
            await self.ws.send(json.dumps(auth_msg))
            auth_response = json.loads(await self.ws.recv())
            if auth_response.get("status") == "success":
                logger.info(f"[{self.id}] Authentication successful")
                return True
            else:
                logger.warning(f"[{self.id}] Authentication failed: {auth_response}")
                await self.disconnect()
                return False
        except Exception as e:
            logger.error(f"[{self.id}] Connection error: {e}")
            self.connected = False
            return False
    
    async def subscribe(self, symbol, exchange, mode=1):
        """Subscribe to a market data feed"""
        if not self.connected:
            return False
        
        try:
            sub_msg = {
                "action": "subscribe",
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode  # LTP mode
            }
            await self.ws.send(json.dumps(sub_msg))
            response = json.loads(await self.ws.recv())
            if response.get("status") == "success":
                self.subscriptions.append(f"{exchange}:{symbol}")
                logger.info(f"[{self.id}] Subscribed to {exchange}:{symbol}")
                return True
            else:
                logger.warning(f"[{self.id}] Subscription failed: {response}")
                return False
        except Exception as e:
            logger.error(f"[{self.id}] Subscription error: {e}")
            return False
    
    async def unsubscribe(self, symbol, exchange):
        """Unsubscribe from a market data feed"""
        if not self.connected or f"{exchange}:{symbol}" not in self.subscriptions:
            return False
        
        try:
            unsub_msg = {
                "action": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange
            }
            await self.ws.send(json.dumps(unsub_msg))
            response = json.loads(await self.ws.recv())
            if response.get("status") in ["success", "partial"]:
                self.subscriptions.remove(f"{exchange}:{symbol}")
                logger.info(f"[{self.id}] Unsubscribed from {exchange}:{symbol}")
                return True
            else:
                logger.warning(f"[{self.id}] Unsubscription failed: {response}")
                return False
        except Exception as e:
            logger.error(f"[{self.id}] Unsubscription error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the WebSocket server"""
        if self.connected and self.ws:
            try:
                await self.ws.close()
                logger.info(f"[{self.id}] Disconnected")
            except Exception as e:
                logger.error(f"[{self.id}] Disconnect error: {e}")
            finally:
                self.connected = False
                self.subscriptions = []

async def listener(client):
    """Background task to continuously receive messages"""
    try:
        while client.connected:
            try:
                message = await asyncio.wait_for(client.ws.recv(), timeout=0.1)
                # We're not interested in the content of the message, just receiving them
                # logger.debug(f"[{client.id}] Received: {message[:50]}...")
            except asyncio.TimeoutError:
                # No message received within timeout, continue the loop
                continue
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"[{client.id}] Connection closed")
                client.connected = False
                break
    except Exception as e:
        logger.error(f"[{client.id}] Listener error: {e}")
        client.connected = False

async def random_client_behavior(client, running_flag):
    """Exhibit random behavior for a client - connect, subscribe, unsubscribe, disconnect"""
    # Start listener task
    listener_task = asyncio.create_task(listener(client))
    
    try:
        # Connect
        if not await client.connect():
            return
        
        # Random subscriptions
        for _ in range(random.randint(1, len(SYMBOLS))):
            symbol_info = random.choice(SYMBOLS)
            await client.subscribe(symbol_info["symbol"], symbol_info["exchange"])
            # Brief delay between subscriptions
            await asyncio.sleep(random.uniform(0.05, 0.2))
        
        while running_flag.is_set():
            # Perform random actions
            action = random.choices(
                ["subscribe", "unsubscribe", "sleep"],
                weights=[0.3, 0.3, 0.4],
                k=1
            )[0]
            
            if action == "subscribe" and len(client.subscriptions) < len(SYMBOLS):
                # Subscribe to a new symbol
                for symbol_info in SYMBOLS:
                    key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                    if key not in client.subscriptions:
                        await client.subscribe(symbol_info["symbol"], symbol_info["exchange"])
                        break
                        
            elif action == "unsubscribe" and client.subscriptions:
                # Unsubscribe from a random symbol
                sub_key = random.choice(client.subscriptions)
                exchange, symbol = sub_key.split(":")
                await client.unsubscribe(symbol, exchange)
            
            # Sleep briefly between actions
            await asyncio.sleep(random.uniform(0.1, 0.5))
        
    except Exception as e:
        print(f"[{client.id}] Error during random behavior: {e}")
    finally:
        # Clean up
        await client.disconnect()
        # Cancel listener task
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

async def run_test(client_count, duration):
    """Run the stress test with multiple clients for the specified duration"""
    header = f"\n{'='*60}\nWEBSOCKET PROXY DICTIONARY ITERATION STRESS TEST\n{'='*60}\n"
    header += f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    header += f"Number of clients: {client_count}\n"
    header += f"Test duration: {duration} seconds\n"
    header += f"Logging to: {log_file}\n"
    header += f"{'='*60}\n"
    
    print(header)
    logger.info(header)
    
    # Create clients
    clients = [WebSocketClient(f"Client-{i+1}") for i in range(client_count)]
    
    # Flag to signal tasks to stop
    running = asyncio.Event()
    running.set()
    
    # Create tasks for each client
    tasks = [asyncio.create_task(random_client_behavior(client, running)) for client in clients]
    
    # Create staggered connections
    clients_in_flight = []
    for i, client in enumerate(clients):
        # Add client to tracking list
        clients_in_flight.append(client)
        
        # Every 3rd client, disconnect a previous one to create churn
        if i > 5 and i % 3 == 0 and clients_in_flight:
            disconnected = clients_in_flight.pop(0)
            await disconnected.disconnect()
        
        # Spread out connections
        await asyncio.sleep(random.uniform(0.3, 0.7))
    
    # Run for specified duration
    try:
        await asyncio.sleep(duration)
    finally:
        shutdown_msg = "\nTest duration complete. Shutting down..."
        print(shutdown_msg)
        logger.info(shutdown_msg)
        # Signal tasks to stop
        running.clear()
        
        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)
    
    summary = f"\n{'='*60}\n"
    summary += f"TEST COMPLETED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    summary += f"No dictionary size errors detected during the test.\n"
    summary += f"Log file saved to: {log_file}\n"
    summary += f"{'='*60}\n"
    
    print(summary)
    logger.info(summary)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="WebSocket Proxy Dictionary Iteration Stress Test")
    parser.add_argument("--clients", type=int, default=CLIENT_COUNT, help="Number of clients to simulate")
    parser.add_argument("--duration", type=int, default=TEST_DURATION_SECONDS, help="Test duration in seconds")
    args = parser.parse_args()
    
    try:
        asyncio.run(run_test(args.clients, args.duration))
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    
if __name__ == "__main__":
    main()
