import os
import httpx
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from utils.logging import get_logger

logger = get_logger(__name__)

try:
    from extensions import socketio  # Import SocketIO
except ImportError:
    socketio = None

# Create a shared httpx client for connection pooling
client = httpx.Client(timeout=30.0)

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Define SymToken table
class SymToken(Base):
    __tablename__ = 'symtoken'
    id = Column(Integer, Sequence('symtoken_id_seq'), primary_key=True)
    symbol = Column(String, nullable=False, index=True)  # Single column index
    brsymbol = Column(String, nullable=False, index=True)  # Single column index
    name = Column(String)
    exchange = Column(String, index=True)  # Include this column in a composite index
    brexchange = Column(String, index=True)
    token = Column(String, index=True)  # Indexed for performance
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    # Define a composite index on symbol and exchange columns
    __table_args__ = (Index('idx_symbol_exchange', 'symbol', 'exchange'),)

def init_db():
    """Initialize the database and create tables"""
    logger.info("Initializing Master Contract DB")
    
    # Create database directory if it doesn't exist
    db_path = os.path.dirname(DATABASE_URL.replace('sqlite:///', ''))
    if db_path and not os.path.exists(db_path):
        os.makedirs(db_path)
    
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient='records')

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row['token'] not in existing_tokens]

    # Insert in bulk the filtered records
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()

# Define Tradejini API endpoints
TRADEJINI_BASE_URL = 'https://api.tradejini.com/v2'
SCRIP_GROUPS_URL = f'{TRADEJINI_BASE_URL}/api/mkt-data/scrips/symbol-store'
SCRIP_DATA_URL = f'{TRADEJINI_BASE_URL}/api/mkt-data/scrips/symbol-store/{{group}}'

def get_scrip_groups():
    """Fetch available scrip groups from Tradejini API"""
    logger.info("Fetching scrip groups")
    try:
        # Add version=0 parameter to force fresh data
        params = {'version': '0'}
        response = client.get(SCRIP_GROUPS_URL, params=params)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Received scrip groups data: {data}")
        
        # Extract symbolStore array from response
        if isinstance(data, dict) and 's' in data and data['s'] == 'ok':
            if 'd' in data and 'symbolStore' in data['d']:
                return data['d']['symbolStore']
        
        logger.info(f"Unexpected response format: {data}")
        return []
    except Exception as e:
        logger.error(f"Error fetching scrip groups: {e}")
        return []

def get_scrip_data(scrip_group):
    """Fetch scrip data for a specific group"""
    logger.info(f"Fetching scrip data for {scrip_group}")
    try:
        # Add version=0 parameter to force fresh data
        params = {'version': '0'}
        response = client.get(SCRIP_DATA_URL.format(group=scrip_group), params=params)
        response.raise_for_status()
        
        # Split the response text into lines
        lines = response.text.strip().split('\n')
        if not lines:
            return []
            
        # First line contains headers
        headers = lines[0].strip().split(',')
        
        # Convert remaining lines into list of dicts
        data = []
        for line in lines[1:]:
            values = line.strip().split(',')
            if len(values) == len(headers):
                data.append(dict(zip(headers, values)))
        
        logger.info(f"Processed {len(data)} records for {scrip_group}")
        return data
    except Exception as e:
        logger.error(f"Error fetching scrip data for {scrip_group}: {e}")
        return []

def format_symbol(row, id_format):
    """Format symbol based on Tradejini's idFormat patterns"""
    try:
        # Handle different idFormat patterns
        if id_format == 'instrument_symbol_series_exchange':
            # For equity symbols
            return row.get('symbol', '')
            
        elif id_format == 'instrument_symbol_exchange_expiry':
            # For futures
            symbol = row.get('symbol', '')
            expiry = row.get('expiry', '')
            return f"{symbol}{expiry}FUT" if expiry else symbol
            
        elif id_format == 'instrument_symbol_exchange_expiry_strike_optType':
            # For options
            symbol = row.get('symbol', '')
            expiry = row.get('expiry', '')
            strike = row.get('strikePrice')
            opt_type = row.get('optionType', 'CE')
            
            if all([symbol, expiry, strike, opt_type]):
                strike_fmt = int(float(strike)) if float(strike).is_integer() else float(strike)
                return f"{symbol}{expiry}{strike_fmt}{opt_type}"
            return symbol
            
        elif id_format == 'instrument_excToken_exchange':
            # For indices
            return row.get('symbol', '').replace(' ', '')
            
        else:
            # Default to trading symbol if format not recognized
            return row.get('tradingSymbol', row.get('symbol', ''))
            
    except Exception as e:
        logger.error(f"Error formatting symbol with format {id_format}: {e}")
        return row.get('tradingSymbol', row.get('symbol', ''))

