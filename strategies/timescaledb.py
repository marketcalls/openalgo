import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import execute_batch
from psycopg2 import pool
from kafka import KafkaConsumer
from kafka.errors import KafkaError
import pytz
import json
import logging
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product, groupby
from operator import itemgetter
from datetime import datetime, timedelta
import os
import random
from dateutil import parser  # For flexible ISO date parsing
import traceback
import argparse
from openalgo import api
import pandas as pd
from backtest_engine import BacktestEngine
import glob
from concurrent.futures import ThreadPoolExecutor
import time
from tabulate import tabulate
from colorama import Fore, Back, Style, init
from textwrap import wrap
from collections import defaultdict

# Initialize colorama
init(autoreset=True)

# Suppress User warnings in output
from warnings import filterwarnings
filterwarnings("ignore", category=UserWarning)

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
            """,
            """
            CREATE TABLE IF NOT EXISTS ohlc_D (
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
            SELECT create_hypertable('ohlc_D', 'time', if_not_exists => TRUE)
            """,
            """CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks (time, symbol)""",
            """CREATE INDEX IF NOT EXISTS idx_ohlc_1m_symbol_time ON ohlc_1m (time, symbol)""",
            """CREATE INDEX IF NOT EXISTS idx_ohlc_5m_symbol_time ON ohlc_5m (time, symbol)""",
            """CREATE INDEX IF NOT EXISTS idx_ohlc_15m_symbol_time ON ohlc_15m (time, symbol)""",
            """CREATE INDEX IF NOT EXISTS idx_ohlc_d_symbol_time ON ohlc_D (time, symbol)"""
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

        # volume tracking
        # Initialize volume tracking for all timeframes
        self.last_period_volume = {
            '1m': {},
            '5m': {},
            '15m': {}
        }

    def clean_database(self):
        """Clear all records from all tables in the database"""
        try:
            self.logger.info("Cleaning database tables...")
            tables = ['ticks', 'ohlc_1m', 'ohlc_5m', 'ohlc_15m', 'ohlc_D']  # Add all your table names here
            
            with self.db_conn.cursor() as cursor:
                # Disable triggers temporarily to avoid hypertable constraints
                cursor.execute("SET session_replication_role = 'replica';")
                
                for table in tables:
                    try:
                        cursor.execute(f"TRUNCATE TABLE {table} CASCADE;")
                        self.logger.info(f"Cleared table: {table}")
                    except Exception as e:
                        self.logger.error(f"Error clearing table {table}: {e}")
                        self.db_conn.rollback()
                        continue
                
                # Re-enable triggers
                cursor.execute("SET session_replication_role = 'origin';")
                self.db_conn.commit()
                
            self.logger.info("Database cleaning completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Database cleaning failed: {e}")
            self.db_conn.rollback()
            return False


    def insert_historical_data(self, df, symbol, interval):
        """
        Insert historical data into the appropriate database table
        
        Args:
            df (pd.DataFrame): DataFrame containing historical data
            symbol (str): Stock symbol (e.g., 'RELIANCE')
            interval (str): Time interval ('1m', '5m', '15m', '1d')
        """
        try:
            if df.empty:
                self.logger.warning(f"No data to insert for {symbol} {interval}")
                return False

            # Reset index to make timestamp a column
            df = df.reset_index()
            
            # Rename columns to match database schema
            df = df.rename(columns={
                'timestamp': 'time',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            
            # Handle timezone conversion differently for intraday vs daily data
            df['time'] = pd.to_datetime(df['time'])
            if interval == 'D':
                # Set to market open time (09:15:00 IST) for each date
                df['time'] = df['time'].dt.tz_localize(None)  # Remove any timezone
                df['time'] = df['time'] + pd.Timedelta(hours=9, minutes=15)
                df['time'] = df['time'].dt.tz_localize('Asia/Kolkata')
            else:
                if df['time'].dt.tz is None:
                    df['time'] = df['time'].dt.tz_localize('Asia/Kolkata')
                else:
                    df['time'] = df['time'].dt.tz_convert('Asia/Kolkata')
            
            # Convert to UTC for database storage
            df['time'] = df['time'].dt.tz_convert('UTC')

            # Add symbol column
            df['symbol'] = symbol
            
            # Select and order the columns we need (excluding 'oi' which we don't store)
            required_columns = ['time', 'symbol', 'open', 'high', 'low', 'close', 'volume']
            df = df[required_columns]
            
            # Convert numeric columns to appropriate types
            numeric_cols = ['open', 'high', 'low', 'close']
            df[numeric_cols] = df[numeric_cols].astype(float)
            df['volume'] = df['volume'].astype(int)
            
            # Determine the target table based on interval
            table_name = f'ohlc_{interval.lower()}'
            
            # Convert DataFrame to list of tuples
            records = [tuple(x) for x in df.to_numpy()]
            
            # Debug: print first record to verify format
            self.logger.debug(f"First record sample: {records[0] if records else 'No records'}")
            
            with self.db_conn.cursor() as cursor:
                # Use execute_batch for efficient bulk insertion
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
                """, records)
                
                self.db_conn.commit()
                self.logger.info(f"Successfully inserted {len(df)} records for {symbol} ({interval}) into {table_name}")
                return True
                
        except KeyError as e:
            self.logger.error(f"Missing required column in data for {symbol} {interval}: {e}")
            self.logger.error(f"Available columns: {df.columns.tolist()}")
            return False
        except Exception as e:
            self.logger.error(f"Error inserting historical data for {symbol} {interval}: {e}")
            self.logger.error(traceback.format_exc())
            self.db_conn.rollback()
            return False
        

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
            
            # Reset volume tracking
            self.last_period_volume = {
                '1m': {},
                '5m': {},
                '15m': {}
            }

    def group_missing_dates(self, missing_dates):
        """
        Groups missing dates into continuous ranges.
        
        Example:
        [2025-05-01, 2025-05-02, 2025-05-03, 2025-05-05]
        → [(2025-05-01, 2025-05-03), (2025-05-05, 2025-05-05)]
        """
        sorted_dates = sorted(missing_dates)
        ranges = []
        for _, g in groupby(enumerate(sorted_dates), lambda x: x[0] - x[1].toordinal()):
            group = list(map(itemgetter(1), g))
            ranges.append((group[0], group[-1]))
        return ranges

    def chunk_dates(self, start_date, end_date, chunk_size_days):
        current = start_date
        while current <= end_date:
            next_chunk = min(current + timedelta(days=chunk_size_days - 1), end_date)
            yield current, next_chunk
            current = next_chunk + timedelta(days=1)

    def get_existing_dates(self, symbol, interval):
        table_name = f"ohlc_d"
        query = f"""
            SELECT DISTINCT DATE(time AT TIME ZONE 'Asia/Kolkata') as trade_date
            FROM {table_name}
            WHERE symbol = %s
            ORDER BY trade_date;
        """
        try:
            with self.db_conn.cursor() as cursor:
                cursor.execute(query, (symbol,))
                rows = cursor.fetchall()
                return set(row[0] for row in rows)
        except Exception as e:
            self.logger.error(f"Error fetching existing dates: {e}")
            return set()
        
    
    def fetch_missing_data(self, symbol, interval, client, start_date, end_date):
        try:
            existing_dates = self.get_existing_dates(symbol, interval)
            all_dates = pd.date_range(start=start_date, end=end_date, freq='D').date
            missing_dates = sorted(set(all_dates) - set(existing_dates))
            missing_ranges = self.group_missing_dates(missing_dates)
            self.logger.info(f"Missing dates for {symbol} {interval}: {missing_ranges}")

            for range_start, range_end in missing_ranges:
                condition_1 = range_start.weekday() in [5, 6] and range_end.weekday() in [5, 6] and (range_end - range_start).days <= 2
                condition_2 = range_start.weekday() in [0, 1, 2, 3, 4] and range_end.weekday() in [0, 1, 2, 3, 4] and (range_end - range_start).days == 0
                if (condition_1 or condition_2): # Skip weekends
                    continue
                df = client.history(
                        symbol=symbol,
                        exchange='NSE',
                        interval=interval,
                        start_date=range_start.strftime('%Y-%m-%d'),
                        end_date=range_end.strftime('%Y-%m-%d')
                    )
                # Check if df is dictionary before accessing 'df'
                if df.__class__ == dict:                    
                    self.logger.warning(f"[{symbol}] ⚠️ API Response error! No data on {range_start}")
                    self.logger.info(f"API Response: {df}")
                    continue
                if not df.empty:
                    self.insert_historical_data(df, symbol, interval)                    
                else:
                    self.logger.warning(f"[{symbol}] ⚠️ Empty Dataframe! No data on {range_start}")

        except Exception as e:
            self.logger.error(f"[{symbol}] ❌ Error during fetch: {e}")
    

    def fetch_historical_data(self, symbol, interval, client, start_date, end_date):
        try:
            df = client.history(
                    symbol=symbol,
                    exchange='NSE',
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date
                )
            # Check if df is dictionary before accessing 'df'
            if df.__class__ == dict:                    
                self.logger.warning(f"[{symbol}] ⚠️ API Response error! No data on {start_date}")
                self.logger.info(f"API Response: {df}")
            if not df.empty:
                self.insert_historical_data(df, symbol, interval)                    
            else:
                self.logger.warning(f"[{symbol}] ⚠️ Empty Dataframe! No data on {start_date}")

        except Exception as e:
            self.logger.error(f"[{symbol}] ❌ Error during fetch: {e}")

    def process_symbol_interval(self, symbol, interval, client, start_date, end_date):
        """Process a single symbol-interval pair"""
        try:
            if interval == "5m" or interval == "1m":
                # Chunk the dates into smaller ranges to avoid timeout
                s_d = datetime.strptime(start_date, "%Y-%m-%d").date()
                e_d = datetime.strptime(end_date, "%Y-%m-%d").date()
                #self.logger.info(f"Fetching data for {symbol} with interval {interval} from {s_d} to {e_d}")
                
                for chunk_start, chunk_end in self.chunk_dates(start_date=s_d, end_date=e_d, chunk_size_days=10):
                    self.fetch_historical_data(
                        symbol, 
                        interval, 
                        client, 
                        chunk_start.strftime("%Y-%m-%d"),
                        chunk_end.strftime("%Y-%m-%d")
                    )
            else:    
                self.fetch_historical_data(symbol, interval, client, start_date, end_date)
        except Exception as e:
            self.logger.error(f"Error processing {symbol} {interval}: {str(e)}")


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
            
            # Validate date range
            if dt.year < 2020 or dt.year > 2030:
                raise ValueError(f"Implausible date {dt} from timestamp {timestamp}")
                       
            # Prepare database record
            record = {
                'time': dt,  # Convert ms to seconds
                'symbol': symbol,
                'open': float(value['ltp']),
                'high': float(value['ltp']),
                'low': float(value['ltp']),
                'close': float(value['ltp']),
                'volume': int(value['volume'])
            }

            #self.logger.info(f"Record---------> {record}")
            
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
        """Add tick to aggregation buffers"""
        with self.aggregation_lock:
            for timeframe in ['1m', '5m', '15m']:
                minutes = int(timeframe[:-1])
                symbol = record['symbol']
                aligned_time = self.floor_to_interval(record['time'], minutes)

                if symbol not in self.tick_buffer[timeframe]:
                    self.tick_buffer[timeframe][symbol] = {}

                # Initialize this specific minute bucket
                if aligned_time not in self.tick_buffer[timeframe][symbol]:
                    self.tick_buffer[timeframe][symbol][aligned_time] = {
                        'opens': [],
                        'highs': [],
                        'lows': [],
                        'closes': [],
                        'volumes': [],
                        'first_tick': None  # Track the first tick separately
                    }

                bucket = self.tick_buffer[timeframe][symbol][aligned_time]

                # For the first tick in this interval, store it separately
                if bucket['first_tick'] is None:
                    bucket['first_tick'] = record

                bucket['opens'].append(record['open'])
                bucket['highs'].append(record['high'])
                bucket['lows'].append(record['low'])
                bucket['closes'].append(record['close'])
                bucket['volumes'].append(record['volume'])

    def check_aggregation(self, current_time):
        """Check if aggregation should occur for any timeframe"""
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
        with self.aggregation_lock:
            symbol_buckets = self.tick_buffer[timeframe]
            if not symbol_buckets:
                return False

            aggregated = []
            table_name = f"ohlc_{timeframe}"

            for symbol, buckets in symbol_buckets.items():
                for bucket_start, data in list(buckets.items()):
                    if bucket_start >= self.last_agg_time[timeframe] + timedelta(minutes=int(timeframe[:-1])):
                        # Don't process future buckets
                        continue

                    if not data['opens']:
                        continue
                    
                    try:
                        # Get OHLC values
                        if data['first_tick'] is not None:
                            open_ = data['first_tick']['open']
                        else:
                            open_ = data['opens'][0]

                        #open_ = data['opens'][0]
                        high = max(data['highs'])
                        low = min(data['lows'])
                        close = data['closes'][-1]      

                        # Calculate volume correctly for cumulative data
                        current_last_volume = data['volumes'][-1]
                        previous_last_volume = self.last_period_volume[timeframe].get(symbol, current_last_volume)
                        volume = max(0, current_last_volume - previous_last_volume)

                        # Store the current last volume for next period
                        self.last_period_volume[timeframe][symbol] = current_last_volume
   
                        aggregated.append((bucket_start, symbol, open_, high, low, close, volume))

                        # Remove this bucket to avoid re-aggregation
                        del self.tick_buffer[timeframe][symbol][bucket_start]
                    
                    except Exception as e:
                        self.logger.error(f"Error aggregating {symbol} for {timeframe}: {e}")
                        continue

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
                        self.logger.info(f"Aggregated {len(aggregated)} symbols to {table_name}")
                        return True
                except Exception as e:
                    self.logger.error(f"Error aggregating {timeframe} data: {e}")
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

    client = api(
        api_key="8009e08498f085ff1a3e7da718c5f4b585eaf9c2b7ce0c72740ab2b5d283d36c",  # Replace with your API key
        host="http://127.0.0.1:5000"
    )
    # Start the timer
    start_time = time.time()

    # Argument parsing
    parser = argparse.ArgumentParser(description='Market Data Processor')
    parser.add_argument('--mode', type=str, choices=['live', 'backtest'], required=True,
                       help='Run mode: "live" for live processing, "backtest" for backtesting')
    
    parser.add_argument('--from_date', type=str,
                       help='Start date for backtest (DD-MM-YYYY format)')
    parser.add_argument('--to_date', type=str,
                       help='End date for backtest (DD-MM-YYYY format)')
    parser.add_argument('--backtest_folder', type=str,
                       help='Folder to store backtest data')
    args = parser.parse_args()

    # Validate arguments
    if args.mode == 'backtest':
        if not args.from_date or not args.to_date:
            parser.error("--from_date and --to_date are required in backtest mode")
        
        try:
            from_date = datetime.strptime(args.from_date, '%d-%m-%Y').date()
            to_date = datetime.strptime(args.to_date, '%d-%m-%Y').date()
            
            if from_date > to_date:
                parser.error("--from_date cannot be after --to_date")
                
        except ValueError as e:
            parser.error(f"Invalid date format. Please use DD-MM-YYYY. Error: {e}")

    # Initialize the processor
    processor = MarketDataProcessor()
    try:
        if args.mode == 'live':
            # Clean the database at the start of the intraday trading session(9:00 AM IST)
            if datetime.now().hour == 9 and datetime.now().minute == 0:
                processor.clean_database()        

            # Fetch the last 10 days historical data(1 min, 5 min, 15min, D) and insert in the DB
            # Dynamic date range: 7 days back to today
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

            # Import symbol list from CSV file
            symbol_list = pd.read_csv('symbol_list.csv')
            symbol_list = symbol_list['Symbol'].tolist()

            # Fetch historical data for each symbol
            for symbol in symbol_list:
                for interval in ["D", "15m", "5m", "1m"]:
                    df = client.history(
                        symbol=symbol,
                        exchange='NSE',
                        interval=interval,
                        start_date=start_date,
                        end_date=end_date
                    )
                    #print(df.head())
                    # Insert historical data into the database
                    processor.insert_historical_data(df, symbol, interval)

            # Process the real-time data
            processor.process_messages()
            
        elif args.mode == 'backtest':
            logger.info(f"Running in backtest mode from {args.from_date} to {args.to_date}")
            # Clean the database
            # processor.clean_database()

            # Load historical data for the specified date range
            # Fetch the last 10 days historical data(1 min, 5 min, 15min, D) and insert in the DB
            # Dynamic date range: 7 days back to today
            end_date = to_date.strftime("%Y-%m-%d")     
            start_date = (from_date - timedelta(days=20)).strftime("%Y-%m-%d") 

            # Cleaning the backtest results folder
            base_output_dir = args.backtest_folder
            output_dir = os.path.join(base_output_dir)
            os.makedirs(output_dir, exist_ok=True)
            for filename in os.listdir(output_dir):
                if filename.endswith(".csv"):
                    os.remove(os.path.join(output_dir, filename))
            
            # Import symbol list from CSV file
            symbol_list = pd.read_csv('symbol_list_backtest.csv')
            symbol_list = symbol_list['Symbol'].tolist()

            # Fetch historical data for each symbol
            intervals = ["D", "15m", "5m", "1m"]

            # Create all combinations of (symbol, interval)
            symbol_interval_pairs = list(product(symbol_list, intervals))

            # UNCOMMENT THIS BLOCK FOR FETCHING HISTORICAL DATA FOR ALL INTERVALS
            with ThreadPoolExecutor(max_workers=8) as executor:  # Adjust max_workers as needed
                futures = []
                for symbol, interval in symbol_interval_pairs:
                    time.sleep(1)
                    futures.append(
                        executor.submit(
                            processor.process_symbol_interval,
                            symbol,
                            interval,
                            client,
                            start_date,
                            end_date
                        )
                    )
                
                # Wait for all tasks to complete (optional)
                try:
                    for future in futures:                        
                        future.result()  # This will re-raise any exceptions from the thread
                except KeyboardInterrupt:
                    print("Interrupted by user. Cancelling all futures.")
                    for future in futures:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)

            
            # Without threading
            # for symbol, interval in symbol_interval_pairs:
            #     if interval == "5m" or interval == "1m":
            #         # Chunk the dates into smaller ranges to avoid timeout
            #         s_d = datetime.strptime(start_date, "%Y-%m-%d").date()
            #         e_d = datetime.strptime(end_date, "%Y-%m-%d").date()
            #         logger.info(f"Fetching data for {symbol} with interval {interval} from {s_d} to {e_d}")
                    
            #         for chunk_start, chunk_end in processor.chunk_dates(start_date=s_d, end_date=e_d, chunk_size_days=10):
            #             processor.fetch_historical_data(symbol, interval, client, chunk_start.strftime("%Y-%m-%d") , chunk_end.strftime("%Y-%m-%d"))
            #     else:    
            #         processor.fetch_historical_data(symbol, interval, client, start_date, end_date)           
            
            
            # Process data in simulation mode     
            def run_backtest_for_symbol(symbol, connection_pool, start_date, end_date, base_output_dir):
                # get connection from pool
                conn = connection_pool.getconn()

                try:
                    engine = BacktestEngine(
                        conn=conn,
                        symbol=symbol,                    
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                    trades_df = engine.run()
                    
                    output_dir = os.path.join(base_output_dir)
                    os.makedirs(output_dir, exist_ok=True)

                    trades_file = os.path.join(output_dir, f"backtest_trades_{symbol}.csv")
                    summary_file = os.path.join(output_dir, f"summary_{symbol}.csv")

                    trades_df.to_csv(trades_file, index=False)

                    #if hasattr(engine, 'export_trail_charts'):
                    #    engine.export_trail_charts()
                    #                     
                    logger.info(f"✅ Backtest completed for {symbol} → Trades: {len(trades_df)} → Saved: backtest_trades_{symbol}.csv")
                
                finally:
                    connection_pool.putconn(conn)


            def aggregate_all_summaries(base_output_dir="backtest_results", output_filename="master_summary.csv"):
                """
                Aggregate all summary files from the organized folder structure
                """
                # Find all summary files recursively
                summary_pattern = os.path.join(base_output_dir, "**", "backtest_trades_*.csv")
                summary_files = glob.glob(summary_pattern, recursive=True)

                if not summary_files:
                    logger.warning(f"No summary files found in {base_output_dir}")
                    return

                logger.info(f"Found {len(summary_files)} summary files to aggregate")
                
                all_dfs = []
                skipped_files = []
                
                for file_path in summary_files:
                    try:
                        # Check if file is empty first
                        if os.path.getsize(file_path) == 0:
                            logger.warning(f"Skipping empty file: {file_path}")
                            skipped_files.append(file_path)
                            continue
                        
                        # Try to read the CSV file
                        df = pd.read_csv(file_path)
                        
                        # Check if DataFrame is empty or has no columns
                        if df.empty:
                            logger.warning(f"Skipping empty DataFrame from file: {file_path}")
                            skipped_files.append(file_path)
                            continue
                            
                        if len(df.columns) == 0:
                            logger.warning(f"Skipping file with no columns: {file_path}")
                            skipped_files.append(file_path)
                            continue
                        
                        # Add metadata columns to track source
                        df['source_file'] = os.path.basename(file_path)
                        df['folder_path'] = os.path.dirname(file_path)
                        all_dfs.append(df)
                        
                    except pd.errors.EmptyDataError:
                        #logger.warning(f"Skipping empty CSV file: {file_path}")
                        skipped_files.append(file_path)
                        continue
                    except pd.errors.ParserError as e:
                        logger.error(f"Parser error reading {file_path}: {e}")
                        skipped_files.append(file_path)
                        continue
                    except FileNotFoundError:
                        logger.error(f"File not found: {file_path}")
                        skipped_files.append(file_path)
                        continue
                    except PermissionError:
                        logger.error(f"Permission denied reading file: {file_path}")
                        skipped_files.append(file_path)
                        continue
                    except Exception as e:
                        logger.error(f"Unexpected error reading {file_path}: {e}")
                        skipped_files.append(file_path)
                        continue
                
                # Log summary of processing
                processed_files = len(summary_files) - len(skipped_files)
                logger.info(f"📊 Processing summary: {processed_files} files processed, {len(skipped_files)} files skipped")
                
                if all_dfs:
                    try:
                        master_df = pd.concat(all_dfs, ignore_index=True)
                        master_df.sort_values(by='entry_time', inplace=True)

                        # Save master trades in the base output directory                        
                        master_output_path_raw = os.path.join(base_output_dir, "backtest_trades_master_raw.csv")
                        master_df.to_csv(master_output_path_raw, index=False)

                        # Process the trades with constraints
                        master_df = process_trades_with_constraints(master_df)
                      
                        # STRATEGY SUMMARY
                        strat_summary = master_df.groupby('strategy').agg(
                            tot_trades=('gross_pnl', 'count'),
                            proftrades=('net_pnl', lambda x: (x > 0).sum()),
                            losstrades=('net_pnl', lambda x: (x < 0).sum()),
                            win_rate=('net_pnl', lambda x: (x > 0).mean() * 100),
                            gross_pnl=('gross_pnl', 'sum'),
                            brokerage=('brokerage', 'sum'),
                            tax_amount=('tax', 'sum'),
                            net_pnl__=('net_pnl', 'sum'),
                            avg_pnl__=('net_pnl', 'mean'),         
                            max_dd__=('net_pnl', lambda x: (x.cumsum() - x.cumsum().cummax()).min()),
                            avg_dd_=('net_pnl', lambda x: 
                                (lambda dd: dd[dd > 0].mean() if (dd > 0).any() else 0)(
                                    x.cumsum() - x.cumsum().cummax()
                                )
                            )
                        ).reset_index()
                        strat_summary = strat_summary.round(2)

                        # MONTH SUMMARY
                        master_df['entry_time'] = pd.to_datetime(master_df['entry_time'])
                        master_df['month'] = master_df['entry_time'].dt.to_period('M').astype(str)

                        month_summary = master_df.groupby('month').agg(
                            tot_trades=('gross_pnl', 'count'),
                            proftrades=('net_pnl', lambda x: (x > 0).sum()),
                            losstrades=('net_pnl', lambda x: (x < 0).sum()),
                            win_rate=('net_pnl', lambda x: (x > 0).mean() * 100),
                            gross_pnl=('gross_pnl', 'sum'),
                            brokerage=('brokerage', 'sum'),
                            tax_amount=('tax', 'sum'),
                            net_pnl__=('net_pnl', 'sum'),
                            avg_pnl__=('net_pnl', 'mean'),         
                            max_dd__=('net_pnl', lambda x: (x.cumsum() - x.cumsum().cummax()).min()),
                            avg_dd_=('net_pnl', lambda x: 
                                (lambda dd: dd[dd > 0].mean() if (dd > 0).any() else 0)(
                                    x.cumsum() - x.cumsum().cummax()
                                )
                            )
                        ).reset_index()
                        month_summary = month_summary.round(2)                        

                        # MONTH-STRATEGY SUMMARY
                        month_strat_summary = master_df.groupby(['month', 'strategy']).agg(
                            tottrades=('gross_pnl', 'count'),
                            p_trades=('net_pnl', lambda x: (x > 0).sum()),
                            l_trades=('net_pnl', lambda x: (x < 0).sum()),
                            win_rate=('net_pnl', lambda x: (x > 0).mean() * 100),
                            gross_pnl=('gross_pnl', 'sum'),
                            brokerage=('brokerage', 'sum'),
                            tax_amt=('tax', 'sum'),
                            net_pnl_=('net_pnl', 'sum'),
                            avg_pnl_=('net_pnl', 'mean'),         
                            max_dd__=('net_pnl', lambda x: (x.cumsum() - x.cumsum().cummax()).min()),
                            avg_dd__=('net_pnl', lambda x: 
                                (lambda dd: dd[dd > 0].mean() if (dd > 0).any() else 0)(
                                    x.cumsum() - x.cumsum().cummax()
                                )
                            )
                        ).reset_index()
                        month_strat_summary = month_strat_summary.round(2)

                        # Save master trades in the base output directory                        
                        master_output_path = os.path.join(base_output_dir, "backtest_trades_master.csv")
                        master_df.to_csv(master_output_path, index=False)
                        
                        # Save strategy summary in the base output directory     
                        master_output_path = os.path.join(base_output_dir, "master_summary_by_strategy.csv")
                        strat_summary.to_csv(master_output_path, index=False)

                        # Save month summary in the base output directory
                        master_output_path = os.path.join(base_output_dir, "master_summary_by_month.csv")
                        month_summary.to_csv(master_output_path, index=False)   

                        # Save month-strategy summary in the base output directory
                        master_output_path = os.path.join(base_output_dir, "master_summary_by_strategy_month.csv")
                        month_strat_summary.to_csv(master_output_path, index=False)

                        # Remove the backtest_trades_* except backtest_trades_master.csv
                        for file in os.listdir(base_output_dir):
                            if file.startswith("backtest_trades_") and file != "backtest_trades_master.csv" and file != "backtest_trades_master_raw.csv":
                                file_path = os.path.join(base_output_dir, file)
                                os.remove(file_path)
                        
                        print(f"📈 Total symbols processed: {len(master_df)}")
                        print(f"📋 Valid files: {len(all_dfs)}, Skipped files: {len(skipped_files)}")
                        
                        if not strat_summary.empty:                            
                            print_aggregate_totals_1(strat_summary, 'PERFORMANCE STRATEGY_WISE')
                        
                        if not month_summary.empty:                            
                            print_aggregate_totals_1(month_summary, 'PERFORMANCE MONTH_WISE')

                        if not month_strat_summary.empty:                            
                            print_aggregate_totals_2(month_strat_summary, "PERFORMANCE MONTH_STRATEGY_WISE")
                        
                    except Exception as e:
                        logger.error(f"Error creating master summary: {e}")
                        logger.error(f"Number of DataFrames to concatenate: {len(all_dfs)}")
                        return
                        
                else:
                    logger.warning("❌ No valid summary data found to aggregate")
                    print(f"\n⚠️  No valid summary files found. All {len(skipped_files)} files were skipped.")
                    
                    # Optionally, create an empty master file with headers if you know the expected structure
                    try:
                        # Create empty master file with basic structure
                        empty_df = pd.DataFrame(columns=['symbol', 'total_trades', 'profitable_trades', 'loss_trades', 
                                                    'win_rate', 'gross_pnl', 'max_drawdown', 'source_file', 'folder_path'])
                        master_output_path = os.path.join(base_output_dir, output_filename)
                        empty_df.to_csv(master_output_path, index=False)
                        logger.info(f"📄 Created empty master summary file: {master_output_path}")
                    except Exception as e:
                        logger.error(f"Error creating empty master summary: {e}")   
          
                        
            def print_aggregate_totals_1(summary_df, title='PERFORMANCE SUMMARY'):
                """
                Print Excel-like table with perfect alignment between headers and data rows
                """
                if not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
                    print(f"{Fore.RED}❌ No valid summary data")
                    return

                try:
                    # Create display copy
                    display_df = summary_df.copy()
                    
                    # Format numeric columns
                    def format_currency(x):
                        if pd.isna(x): return "N/A"
                        x = float(x)
                        if abs(x) >= 1000000: return f"₹{x/1000000:.1f}M"
                        if abs(x) >= 1000: return f"₹{x/1000:.1f}K"
                        return f"₹{x:.0f}"

                    currency_cols = ['gross_pnl', 'tax_amount', 'brokerage', 'net_pnl__', 'avg_pnl__', 'max_dd__', 'avg_dd_']
                    for col in currency_cols:
                        display_df[col] = display_df[col].apply(format_currency)

                    # Get terminal width
                    try:
                        terminal_width = os.get_terminal_size().columns
                    except:
                        terminal_width = 80

                    # Calculate column widths (content + header)
                    col_widths = {}
                    for col in display_df.columns:
                        content_width = max(display_df[col].astype(str).apply(len).max(), len(col))
                        col_widths[col] = min(content_width + 2, 20)  # Max 20 chars per column

                    # Adjust to fit terminal
                    while sum(col_widths.values()) + len(col_widths) + 1 > terminal_width:
                        max_col = max(col_widths, key=col_widths.get)
                        if col_widths[max_col] > 8:  # Never go below 8 chars
                            col_widths[max_col] -= 1
                        else:
                            break  # Can't shrink further

                    # Build horizontal border
                    border = '+' + '+'.join(['-' * (col_widths[col]) for col in display_df.columns]) + '+'

                    # Print header
                    print(f"\n{Style.BRIGHT}{Fore.BLUE}📊 {title}")
                    print(border)
                    
                    # Print column headers
                    header_cells = []
                    for col in display_df.columns:
                        header = f" {col.upper().replace('_', ' ')}"
                        header = header.ljust(col_widths[col]-1)
                        header_cells.append(f"{Style.BRIGHT}{header}{Style.RESET_ALL}")
                    print('|' + '|'.join(header_cells) + '|')
                    print(border)

                    # Print data rows
                    for _, row in display_df.iterrows():
                        cells = []
                        for col in display_df.columns:
                            cell_content = str(row[col])[:col_widths[col]-2]
                            if len(str(row[col])) > col_widths[col]-2:
                                cell_content = cell_content[:-1] + '…'
                            cells.append(f" {cell_content.ljust(col_widths[col]-1)}")
                        print('|' + '|'.join(cells) + '|')

                    # Print footer
                    print(border)

                    # Print summary
                    if 'net_pnl__' in summary_df.columns:
                        total_net = summary_df['net_pnl__'].sum()
                        status = (f"{Fore.GREEN}↑PROFIT" if total_net > 0 else 
                                f"{Fore.RED}↓LOSS" if total_net < 0 else 
                                f"{Fore.YELLOW}➔BREAKEVEN")
                        print(f"| {status}{Style.RESET_ALL}  Net: {format_currency(total_net)}  "
                            f"Trades: {summary_df['tot_trades'].sum():,}  "
                            f"Win%: {summary_df['proftrades'].sum()/summary_df['tot_trades'].sum()*100:.1f}%".ljust(len(border)-1) + "|")
                        print(border + Style.RESET_ALL)

                except Exception as e:
                    print(f"{Fore.RED}❌ Error displaying table: {e}")

            def print_aggregate_totals_2(summary_df, title='PERFORMANCE SUMMARY'):
                """
                Print Excel-like table with perfect alignment between headers and data rows
                """
                if not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
                    print(f"{Fore.RED}❌ No valid summary data")
                    return

                try:
                    # Create display copy
                    display_df = summary_df.copy()
                    
                    # Format numeric columns
                    def format_currency(x):
                        if pd.isna(x): return "N/A"
                        x = float(x)
                        if abs(x) >= 1000000: return f"₹{x/1000000:.1f}M"
                        if abs(x) >= 1000: return f"₹{x/1000:.1f}K"
                        return f"₹{x:.0f}"

                    currency_cols = ['gross_pnl', 'tax_amt', 'brokerage', 'net_pnl_', 'avg_pnl_', 'max_dd__', 'avg_dd__']
                    for col in currency_cols:
                        display_df[col] = display_df[col].apply(format_currency)

                    # Get terminal width
                    try:
                        terminal_width = os.get_terminal_size().columns
                    except:
                        terminal_width = 80

                    # Calculate column widths (content + header)
                    col_widths = {}
                    for col in display_df.columns:
                        content_width = max(display_df[col].astype(str).apply(len).max(), len(col))
                        col_widths[col] = min(content_width + 2, 20)  # Max 20 chars per column

                    # Adjust to fit terminal
                    while sum(col_widths.values()) + len(col_widths) + 1 > terminal_width:
                        max_col = max(col_widths, key=col_widths.get)
                        if col_widths[max_col] > 8:  # Never go below 8 chars
                            col_widths[max_col] -= 1
                        else:
                            break  # Can't shrink further

                    # Build horizontal border
                    border = '+' + '+'.join(['-' * (col_widths[col]) for col in display_df.columns]) + '+'

                    # Print header
                    print(f"\n{Style.BRIGHT}{Fore.BLUE}📊 {title}")
                    print(border)
                    
                    # Print column headers
                    header_cells = []
                    for col in display_df.columns:
                        header = f" {col.upper().replace('_', ' ')}"
                        header = header.ljust(col_widths[col]-1)
                        header_cells.append(f"{Style.BRIGHT}{header}{Style.RESET_ALL}")
                    print('|' + '|'.join(header_cells) + '|')
                    print(border)

                    # Print data rows
                    for _, row in display_df.iterrows():
                        cells = []
                        for col in display_df.columns:
                            cell_content = str(row[col])[:col_widths[col]-2]
                            if len(str(row[col])) > col_widths[col]-2:
                                cell_content = cell_content[:-1] + '…'
                            cells.append(f" {cell_content.ljust(col_widths[col]-1)}")
                        print('|' + '|'.join(cells) + '|')

                    # Print footer
                    print(border)

                    # Print summary
                    if 'net_pnl_' in summary_df.columns:
                        total_net = summary_df['net_pnl_'].sum()
                        status = (f"{Fore.GREEN}↑PROFIT" if total_net > 0 else 
                                f"{Fore.RED}↓LOSS" if total_net < 0 else 
                                f"{Fore.YELLOW}➔BREAKEVEN")
                        print(f"| {status}{Style.RESET_ALL}  Net: {format_currency(total_net)}  "
                            f"Trades: {summary_df['tottrades'].sum():,}  "
                            f"Win%: {summary_df['p_trades'].sum()/summary_df['tottrades'].sum()*100:.1f}%".ljust(len(border)-1) + "|")
                        print(border + Style.RESET_ALL)

                except Exception as e:
                    print(f"{Fore.RED}❌ Error displaying table: {e}")

            def process_trades_with_constraints(trades_df):
                # Convert string times to datetime objects
                trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
                trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
                
                # Sort trades by entry time
                trades_df = trades_df.sort_values('entry_time')
                
                # Initialize tracking variables
                active_positions = []
                strategy_counts = defaultdict(int)
                daily_strategy_tracker = defaultdict(set)  # {date: {strategies_used}}
                filtered_trades = []
                
                for _, trade in trades_df.iterrows():
                    trade_date = trade['entry_time'].date()
                    strategy = str(trade['strategy'])
                    symbol = trade['symbol']
                    
                    # Check if we've already used this strategy today
                    if strategy in daily_strategy_tracker.get(trade_date, set()):
                        continue
                    
                    # Check if we have capacity for new positions (max 3)
                    if len(active_positions) >= 3:
                        # Find the earliest exit time among active positions
                        earliest_exit = min(pos['exit_time'] for pos in active_positions)
                        if trade['entry_time'] < earliest_exit:
                            # Can't take this trade as all 3 positions would still be open
                            continue
                    
                    # For same-time entries, we need to check alphabetical priority
                    # Get all trades at the same entry time for the same strategy
                    same_time_trades = trades_df[
                        (trades_df['entry_time'] == trade['entry_time']) & 
                        (trades_df['strategy'] == trade['strategy'])]
                    
                    if len(same_time_trades) > 1:
                        # Sort by symbol alphabetically and take the first one
                        same_time_trades = same_time_trades.sort_values('symbol')
                        if symbol != same_time_trades.iloc[0]['symbol']:
                            continue
                    
                    # If we get here, the trade passes all constraints
                    filtered_trades.append(trade)
                    
                    # Update tracking
                    daily_strategy_tracker[trade_date].add(strategy)
                    
                    # Add to active positions
                    active_positions.append({
                        'symbol': symbol,
                        'strategy': strategy,
                        'entry_time': trade['entry_time'],
                        'exit_time': trade['exit_time']
                    })
                    
                    # Remove any positions that have exited
                    active_positions = [pos for pos in active_positions 
                                    if pos['exit_time'] > trade['entry_time']]
                
                # Create new DataFrame with filtered trades
                filtered_df = pd.DataFrame(filtered_trades)
                
                return filtered_df
                    
            # Run backtests in parallel 
            # Create connection pool once
            # db_config = {
            #         "user": processor.db_manager.user,
            #         "password": processor.db_manager.password,
            #         "host": processor.db_manager.host,
            #         "port": processor.db_manager.port,
            #         "dbname": processor.db_manager.dbname
            # }

            # connection_pool = psycopg2.pool.ThreadedConnectionPool(
            #     minconn=1, maxconn=8,  # Adjust based on your needs
            #     user=db_config['user'],
            #     password=db_config['password'],
            #     host=db_config['host'],
            #     port=db_config['port'],
            #     dbname=db_config['dbname']
            # )    
            # with ThreadPoolExecutor(max_workers=8) as executor:
            #     futures = []                
            #     for symbol in symbol_list:
            #         futures.append(executor.submit(run_backtest_for_symbol, symbol, connection_pool, from_date, to_date, base_output_dir))
            #     try:
            #         for future in futures:
            #             future.result()
            #     except KeyboardInterrupt:
            #         print("Interrupted by user. Cancelling all futures.")
            #         for future in futures:
            #             future.cancel()
            #         executor.shutdown(wait=False, cancel_futures=True)
                
            # # Aggregate summaries from the organized folder structure                
            # aggregate_all_summaries(base_output_dir, "master_summary.csv")               
            
            # End the timer
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.info(f"Elapsed time: {elapsed_time} seconds")
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        processor.shutdown()
