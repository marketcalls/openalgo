# database/master_contract_db.py

import gzip
import os
import shutil

import pandas as pd
import requests
from sqlalchemy import Column, Float, Index, Integer, Sequence, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from extensions import socketio  # Import SocketIO
from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your database path

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
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
    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Symtoken Table")
    SymToken.query.delete()
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Bulk Insert")
    # Convert DataFrame to a list of dictionaries
    data_dict = df.to_dict(orient="records")

    # Retrieve existing tokens to filter them out from the insert
    existing_tokens = {result.token for result in db_session.query(SymToken.token).all()}

    # Filter out data_dict entries with tokens that already exist
    filtered_data_dict = [row for row in data_dict if row["token"] not in existing_tokens]

    # Insert in bulk the filtered records
    try:
        if filtered_data_dict:  # Proceed only if there's anything to insert
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(
                f"Bulk insert completed successfully with {len(filtered_data_dict)} new records."
            )
        else:
            logger.info("No new records to insert.")
    except Exception as e:
        logger.error(f"Error during bulk insert: {e}")
        db_session.rollback()


def download_and_unzip_upstox_data(url, input_path, output_path):
    """
    Downloads the compressed JSON from Upstox, unzips it, and saves it to the specified path.
    """
    logger.info("Downloading Upstox Master Contract")
    response = requests.get(url, timeout=10)  # timeout after 10 seconds
    with open(input_path, "wb") as f:
        f.write(response.content)
    logger.info("Decompressing the JSON file")
    with gzip.open(input_path, "rb") as f_in:
        with open(output_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def reformat_symbol(row):
    symbol = row["symbol"]
    instrument_type = row["instrumenttype"]

    if instrument_type == "FUT":
        # For FUT, remove the spaces and append 'FUT' at the end
        parts = symbol.split(" ")
        if len(parts) == 5:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[2] + parts[3] + parts[4] + parts[1]
    elif instrument_type in ["CE", "PE"]:
        # For CE/PE, rearrange the parts and remove spaces
        parts = symbol.split(" ")
        if len(parts) == 6:  # Make sure the symbol has the correct format
            symbol = parts[0] + parts[3] + parts[4] + parts[5] + parts[1] + parts[2]
    else:
        symbol = symbol  # No change for other instrument types

    return symbol


def process_upstox_json(path):
    """
    Processes the Upstox JSON file to fit the existing database schema and performs exchange name mapping.
    """
    logger.info("Processing Upstox Data")
    df = pd.read_json(path)

    # Filter out NSE_COM instruments
    df = df[df["segment"] != "NSE_COM"]

    # return df

    # Assume your JSON structure requires some transformations to match your schema
    # For the sake of this example, let's assume 'df' now represents your transformed DataFrame
    # Map exchange names
    exchange_map = {
        "NSE_EQ": "NSE",
        "NSE_FO": "NFO",
        "NCD_FO": "CDS",
        "NSE_INDEX": "NSE_INDEX",
        "BSE_INDEX": "BSE_INDEX",
        "BSE_EQ": "BSE",
        "BSE_FO": "BFO",
        "BCD_FO": "BCD",
        "MCX_FO": "MCX",
    }
    segment_copy = df["segment"].copy()
    df["segment"] = df["segment"].map(exchange_map)
    df["expiry"] = pd.to_datetime(df["expiry"], unit="ms").dt.strftime("%d-%b-%y").str.upper()

    df = df[
        [
            "instrument_key",
            "trading_symbol",
            "name",
            "expiry",
            "strike_price",
            "lot_size",
            "instrument_type",
            "segment",
            "tick_size",
        ]
    ].rename(
        columns={
            "instrument_key": "token",
            "trading_symbol": "symbol",
            "name": "name",
            "expiry": "expiry",
            "strike_price": "strike",
            "lot_size": "lotsize",
            "instrument_type": "instrumenttype",
            "segment": "exchange",
            "tick_size": "tick_size",
        }
    )

    df["brsymbol"] = df["symbol"]
    df["symbol"] = df.apply(reformat_symbol, axis=1)
    df["brexchange"] = segment_copy

    # NSE Index Symbol Mapping (Upstox trading_symbol → OpenAlgo format)
    df["symbol"] = df["symbol"].replace({
        # Major NSE Indices
        "NIFTY 50": "NIFTY",
        "NIFTY NEXT 50": "NIFTYNXT50",
        "NIFTY FIN SERVICE": "FINNIFTY",
        "NIFTY BANK": "BANKNIFTY",
        "NIFTY MID SELECT": "MIDCPNIFTY",
        "INDIA VIX": "INDIAVIX",
        "HANGSENG BEES NAV": "HANGSENGBEESNAV",
        # Broad Market Indices
        "NIFTY 100": "NIFTY100",
        "NIFTY 200": "NIFTY200",
        "NIFTY 500": "NIFTY500",
        # Sectoral Indices
        "NIFTY ALPHA 50": "NIFTYALPHA50",
        "NIFTY AUTO": "NIFTYAUTO",
        "NIFTY COMMODITIES": "NIFTYCOMMODITIES",
        "NIFTY CONSUMPTION": "NIFTYCONSUMPTION",
        "NIFTY CPSE": "NIFTYCPSE",
        "NIFTY DIV OPPS 50": "NIFTYDIVOPPS50",
        "NIFTY ENERGY": "NIFTYENERGY",
        "NIFTY FMCG": "NIFTYFMCG",
        "NIFTY GROWSECT 15": "NIFTYGROWSECT15",
        "NIFTY INFRA": "NIFTYINFRA",
        "NIFTY IT": "NIFTYIT",
        "NIFTY MEDIA": "NIFTYMEDIA",
        "NIFTY METAL": "NIFTYMETAL",
        "NIFTY MNC": "NIFTYMNC",
        "NIFTY PHARMA": "NIFTYPHARMA",
        "NIFTY PSE": "NIFTYPSE",
        "NIFTY PSU BANK": "NIFTYPSUBANK",
        "NIFTY PVT BANK": "NIFTYPVTBANK",
        "NIFTY REALTY": "NIFTYREALTY",
        "NIFTY SERV SECTOR": "NIFTYSERVSECTOR",
        # Market Cap Indices
        "NIFTY MID LIQ 15": "NIFTYMIDLIQ15",
        "NIFTY MIDCAP 50": "NIFTYMIDCAP50",
        "NIFTY MIDCAP 100": "NIFTYMIDCAP100",
        "NIFTY MIDCAP 150": "NIFTYMIDCAP150",
        "NIFTY MIDSML 400": "NIFTYMIDSML400",
        "NIFTY SMLCAP 50": "NIFTYSMLCAP50",
        "NIFTY SMLCAP 100": "NIFTYSMLCAP100",
        "NIFTY SMLCAP 250": "NIFTYSMLCAP250",
        # Strategy Indices
        "NIFTY100 EQL WGT": "NIFTY100EQLWGT",
        "NIFTY100 LIQ 15": "NIFTY100LIQ15",
        "NIFTY100 LOWVOL30": "NIFTY100LOWVOL30",
        "NIFTY100 QUALTY30": "NIFTY100QUALTY30",
        "NIFTY200 QUALTY30": "NIFTY200QUALTY30",
        "NIFTY50 DIV POINT": "NIFTY50DIVPOINT",
        "NIFTY50 EQL WGT": "NIFTY50EQLWGT",
        "NIFTY50 PR 1X INV": "NIFTY50PR1XINV",
        "NIFTY50 PR 2X LEV": "NIFTY50PR2XLEV",
        "NIFTY50 TR 1X INV": "NIFTY50TR1XINV",
        "NIFTY50 TR 2X LEV": "NIFTY50TR2XLEV",
        "NIFTY50 VALUE 20": "NIFTY50VALUE20",
        # Government Securities Indices
        "NIFTY GS 10YR": "NIFTYGS10YR",
        "NIFTY GS 10YR CLN": "NIFTYGS10YRCLN",
        "NIFTY GS 11 15YR": "NIFTYGS1115YR",
        "NIFTY GS 15YRPLUS": "NIFTYGS15YRPLUS",
        "NIFTY GS 4 8YR": "NIFTYGS48YR",
        "NIFTY GS 8 13YR": "NIFTYGS813YR",
        "NIFTY GS COMPSITE": "NIFTYGSCOMPSITE",
    })

    # BSE Index Symbol Mapping (applied only to BSE_INDEX rows to avoid
    # conflicts with equity symbols that may share short names like AUTO, METAL)
    bse_idx_mask = df["exchange"] == "BSE_INDEX"
    df.loc[bse_idx_mask, "symbol"] = df.loc[bse_idx_mask, "symbol"].replace({
        "SNSX50": "SENSEX50",
        "SNXT50": "BSESENSEXNEXT50",
        "MID150": "BSE150MIDCAPINDEX",
        "LMI250": "BSE250LARGEMIDCAPINDEX",
        "MSL400": "BSE400MIDSMALLCAPINDEX",
        "AUTO": "BSEAUTO",
        "BSE CG": "BSECAPITALGOODS",
        "CARBON": "BSECARBONEX",
        "BSE CD": "BSECONSUMERDURABLES",
        "CPSE": "BSECPSE",
        "DOL100": "BSEDOLLEX100",
        "DOL200": "BSEDOLLEX200",
        "DOL30": "BSEDOLLEX30",
        "ENERGY": "BSEENERGY",
        "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
        "FINSER": "BSEFINANCIALSERVICES",
        "GREENX": "BSEGREENEX",
        "BSE HC": "BSEHEALTHCARE",
        "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
        "INDSTR": "BSEINDUSTRIALS",
        "BSE IT": "BSEINFORMATIONTECHNOLOGY",
        "BSEIPO": "BSEIPO",
        "LRGCAP": "BSELARGECAP",
        "METAL": "BSEMETAL",
        "MIDCAP": "BSEMIDCAP",
        "MIDSEL": "BSEMIDCAPSELECTINDEX",
        "OILGAS": "BSEOIL&GAS",
        "POWER": "BSEPOWER",
        "BSEPSU": "BSEPSU",
        "REALTY": "BSEREALTY",
        "SMLCAP": "BSESMALLCAP",
        "SMLSEL": "BSESMALLCAPSELECTINDEX",
        "SMEIPO": "BSESMEIPO",
        "TECK": "BSETECK",
        "TELCOM": "BSETELECOM",
    })

    return df


def delete_upstox_temp_data(input_path, output_path):
    try:
        # Check if the file exists
        if os.path.exists(input_path) and os.path.exists(output_path):
            # Delete the file
            os.remove(input_path)
            os.remove(output_path)
            logger.info(f"The temporary file {input_path} and {output_path} has been deleted.")
        else:
            logger.info(f"The temporary file {input_path} and {output_path} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while deleting the file: {e}")


def master_contract_download():
    logger.info("Downloading Master Contract")
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    input_path = "tmp/temp_upstox.json.gz"
    output_path = "tmp/upstox.json"
    try:
        download_and_unzip_upstox_data(url, input_path, output_path)
        token_df = process_upstox_json(output_path)
        delete_upstox_temp_data(input_path, output_path)
        # token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)

        # token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        delete_symtoken_table()  # Consider the implications of this action
        copy_from_dataframe(token_df)

        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )

    except Exception as e:
        logger.info(f"{str(e)}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})


def search_symbols(symbol, exchange):
    return SymToken.query.filter(
        SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange
    ).all()
