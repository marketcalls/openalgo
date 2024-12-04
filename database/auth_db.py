# database/auth_db.py

import os
import base64
from sqlalchemy import create_engine, UniqueConstraint
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean  
from sqlalchemy.sql import func
from dotenv import load_dotenv
from cachetools import TTLCache
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Initialize Argon2 hasher
ph = PasswordHasher()

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
PEPPER = os.getenv('API_KEY_PEPPER', 'default-pepper-change-in-production')

# Setup Fernet encryption for auth tokens
def get_encryption_key():
    """Generate a Fernet key from the pepper"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'openalgo_static_salt',  # Static salt is fine here as we have the pepper
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)

# Initialize Fernet cipher
fernet = get_encryption_key()

# Define a cache for the auth tokens with a 30-second TTL
auth_cache = TTLCache(maxsize=1024, ttl=30)

engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Auth(Base):
    __tablename__ = 'auth'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    auth = Column(Text, nullable=False)  # Will store encrypted auth token
    broker = Column(String(20), nullable=False)
    is_revoked = Column(Boolean, default=False)

class ApiKeys(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    api_key_hash = Column(Text, nullable=False)  # Store hashed API key
    created_at = Column(DateTime(timezone=True), default=func.now())

def init_db():
    print("Initializing Auth DB")
    Base.metadata.create_all(bind=engine)

def encrypt_token(token):
    """Encrypt auth token"""
    if not token:  # Handle empty token case
        return ''
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token):
    """Decrypt auth token"""
    if not encrypted_token:  # Handle empty token case
        return ''
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        print(f"Error decrypting token: {e}")
        return None

def upsert_auth(name, auth_token, broker, revoke=False):
    """Store encrypted auth token"""
    encrypted_token = encrypt_token(auth_token)
    auth_obj = Auth.query.filter_by(name=name).first()
    if auth_obj:
        auth_obj.auth = encrypted_token
        auth_obj.broker = broker
        auth_obj.is_revoked = revoke
    else:
        auth_obj = Auth(name=name, auth=encrypted_token, broker=broker, is_revoked=revoke)
        db_session.add(auth_obj)
    db_session.commit()
    return auth_obj.id

def get_auth_token(name):
    """Get decrypted auth token"""
    cache_key = f"auth-{name}"
    if cache_key in auth_cache:
        auth_obj = auth_cache[cache_key]
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            return decrypt_token(auth_obj.auth)
        else:
            del auth_cache[cache_key]
            return None
    else:
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            auth_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.auth)
        return None

def get_auth_token_dbquery(name):
    try:
        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj
        else:
            print(f"No valid auth token found for name '{name}'.")
            return None
    except Exception as e:
        print("Error while querying the database for auth token:", e)
        return None

def upsert_api_key(user_id, hashed_key):
    """Store hashed API key in database"""
    api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
    if api_key_obj:
        api_key_obj.api_key_hash = hashed_key
    else:
        api_key_obj = ApiKeys(user_id=user_id, api_key_hash=hashed_key)
        db_session.add(api_key_obj)
    db_session.commit()
    return api_key_obj.id

def get_api_key(user_id):
    """Check if user has an API key"""
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        return api_key_obj is not None
    except Exception as e:
        print("Error while querying the database for API key:", e)
        return None

def verify_api_key(provided_api_key):
    """Verify an API key and return user_id if valid"""
    peppered_key = provided_api_key + PEPPER
    
    try:
        # Query all API keys (this is fine as we're using secure hashing)
        api_keys = ApiKeys.query.all()
        
        # Try to verify against each stored hash
        for api_key_obj in api_keys:
            try:
                ph.verify(api_key_obj.api_key_hash, peppered_key)
                return api_key_obj.user_id
            except VerifyMismatchError:
                continue
        
        return None
    except Exception as e:
        print(f"Error verifying API key: {e}")
        return None

def get_auth_token_broker(provided_api_key):
    """Get auth token and broker for a valid API key"""
    user_id = verify_api_key(provided_api_key)
    
    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                decrypted_token = decrypt_token(auth_obj.auth)
                return decrypted_token, auth_obj.broker
            else:
                print(f"No valid auth token or broker found for user_id '{user_id}'.")
                return None, None
        except Exception as e:
            print("Error while querying the database for auth token and broker:", e)
            return None, None
    else:
        return None, None
