"""
Unit Tests for Event Publisher

Tests both Socket.IO and Kafka event publishers to ensure
proper functionality in both modes.

Run tests:
    python -m pytest test/test_event_publisher.py -v
    
Run with coverage:
    python -m pytest test/test_event_publisher.py --cov=utils.event_publisher --cov-report=html
"""

import json
import os
import unittest
from unittest.mock import MagicMock, Mock, patch, call
from datetime import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.event_publisher import (
    EventPublisher,
    EventPublisherFactory,
    SocketIOEventPublisher,
    KafkaEventPublisher,
    get_event_publisher
)


class TestEventPublisherFactory(unittest.TestCase):
    """Test EventPublisherFactory class"""
    
    def setUp(self):
        """Reset factory before each test"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after each test"""
        EventPublisherFactory.reset()
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    @patch('utils.event_publisher.socketio')
    def test_factory_creates_socketio_publisher_when_mode_is_socketio(self, mock_socketio):
        """Test factory creates Socket.IO publisher when ORDER_EVENT_MODE=SOCKETIO"""
        publisher = EventPublisherFactory.create_publisher()
        
        self.assertIsInstance(publisher, SocketIOEventPublisher)
        self.assertEqual(publisher.socketio, mock_socketio)
    
    @patch.dict(os.environ, {
        'ORDER_EVENT_MODE': 'KAFKA',
        'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
        'KAFKA_ORDER_EVENTS_TOPIC': 'test-topic'
    })
    @patch('utils.event_publisher.KafkaProducer')
    def test_factory_creates_kafka_publisher_when_mode_is_kafka(self, mock_kafka_producer):
        """Test factory creates Kafka publisher when ORDER_EVENT_MODE=KAFKA"""
        publisher = EventPublisherFactory.create_publisher()
        
        self.assertIsInstance(publisher, KafkaEventPublisher)
        self.assertEqual(publisher.topic, 'test-topic')
        mock_kafka_producer.assert_called_once()
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'INVALID'})
    def test_factory_raises_error_for_invalid_mode(self):
        """Test factory raises ValueError for invalid ORDER_EVENT_MODE"""
        with self.assertRaises(ValueError) as context:
            EventPublisherFactory.create_publisher()
        
        self.assertIn("Invalid ORDER_EVENT_MODE", str(context.exception))
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'KAFKA'})
    def test_factory_raises_error_when_kafka_config_missing(self):
        """Test factory raises ValueError when Kafka config is missing"""
        # Remove required Kafka config
        if 'KAFKA_BOOTSTRAP_SERVERS' in os.environ:
            del os.environ['KAFKA_BOOTSTRAP_SERVERS']
        if 'KAFKA_ORDER_EVENTS_TOPIC' in os.environ:
            del os.environ['KAFKA_ORDER_EVENTS_TOPIC']
        
        with self.assertRaises(ValueError) as context:
            EventPublisherFactory.create_publisher()
        
        self.assertIn("KAFKA_BOOTSTRAP_SERVERS", str(context.exception))
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    @patch('utils.event_publisher.socketio')
    def test_factory_returns_same_instance_on_multiple_calls(self, mock_socketio):
        """Test factory returns singleton instance"""
        publisher1 = EventPublisherFactory.create_publisher()
        publisher2 = EventPublisherFactory.create_publisher()
        
        self.assertIs(publisher1, publisher2)
    
    @patch.dict(os.environ, {}, clear=True)
    @patch('utils.event_publisher.socketio')
    def test_factory_defaults_to_socketio_when_no_mode_specified(self, mock_socketio):
        """Test factory defaults to Socket.IO when ORDER_EVENT_MODE not set"""
        publisher = EventPublisherFactory.create_publisher()
        
        self.assertIsInstance(publisher, SocketIOEventPublisher)


