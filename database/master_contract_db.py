# database/master_contract_db.py

import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from io import StringIO
import os
from dotenv import load_dotenv


def get_db_connection():
    try:
        conn = psycopg2.connect(database=os.getenv('POSTGRES_DATABASE'),
                                host=os.getenv('POSTGRES_HOST'),
                                user=os.getenv('POSTGRES_USER'),
                                password=os.getenv('POSTGRES_PASSWORD'),
                                port=os.getenv('POSTGRES_PORT'),
                                sslmode=os.getenv('POSTGRES_SSLMODE'))
        return conn
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error while connecting to PostgreSQL", error)
        return None
# Load environment variables from .env file
load_dotenv()

def check_and_create_table(conn):
    cursor = conn.cursor()
    # Check if the table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM pg_tables 
            WHERE schemaname = 'public' AND tablename  = 'symtoken'
        );
    """)
    exists = cursor.fetchone()[0]
    if not exists:
        # Create table if it does not exist
        cursor.execute("""
            CREATE TABLE symtoken (
                token INTEGER,
                symbol VARCHAR(255) UNIQUE,
                name VARCHAR(255),
                expiry VARCHAR(255),
                strike NUMERIC,
                lotsize INTEGER,
                instrumenttype VARCHAR(255),
                exch_seg VARCHAR(255),
                tick_size NUMERIC
            );
        """)
        conn.commit()
        print("Table 'symtoken' created.")
    cursor.close()

def copy_from_stringio(conn, df, table):
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    cursor = conn.cursor()
    try:
        cursor.copy_from(buffer, table, sep=",", null="")
        conn.commit()
        print("Master Contract Added to the DB successfully")
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error during copy from StringIO", error)
        conn.rollback()
    finally:
        cursor.close()

def delete_symtoken_table():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS symtoken;")
        conn.commit()
        print("Table 'symtoken' has been deleted.")
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error while deleting the 'symtoken' table:", error)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def db_indexing(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("CREATE INDEX idx_symbol ON symtoken(symbol);")
        cursor.execute("CREATE INDEX idx_symbol_exch_seg ON symtoken(symbol, exch_seg);")
        conn.commit()
        print("Indexing idx_symbol_exch_seg created successfully.")
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error creating indexing:", error)
    finally:
        cursor.close()

def search_symbols(symbol):
    conn = get_db_connection()  # Utilize the existing connection function
    if conn is None:
        print("Database connection error.")
        return []

    cursor = conn.cursor()
    query = """
    SELECT * FROM symtoken
    WHERE symbol ILIKE %s;  -- Use ILIKE for case-insensitive matching
    """
    try:
        cursor.execute(query, (f'%{symbol}%',))
        rows = cursor.fetchall()
        return rows  # Each row is a tuple of column values
    finally:
        cursor.close()
        conn.close()



def master_contract_download():
    try:
        print("Downloading Master Contract")
        url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        data = requests.get(url).json()
        token_df = pd.DataFrame.from_dict(data)
        token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)
        token_df = token_df.drop_duplicates(subset='symbol', keep='first')

        conn = get_db_connection()

        if conn is not None:
            delete_symtoken_table()
            check_and_create_table(conn)
            copy_from_stringio(conn, token_df, 'symtoken')
            db_indexing(conn)  # Call db_indexing right after copying data into the table
            conn.close()
        print("Master Contract Download Completed")

        return {'status': 'success', 'message': 'Master contract downloaded successfully'}
    except Exception as e:
            print(str(e))
            return {'status': 'error', 'message': 'Failed to download master contract'}
    

