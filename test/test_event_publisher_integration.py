"""
Integration Tests for Event Publisher

These tests verify the event publisher works correctly in real scenarios,
testing the integration between different components.

Run tests:
    python -m pytest test/test_event_publisher_integration.py -v
"""

import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.event_publisher import (
    EventPublisherFactory,
    get_event_publisher
)


class TestSocketIOKafkaModeSwitching(unittest.TestCase):
    """Test switching between Socket.IO and Kafka modes"""
    
    def tearDown(self):
        """Cleanup after each test"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_switch_from_default_to_socketio(self, mock_socketio):
        """Test explicitly setting SOCKETIO mode"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            EventPublisherFactory.reset()
            publisher = get_event_publisher()
            
            result = publisher.publish_order_event(
                user_id="user123",
                symbol="TEST-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            self.assertTrue(result)
            mock_socketio.start_background_task.assert_called_once()
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_switch_to_kafka_mode(self, mock_kafka_producer):
        """Test switching to Kafka mode"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        with patch.dict(os.environ, {
            'ORDER_EVENT_MODE': 'KAFKA',
            'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
            'KAFKA_ORDER_EVENTS_TOPIC': 'test-events'
        }):
            EventPublisherFactory.reset()
            publisher = get_event_publisher()
            
            future = MagicMock()
            future.get.return_value = MagicMock(partition=0, offset=1)
            mock_producer.send.return_value = future
            
            result = publisher.publish_order_event(
                user_id="user123",
                symbol="TEST-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            self.assertTrue(result)
            mock_producer.send.assert_called_once()


class TestOrderEventWorkflow(unittest.TestCase):
    """Test complete order event workflow"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_order_placement_workflow(self, mock_socketio):
        """Test complete order placement workflow"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            # Step 1: Order placed
            result1 = publisher.publish_order_event(
                user_id="user123",
                symbol="SBIN-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live",
                broker="angel",
                quantity="1",
                price="850.50"
            )
            
            # Step 2: Order notification
            result2 = publisher.publish_order_notification(
                user_id="user123",
                symbol="SBIN-EQ",
                status="success",
                message="Order placed successfully"
            )
            
            self.assertTrue(result1)
            self.assertTrue(result2)
            
            # Verify both events were published
            self.assertEqual(mock_socketio.start_background_task.call_count, 2)


class TestAnalyzerModeWorkflow(unittest.TestCase):
    """Test analyzer/sandbox mode workflow"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_analyzer_update_workflow(self, mock_socketio):
        """Test analyzer mode update workflow"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            request_data = {
                "symbol": "RELIANCE-EQ",
                "action": "BUY",
                "quantity": "1",
                "api_type": "placesmartorder"
            }
            
            response_data = {
                "mode": "analyze",
                "status": "success",
                "orderid": "SANDBOX_ORD_123"
            }
            
            result = publisher.publish_analyzer_update(
                user_id="user123",
                request=request_data,
                response=response_data
            )
            
            self.assertTrue(result)
            mock_socketio.start_background_task.assert_called_once()
            
            # Verify event data
            args = mock_socketio.start_background_task.call_args[0]
            self.assertEqual(args[1], "analyzer_update")
            data = args[2]
            self.assertEqual(data["request"], request_data)
            self.assertEqual(data["response"], response_data)


class TestSystemEventsWorkflow(unittest.TestCase):
    """Test system events workflow"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_master_contract_download_workflow(self, mock_socketio):
        """Test master contract download workflow"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            result = publisher.publish_master_contract_download(
                broker="angel",
                status="success",
                message="Master contract downloaded successfully",
                symbols_count=5000,
                download_time_seconds=45.2
            )
            
            self.assertTrue(result)
            
            # Verify direct emit (not background task)
            mock_socketio.emit.assert_called_once()
            args = mock_socketio.emit.call_args[0]
            self.assertEqual(args[0], "master_contract_download")
            
            data = args[1]
            self.assertEqual(data["broker"], "angel")
            self.assertEqual(data["symbols_count"], 5000)
    
    @patch('utils.event_publisher.socketio')
    def test_password_change_workflow(self, mock_socketio):
        """Test password change workflow"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            result = publisher.publish_password_change(
                user_id="user123",
                status="success",
                message="Password changed successfully",
                ip_address="192.168.1.100",
                user_agent="Mozilla/5.0"
            )
            
            self.assertTrue(result)
            
            # Verify direct emit
            mock_socketio.emit.assert_called_once()
            args = mock_socketio.emit.call_args[0]
            self.assertEqual(args[0], "password_change")
            
            data = args[1]
            self.assertEqual(data["user"], "user123")
            self.assertEqual(data["ip_address"], "192.168.1.100")