class TestSocketIOEventPublisher(unittest.TestCase):
    """Test SocketIOEventPublisher class"""
    
    def setUp(self):
        """Create mock Socket.IO instance for tests"""
        self.mock_socketio = MagicMock()
        self.publisher = SocketIOEventPublisher(self.mock_socketio)
    
    def test_publish_order_event_emits_correct_data(self):
        """Test publish_order_event emits correct Socket.IO event"""
        result = self.publisher.publish_order_event(
            user_id="user123",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live",
            broker="angel",
            quantity="1"
        )
        
        self.assertTrue(result)
        
        # Verify start_background_task was called
        self.mock_socketio.start_background_task.assert_called_once()
        
        # Get the call arguments
        args = self.mock_socketio.start_background_task.call_args[0]
        self.assertEqual(args[0], self.mock_socketio.emit)
        self.assertEqual(args[1], "order_event")
        
        # Verify data structure
        data = args[2]
        self.assertEqual(data["symbol"], "SBIN-EQ")
        self.assertEqual(data["action"], "BUY")
        self.assertEqual(data["orderid"], "ORD123")
        self.assertEqual(data["mode"], "live")
        self.assertEqual(data["broker"], "angel")
    
    def test_publish_analyzer_update_emits_correct_data(self):
        """Test publish_analyzer_update emits correct Socket.IO event"""
        request_data = {"symbol": "RELIANCE-EQ", "action": "BUY"}
        response_data = {"status": "success", "orderid": "SAND123"}
        
        result = self.publisher.publish_analyzer_update(
            user_id="user123",
            request=request_data,
            response=response_data
        )
        
        self.assertTrue(result)
        
        # Verify emission
        self.mock_socketio.start_background_task.assert_called_once()
        args = self.mock_socketio.start_background_task.call_args[0]
        self.assertEqual(args[1], "analyzer_update")
        
        data = args[2]
        self.assertEqual(data["request"], request_data)
        self.assertEqual(data["response"], response_data)
    
    def test_publish_order_notification_emits_correct_data(self):
        """Test publish_order_notification emits correct Socket.IO event"""
        result = self.publisher.publish_order_notification(
            user_id="user123",
            symbol="INFY-EQ",
            status="info",
            message="Position matched",
            notification_type="position_match"
        )
        
        self.assertTrue(result)
        
        # Verify emission
        self.mock_socketio.start_background_task.assert_called_once()
        args = self.mock_socketio.start_background_task.call_args[0]
        self.assertEqual(args[1], "order_notification")
        
        data = args[2]
        self.assertEqual(data["symbol"], "INFY-EQ")
        self.assertEqual(data["status"], "info")
        self.assertEqual(data["message"], "Position matched")
    
    def test_publish_master_contract_download_emits_correct_data(self):
        """Test publish_master_contract_download emits correct Socket.IO event"""
        result = self.publisher.publish_master_contract_download(
            broker="angel",
            status="success",
            message="Download complete",
            symbols_count=5000
        )
        
        self.assertTrue(result)
        
        # Verify direct emit (not background task)
        self.mock_socketio.emit.assert_called_once()
        args = self.mock_socketio.emit.call_args[0]
        self.assertEqual(args[0], "master_contract_download")
        
        data = args[1]
        self.assertEqual(data["broker"], "angel")
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["symbols_count"], 5000)
    
    def test_publish_password_change_emits_correct_data(self):
        """Test publish_password_change emits correct Socket.IO event"""
        result = self.publisher.publish_password_change(
            user_id="user123",
            status="success",
            message="Password changed",
            ip_address="192.168.1.1"
        )
        
        self.assertTrue(result)
        
        # Verify direct emit
        self.mock_socketio.emit.assert_called_once()
        args = self.mock_socketio.emit.call_args[0]
        self.assertEqual(args[0], "password_change")
        
        data = args[1]
        self.assertEqual(data["user"], "user123")
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["ip_address"], "192.168.1.1")
    
    def test_publish_returns_false_on_exception(self):
        """Test publisher returns False when exception occurs"""
        # Make emit raise exception
        self.mock_socketio.start_background_task.side_effect = Exception("Test error")
        
        result = self.publisher.publish_order_event(
            user_id="user123",
            symbol="TEST-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
        
        self.assertFalse(result)
    
    def test_close_does_not_raise_exception(self):
        """Test close() method completes without error"""
        try:
            self.publisher.close()
        except Exception as e:
            self.fail(f"close() raised exception: {e}")


class TestKafkaEventPublisher(unittest.TestCase):
    """Test KafkaEventPublisher class"""
    
    @patch('utils.event_publisher.KafkaProducer')
    def setUp(self, mock_kafka_producer_class):
        """Create Kafka publisher with mocked producer"""
        self.mock_producer = MagicMock()
        mock_kafka_producer_class.return_value = self.mock_producer
        
        self.publisher = KafkaEventPublisher(
            bootstrap_servers="localhost:9092",
            topic="test-topic"
        )
    
    def test_initialization_creates_kafka_producer(self):
        """Test Kafka publisher initializes with correct config"""
        self.assertEqual(self.publisher.topic, "test-topic")
        self.assertEqual(self.publisher.bootstrap_servers, "localhost:9092")
        self.assertIsNotNone(self.publisher.producer)
    
    def test_publish_order_event_sends_to_kafka(self):
        """Test publish_order_event sends message to Kafka"""
        # Mock successful send
        future = MagicMock()
        future.get.return_value = MagicMock(partition=0, offset=123)
        self.mock_producer.send.return_value = future
        
        result = self.publisher.publish_order_event(
            user_id="user123",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live",
            broker="angel"
        )
        
        self.assertTrue(result)
        
        # Verify send was called
        self.mock_producer.send.assert_called_once()
        
        # Check arguments
        call_args = self.mock_producer.send.call_args
        self.assertEqual(call_args[0][0], "test-topic")  # Topic
        self.assertEqual(call_args[1]['key'], "user123")  # Key
        
        # Verify message structure
        message = call_args[1]['value']
        self.assertEqual(message['event_type'], "order_event")
        self.assertEqual(message['user_id'], "user123")
        self.assertEqual(message['source'], "openalgo")
        self.assertIn('timestamp', message)
        
        # Verify data payload
        data = message['data']
        self.assertEqual(data['symbol'], "SBIN-EQ")
        self.assertEqual(data['action'], "BUY")
        self.assertEqual(data['orderid'], "ORD123")
    
    def test_publish_analyzer_update_sends_to_kafka(self):
        """Test publish_analyzer_update sends message to Kafka"""
        future = MagicMock()
        self.mock_producer.send.return_value = future
        
        request_data = {"symbol": "TEST-EQ", "action": "BUY"}
        response_data = {"status": "success"}
        
        result = self.publisher.publish_analyzer_update(
            user_id="user123",
            request=request_data,
            response=response_data
        )
        
        self.assertTrue(result)
        self.mock_producer.send.assert_called_once()
        
        # Verify message
        message = self.mock_producer.send.call_args[1]['value']
        self.assertEqual(message['event_type'], "analyzer_update")
        self.assertEqual(message['data']['request'], request_data)
        self.assertEqual(message['data']['response'], response_data)
    
    def test_publish_order_notification_sends_to_kafka(self):
        """Test publish_order_notification sends message to Kafka"""
        future = MagicMock()
        self.mock_producer.send.return_value = future
        
        result = self.publisher.publish_order_notification(
            user_id="user123",
            symbol="INFY-EQ",
            status="info",
            message="Test notification"
        )
        
        self.assertTrue(result)
        self.mock_producer.send.assert_called_once()
        
        message = self.mock_producer.send.call_args[1]['value']
        self.assertEqual(message['event_type'], "order_notification")
        self.assertEqual(message['data']['symbol'], "INFY-EQ")
    
    def test_publish_master_contract_download_sends_to_kafka(self):
        """Test publish_master_contract_download sends message to Kafka"""
        future = MagicMock()
        self.mock_producer.send.return_value = future
        
        result = self.publisher.publish_master_contract_download(
            broker="angel",
            status="success",
            message="Download complete",
            symbols_count=5000
        )
        
        self.assertTrue(result)
        self.mock_producer.send.assert_called_once()
        
        # Verify admin user_id for system events
        message = self.mock_producer.send.call_args[1]['value']
        self.assertEqual(message['user_id'], "admin")
        self.assertEqual(message['event_type'], "master_contract_download")
    
    def test_publish_password_change_sends_to_kafka(self):
        """Test publish_password_change sends message to Kafka"""
        future = MagicMock()
        future.get.return_value = MagicMock(partition=0, offset=456)
        self.mock_producer.send.return_value = future
        
        result = self.publisher.publish_password_change(
            user_id="user123",
            status="success",
            message="Password changed"
        )
        
        self.assertTrue(result)
        
        # Verify waits for ack (security event)
        future.get.assert_called_once()
    
    def test_publish_returns_false_on_kafka_error(self):
        """Test publisher returns False when Kafka send fails"""
        self.mock_producer.send.side_effect = Exception("Kafka error")
        
        result = self.publisher.publish_order_event(
            user_id="user123",
            symbol="TEST-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
        
        self.assertFalse(result)
    
    def test_message_contains_timestamp(self):
        """Test published message contains ISO format timestamp"""
        future = MagicMock()
        self.mock_producer.send.return_value = future
        
        self.publisher.publish_order_event(
            user_id="user123",
            symbol="TEST-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
        
        message = self.mock_producer.send.call_args[1]['value']
        timestamp = message['timestamp']
        
        # Verify ISO format with Z suffix
        self.assertTrue(timestamp.endswith('Z'))
        # Verify can be parsed
        datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    
    def test_close_flushes_and_closes_producer(self):
        """Test close() flushes pending messages and closes producer"""
        self.publisher.close()
        
        self.mock_producer.flush.assert_called_once()
        self.mock_producer.close.assert_called_once()
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_initialization_with_custom_config(self, mock_kafka_producer_class):
        """Test Kafka publisher uses environment configuration"""
        with patch.dict(os.environ, {
            'KAFKA_PRODUCER_COMPRESSION': 'gzip',
            'KAFKA_PRODUCER_BATCH_SIZE': '32768',
            'KAFKA_PRODUCER_LINGER_MS': '20',
            'KAFKA_PRODUCER_ACKS': '1',
            'KAFKA_PRODUCER_RETRIES': '5'
        }):
            publisher = KafkaEventPublisher("localhost:9092", "test-topic")
            
            # Verify producer was created with custom config
            call_kwargs = mock_kafka_producer_class.call_args[1]
            self.assertEqual(call_kwargs['compression_type'], 'gzip')
            self.assertEqual(call_kwargs['batch_size'], 32768)
            self.assertEqual(call_kwargs['linger_ms'], 20)
            self.assertEqual(call_kwargs['acks'], '1')
            self.assertEqual(call_kwargs['retries'], 5)


class TestGetEventPublisher(unittest.TestCase):
    """Test get_event_publisher convenience function"""
    
    def setUp(self):
        """Reset factory before each test"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after each test"""
        EventPublisherFactory.reset()
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    @patch('utils.event_publisher.socketio')
    def test_get_event_publisher_returns_publisher(self, mock_socketio):
        """Test get_event_publisher() returns publisher instance"""
        publisher = get_event_publisher()
        
        self.assertIsInstance(publisher, EventPublisher)
        self.assertIsInstance(publisher, SocketIOEventPublisher)
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    @patch('utils.event_publisher.socketio')
    def test_get_event_publisher_returns_same_instance(self, mock_socketio):
        """Test get_event_publisher() returns singleton"""
        publisher1 = get_event_publisher()
        publisher2 = get_event_publisher()
        
        self.assertIs(publisher1, publisher2)


class TestEventPublisherIntegration(unittest.TestCase):
    """Integration tests for event publisher"""
    
    def setUp(self):
        """Reset factory before each test"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after each test"""
        EventPublisherFactory.reset()
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    @patch('utils.event_publisher.socketio')
    def test_publish_multiple_events_in_sequence(self, mock_socketio):
        """Test publishing multiple different events works correctly"""
        publisher = get_event_publisher()
        
        # Publish order event
        result1 = publisher.publish_order_event(
            user_id="user1",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD1",
            mode="live"
        )
        
        # Publish notification
        result2 = publisher.publish_order_notification(
            user_id="user1",
            symbol="SBIN-EQ",
            status="success",
            message="Order placed"
        )
        
        # Publish password change
        result3 = publisher.publish_password_change(
            user_id="user1",
            status="success",
            message="Password changed"
        )
        
        self.assertTrue(result1)
        self.assertTrue(result2)
        self.assertTrue(result3)
        
        # Verify all emissions occurred
        self.assertEqual(mock_socketio.start_background_task.call_count, 2)  # order + notification
        self.assertEqual(mock_socketio.emit.call_count, 1)  # password change


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