def process_scrip_data(scrip_data, group_info):
    """Process scrip data into DataFrame format"""
    records = []
    
    # Convert CSV string to list of dictionaries if needed
    if isinstance(scrip_data, str):
        lines = scrip_data.strip().split('\n')
        if not lines:
            return pd.DataFrame()
            
        # First line contains headers
        headers = lines[0].strip().split(',')
        
        # Convert remaining lines into list of dicts
        scrip_data = []
        for line in lines[1:]:
            values = line.strip().split(',')
            if len(values) == len(headers):
                scrip_data.append(dict(zip(headers, values)))
    
    # Get group name and format
    group_name = group_info.get('name', '')
    
    # Common index symbol mappings
    COMMON_INDEX_MAP = {
        'NSE_INDEX': [
            'NIFTY', 'NIFTYNXT50', 'FINNIFTY', 'BANKNIFTY',
            'MIDCPNIFTY', 'INDIAVIX'
        ],
        'BSE_INDEX': [
            'SENSEX', 'BANKEX', 'SENSEX50'
        ]
    }
    
    # Handle index data separately
    if group_name == 'Index':
        # Process index records
        for item in scrip_data:
            try:
                # Parse the id to get exchange
                parts = item['id'].split('_')
                if len(parts) >= 3:
                    raw_exchange = parts[-1]  # Last part is exchange (NSE/BSE)
                    
                    # Map exchange for OpenAlgo format
                    exchange_map = {
                        'NSE': 'NSE_INDEX',
                        'BSE': 'BSE_INDEX'
                    }
                    
                    # Symbol mapping for special cases
                    symbol_map = {
                        'India VIX': 'INDIAVIX',
                        'SNXT50': 'SENSEX50'
                    }
                    
                    # Apply symbol mapping if needed
                    if item['symbol'] in symbol_map:
                        item['symbol'] = symbol_map[item['symbol']]
                    
                    record = {
                        'symbol': item['symbol'],  # Use symbol field directly
                        'brsymbol': item['dispName'],  # Use display name as broker symbol
                        'name': item['dispName'],  # Use display name as full name
                        'exchange': exchange_map.get(raw_exchange, raw_exchange),
                        'brexchange': raw_exchange,
                        'token': str(item['excToken']),
                        'expiry': '',
                        'strike': 0,
                        'lotsize': 1,
                        'instrumenttype': 'INDEX',
                        'tick_size': 0.05
                    }
                    records.append(record)
            except Exception as e:
                logger.info(f"Error processing index {item.get('dispName', '')}: {e}")
                continue
    else:
        # Process regular records
        for item in scrip_data:
            try:
                # Skip spot records
                if 'spot' in item['id'].lower():
                    continue
                    
                # Parse the id to get exchange and other details
                parts = item['id'].split('_')
                if len(parts) < 2:  # Need at least instrument type and symbol
                    continue
                    
                instr_type = parts[0]
                
                # Skip spot records early
                if item.get('asset') == 'spot' or 'spot' in item['id'].lower():
                    continue
                
                # Handle different groups
                if group_name == 'Securities':
                    # Format: instrument_symbol_series_exchange
                    if len(parts) >= 4:
                        exchange = parts[-1]
                        record = {
                            'symbol': item['dispName'],
                            'brsymbol': item['id'],
                            'name': item.get('desc', item['dispName']),
                            'exchange': exchange,
                            'brexchange': exchange,
                            'token': str(item['excToken']),
                            'expiry': '',
                            'strike': 0,
                            'lotsize': int(item.get('lot', 1)),
                            'instrumenttype': 'EQ',
                            'tick_size': float(item.get('tick', 0.05))
                        }
                        records.append(record)
                        
                elif group_name in ['FutureContracts', 'CurrencyFuture', 'CommodityFuture']:
                    # Format: instrument_symbol_exchange_expiry
                    if len(parts) >= 4:
                        base_symbol = parts[1]
                        exchange = parts[2]
                        expiry_date = parts[3]
                        
                        try:
                            expiry_dt = datetime.strptime(expiry_date, '%Y-%m-%d')
                            expiry_formatted = expiry_dt.strftime('%d%b%y').upper()
                            openalgo_symbol = f"{base_symbol}{expiry_formatted}FUT"
                            
                            record = {
                                'symbol': openalgo_symbol,
                                'brsymbol': item['id'],
                                'name': item.get('desc', item['dispName']),
                                'exchange': exchange,
                                'brexchange': exchange,
                                'token': str(item['excToken']),
                                'expiry': expiry_date,
                                'strike': 0,
                                'lotsize': int(item.get('lot', 1)),
                                'instrumenttype': 'FUT',
                                'tick_size': float(item.get('tick', 0.05))
                            }
                            records.append(record)
                        except Exception as e:
                            logger.info(f"Error processing future {item['id']}: {e}")
                            
                elif group_name in ['NSEOptions', 'BSEOptions', 'CurrencyOptions', 'CommodityOptions']:
                    # Format: instrument_symbol_exchange_expiry_strike_optType
                    if len(parts) >= 6:
                        base_symbol = parts[1]
                        exchange = parts[2]
                        expiry_date = parts[3]
                        strike_price = float(parts[4])
                        option_type = parts[5]
                        
                        try:
                            expiry_dt = datetime.strptime(expiry_date, '%Y-%m-%d')
                            expiry_formatted = expiry_dt.strftime('%d%b%y').upper()
                            strike_str = str(int(strike_price)) if strike_price.is_integer() else str(strike_price)
                            openalgo_symbol = f"{base_symbol}{expiry_formatted}{strike_str}{option_type}"
                            
                            record = {
                                'symbol': openalgo_symbol,
                                'brsymbol': item['id'],
                                'name': item.get('desc', item['dispName']),
                                'exchange': exchange,
                                'brexchange': exchange,
                                'token': str(item['excToken']),
                                'expiry': expiry_date,
                                'strike': strike_price,
                                'lotsize': int(item.get('lot', 1)),
                                'instrumenttype': option_type,
                                'tick_size': float(item.get('tick', 0.05))
                            }
                            records.append(record)
                        except Exception as e:
                            logger.info(f"Error processing option {item['id']}: {e}")
                            
                elif instr_type == 'IDX':
                    # Handle index symbols
                    raw_exchange = parts[-1]  # Last part is exchange (NSE/BSE)
                    
                    # Map exchange for OpenAlgo format
                    exchange_map = {
                        'NSE': 'NSE_INDEX',
                        'BSE': 'BSE_INDEX'
                    }
                    
                    # Get OpenAlgo exchange
                    openalgo_exchange = exchange_map.get(raw_exchange, raw_exchange)
                    
                    # Check if this is a common index symbol
                    if openalgo_exchange == 'BSE_INDEX':
                        # Handle BSE indices
                        if item['symbol'].upper() in COMMON_INDEX_MAP[openalgo_exchange]['common']:
                            # Use common symbol format for main indices
                            record = {
                                'symbol': item['symbol'].upper(),  # Use uppercase symbol
                                'brsymbol': item['id'],  # Use dispName as brsymbol
                                'name': item.get('symbol', item['dispName']),  # Use symbol field if available
                                'exchange': openalgo_exchange,
                                'brexchange': raw_exchange,
                                'token': str(item['excToken']),
                                'expiry': '',
                                'strike': 0,
                                'lotsize': 1,
                                'instrumenttype': 'INDEX',
                                'tick_size': 0.05
                            }
                        elif item['symbol'].upper() in COMMON_INDEX_MAP[openalgo_exchange]['sectoral']:
                            # Use sectoral index format
                            record = {
                                'symbol': item['symbol'].upper(),  # Use uppercase symbol
                                'brsymbol': COMMON_INDEX_MAP[openalgo_exchange]['sectoral'][item['symbol'].upper()],  # Use mapped brsymbol
                                'name': item.get('symbol', item['dispName']),  # Use symbol field if available
                                'exchange': openalgo_exchange,
                                'brexchange': raw_exchange,
                                'token': str(item['excToken']),
                                'expiry': '',
                                'strike': 0,
                                'lotsize': 1,
                                'instrumenttype': 'INDEX',
                                'tick_size': 0.05
                            }
                        else:
                            # Use regular symbol format
                            record = {
                                'symbol': item['dispName'],  # Use dispName for non-common symbols
                                'brsymbol': item['id'],
                                'name': item.get('symbol', item['dispName']),
                                'exchange': openalgo_exchange,
                                'brexchange': raw_exchange,
                                'token': str(item['excToken']),
                                'expiry': '',
                                'strike': 0,
                                'lotsize': 1,
                                'instrumenttype': 'INDEX',
                                'tick_size': 0.05
                            }
                    else:
                        # Handle NSE indices
                        if item['symbol'].upper() in COMMON_INDEX_MAP[openalgo_exchange]:
                            # Use common symbol format
                            record = {
                                'symbol': item['symbol'].upper(),  # Use uppercase symbol
                                'brsymbol': item['id'],  # Use dispName as brsymbol
                                'name': item.get('symbol', item['dispName']),  # Use symbol field if available
                                'exchange': openalgo_exchange,
                                'brexchange': raw_exchange,
                                'token': str(item['excToken']),
                                'expiry': '',
                                'strike': 0,
                                'lotsize': 1,
                                'instrumenttype': 'INDEX',
                                'tick_size': 0.05
                            }
                        else:
                            # Use regular symbol format
                            record = {
                                'symbol': item['dispName'],  # Use dispName for non-common symbols
                                'brsymbol': item['id'],
                                'name': item.get('symbol', item['dispName']),
                                'exchange': openalgo_exchange,
                                'brexchange': raw_exchange,
                                'token': str(item['excToken']),
                                'expiry': '',
                                'strike': 0,
                                'lotsize': 1,
                                'instrumenttype': 'INDEX',
                                'tick_size': 0.05
                            }
            except Exception as e:
                logger.error(f"Error processing item {item}: {e}")
                continue
    
    return pd.DataFrame(records)

