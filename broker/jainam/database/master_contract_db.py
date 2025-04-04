# database/master_contract_db.py

import os
import pandas as pd
import numpy as np
import gzip
import shutil
import json
import gzip
import io
import csv
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio  # Import SocketIO
from utils.httpx_client import get_httpx_client
from broker.jainam.baseurl import MARKET_DATA_URL

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database path

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

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
    print("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    print("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    print("Performing Bulk Insert")
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
            print(f"Bulk insert completed successfully with {len(filtered_data_dict)} new records.")
        else:
            print("No new records to insert.")
    except Exception as e:
        print(f"Error during bulk insert: {e}")
        db_session.rollback()

def download_csv_compositedge_data(output_path):
    print("Downloading Master Contract CSV Files")
    exchange_segments = ["NSECM", "NSECD", "NSEFO", "BSECM", "BSEFO", "MCXFO"]
    headers_equity = "ExchangeSegment,ExchangeInstrumentID,InstrumentType,Name,Description,Series,NameWithSeries,InstrumentID,PriceBand.High,PriceBand.Low, FreezeQty,TickSize,LotSize,Multiplier,DisplayName,ISIN,PriceNumerator,PriceDenominator,DetailedDescription,ExtendedSurvIndicator,CautionIndicator,GSMIndicator\n"
    headers_fo = "ExchangeSegment,ExchangeInstrumentID,InstrumentType,Name,Description,Series,NameWithSeries,InstrumentID,PriceBand.High,PriceBand.Low,FreezeQty,TickSize,LotSize,Multiplier,UnderlyingInstrumentId,UnderlyingIndexName,ContractExpiration,StrikePrice,OptionType,DisplayName, PriceNumerator,PriceDenominator,DetailedDescription\n"

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    headers = {'Content-Type': 'application/json'}

    downloaded_files = []
    for segment in exchange_segments:
        payload = json.dumps({"exchangeSegmentList": [segment]})
        response = client.post(
            f"{MARKET_DATA_URL}/instruments/master",
            headers=headers,
            content=payload
        )
        if response.status_code != 200:
            raise Exception(f"Failed to download {segment}. Status: {response.status_code}")

        data = response.json()
        if "result" not in data:
            raise Exception(f"Invalid response format for {segment}: Missing 'result' field")

        if segment in ["NSECM", "BSECM"]:
            header = headers_equity
        else:
            header = headers_fo

        segment_output_path = f"{output_path}/{segment}.csv"
        os.makedirs(output_path, exist_ok=True)

        csv_data = data["result"].split("\n")  # Convert result string to list of rows
        csv_data = [row.split("|") for row in csv_data if row.strip()]  # Convert each row into a list

        with open(segment_output_path, 'w', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header.strip().split(","))  # Write headers
            writer.writerows(csv_data)
        downloaded_files.append(segment_output_path)

def fetch_index_list():
    print("Fetching Index List")
    exchange_segments = [1, 11]  # NSE and BSE indexes
    headers = {'Content-Type': 'application/json'}

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    index_data = []

    for segment in exchange_segments:
        url = f"{MARKET_DATA_URL}/instruments/indexlist?exchangeSegment={segment}"
        response = client.get(url, headers=headers)

        if response.status_code != 200:
            print(f"Failed to fetch index list for segment {segment}. Status: {response.status_code}")
            continue

        data = response.json()

        if "result" not in data or "indexList" not in data["result"]:
            print(f"Invalid response format for segment {segment}")
            continue

        for index_entry in data["result"]["indexList"]:
            # Extract symbol name and token
            symbol_name, token = index_entry.rsplit("_", 1)

            index_data.append({
                "brsymbol": index_entry,  # Full format (e.g., "NIFTY 100_26004")
                "symbol": symbol_name,    # Raw symbol before mapping
                "exchange": "NSE_INDEX" if segment == 1 else "BSE_INDEX",
                "token": token
            })

    return index_data

def reformat_symbol_detail(s):
    parts = s.split()  # Split the string into parts
    # Reorder and format the parts to match the desired output
    # Assuming the format is consistent and always "Name DD Mon YY FUT"
    return f"{parts[0]}{parts[3]}{parts[2].upper()}{parts[1]}{parts[4]}"

def process_compositedge_nse_csv(path):
    """
    Processes the compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing compositedge NSE CSV Data")
    file_path = f'{path}/NSECM.csv'

    df = pd.read_csv(file_path)

    df = df[df['Series'].isin(['EQ'])]

    token_df = pd.DataFrame()
    token_df['symbol'] = df['Name']
    token_df['brsymbol'] = df['DisplayName']
    token_df['name'] = df['Name']
    token_df['exchange'] = df['ExchangeSegment'].map({
            "NSECM": "NSE"})
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID']
    token_df['expiry'] = ''
    token_df['strike'] = 1.0
    token_df['lotsize'] = df['LotSize']
    token_df['instrumenttype'] = df['Series']
    token_df['tick_size'] = df['TickSize']

    return token_df


def process_compositedge_bse_csv(path):
    """
    Processes the compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing compositedge BSE CSV Data")
    file_path = f'{path}/BSECM.csv'

    df = pd.read_csv(file_path)

    # df = df[df['Series'].isin(['EQ'])]

    token_df = pd.DataFrame()
    token_df['symbol'] = df['Name']
    token_df['brsymbol'] = df['DisplayName']
    token_df['name'] = df['Name']
    token_df['exchange'] = df['ExchangeSegment'].map({
            "BSECM": "BSE"})
    token_df['exchange'] = df.apply(
    lambda row: "BSE_INDEX" if row['Series'] == "SPOT" else "BSE", axis=1
    )
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID']
    token_df['expiry'] = ''
    token_df['strike'] = 1.0
    token_df['lotsize'] = df['LotSize']
    token_df['instrumenttype'] = df['Series']
    token_df['tick_size'] = df['TickSize']

    return token_df


def process_compositedge_nfo_csv(path):
    """
    Processes the Compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing Compositedge NFO CSV Data")
    file_path = f'{path}/NSEFO.csv'

    df = pd.read_csv(file_path, dtype={"StrikePrice": str, " PriceNumerator": str}, low_memory=False)


    # Convert 'Expiry Date' column to datetime format
    df['ContractExpiration'] = pd.to_datetime(df['ContractExpiration'])

    df["StrikePrice"] = pd.to_numeric(df["StrikePrice"], errors='coerce').fillna(1.0)

    df["symbol"] = df.apply(
        lambda row: f"{row['Name']}"
                f"{row['ContractExpiration'].strftime('%d%b%y').upper()}"
                f"{'' if row['OptionType'] == 1 else (str(int(float(row['StrikePrice']))) if float(row['StrikePrice']) == int(float(row['StrikePrice'])) else str(row['StrikePrice'])) if pd.notna(row['StrikePrice']) else ''}"
                f"{'FUT' if row['OptionType'] == 1 else 'CE' if row['OptionType'] == 3 else 'PE'}",
        axis=1
        )

    # Create token_df with the relevant columns
    token_df = df[['symbol']].copy()
    token_df['symbol'] = df['symbol'].values
    token_df['brsymbol'] = df['Description'].values
    token_df['name'] = df['Name'].values
    token_df['exchange'] = df['ExchangeSegment'].map({
            "NSEFO": "NFO"})
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID'].values

        # Convert 'Expiry Date' to desired format
    token_df['expiry'] = df['ContractExpiration'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['StrikePrice'].values
    token_df['lotsize'] = df['LotSize'].values
    token_df['instrumenttype'] = df['OptionType'].map({
            1: 'FUT',
            3: 'CE',
            4: 'PE'
        })
    token_df['tick_size'] = df['TickSize'].values

    return token_df


def process_compositedge_cds_csv(path):
    """
    Processes the compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing compositedge CDS CSV Data")
    file_path = f'{path}/NSECD.csv'

    df = pd.read_csv(file_path)

    df = df.dropna(subset=['OptionType'])

        # Convert 'Expiry Date' column to datetime format
    df['ContractExpiration'] = pd.to_datetime(df['ContractExpiration'])

    df["StrikePrice"] = pd.to_numeric(df["StrikePrice"], errors='coerce').fillna(1.0)

    
    df["symbol"] = df.apply(
        lambda row: f"{row['Name']}"
                f"{row['ContractExpiration'].strftime('%d%b%y').upper()}"
                f"{'' if row['OptionType'] == 1 else (str(int(float(row['StrikePrice']))) if float(row['StrikePrice']) == int(float(row['StrikePrice'])) else str(row['StrikePrice'])) if pd.notna(row['StrikePrice']) else ''}"
                f"{'FUT' if row['OptionType'] == 1 else 'CE' if row['OptionType'] == 3 else 'PE'}",
        axis=1
        )

    # Generate symbols based on instrument type
    # df['symbol'] = df.apply(lambda x: 
    #    f"{x['Name']}{x['ContractExpiration'].strftime('%d%b%y').upper()}{'FUT' if x['OptionType']=='1' else str(int(float(x['StrikePrice'])))+('CE' if x['OptionType']=='3' else 'PE')}", 
    #    axis=1
    # )
    # Remove any rows where symbol generation failed
    # df = df[df['symbol'].notna()]

    
    # Create token_df with the relevant columns
    token_df = df[['symbol']].copy()
    token_df['symbol'] = df['symbol'].values
    token_df['brsymbol'] = df['Description'].values
    token_df['name'] = df['Name'].values
    token_df['exchange'] = df['ExchangeSegment'].map({
            "NSECD": "CDS"})
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID'].values

    # Convert 'Expiry Date' to desired format
    token_df['expiry'] = df['ContractExpiration'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['StrikePrice'].values
    token_df['lotsize'] = df['LotSize'].values
    token_df['instrumenttype'] = token_df['symbol'].apply(
       lambda x: 'FUT' if 'FUT' in x else ('PE' if 'PE' in x else 'CE'))
    # token_df['instrumenttype'] = df['OptionType'].map({
    #        1: 'FUT',
    #        872604 : 'FUT',
    #        5892 : 'FUT',
    #        3: 'CE',
    #        4: 'PE'
    #    })
    token_df['tick_size'] = df['TickSize'].values

    return token_df


def process_compositedge_bfo_csv(path):
    """
    Processes the Compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing Compositedge BFO CSV Data")
    file_path = f'{path}/BSEFO.csv'

    df = pd.read_csv(file_path, dtype={"StrikePrice": str, " PriceNumerator": str}, low_memory=False)

        # Convert 'Expiry Date' column to datetime format
    df['ContractExpiration'] = pd.to_datetime(df['ContractExpiration'])

    df["StrikePrice"] = pd.to_numeric(df["StrikePrice"], errors='coerce').fillna(1.0)

    df["symbol"] = df.apply(
        lambda row: f"{row['Name']}"
                f"{row['ContractExpiration'].strftime('%d%b%y').upper()}"
                f"{'' if row['OptionType'] == 1 else (str(int(float(row['StrikePrice']))) if float(row['StrikePrice']) == int(float(row['StrikePrice'])) else str(row['StrikePrice'])) if pd.notna(row['StrikePrice']) else ''}"
                f"{'FUT' if row['OptionType'] == 1 else 'CE' if row['OptionType'] == 3 else 'PE'}",
        axis=1
        )

        
    token_df = df[['symbol']].copy()
    token_df['symbol'] = df['symbol'].values
    token_df['brsymbol'] = df['Description'].values
    token_df['name'] = df['Name'].values
    token_df['exchange'] = df['ExchangeSegment'].map({
            "BSEFO": "BFO"})
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID'].values

        # Convert 'Expiry Date' to desired format
    token_df['expiry'] = df['ContractExpiration'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['StrikePrice'].values
    token_df['lotsize'] = df['LotSize'].values
    token_df['instrumenttype'] = df['OptionType'].map({
            1: 'FUT',
            3: 'CE',
            4: 'PE'
        })
    token_df['tick_size'] = df['TickSize'].values

    return token_df


def process_compositedge_mcx_csv(path):
    """
    Processes the Compositedge CSV file to fit the existing database schema and performs exchange name mapping.
    """
    print("Processing Compositedge MCX CSV Data")
    file_path = f'{path}/MCXFO.csv'

    df = pd.read_csv(file_path)

    # Drop rows where the 'Exch Seg' column has the value 'COMTDY'
    df = df[df['ContractExpiration'] != '1']

    df['ContractExpiration'] = pd.to_datetime(df['ContractExpiration'])
    df["StrikePrice"] = pd.to_numeric(df["StrikePrice"], errors='coerce').fillna(1.0)
    
    df["symbol"] = df.apply(
        lambda row: f"{row['Name']}"
                f"{row['ContractExpiration'].strftime('%d%b%y').upper()}"
                f"{'' if row['OptionType'] == 1 else (str(int(float(row['StrikePrice']))) if float(row['StrikePrice']) == int(float(row['StrikePrice'])) else str(row['StrikePrice'])) if pd.notna(row['StrikePrice']) else ''}"
                f"{'FUT' if row['OptionType'] == 1 else 'CE' if row['OptionType'] == 3 else 'PE'}",
        axis=1
        )

    
    # Create token_df with the relevant columns
    token_df = df[['symbol']].copy()
    token_df['symbol'] = df['symbol'].values
    token_df['brsymbol'] = df['Description'].values
    token_df['name'] = df['Name'].values
    token_df['exchange'] = df['ExchangeSegment'].map({
            "MCXFO": "MCX"})
    token_df['brexchange'] = df['ExchangeSegment']
    token_df['token'] = df['ExchangeInstrumentID'].values

    # Convert 'Expiry Date' to desired format
    token_df['expiry'] = df['ContractExpiration'].dt.strftime('%d-%b-%y').str.upper()
    token_df['strike'] = df['StrikePrice'].values
    token_df['lotsize'] = df['LotSize'].values
    token_df['instrumenttype'] = df['OptionType'].map({
            1: 'FUT',
            3: 'CE',
            4: 'PE'
        })
    token_df['tick_size'] = df['TickSize'].values

    return token_df

def process_index_data(index_data):
    print("Processing Index Data")
    df = pd.DataFrame(index_data)

    # Map Symbols to Standard Format
    df['symbol'] = df['symbol'].replace({
        'NIFTY 50': 'NIFTY',
        'NIFTY BANK': 'BANKNIFTY',
        'INDIA VIX': 'INDIAVIX',
        'NIFTY FIN SERVICE': 'FINNIFTY',
        'NIFTY MID SELECT': 'MIDCPNIFTY',
        'NIFTY NEXT 50': 'NIFTYNXT50',
        'SENSEX': 'SENSEX',
        'BANKEX': 'BANKEX',
        'SNSX50': 'SENSEX50'
    })

    df['name'] = df['symbol']
    df['brexchange'] = df['exchange']
    df['expiry'] = ''
    df['strike'] = 1.0
    df['lotsize'] = 1  # Default index lot size
    df['instrumenttype'] = 'INDEX'
    df['tick_size'] = 0.05 
    # print(df)

    return df

def delete_compositedge_temp_data(output_path):
    # Check each file in the directory
    for filename in os.listdir(output_path):
        # Construct the full file path
        file_path = os.path.join(output_path, filename)
        # If the file is a CSV, delete it
        if filename.endswith(".csv") and os.path.isfile(file_path):
            os.remove(file_path)
            print(f"Deleted {file_path}")
    

def master_contract_download():
    print("Downloading Master Contract")
    

    output_path = 'tmp'
    try:
        download_csv_compositedge_data(output_path)
        delete_symtoken_table()
        token_df = process_compositedge_nse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_compositedge_bse_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_compositedge_nfo_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_compositedge_cds_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_compositedge_mcx_csv(output_path)
        copy_from_dataframe(token_df)
        token_df = process_compositedge_bfo_csv(output_path)
        copy_from_dataframe(token_df)

        # Fetch and Process Index Data
        index_data = fetch_index_list()
        if index_data:
            index_df = process_index_data(index_data)
            copy_from_dataframe(index_df)
        
        delete_compositedge_temp_data(output_path)
        
        return socketio.emit('master_contract_download', {'status': 'success', 'message': 'Successfully Downloaded'})

    
    except Exception as e:
        print(str(e))
        return socketio.emit('master_contract_download', {'status': 'error', 'message': str(e)})



def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f'%{symbol}%'), SymToken.exchange == exchange).all()
