from flask import Flask
import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from io import StringIO
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

def get_db_connection():
    try:
        conn = psycopg2.connect(database=os.getenv('POSTGRES_DATABASE'),
                                host=os.getenv('POSTGRES_HOST'),
                                user=os.getenv('POSTGRES_USER'),
                                password=os.getenv('POSTGRES_PASSWORD'),
                                port="5432",
                                sslmode='require')
        return conn
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error while connecting to PostgreSQL", error)
        return None

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
        # Create table if it does not exist, with 'symbol' as a unique column
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
    # Save the dataframe to an in-memory buffer
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    cursor = conn.cursor()
    try:
        cursor.copy_from(buffer, table, sep=",", null="")  # Adjust the separator and null handling as needed
        conn.commit()
        print("Data copied successfully")
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error during copy from StringIO", error)
        conn.rollback()
    finally:
        cursor.close()

@app.route('backup_cron', methods=['GET'])
def cron_job():
    print("Cron Job Starting")
    # Fetch and prepare your data
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    data = requests.get(url).json()
    token_df = pd.DataFrame.from_dict(data)

    # Ensure 'token' column is numeric, handling non-convertible values
    token_df['token'] = pd.to_numeric(token_df['token'], errors='coerce').fillna(-1).astype(int)

    # Remove duplicate symbols
    token_df = token_df.drop_duplicates(subset='symbol', keep='first')

    conn = get_db_connection()

    # Copy data to the database
    if conn is not None:
        check_and_create_table(conn)
        copy_from_stringio(conn, token_df, 'symtoken')
        conn.close()
    print("Cron Job Ended Successfully")

    return "Cron job ran successfully", 200

# The Flask application's entry point
if __name__ == '__main__':
    app.run(debug=True)