def master_contract_download():
    """Download and process Tradejini scrip data"""
    logger.info("Starting Tradejini Master Contract Download")
    
    try:
        # Delete existing data
        delete_symtoken_table()
        
        # Get scrip groups
        scrip_groups = get_scrip_groups()
        if not scrip_groups:
            logger.info("No scrip groups found. Exiting.")
            return False
            
        logger.info(f"Found {len(scrip_groups)} scrip groups")
        
        # Process each scrip group
        for group in scrip_groups:
            try:
                group_name = group.get('name')
                if not group_name:
                    continue
                    
                logger.info(f"Processing group: {group_name} (format: {group.get('idFormat')})")
                scrip_data = get_scrip_data(group_name)
                
                if scrip_data:
                    # Check if response is successful
                    if isinstance(scrip_data, dict) and scrip_data.get('s') == 'ok':
                        scrip_data = scrip_data.get('d', [])
                    
                    # Process the data into DataFrame
                    df = process_scrip_data(scrip_data, group)
                    
                    # Insert into database
                    if not df.empty:
                        copy_from_dataframe(df)
                        logger.info(f"Processed {len(df)} symbols for {group_name}")
                    else:
                        logger.info(f"No valid records found for {group_name}")
                else:
                    logger.info(f"No data received for {group_name}")
                    
            except Exception as group_error:
                logger.error(f"Error processing group {group_name}: {group_error}")
                continue
        
        if socketio:
            socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully downloaded all contracts'})
        return True
    
    except Exception as e:
        error_msg = f"Error in master contract download: {e}"
        logger.error(f"{error_msg}")
        if socketio:
            socketio.emit('master_contract_download', {'status': 'error', 'message': error_msg})
        return False