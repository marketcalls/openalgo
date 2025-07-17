import asyncio
import websockets
import json
import random
from datetime import datetime

# Mock database
valid_tokens = {
    "valid_token_123": {"user_id": "FZ15709", "client_id": "74eb594de4a944558aeacd623a714d16"}
}

# Initialize market data variables
last_price = 1300.0
volume = 300
open_price = 1296.0
high = 1302.0
low = 1294.0
close = 1299.5

last_price_2 = 425.0
volume_2 = 1000
open_price_2 = 422.0
high_2 = 430.0
low_2 = 420.0
close_2 = 426.0

async def handle_connection(websocket):
    print("Client connected")
    authenticated = False
    subscribed = False
    
    try:
        # Create a task for sending market data
        market_data_task = None
        
        async for message in websocket:
            try:
                data = json.loads(message)
                print(f"Received: {data}")
                
                # Authentication handling
                if data.get("t") == "c" and not authenticated:
                    response = {
                        "t": "ck",
                        "s": "OK",
                        "uid": "FZ15709"
                    }
                    authenticated = True
                    await websocket.send(json.dumps(response))
                    print("Authentication successful")
                
                # Subscription handling
                elif data.get("t") == "t" and authenticated and not subscribed:
                    response = {
                        "t": "tk",
                        "e": "NSE",
                        "tk": "2885",
                        #"ts": "RELIANCE-EQ",
                        "ti": "1",
                        "ls": "1",
                        "lp": str(last_price),
                        "pc": "0.5",
                        "v": str(volume),
                        "o": str(open_price),
                        "h": str(high),
                        "l": str(low),
                        "c": str(close),
                        "ap": str(last_price)
                    }
                    response_2 = {
                        "t": "tk",
                        "e": "NSE",
                        "tk": "11536",
                        "ts": "TCS-EQ",
                        "ti": "1",
                        "ls": "1",
                        "lp": str(last_price_2),
                        "pc": "0.5",
                        "v": str(volume_2),
                        "o": str(open_price_2),
                        "h": str(high_2),
                        "l": str(low_2),
                        "c": str(close_2),
                        "ap": str(last_price_2)
                    }
                    subscribed = True
                    await websocket.send(json.dumps(response))
                    await websocket.send(json.dumps(response_2))            
                    print("Subscribed")
                    
                    # Start sending market data after subscription
                    market_data_task = asyncio.create_task(send_market_data(websocket))
                
                elif data.get("t") == "u" and subscribed:
                    if market_data_task:
                        market_data_task.cancel()
                        try:
                            await market_data_task
                        except asyncio.CancelledError:
                            pass
                    
                    response = {
                            "t": "uk",
                            "k": "NSE|2885#NSE|11536"
                        }
                    subscribed = False
                    await websocket.send(json.dumps(response))
                    print("Unsubscribed")


                # Unknown message type
                else:
                    if not authenticated:
                        response = {
                            "t": "error",
                            "emsg": "Not authenticated"
                        }
                        await websocket.send(json.dumps(response))
                        print("Not Authenticated")
            
            except json.JSONDecodeError:
                response = {
                    "t": "error",
                    "emsg": "Invalid JSON"
                }
                await websocket.send(json.dumps(response))
    
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
        if market_data_task:
            market_data_task.cancel()

async def send_market_data(websocket):
    """Continuously send market data updates"""
    global last_price, volume, open_price, high, low, close
    global last_price_2, volume_2, open_price_2, high_2, low_2, close_2
    
    print("Starting market data stream")
    while True:
        try:
            # Update market data
            last_price += round(random.uniform(-2, 2), 2)
            volume += random.randint(100, 1000)
            open_price += round(random.uniform(-2, 2), 2)
            high += round(random.uniform(-2, 2), 2)
            low += round(random.uniform(-2, 2), 2)
            close += round(random.uniform(-2, 2), 2)

            last_price_2 += round(random.uniform(-2, 2), 2)
            volume_2 += random.randint(100, 1000)
            open_price_2 += round(random.uniform(-2, 2), 2)
            high_2 += round(random.uniform(-2, 2), 2)
            low_2 += round(random.uniform(-2, 2), 2)
            close_2 += round(random.uniform(-2, 2), 2)
            
            touchline_data = {
                "t": "tf",
                "e": "NSE",
                "tk": "2885",
                "lp": str(last_price),
                "pc": "0.5",
                "v": str(volume),
                "o": str(open_price),
                "h": str(high),
                "l": str(low),
                "c": str(close),
                "ap": str(last_price)
            }
            
            touchline_data_2 = {
                "t": "tf",
                "e": "NSE",
                "tk": "11536",
                "lp": str(last_price_2),
                "pc": "0.5",
                "v": str(volume_2),
                "o": str(open_price_2),
                "h": str(high_2),
                "l": str(low_2),
                "c": str(close_2),
                "ap": str(last_price_2)
            }

            await websocket.send(json.dumps(touchline_data))
            await websocket.send(json.dumps(touchline_data_2))
            print("Sent market data update")
            await asyncio.sleep(2)
        
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed while sending market data")
            break
        except Exception as e:
            print(f"Error in market data stream: {e}")
            break

async def main():
    async with websockets.serve(handle_connection, "localhost", 8766):
        print("Dummy WebSocket server running on ws://localhost:8766")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())