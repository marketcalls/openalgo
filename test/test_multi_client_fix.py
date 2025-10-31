#!/usr/bin/env python3
"""
Test script to demonstrate the multi-client subscription fix.
This script simulates multiple clients subscribing to the same symbol
and verifies that unsubscribing one client doesn't affect others.
"""

import asyncio
import websockets
import json
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebSocketClient:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.websocket = None
        self.received_messages = []
        
    async def connect(self, uri: str):
        """Connect to WebSocket server"""
        try:
            self.websocket = await websockets.connect(uri)
            logger.info(f"Client {self.client_id} connected to {uri}")
            return True
        except Exception as e:
            logger.error(f"Client {self.client_id} failed to connect: {e}")
            return False
    
    async def authenticate(self, api_key: str):
        """Authenticate with the server"""
        auth_message = {
            "action": "authenticate",
            "api_key": api_key
        }
        await self.send_message(auth_message)
        
    async def subscribe(self, symbol: str, exchange: str, mode: str = "Quote"):
        """Subscribe to market data"""
        subscribe_message = {
            "action": "subscribe",
            "symbols": [{
                "symbol": symbol,
                "exchange": exchange
            }],
            "mode": mode
        }
        await self.send_message(subscribe_message)
        
    async def unsubscribe(self, symbol: str, exchange: str, mode: str = "Quote"):
        """Unsubscribe from market data"""
        unsubscribe_message = {
            "action": "unsubscribe",
            "symbols": [{
                "symbol": symbol,
                "exchange": exchange
            }],
            "mode": mode
        }
        await self.send_message(unsubscribe_message)
        
    async def send_message(self, message: dict):
        """Send a message to the server"""
        if self.websocket:
            await self.websocket.send(json.dumps(message))
            logger.info(f"Client {self.client_id} sent: {message}")
    
    async def listen_for_messages(self, duration: int = 10):
        """Listen for messages from the server"""
        start_time = time.time()
        try:
            while time.time() - start_time < duration:
                if self.websocket:
                    try:
                        message = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        self.received_messages.append(data)
                        logger.info(f"Client {self.client_id} received: {data.get('type', 'unknown')} - {data.get('symbol', 'N/A')}")
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        logger.info(f"Client {self.client_id} connection closed")
                        break
        except Exception as e:
            logger.error(f"Client {self.client_id} error listening: {e}")
    
    async def close(self):
        """Close the WebSocket connection"""
        if self.websocket:
            await self.websocket.close()
            # Wait for connection to close cleanly
            await asyncio.sleep(0.5)  # Give time for proper WebSocket closure
            logger.info(f"Client {self.client_id} disconnected")

async def test_multi_client_subscription():
    """Test multi-client subscription scenario"""
    logger.info("Starting multi-client subscription test...")
    
    # Test configuration
    WEBSOCKET_URI = "ws://127.0.0.1:8765"
    API_KEY = "your-openalgo-api-key"  # Replace with actual API key
    SYMBOL = "CRUDEOIL17NOV255450CE"
    EXCHANGE = "MCX"
    
    # Create multiple clients
    clients = []
    for i in range(3):
        client = WebSocketClient(f"client_{i+1}")
        clients.append(client)
    
    try:
        # Connect all clients
        logger.info("Connecting all clients...")
        for client in clients:
            if not await client.connect(WEBSOCKET_URI):
                logger.error(f"Failed to connect client {client.client_id}")
                return
        
        # Authenticate all clients
        logger.info("Authenticating all clients...")
        for client in clients:
            await client.authenticate(API_KEY)
            await asyncio.sleep(0.1)  # Small delay between authentications
        
        # Subscribe all clients to the same symbol
        logger.info(f"Subscribing all clients to {SYMBOL}.{EXCHANGE}...")
        for client in clients:
            await client.subscribe(SYMBOL, EXCHANGE)
            await asyncio.sleep(0.1)  # Small delay between subscriptions
        
        # Start listening for messages in parallel
        logger.info("Starting message listeners...")
        listen_tasks = []
        for client in clients:
            task = asyncio.create_task(client.listen_for_messages(duration=15))
            listen_tasks.append(task)
        
        # Let clients receive data for a few seconds
        logger.info("Waiting for market data...")
        await asyncio.sleep(5)
        
        # Check that all clients are receiving data
        for i, client in enumerate(clients):
            market_data_count = len([msg for msg in client.received_messages if msg.get('type') == 'market_data'])
            logger.info(f"Client {client.client_id} received {market_data_count} market data messages")
            assert market_data_count > 0, f"Client {client.client_id} should have received market data before unsubscription"
        
        # Store counts before unsubscription
        counts_before_unsub = []
        for i, client in enumerate(clients):
            market_data_count = len([msg for msg in client.received_messages if msg.get('type') == 'market_data'])
            counts_before_unsub.append(market_data_count)
            logger.info(f"Client {client.client_id} received {market_data_count} market data messages before unsubscription")
        
        # Now unsubscribe one client
        logger.info("Unsubscribing client_1...")
        await clients[0].unsubscribe(SYMBOL, EXCHANGE)
        await asyncio.sleep(1)
        
        # Check that other clients are still receiving data
        logger.info("Checking if other clients still receive data...")
        await asyncio.sleep(5)
        
        # Count messages after unsubscription
        for i, client in enumerate(clients):
            market_data_count = len([msg for msg in client.received_messages if msg.get('type') == 'market_data'])
            logger.info(f"Client {client.client_id} total market data messages: {market_data_count}")
        
        # Assert that clients 1 and 2 continue receiving data after client 0 unsubscribes
        for i in range(1, len(clients)):  # Skip client 0 (unsubscribed)
            final_count = len([msg for msg in clients[i].received_messages if msg.get('type') == 'market_data'])
            initial_count = counts_before_unsub[i]
            assert final_count > initial_count, f"Client {clients[i].client_id} should continue receiving data after other client unsubscribes (initial: {initial_count}, final: {final_count})"
        
        # Wait for remaining tasks to complete
        await asyncio.sleep(2)
        
        # Cancel remaining listen tasks
        for task in listen_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    finally:
        # Close all connections
        logger.info("Closing all client connections...")
        for i, client in enumerate(clients):
            await client.close()
            # Small delay between client disconnections
            if i < len(clients) - 1:  # Don't delay after last client
                await asyncio.sleep(0.2)
        
        # Additional wait for all connections to fully close
        await asyncio.sleep(1.0)
        logger.info("Multi-client subscription test completed!")

async def main():
    """Main test function"""
    logger.info("Multi-Client Subscription Fix Test")
    logger.info("=" * 50)
    logger.info("This test verifies that unsubscribing one client")
    logger.info("doesn't affect other clients' data reception.")
    logger.info("=" * 50)
    
    await test_multi_client_subscription()

if __name__ == "__main__":
    asyncio.run(main())
