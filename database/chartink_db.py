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
WEBHOOK_PEPPER = os.getenv('API_KEY_PEPPER', 'default-pepper-change-in-production')

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
    random_bytes = secrets.token_bytes(32)
    hash_input = random_bytes + WEBHOOK_PEPPER.encode()
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
    user_id = Column(String(255), nullable=False)
    webhook_id = Column(String(32), unique=True, nullable=False)
    webhook_url_encrypted = Column(Text, nullable=False)
    is_intraday = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)  # Strategy status
    start_time = Column(String(8))
    end_time = Column(String(8))
    squareoff_time = Column(String(8))
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
    chartink_symbol = Column(String(50), nullable=False)
    exchange = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    strategy = relationship("ChartinkStrategy", back_populates="symbol_mappings")

def init_db():
    """Initialize the database tables"""
    print("Initializing Chartink DB")
    Base.metadata.create_all(bind=engine)

def create_strategy(name: str, base_url: str, user_id: str, is_intraday: bool = True, 
                   start_time: str = "09:30:00", end_time: str = "15:00:00", 
                   squareoff_time: str = "15:15:00") -> ChartinkStrategy:
    """Create a new Chartink strategy with secure webhook URL"""
    try:
        # Add chartink_ prefix if not present
        if not name.startswith('chartink_'):
            name = f'chartink_{name}'
            
        webhook_id = generate_webhook_id()
        webhook_url = f"{base_url}/chartink/webhook/{webhook_id}"
        encrypted_url = encrypt_webhook_url(webhook_url)
        
        strategy = ChartinkStrategy(
            name=name,
            user_id=user_id,
            webhook_id=webhook_id,
            webhook_url_encrypted=encrypted_url,
            is_intraday=is_intraday,
            is_active=True,  # Start as active
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

def toggle_strategy(strategy_id: int) -> bool:
    """Toggle strategy active status"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
            strategy.is_active = not strategy.is_active
            db_session.commit()
            return True
        return False
    except Exception as e:
        db_session.rollback()
        raise e

def get_strategy(strategy_id: int) -> ChartinkStrategy:
    """Get strategy by ID"""
    return ChartinkStrategy.query.get(strategy_id)

def get_strategy_by_webhook_id(webhook_id: str) -> ChartinkStrategy:
    """Get strategy by webhook ID"""
    return ChartinkStrategy.query.filter_by(webhook_id=webhook_id).first()

def get_symbol_mappings(strategy_id: int) -> List[ChartinkSymbolMapping]:
    """Get all symbol mappings for a strategy"""
    return ChartinkSymbolMapping.query.filter_by(strategy_id=strategy_id).all()

def get_all_strategies() -> List[ChartinkStrategy]:
    """Get all strategies"""
    return ChartinkStrategy.query.all()

def update_strategy_times(strategy_id: int, start_time: str = None, 
                        end_time: str = None, squareoff_time: str = None) -> bool:
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

def delete_strategy(strategy_id: int) -> bool:
    """Delete a strategy and its symbol mappings"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if strategy:
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

def add_symbol_mapping(strategy_id: int, chartink_symbol: str, exchange: str, 
                      quantity: int, product_type: str) -> ChartinkSymbolMapping:
    """Add symbol mapping for a strategy"""
    try:
        existing = ChartinkSymbolMapping.query.filter_by(
            strategy_id=strategy_id,
            chartink_symbol=chartink_symbol,
            exchange=exchange
        ).first()
        
        if existing:
            existing.quantity = quantity
            existing.product_type = product_type
            mapping = existing
        else:
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

def bulk_add_symbol_mappings(strategy_id: int, symbols: List[Dict]) -> bool:
    """Add multiple symbol mappings at once"""
    try:
        existing_mappings = {
            (m.chartink_symbol, m.exchange): m 
            for m in ChartinkSymbolMapping.query.filter_by(strategy_id=strategy_id).all()
        }
        
        for symbol_data in symbols:
            key = (symbol_data['symbol'], symbol_data['exchange'])
            if key in existing_mappings:
                mapping = existing_mappings[key]
                mapping.quantity = symbol_data['quantity']
                mapping.product_type = symbol_data['product_type']
            else:
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
