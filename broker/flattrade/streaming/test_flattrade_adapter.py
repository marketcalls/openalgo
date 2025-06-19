import time
import logging
from broker.flattrade.streaming.flattrade_adapter import FlattradeWebSocketAdapter

broker_name = 'flattrade'

# Symbols and exchanges to test (ensure these exist in your symbol/token DB)
symbols = [
    ('RELIANCE', 'NSE'),
    ('SBIN', 'NSE'),
]

logging.basicConfig(level=logging.INFO)

adapter = FlattradeWebSocketAdapter()
adapter.initialize(broker_name)
adapter.connect()

print('Subscribing to LTP for multiple symbols...')
for symbol, exchange in symbols:
    resp = adapter.subscribe(symbol, exchange, mode=1)
    print(f'LTP subscribe response for {symbol}-{exchange}:', resp)

print('Subscribing to Depth for multiple symbols...')
for symbol, exchange in symbols:
    resp = adapter.subscribe(symbol, exchange, mode=3)
    print(f'Depth subscribe response for {symbol}-{exchange}:', resp)

print('Waiting for data (20 seconds)...')
time.sleep(20)

print('Unsubscribing from LTP for all symbols...')
for symbol, exchange in symbols:
    resp = adapter.unsubscribe(symbol, exchange, mode=1)
    print(f'LTP unsubscribe response for {symbol}-{exchange}:', resp)

print('Unsubscribing from Depth for all symbols...')
for symbol, exchange in symbols:
    resp = adapter.unsubscribe(symbol, exchange, mode=3)
    print(f'Depth unsubscribe response for {symbol}-{exchange}:', resp)

print('Disconnecting...')
adapter.disconnect()

print('\nTesting capability registry...')
capabilities = adapter.get_capabilities()
print('Capabilities:', capabilities)

print('Test complete.')