class TestErrorHandling(unittest.TestCase):
    """Test error handling in various scenarios"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_publisher_handles_socketio_errors_gracefully(self, mock_socketio):
        """Test publisher handles Socket.IO errors gracefully"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            # Make emit raise exception
            mock_socketio.start_background_task.side_effect = Exception("Connection error")
            
            # Should return False but not raise exception
            result = publisher.publish_order_event(
                user_id="user123",
                symbol="TEST-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            self.assertFalse(result)
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_publisher_handles_kafka_errors_gracefully(self, mock_kafka_producer):
        """Test publisher handles Kafka errors gracefully"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        with patch.dict(os.environ, {
            'ORDER_EVENT_MODE': 'KAFKA',
            'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
            'KAFKA_ORDER_EVENTS_TOPIC': 'test-events'
        }):
            publisher = get_event_publisher()
            
            # Make send raise exception
            mock_producer.send.side_effect = Exception("Kafka unavailable")
            
            # Should return False but not raise exception
            result = publisher.publish_order_event(
                user_id="user123",
                symbol="TEST-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            self.assertFalse(result)


class TestMessageFormatValidation(unittest.TestCase):
    """Test message format validation"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_kafka_message_has_required_fields(self, mock_kafka_producer):
        """Test Kafka messages contain all required fields"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        with patch.dict(os.environ, {
            'ORDER_EVENT_MODE': 'KAFKA',
            'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
            'KAFKA_ORDER_EVENTS_TOPIC': 'test-events'
        }):
            publisher = get_event_publisher()
            
            future = MagicMock()
            mock_producer.send.return_value = future
            
            publisher.publish_order_event(
                user_id="user123",
                symbol="SBIN-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            # Get sent message
            message = mock_producer.send.call_args[1]['value']
            
            # Verify required top-level fields
            self.assertIn('event_type', message)
            self.assertIn('timestamp', message)
            self.assertIn('user_id', message)
            self.assertIn('source', message)
            self.assertIn('version', message)
            self.assertIn('data', message)
            
            # Verify values
            self.assertEqual(message['event_type'], 'order_event')
            self.assertEqual(message['user_id'], 'user123')
            self.assertEqual(message['source'], 'openalgo')
            self.assertEqual(message['version'], '1.0')
            
            # Verify data payload
            data = message['data']
            self.assertEqual(data['symbol'], 'SBIN-EQ')
            self.assertEqual(data['action'], 'BUY')
            self.assertEqual(data['orderid'], 'ORD123')
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_kafka_message_timestamp_format(self, mock_kafka_producer):
        """Test Kafka message timestamp is ISO format"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        with patch.dict(os.environ, {
            'ORDER_EVENT_MODE': 'KAFKA',
            'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
            'KAFKA_ORDER_EVENTS_TOPIC': 'test-events'
        }):
            publisher = get_event_publisher()
            
            future = MagicMock()
            mock_producer.send.return_value = future
            
            publisher.publish_order_event(
                user_id="user123",
                symbol="TEST-EQ",
                action="BUY",
                orderid="ORD123",
                mode="live"
            )
            
            message = mock_producer.send.call_args[1]['value']
            timestamp = message['timestamp']
            
            # Verify ISO format with Z suffix
            self.assertTrue(timestamp.endswith('Z'))
            
            # Verify can be parsed as datetime
            from datetime import datetime
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))


class TestPerformance(unittest.TestCase):
    """Performance tests for event publisher"""
    
    def setUp(self):
        """Setup for tests"""
        EventPublisherFactory.reset()
    
    def tearDown(self):
        """Cleanup after tests"""
        EventPublisherFactory.reset()
    
    @patch('utils.event_publisher.socketio')
    def test_socketio_publisher_handles_rapid_events(self, mock_socketio):
        """Test Socket.IO publisher can handle rapid event publishing"""
        with patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'}):
            publisher = get_event_publisher()
            
            # Publish 100 events rapidly
            start_time = time.time()
            for i in range(100):
                publisher.publish_order_event(
                    user_id=f"user{i}",
                    symbol="TEST-EQ",
                    action="BUY",
                    orderid=f"ORD{i}",
                    mode="live"
                )
            duration = time.time() - start_time
            
            # Should complete in reasonable time (< 1 second)
            self.assertLess(duration, 1.0)
            
            # Verify all events were queued
            self.assertEqual(mock_socketio.start_background_task.call_count, 100)
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_kafka_publisher_handles_rapid_events(self, mock_kafka_producer):
        """Test Kafka publisher can handle rapid event publishing"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        future = MagicMock()
        mock_producer.send.return_value = future
        
        with patch.dict(os.environ, {
            'ORDER_EVENT_MODE': 'KAFKA',
            'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
            'KAFKA_ORDER_EVENTS_TOPIC': 'test-events'
        }):
            publisher = get_event_publisher()
            
            # Publish 100 events rapidly
            start_time = time.time()
            for i in range(100):
                publisher.publish_order_notification(
                    user_id=f"user{i}",
                    symbol="TEST-EQ",
                    status="info",
                    message=f"Test {i}"
                )
            duration = time.time() - start_time
            
            # Should complete in reasonable time (< 1 second)
            self.assertLess(duration, 1.0)
            
            # Verify all events were sent
            self.assertEqual(mock_producer.send.call_count, 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
