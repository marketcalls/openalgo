# database/token_db.py

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


def get_token(symbol, exch_seg):
    conn = get_db_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            select_query = """
                SELECT token FROM symtoken
                WHERE symbol = %s AND exch_seg = %s;
            """
            cursor.execute(select_query, (symbol, exch_seg))
            result = cursor.fetchone()
            if result:
                print(f"The token for symbol '{symbol}' and exch_seg '{exch_seg}' is: {result[0]}")
                return result[0]
            else:
                print(f"No match found for symbol '{symbol}' and exch_seg '{exch_seg}'.")
                return None
        except (Exception, psycopg2.DatabaseError) as error:
            print("Error while querying PostgreSQL", error)
            return None
        finally:
            cursor.close()
            conn.close()
    else:
        return None