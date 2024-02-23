# database/auth_db.py

import os
import psycopg2


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

def upsert_auth(name, auth_token):
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        upsert_sql = """
        INSERT INTO auth (name, auth) VALUES (%s, %s)
        ON CONFLICT (name) DO UPDATE
        SET auth = EXCLUDED.auth
        RETURNING id;
        """
        values = (name, auth_token)
        cursor.execute(upsert_sql, values)
        inserted_id = cursor.fetchone()[0]
        conn.commit()
        return inserted_id
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error while working with PostgreSQL", error)
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()

def get_auth_token(name):
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cursor = conn.cursor()
        select_sql = "SELECT auth FROM auth WHERE name = %s;"
        cursor.execute(select_sql, (name,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            return None
    finally:
        cursor.close()
        conn.close()


def ensure_auth_table_exists():
    conn = get_db_connection()
    if conn is None:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM 
                    information_schema.tables 
                WHERE 
                    table_schema = 'public' AND 
                    table_name = 'auth'
            );
        """)
        exists = cursor.fetchone()[0]
        if not exists:
            cursor.execute("""
                CREATE TABLE auth (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE,
                    auth VARCHAR(1000)
                );
            """)
            conn.commit()
            print("Auth table created successfully.")
        return True
    except (Exception, psycopg2.DatabaseError) as error:
        print("Error ensuring auth table exists:", error)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

