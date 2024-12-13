import os
import base64
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from dotenv import load_dotenv
from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import secrets
import hashlib
from typing import List, Dict

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
WEBHOOK_PEPPER = os.getenv('API_KEY_PEPPER', 'default-pepper-change-in-production')  # Use same pepper as API keys

# Setup Fernet encryption for webhook URLs
def get_encryption_key():
    """Generate a Fernet key from the pepper"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'chartink_static_salt',
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(WEBHOOK_PEPPER.encode()))
    return Fernet(key)

# Initialize Fernet cipher
fernet = get_encryption_key()

# Define a cache for webhook URLs with a 30-second TTL
webhook_cache = TTLCache(maxsize=1024, ttl=30)

engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

def generate_webhook_id():
    """Generate a secure webhook identifier"""
    # Generate random bytes
    random_bytes = secrets.token_bytes(32)
    # Create a hash using the random bytes and the webhook secret
    hash_input = random_bytes + WEBHOOK_PEPPER.encode()
    # Use SHA-256 to create a fixed-length hash
    hasher = hashlib.sha256()
    hasher.update(hash_input)
    webhook_id = base64.urlsafe_b64encode(hasher.digest()).decode()[:32]
    return webhook_id

def encrypt_webhook_url(webhook_id):
    """Encrypt webhook URL"""
    if not webhook_id:
        return ''
    return fernet.encrypt(webhook_id.encode()).decode()

def decrypt_webhook_url(encrypted_url):
    """Decrypt webhook URL"""
    if not encrypted_url:
        return ''
    try:
        return fernet.decrypt(encrypted_url.encode()).decode()
    except Exception as e:
        print(f"Error decrypting webhook URL: {e}")
        return None

class ChartinkStrategy(Base):
    __tablename__ = 'chartink_strategies'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    webhook_id = Column(String(32), unique=True, nullable=False)  # Public webhook identifier
    webhook_url_encrypted = Column(Text, nullable=False)  # Encrypted full webhook URL
    is_intraday = Column(Boolean, default=True)
    start_time = Column(String(8))  # HH:MM:SS format
    end_time = Column(String(8))    # HH:MM:SS format
    squareoff_time = Column(String(8))  # HH:MM:SS format
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    symbol_mappings = relationship("ChartinkSymbolMapping", back_populates="strategy", cascade="all, delete-orphan")

    @property
    def webhook_url(self):
        """Get decrypted webhook URL"""
        cache_key = f"webhook-{self.id}"
        if cache_key in webhook_cache:
            return webhook_cache[cache_key]
        else:
            decrypted = decrypt_webhook_url(self.webhook_url_encrypted)
            if decrypted:
                webhook_cache[cache_key] = decrypted
            return decrypted

class ChartinkSymbolMapping(Base):
    __tablename__ = 'chartink_symbol_mappings'
    
    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey('chartink_strategies.id'), nullable=False)
    chartink_symbol = Column(String(50), nullable=False)  # Symbol from Chartink
    exchange = Column(String(10), nullable=False)  # NSE/BSE
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS/CNC
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    strategy = relationship("ChartinkStrategy", back_populates="symbol_mappings")

def init_db():
    """Initialize the database tables"""
    print("Initializing Chartink DB")
    Base.metadata.create_all(bind=engine)

def create_strategy(name, base_url, is_intraday=True, start_time="09:30:00", end_time="15:00:00", squareoff_time="15:15:00"):
    """Create a new Chartink strategy with secure webhook URL"""
    try:
        # Generate webhook ID and URL
        webhook_id = generate_webhook_id()
        webhook_url = f"{base_url}/chartink/webhook/{webhook_id}"
        
        # Encrypt webhook URL
        encrypted_url = encrypt_webhook_url(webhook_url)
        
        strategy = ChartinkStrategy(
            name=name,
            webhook_id=webhook_id,
            webhook_url_encrypted=encrypted_url,
            is_intraday=is_intraday,
            start_time=start_time,
            end_time=end_time,
            squareoff_time=squareoff_time
        )
        db_session.add(strategy)
        db_session.commit()
        return strategy
    except Exception as e:
        db_session.rollback()
        raise e

def add_symbol_mapping(strategy_id, chartink_symbol, exchange, quantity, product_type):
    """Add symbol mapping for a strategy"""
    try:
        # Check if mapping already exists
        existing = ChartinkSymbolMapping.query.filter_by(
            strategy_id=strategy_id,
            chartink_symbol=chartink_symbol,
            exchange=exchange
        ).first()
        
        if existing:
            # Update existing mapping
            existing.quantity = quantity
            existing.product_type = product_type
            mapping = existing
        else:
            # Create new mapping
            mapping = ChartinkSymbolMapping(
                strategy_id=strategy_id,
                chartink_symbol=chartink_symbol,
                exchange=exchange,
                quantity=quantity,
                product_type=product_type
            )
            db_session.add(mapping)
            
        db_session.commit()
        return mapping
    except Exception as e:
        db_session.rollback()
        raise e

def bulk_add_symbol_mappings(strategy_id: int, symbols: List[Dict]):
    """Add multiple symbol mappings at once"""
    try:
        # Get existing mappings
        existing_mappings = {
            (m.chartink_symbol, m.exchange): m 
            for m in ChartinkSymbolMapping.query.filter_by(strategy_id=strategy_id).all()
        }
        
        for symbol_data in symbols:
            key = (symbol_data['symbol'], symbol_data['exchange'])
            if key in existing_mappings:
                # Update existing mapping
                mapping = existing_mappings[key]
                mapping.quantity = symbol_data['quantity']
                mapping.product_type = symbol_data['product_type']
            else:
                # Create new mapping
                mapping = ChartinkSymbolMapping(
                    strategy_id=strategy_id,
                    chartink_symbol=symbol_data['symbol'],
                    exchange=symbol_data['exchange'],
                    quantity=symbol_data['quantity'],
                    product_type=symbol_data['product_type']
                )
                db_session.add(mapping)
        
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        raise e

def delete_symbol_mapping(strategy_id: int, mapping_id: int) -> bool:
    """Delete a symbol mapping"""
    try:
        mapping = ChartinkSymbolMapping.query.filter_by(
            id=mapping_id,
            strategy_id=strategy_id
        ).first()
        
        if mapping:
            db_session.delete(mapping)
            db_session.commit()
            return True
        return False
    except Exception as e:
        db_session.rollback()
        raise e

def get_strategy_by_webhook_id(webhook_id):
    """Get strategy by webhook ID"""
    return ChartinkStrategy.query.filter_by(webhook_id=webhook_id).first()

def get_symbol_mappings(strategy_id):
    """Get all symbol mappings for a strategy"""
    return ChartinkSymbolMapping.query.filter_by(strategy_id=strategy_id).all()

def get_all_strategies():
    """Get all strategies"""
    return ChartinkStrategy.query.all()

def update_strategy_times(strategy_id: int, start_time=None, end_time=None, squareoff_time=None):
    """Update strategy trading times"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if not strategy:
            return False
            
        if start_time:
            strategy.start_time = start_time
        if end_time:
            strategy.end_time = end_time
        if squareoff_time:
            strategy.squareoff_time = squareoff_time
            
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        raise e

def delete_strategy(strategy_id):
    """Delete a strategy and its symbol mappings"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
            # Clear from cache if exists
            cache_key = f"webhook-{strategy.id}"
            if cache_key in webhook_cache:
                del webhook_cache[cache_key]
            
            db_session.delete(strategy)
            db_session.commit()
            return True
        return False
    except Exception as e:
        db_session.rollback()
        raise e
