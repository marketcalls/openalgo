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
            #self.logger.info(f"Missing dates for {symbol} {interval}: {missing_ranges}")

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
                    self.logger.warning(f"[{symbol}] ⚠️ No data on {range_start}")
                    continue
                if not df.empty:
                    self.insert_historical_data(df, symbol, interval)                    
                else:
                    self.logger.warning(f"[{symbol}] ⚠️ No data on {range_start}")

        except Exception as e:
            self.logger.error(f"[{symbol}] ❌ Error during fetch: {e}")
    
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

    # Argument parsing
    parser = argparse.ArgumentParser(description='Market Data Processor')
    parser.add_argument('--mode', type=str, choices=['live', 'backtest'], required=True,
                       help='Run mode: "live" for live processing, "backtest" for backtesting')
    
    parser.add_argument('--from_date', type=str,
                       help='Start date for backtest (DD-MM-YYYY format)')
    parser.add_argument('--to_date', type=str,
                       help='End date for backtest (DD-MM-YYYY format)')
    parser.add_argument('--interval', type=str, default='1m', help='Interval to use for backtest/live (e.g., 1m, 5m, 15m, D)')
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
                for interval in ["1m", "5m", "15m", "D"]:
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
            start_date = from_date.strftime("%Y-%m-%d")

            # Import symbol list from CSV file
            symbol_list = pd.read_csv('symbol_list_backtest.csv')
            symbol_list = symbol_list['Symbol'].tolist()

            # Fetch historical data for each symbol
            intervals = ["1m", "5m", "15m", "D"]

            # Create all combinations of (symbol, interval)
            symbol_interval_pairs = list(product(symbol_list, intervals))

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(
                        processor.fetch_missing_data,
                        symbol,
                        interval,
                        client,
                        start_date,
                        end_date
                    )
                    for symbol, interval in symbol_interval_pairs
                ]

                for future in as_completed(futures):
                    future.result()

            # Process data in simulation mode     
            def run_backtest_for_symbol(symbol, db_config, start_date, end_date, interval):
                # Create new connection per thread
                conn = psycopg2.connect(
                    user=db_config['user'],
                    password=db_config['password'],
                    host=db_config['host'],
                    port=db_config['port'],
                    dbname=db_config['dbname']
                )

                engine = BacktestEngine(
                    conn=conn,
                    symbol=symbol,
                    interval=interval,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d")
                )
                trades_df = engine.run()
                trades_df.to_csv(f"backtest_trades_{symbol}.csv", index=False)

                summary = engine.get_summary_metrics()
                pd.DataFrame([summary]).to_csv(f"summary_{symbol}.csv", index=False)

                if hasattr(engine, 'export_trail_charts'):
                    engine.export_trail_charts()

                conn.close()
                logger.info(f"✅ Backtest completed for {symbol} → Trades: {len(trades_df)} → Saved: backtest_trades_{symbol}.csv")


            def aggregate_all_summaries(output_path="master_summary.csv"):
                summary_files = glob.glob("summary_*.csv")

                if not summary_files:
                    logger.warning("No summary files found to aggregate.")
                    return

                all_dfs = [pd.read_csv(f) for f in summary_files]
                master_df = pd.concat(all_dfs, ignore_index=True)
                master_df.to_csv(output_path, index=False)

                logger.info(f"✅ Aggregated {len(summary_files)} summaries into {output_path}")
                print(master_df)

            # Run backtests in parallel
            interval = args.interval
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = []
                db_config = {
                    "user": processor.db_manager.user,
                    "password": processor.db_manager.password,
                    "host": processor.db_manager.host,
                    "port": processor.db_manager.port,
                    "dbname": processor.db_manager.dbname
                }
                for symbol in symbol_list:
                    futures.append(executor.submit(run_backtest_for_symbol, symbol, db_config, from_date, to_date, interval))
                for future in futures:
                    future.result()
                aggregate_all_summaries("master_summary.csv")                 

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        processor.shutdown()
