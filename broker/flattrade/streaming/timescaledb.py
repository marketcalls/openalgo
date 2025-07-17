import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import execute_batch
from kafka import KafkaConsumer
from kafka.errors import KafkaError
import pytz
import json
import logging
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import random
from dateutil import parser  # For flexible ISO date parsing
import traceback

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check if Kafka is available
try:    
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logger.warning("Kafka library not available. Install with: pip install kafka-python")

class TimescaleDBManager:
    def __init__(self, dbname=os.getenv('TIMESCALE_DB_NAME'), user=os.getenv('TIMESCALE_DB_USER'), password=os.getenv('TIMESCALE_DB_PASSWORD'), host=os.getenv('TIMESCALE_DB_HOST'), port=os.getenv('TIMESCALE_DB_PORT')):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.admin_conn = None
        self.app_conn = None
        self.logger = logging.getLogger(f"TimeScaleDBManager")
        
        self.logger.info(f"Initializing TimescaleDB connection to {self.host}:{self.port} as user '{self.user}' for database '{self.dbname}'")

    def _get_admin_connection(self):
        """Connection without specifying database (for admin operations)"""
        try:
            conn = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname='postgres'  # Connect to default admin DB
            )
            # Set autocommit mode for DDL operations like CREATE DATABASE
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            return conn
        except psycopg2.Error as e:
            self.logger.error(f"Failed to connect to PostgreSQL server: {e}")
            raise

    def _database_exists(self):
        """Check if database exists"""
        try:
            with self._get_admin_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s",
                        (self.dbname,)
                    )
                    return cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Error checking database existence: {e}")
            return False
    

    def _create_database(self):
        """Create new database with TimescaleDB extension"""
        try:
            self.logger.info(f"Creating database '{self.dbname}'...")
            
            # Create database with autocommit connection
            conn = self._get_admin_connection()
            try:
                with conn.cursor() as cursor:
                    # Create database
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {}").format(
                            sql.Identifier(self.dbname)
                        )
                    )
                    self.logger.info(f"Database '{self.dbname}' created successfully")
            finally:
                conn.close()
                    
            # Connect to new database to install extensions
            self.logger.info("Installing TimescaleDB extension...")
            conn_newdb = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname=self.dbname
            )
            try:
                with conn_newdb.cursor() as cursor_new:
                    cursor_new.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                    conn_newdb.commit()
                    self.logger.info("TimescaleDB extension installed successfully")
            finally:
                conn_newdb.close()
                    
            self.logger.info(f"Created database {self.dbname} with TimescaleDB extension")
            return True
            
        except psycopg2.Error as e:
            self.logger.error(f"PostgreSQL error creating database: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error creating database: {e}")
            return False
    

    def _create_tables(self):
        """Create required tables and hypertables"""
        commands = [
            """
            CREATE TABLE IF NOT EXISTS ticks (
                time TIMESTAMPTZ NOT NULL,
                symbol VARCHAR(20) NOT NULL,                
                open DECIMAL(18, 2),
                high DECIMAL(18, 2),
                low DECIMAL(18, 2),
                close DECIMAL(18, 2),
                volume BIGINT,
                PRIMARY KEY (time, symbol)
            )
            """,
            """
            SELECT create_hypertable('ticks', 'time', if_not_exists => TRUE)
            """,
            """
            CREATE TABLE IF NOT EXISTS ohlc_1m (
                time TIMESTAMPTZ NOT NULL,
                symbol VARCHAR(20) NOT NULL,                
                open DECIMAL(18, 2),
                high DECIMAL(18, 2),
                low DECIMAL(18, 2),
                close DECIMAL(18, 2),
                volume BIGINT,
                PRIMARY KEY (time, symbol)
            )
            """,
            """
            SELECT create_hypertable('ohlc_1m', 'time', if_not_exists => TRUE)
            """,
            """
            CREATE TABLE IF NOT EXISTS ohlc_5m (
                time TIMESTAMPTZ NOT NULL,
                symbol VARCHAR(20) NOT NULL,                
                open DECIMAL(18, 2),
                high DECIMAL(18, 2),
                low DECIMAL(18, 2),
                close DECIMAL(18, 2),
                volume BIGINT,
                PRIMARY KEY (time, symbol)
            )
            """,
            """
            SELECT create_hypertable('ohlc_5m', 'time', if_not_exists => TRUE)
            """,
            """
            CREATE TABLE IF NOT EXISTS ohlc_15m (
                time TIMESTAMPTZ NOT NULL,
                symbol VARCHAR(20) NOT NULL,                
                open DECIMAL(18, 2),
                high DECIMAL(18, 2),
                low DECIMAL(18, 2),
                close DECIMAL(18, 2),
                volume BIGINT,
                PRIMARY KEY (time, symbol)
            )
            """,
            """
            SELECT create_hypertable('ohlc_15m', 'time', if_not_exists => TRUE)
            """
        ]
        
        try:
            conn = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname=self.dbname
            )
            try:
                with conn.cursor() as cursor:
                    for i, command in enumerate(commands):
                        try:
                            cursor.execute(command)
                            self.logger.debug(f"Executed command {i+1}/{len(commands)}")
                        except psycopg2.Error as e:
                            # Skip hypertable creation if table already exists as hypertable
                            if "already a hypertable" in str(e):
                                self.logger.info(f"Table already exists as hypertable, skipping: {e}")
                                continue
                            else:
                                self.logger.error(f"Error executing command {i+1}: {e}")
                                self.logger.error(f"Command was: {command}")
                                raise
                conn.commit()
                self.logger.info("Created tables and hypertables successfully")
            finally:
                conn.close()
                
        except psycopg2.Error as e:
            self.logger.error(f"PostgreSQL error creating tables: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error creating tables: {e}")
            raise
    
    def test_connection(self):
        """Test database connection"""
        try:
            conn = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname='postgres'  # Test with default database first
            )
            conn.close()
            self.logger.info("Database connection test successful")
            return True
        except psycopg2.Error as e:
            self.logger.error(f"Database connection test failed: {e}")
            return False

    def initialize_database(self):
        """Main initialization method"""
        # Test connection first
        if not self.test_connection():
            raise RuntimeError("Cannot connect to PostgreSQL server. Check your connection parameters.")
        
        if not self._database_exists():
            self.logger.info(f"Database {self.dbname} not found, creating...")
            if not self._create_database():
                raise RuntimeError("Failed to create database")
        else:
            self.logger.info(f"Database {self.dbname} already exists")
        
        self._create_tables()
        
        # Return an application connection
        try:
            self.app_conn = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname=self.dbname
            )
            self.logger.info("Database connection established successfully")
            return self.app_conn
        
        except psycopg2.Error as e:
            self.logger.error(f"Database connection failed: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            raise

# Integration with your existing code
class MarketDataProcessor:
    def __init__(self):
        # Initialize TimescaleDBManager and connect to the database
        self.db_manager = TimescaleDBManager()
        self.db_conn = self.db_manager.initialize_database()
        self.logger = logging.getLogger(f"MarketDataProcessor")
        
        # Initialize Redpanda consumer
        # self.consumer = KafkaConsumer(
        #     'tick_data',
        #     bootstrap_servers='localhost:9092',
        #     group_id='tick-processors-v5',
        #     auto_offset_reset='earliest',
        #     enable_auto_commit=False,
        #     max_poll_interval_ms=300000,
        #     session_timeout_ms=10000,
        #     heartbeat_interval_ms=3000
        #     #key_deserializer=lambda k: k.decode('utf-8') if k else None,
        #     #value_deserializer=lambda v: json.loads(v.decode('utf-8'))
        # )

        self.consumer = KafkaConsumer(
            'tick_data',
            bootstrap_servers='localhost:9092',
            group_id='tick-processor',
            auto_offset_reset='earliest'
            #key_deserializer=lambda k: k.decode('utf-8') if k else None,
            #value_deserializer=lambda v: json.loads(v.decode('utf-8'))
        )

        self.logger.info("Starting consumer with configuration:")
        self.logger.info(f"Group ID: {self.consumer.config['group_id']}")
        self.logger.info(f"Brokers: {self.consumer.config['bootstrap_servers']}")

        self.aggregation_lock = Lock()

        self.executor = ThreadPoolExecutor(max_workers=8)

        # Initialize aggregation buffers
        self.reset_aggregation_buffers()
        
        # Rest of your initialization...

    def reset_aggregation_buffers(self):
        """Initialize/reset aggregation buffers"""
        with self.aggregation_lock:
            self.tick_buffer = {
                '1m': {},
                '5m': {},
                '15m': {}
            }
            now = datetime.now(pytz.utc)
            self.last_agg_time = {
                '1m': self.floor_to_interval(now, 1),
                '5m': self.floor_to_interval(now, 5),
                '15m': self.floor_to_interval(now, 15)
            }
            self.aggregation_state = {
                '1m': {},
                '5m': {},
                '15m': {}
            }

    def process_messages(self):
        """Main processing loop"""
        
        self.consumer.subscribe(['tick_data'])
        self.logger.info("Started listening messages...")       

        try:
            while True:
                raw_msg = self.consumer.poll(1000.0)
                self.logger.info(f"\n\n\n\nReceived messages: {raw_msg}")

                if raw_msg is None:
                    self.logger.info("No messages received during timeout period ----------->")
                    continue
                
                #if not hasattr(raw_msg, 'error'):
                #    self.logger.info("gargerger----------------------->")

                # Handle Kafka protocol messages
                #if raw_msg is None or not hasattr(raw_msg, 'error'):
                #    self.logger.info("Received None or non-Kafka message")
                #    continue

                # if raw_msg.error():
                #     self.logger.info("Received None or non-Kafka message\n\n\n\n\n\n")
                #     self._handle_kafka_error(raw_msg.error())
                #     continue
                
                self.logger.info("I'm here---------------------------------->")

                for topic_partition, messages in raw_msg.items():    
                    for message in messages:
                        try:
                            # Extract key and value
                            key = message.key.decode('utf-8')  # 'NSE_RELIANCE_LTP'
                            value = json.loads(message.value.decode('utf-8'))

                            self.logger.info(f"Processing {key}: {value['symbol']}@{value['close']}")

                            # Process the message
                            self.process_single_message(key, value)

                        except Exception as e:
                            self.logger.error(f"Error processing message: {e}")
                    
                # Periodically commit offsets
                #if random.random() < 0.01:  # ~1% of messages
                #    self.consumer.commit()

        except KeyboardInterrupt:
            self.logger.info("Kafka Consumer Shutting down...")
        finally:
            self.shutdown()

    def _handle_kafka_error(self, error):
        """Handle Kafka protocol errors"""
        error_codes = {
            KafkaError._PARTITION_EOF: "End of partition",
            KafkaError.UNKNOWN_TOPIC_OR_PART: "Topic/partition does not exist",
            KafkaError.NOT_COORDINATOR_FOR_GROUP: "Coordinator changed",
            KafkaError.ILLEGAL_GENERATION: "Consumer group rebalanced",
            KafkaError.UNKNOWN_MEMBER_ID: "Member ID expired"
        }
        
        if error.code() in error_codes:
            self.logger.warning(error_codes[error.code()])
        else:
            self.logger.error(f"Kafka error [{error.code()}]: {error.str()}")

    
    def process_single_message(self, key, value):
        """Process extracted tick data"""
        try:
            # Extract components from key
            components = key.split('_')
            exchange = components[0]  # 'NSE'
            symbol = components[1]    # 'RELIANCE'
            data_type = components[2] # 'LTP' or 'QUOTE'

             # Convert timestamp (handling milliseconds since epoch)
            timestamp = value['timestamp']
            if not isinstance(timestamp, (int, float)):
                raise ValueError(f"Invalid timestamp type: {type(timestamp)}")

            # Convert to proper datetime object
            # Ensure milliseconds (not seconds or microseconds)
            if timestamp < 1e12:  # Likely in seconds
                timestamp *= 1000
            elif timestamp > 1e13:  # Likely in microseconds
                timestamp /= 1000
                
            dt = datetime.fromtimestamp(timestamp / 1000, tz=pytz.UTC)
            #ist_dt = dt.astimezone(pytz.timezone('Asia/Kolkata'))
            
            # Validate date range
            if dt.year < 2020 or dt.year > 2030:
                raise ValueError(f"Implausible date {dt} from timestamp {timestamp}")
                       
            # Prepare database record
            record = {
                'time': dt,  # Convert ms to seconds
                'symbol': symbol,
                'open': float(value['open']),
                'high': float(value['high']),
                'low': float(value['low']),
                'close': float(value['close']),
                'volume': int(value['volume'])
            }

            self.logger.info(f"Record---------> {record}")
            
            # Store in TimescaleDB
            self.store_tick(record)

            # Add to aggregation buffers
            self.buffer_tick(record)

            # Check for aggregation opportunities
            self.check_aggregation(record['time'])
            
        except Exception as e:
            self.logger.error(f"Tick processing failed: {e}")
            self.logger.debug(traceback.format_exc())


    def store_tick(self, record):
        """Store raw tick in database"""
        try:
            self.logger.info("Storing tick in database-------->")
            with self.db_conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO ticks (time, symbol, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (time, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume
                    """, (record['time'], record['symbol'], record['open'], record['high'], record['low'], record['close'], record['volume']))
                self.db_conn.commit()
        except Exception as e:
            logger.error(f"Error storing tick: {e}")
            self.db_conn.rollback()

    def buffer_tick(self, record):
        self.logger.info("Storing buffer in database-------->")
        """Add tick to aggregation buffers"""
        with self.aggregation_lock:
            for timeframe in ['1m', '5m', '15m']:
                minutes = int(timeframe[:-1])
                symbol = record['symbol']
                aligned_time = self.floor_to_interval(record['time'], minutes)

                if symbol not in self.tick_buffer[timeframe]:
                    self.tick_buffer[timeframe][symbol] = {
                        'opens': [],
                        'highs': [],
                        'lows': [],
                        'closes': [],
                        'volumes': [],
                        'first_ts': aligned_time
                    }

                self.tick_buffer[timeframe][symbol]['opens'].append(record['open'])
                self.tick_buffer[timeframe][symbol]['highs'].append(record['high'])
                self.tick_buffer[timeframe][symbol]['lows'].append(record['low'])
                self.tick_buffer[timeframe][symbol]['closes'].append(record['close'])
                self.tick_buffer[timeframe][symbol]['volumes'].append(record['volume'])

    def check_aggregation(self, current_time):
        """Check if aggregation should occur for any timeframe"""
        self.logger.info("Check aggregation-------->")
        timeframes = ['1m', '5m', '15m']
        
        for timeframe in timeframes:
            agg_interval = timedelta(minutes=int(timeframe[:-1]))
            last_agg = self.last_agg_time[timeframe]
            
            self.logger.info(f"{timeframe}: current_time={current_time}, last_agg={last_agg}, interval={agg_interval}")

            if current_time - last_agg >= agg_interval:
                if self.aggregate_data(timeframe, current_time):
                    self.last_agg_time[timeframe] = self.floor_to_interval(current_time, int(timeframe[:-1]))


    def floor_to_interval(self, dt, minutes=1):
        """Floor a datetime to the start of its minute/5m/15m interval"""
        discard = timedelta(
            minutes=dt.minute % minutes,
            seconds=dt.second,
            microseconds=dt.microsecond
        )
        return dt - discard

    def aggregate_data(self, timeframe, agg_time):
        self.logger.info("Inside aggregate data-------->")
        """Perform aggregation for specific timeframe"""
        with self.aggregation_lock:
            buffer = self.tick_buffer[timeframe]

            if not buffer:
                return False

            aggregated = []
            table_name = f"ohlc_{timeframe}"           
            
            for symbol, data in buffer.items():
                if not data['opens']:
                    continue

                bucket_start = self.floor_to_interval(data['first_ts'], minutes=int(timeframe[:-1]))
            
                open = data['opens'][0]
                high = max(data['highs'])
                low = min(data['lows'])
                close = data['closes'][-1]
                volume = sum(data['volumes'])                
                
                aggregated.append((
                    bucket_start,
                    symbol,
                    open,
                    high,
                    low,
                    close,
                    volume
                ))

            if aggregated:
                try:
                    with self.db_conn.cursor() as cursor:
                        execute_batch(cursor, f"""
                            INSERT INTO {table_name} 
                            (time, symbol, open, high, low, close, volume)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (time, symbol) DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume
                            """, aggregated)
                        self.db_conn.commit()
                        logger.info(f"Aggregated {len(aggregated)} symbols to {table_name}")
                        
                        # Reset buffers for aggregated symbols
                        self.tick_buffer[timeframe] = {}
                        return True
                except Exception as e:
                    logger.error(f"Error aggregating {timeframe} data: {e}")
                    self.db_conn.rollback()
                    return False
            return False

    def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down processors")
        self.executor.shutdown(wait=True)
        self.consumer.close()
        self.db_conn.close()
        logger.info("Clean shutdown complete")

if __name__ == "__main__":
    processor = MarketDataProcessor()
    try:
        processor.process_messages()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        processor.shutdown()
