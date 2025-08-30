from kafka import KafkaConsumer
import json

consumer = KafkaConsumer(
    #'tick_raw',
    'tick_data',
    bootstrap_servers='localhost:9092',
    group_id='test-group',
    auto_offset_reset='earliest',
    key_deserializer=lambda k: k.decode('utf-8') if k else None,
    value_deserializer=lambda v: json.loads(v.decode('utf-8'))
)

print("Listening for messages...")

for msg in consumer:
    print(f"{msg.key} => {msg.value}")
