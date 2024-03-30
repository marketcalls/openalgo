# database/auth_db.py


import os


from sqlalchemy import create_engine, UniqueConstraint
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean  
from sqlalchemy.sql import func
from dotenv import load_dotenv
from cachetools import TTLCache

# Define a cache for the auth tokens and api_key with a max size and a 30-second TTL
auth_cache = TTLCache(maxsize=1024, ttl=1000)
api_key_cache = TTLCache(maxsize=1024, ttl=30)

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your SQLite path

engine = create_engine(
    DATABASE_URL,
    pool_size=50,  # Increase pool size
    max_overflow=100,  # Increase overflow
    pool_timeout=10  # Increase timeout to 10 seconds
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Auth(Base):
    __tablename__ = 'auth'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    auth = Column(String(1000), nullable=False)
    is_revoked = Column(Boolean, default=False)  


class ApiKeys(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    api_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

def init_db():
    print("Initializing Auth DB")
    Base.metadata.create_all(bind=engine)

def upsert_auth(name, auth_token, revoke=False):
    auth_obj = Auth.query.filter_by(name=name).first()
    if auth_obj:
        auth_obj.auth = auth_token
        auth_obj.is_revoked = revoke  # Update revoke status
    else:
        auth_obj = Auth(name=name, auth=auth_token, is_revoked=revoke)
        db_session.add(auth_obj)
    db_session.commit()
    return auth_obj.id

def get_auth_token(name):
    cache_key = f"auth-{name}"
    if cache_key in auth_cache:
        auth_obj = auth_cache[cache_key]
        # Ensure that auth_obj is an instance of Auth, not a string
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            return auth_obj.auth
        else:
            del auth_cache[cache_key]  # Remove invalid cache entry
            return None
    else:
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            auth_cache[cache_key] = auth_obj  # Store the Auth object, not the string
            return auth_obj.auth
        return None


def get_auth_token_dbquery(name):
    try:
        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            #print(f"The auth token for name '{name}' is fetched from the Database")
            return auth_obj  # Return the Auth object
        else:
            print(f"No valid auth token found for name '{name}'.")
            return None
    except Exception as e:
        print("Error while querying the database for auth token:", e)
        return None



def upsert_api_key(user_id, api_key):
    api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
    if api_key_obj:
        api_key_obj.api_key = api_key
    else:
        api_key_obj = ApiKeys(user_id=user_id, api_key=api_key)
        db_session.add(api_key_obj)
    db_session.commit()
    return api_key_obj.id

def get_api_key(user_id):
    cache_key = f"api-key-{user_id}"
    if cache_key in api_key_cache:
        #print(f"Cache hit for {cache_key}.")
        return api_key_cache[cache_key]
    else:
        api_key_obj = get_api_key_dbquery(user_id)
        if api_key_obj is not None:
            api_key_cache[cache_key] = api_key_obj
        return api_key_obj

def get_api_key_dbquery(user_id):
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj:
            #print(f"The API key for user_id '{user_id}' is fetched from the Database")
            return api_key_obj.api_key
        else:
            print(f"No API key found for user_id '{user_id}'.")
            return None
    except Exception as e:
        print("Error while querying the database for API key:", e)
        return None
    

def validate_api_key(provided_api_key):
    # First, attempt to find the API key in the cache
    for cache_key, api_key in api_key_cache.items():
        if api_key == provided_api_key:
            #print(f"API Key validated from cache: {provided_api_key}")
            return True

    # If not found in cache, query the database
    try:
        api_key_obj = db_session.query(ApiKeys).filter_by(api_key=provided_api_key).first()
        if api_key_obj:
            # If found, cache the result for future requests and return True
            user_id_cache_key = f"api-key-{api_key_obj.user_id}"
            api_key_cache[user_id_cache_key] = provided_api_key
            #print(f"API Key validated from database: {provided_api_key}")
            return True
    except Exception as e:
        print(f"Error while validating API key: {e}")

    # If the API key is not found in either the cache or the database, return False
    return False


