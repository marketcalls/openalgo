# database/broker_config_db.py

import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')
PEPPER = os.getenv('API_KEY_PEPPER', 'default-pepper-change-in-production')

# Setup Fernet encryption for broker credentials
def get_encryption_key():
    """Generate a Fernet key from the pepper for broker configs"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'openalgo_broker_salt',
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)

# Initialize Fernet cipher
fernet = get_encryption_key()

# Define caches for broker configurations
broker_config_cache = TTLCache(maxsize=1024, ttl=300)  # 5-minute TTL
broker_template_cache = TTLCache(maxsize=100, ttl=3600)  # 1-hour TTL

# Database setup
engine = create_engine(
    DATABASE_URL,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10
)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class BrokerConfig(Base):
    """Broker configuration model with encrypted credentials"""
    __tablename__ = 'broker_configs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    broker_name = Column(String(20), nullable=False)
    display_name = Column(String(100))
    api_key_encrypted = Column(Text, nullable=False)
    api_secret_encrypted = Column(Text, nullable=False)
    market_api_key_encrypted = Column(Text)
    market_api_secret_encrypted = Column(Text)
    redirect_url = Column(String(500))
    additional_config = Column(Text)  # JSON field for broker-specific configs
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    connection_status = Column(String(20), default='untested')
    last_validated = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('user_id', 'broker_name'),
    )

class BrokerTemplate(Base):
    """Broker template for UI generation and validation"""
    __tablename__ = 'broker_templates'
    
    id = Column(Integer, primary_key=True)
    broker_name = Column(String(20), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text)
    logo_url = Column(String(255))
    redirect_url_template = Column(String(500))
    required_fields = Column(Text, nullable=False)  # JSON array
    optional_fields = Column(Text)  # JSON array
    documentation_url = Column(String(255))
    is_active = Column(Boolean, default=True)
    supports_market_data = Column(Boolean, default=False)
    is_xts_broker = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class BrokerConfigAudit(Base):
    """Audit trail for broker configuration changes"""
    __tablename__ = 'broker_config_audit'
    
    id = Column(Integer, primary_key=True)
    broker_config_id = Column(Integer, nullable=False)
    user_id = Column(String(255), nullable=False)
    action = Column(String(20), nullable=False)  # create, update, delete, activate, deactivate
    old_values = Column(Text)  # JSON
    new_values = Column(Text)  # JSON
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())

def init_db():
    """Initialize broker configuration database tables"""
    logger.info("Initializing Broker Config DB")
    Base.metadata.create_all(bind=engine)

def encrypt_credential(value):
    """Encrypt sensitive credential"""
    if not value:
        return None
    return fernet.encrypt(value.encode()).decode()

def decrypt_credential(encrypted_value):
    """Decrypt sensitive credential"""
    if not encrypted_value:
        return None
    try:
        return fernet.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        logger.error(f"Error decrypting credential: {e}")
        return None

def create_broker_config(user_id, broker_name, api_key, api_secret, 
                        market_api_key=None, market_api_secret=None, 
                        redirect_url=None, additional_config=None,
                        is_default=False, ip_address=None, user_agent=None):
    """Create or update broker configuration with encrypted credentials"""
    try:
        # Check if config exists
        config = BrokerConfig.query.filter_by(user_id=user_id, broker_name=broker_name).first()
        
        # If setting as default, unset other defaults for this user
        if is_default:
            BrokerConfig.query.filter_by(user_id=user_id, is_default=True).update({'is_default': False})
        
        if config:
            # Update existing
            old_values = {
                'broker_name': config.broker_name,
                'is_active': config.is_active,
                'is_default': config.is_default
            }
            
            config.api_key_encrypted = encrypt_credential(api_key)
            config.api_secret_encrypted = encrypt_credential(api_secret)
            config.market_api_key_encrypted = encrypt_credential(market_api_key) if market_api_key else None
            config.market_api_secret_encrypted = encrypt_credential(market_api_secret) if market_api_secret else None
            config.redirect_url = redirect_url
            config.additional_config = json.dumps(additional_config) if additional_config else None
            config.is_default = is_default
            config.connection_status = 'untested'
            config.updated_at = func.now()
            
            action = 'update'
        else:
            # Create new
            config = BrokerConfig(
                user_id=user_id,
                broker_name=broker_name,
                api_key_encrypted=encrypt_credential(api_key),
                api_secret_encrypted=encrypt_credential(api_secret),
                market_api_key_encrypted=encrypt_credential(market_api_key) if market_api_key else None,
                market_api_secret_encrypted=encrypt_credential(market_api_secret) if market_api_secret else None,
                redirect_url=redirect_url,
                additional_config=json.dumps(additional_config) if additional_config else None,
                is_default=is_default
            )
            db_session.add(config)
            old_values = None
            action = 'create'
        
        db_session.commit()
        
        # Create audit record
        audit = BrokerConfigAudit(
            broker_config_id=config.id,
            user_id=user_id,
            action=action,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps({'broker_name': broker_name, 'is_default': is_default}),
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(audit)
        db_session.commit()
        
        # Clear cache
        cache_key = f"broker_config:{user_id}:{broker_name}"
        if cache_key in broker_config_cache:
            del broker_config_cache[cache_key]
        
        return config.id
        
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error creating broker config: {e}")
        raise

def get_broker_config(user_id, broker_name):
    """Get decrypted broker configuration"""
    cache_key = f"broker_config:{user_id}:{broker_name}"
    
    # Check cache first
    if cache_key in broker_config_cache:
        return broker_config_cache[cache_key]
    
    try:
        config = BrokerConfig.query.filter_by(
            user_id=user_id, 
            broker_name=broker_name,
            is_active=True
        ).first()
        
        if not config:
            return None
        
        # Decrypt and prepare response
        result = {
            'broker_name': config.broker_name,
            'api_key': decrypt_credential(config.api_key_encrypted),
            'api_secret': decrypt_credential(config.api_secret_encrypted),
            'market_api_key': decrypt_credential(config.market_api_key_encrypted) if config.market_api_key_encrypted else None,
            'market_api_secret': decrypt_credential(config.market_api_secret_encrypted) if config.market_api_secret_encrypted else None,
            'redirect_url': config.redirect_url,
            'additional_config': json.loads(config.additional_config) if config.additional_config else {},
            'is_default': config.is_default,
            'connection_status': config.connection_status,
            'last_validated': config.last_validated
        }
        
        # Cache the result
        broker_config_cache[cache_key] = result
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting broker config: {e}")
        return None

def get_user_brokers(user_id):
    """Get all broker configurations for a user"""
    try:
        configs = BrokerConfig.query.filter_by(user_id=user_id, is_active=True).all()
        
        result = []
        for config in configs:
            result.append({
                'id': config.id,
                'broker_name': config.broker_name,
                'display_name': config.display_name,
                'is_default': config.is_default,
                'connection_status': config.connection_status,
                'last_validated': config.last_validated,
                'created_at': config.created_at
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting user brokers: {e}")
        return []

def get_default_broker(user_id):
    """Get default broker configuration for a user"""
    try:
        config = BrokerConfig.query.filter_by(
            user_id=user_id, 
            is_default=True,
            is_active=True
        ).first()
        
        if not config:
            # If no default, get the first active broker
            config = BrokerConfig.query.filter_by(
                user_id=user_id,
                is_active=True
            ).first()
        
        if not config:
            return None
            
        return get_broker_config(user_id, config.broker_name)
        
    except Exception as e:
        logger.error(f"Error getting default broker: {e}")
        return None

def update_connection_status(user_id, broker_name, status, ip_address=None):
    """Update broker connection status after validation"""
    try:
        config = BrokerConfig.query.filter_by(
            user_id=user_id,
            broker_name=broker_name
        ).first()
        
        if config:
            config.connection_status = status
            if status == 'valid':
                config.last_validated = func.now()
            db_session.commit()
            
            # Create audit record
            audit = BrokerConfigAudit(
                broker_config_id=config.id,
                user_id=user_id,
                action='validate',
                new_values=json.dumps({'status': status}),
                ip_address=ip_address
            )
            db_session.add(audit)
            db_session.commit()
            
            # Clear cache
            cache_key = f"broker_config:{user_id}:{broker_name}"
            if cache_key in broker_config_cache:
                del broker_config_cache[cache_key]
                
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error updating connection status: {e}")

def delete_broker_config(user_id, broker_name, ip_address=None):
    """Soft delete broker configuration"""
    try:
        config = BrokerConfig.query.filter_by(
            user_id=user_id,
            broker_name=broker_name
        ).first()
        
        if config:
            config.is_active = False
            db_session.commit()
            
            # Create audit record
            audit = BrokerConfigAudit(
                broker_config_id=config.id,
                user_id=user_id,
                action='delete',
                ip_address=ip_address
            )
            db_session.add(audit)
            db_session.commit()
            
            # Clear cache
            cache_key = f"broker_config:{user_id}:{broker_name}"
            if cache_key in broker_config_cache:
                del broker_config_cache[cache_key]
                
            return True
            
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error deleting broker config: {e}")
        return False

def get_broker_templates(active_only=True):
    """Get broker templates for UI generation"""
    cache_key = "broker_templates:active" if active_only else "broker_templates:all"
    
    # Check cache first
    if cache_key in broker_template_cache:
        return broker_template_cache[cache_key]
    
    try:
        query = BrokerTemplate.query
        if active_only:
            query = query.filter_by(is_active=True)
        
        templates = query.all()
        
        result = []
        for template in templates:
            result.append({
                'broker_name': template.broker_name,
                'display_name': template.display_name,
                'description': template.description,
                'logo_url': template.logo_url,
                'redirect_url_template': template.redirect_url_template,
                'required_fields': json.loads(template.required_fields) if template.required_fields else [],
                'optional_fields': json.loads(template.optional_fields) if template.optional_fields else [],
                'documentation_url': template.documentation_url,
                'supports_market_data': template.supports_market_data,
                'is_xts_broker': template.is_xts_broker
            })
        
        # Cache the result
        broker_template_cache[cache_key] = result
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting broker templates: {e}")
        return []

def get_broker_template(broker_name):
    """Get specific broker template"""
    templates = get_broker_templates()
    for template in templates:
        if template['broker_name'] == broker_name:
            return template
    return None

def is_xts_broker(broker_name):
    """Check if broker is XTS-based"""
    template = get_broker_template(broker_name)
    return template.get('is_xts_broker', False) if template else False