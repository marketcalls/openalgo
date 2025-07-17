from kafka import KafkaProducer
import json

producer = KafkaProducer(
    bootstrap_servers='localhost:9092',
    key_serializer=lambda k: k.encode('utf-8'),
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# Sample tick data
tick_data = {
    "symbol": "RELIANCE",
    "ltp": 2810.50,
    "volume": 100,
    "timestamp": 1720458436000
}

producer.send('tick_raw', key='RELIANCE', value=tick_data)
producer.flush()
print("Tick sent!")
