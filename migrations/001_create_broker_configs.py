# migrations/001_create_broker_configs.py

import os
import sys
import json
from sqlalchemy import create_engine, text

# Add current directory to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

try:
    from utils.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

def run_migration():
    """Create broker configuration tables and insert default templates"""
    
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable not set")
        return False
    
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Create broker_templates table
            logger.info("Creating broker_templates table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS broker_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_name VARCHAR(20) UNIQUE NOT NULL,
                    display_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    logo_url VARCHAR(255),
                    redirect_url_template VARCHAR(500),
                    required_fields TEXT NOT NULL,
                    optional_fields TEXT,
                    documentation_url VARCHAR(255),
                    is_active BOOLEAN DEFAULT TRUE,
                    supports_market_data BOOLEAN DEFAULT FALSE,
                    is_xts_broker BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Create broker_configs table
            logger.info("Creating broker_configs table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS broker_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id VARCHAR(255) NOT NULL,
                    broker_name VARCHAR(20) NOT NULL,
                    display_name VARCHAR(100),
                    api_key_encrypted TEXT NOT NULL,
                    api_secret_encrypted TEXT NOT NULL,
                    market_api_key_encrypted TEXT,
                    market_api_secret_encrypted TEXT,
                    redirect_url VARCHAR(500),
                    additional_config TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    is_default BOOLEAN DEFAULT FALSE,
                    connection_status VARCHAR(20) DEFAULT 'untested',
                    last_validated TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, broker_name)
                );
            """))
            
            # Create broker_config_audit table
            logger.info("Creating broker_config_audit table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS broker_config_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_config_id INTEGER NOT NULL,
                    user_id VARCHAR(255) NOT NULL,
                    action VARCHAR(20) NOT NULL,
                    old_values TEXT,
                    new_values TEXT,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Create indexes
            logger.info("Creating indexes...")
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_broker_configs_user_id ON broker_configs(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_broker_configs_broker_name ON broker_configs(broker_name);",
                "CREATE INDEX IF NOT EXISTS idx_broker_configs_user_broker ON broker_configs(user_id, broker_name);",
                "CREATE INDEX IF NOT EXISTS idx_broker_configs_active ON broker_configs(user_id, is_active);",
                "CREATE INDEX IF NOT EXISTS idx_broker_configs_status ON broker_configs(connection_status, last_validated);",
                "CREATE INDEX IF NOT EXISTS idx_broker_audit_config_id ON broker_config_audit(broker_config_id);",
                "CREATE INDEX IF NOT EXISTS idx_broker_audit_user_id ON broker_config_audit(user_id);",
                "CREATE INDEX IF NOT EXISTS idx_broker_audit_created_at ON broker_config_audit(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_broker_templates_name ON broker_templates(broker_name);",
                "CREATE INDEX IF NOT EXISTS idx_broker_templates_active ON broker_templates(is_active);"
            ]
            
            for index_sql in indexes:
                conn.execute(text(index_sql))
            
            # Insert default broker templates
            logger.info("Inserting default broker templates...")
            
            # Check if templates already exist
            result = conn.execute(text("SELECT COUNT(*) as count FROM broker_templates;"))
            count = result.fetchone()[0]
            
            if count == 0:
                templates = [
                    # Regular brokers
                    {
                        'broker_name': 'dhan',
                        'display_name': 'Dhan',
                        'description': 'Dhan Securities broker integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "API Key", "type": "text", "placeholder": "Enter your Dhan API Key"},
                            {"name": "api_secret", "label": "API Secret", "type": "password", "placeholder": "Enter your Dhan API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': False
                    },
                    {
                        'broker_name': 'angel',
                        'display_name': 'Angel One',
                        'description': 'Angel One (Angel Broking) integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "API Key", "type": "text", "placeholder": "Enter your Angel One API Key"},
                            {"name": "api_secret", "label": "API Secret", "type": "password", "placeholder": "Enter your Angel One API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': False
                    },
                    {
                        'broker_name': 'zerodha',
                        'display_name': 'Zerodha',
                        'description': 'Zerodha Kite Connect integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "API Key", "type": "text", "placeholder": "Enter your Kite Connect API Key"},
                            {"name": "api_secret", "label": "API Secret", "type": "password", "placeholder": "Enter your Kite Connect API Secret"}
                        ]),
                        'supports_market_data': False,
                        'is_xts_broker': False
                    },
                    {
                        'broker_name': 'upstox',
                        'display_name': 'Upstox',
                        'description': 'Upstox Pro API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "API Key", "type": "text", "placeholder": "Enter your Upstox API Key"},
                            {"name": "api_secret", "label": "API Secret", "type": "password", "placeholder": "Enter your Upstox API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': False
                    },
                    
                    # XTS-based brokers
                    {
                        'broker_name': 'fivepaisaxts',
                        'display_name': '5Paisa XTS',
                        'description': '5Paisa XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'compositedge',
                        'display_name': 'Compositedge',
                        'description': 'Compositedge XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'iifl',
                        'display_name': 'IIFL',
                        'description': 'IIFL XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'ibulls',
                        'display_name': 'Indiabulls',
                        'description': 'Indiabulls XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'jainam',
                        'display_name': 'Jainam',
                        'description': 'Jainam XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'jainampro',
                        'display_name': 'Jainam Pro',
                        'description': 'Jainam Pro XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    },
                    {
                        'broker_name': 'wisdom',
                        'display_name': 'Wisdom',
                        'description': 'Wisdom XTS API integration',
                        'required_fields': json.dumps([
                            {"name": "api_key", "label": "Trading API Key", "type": "text", "placeholder": "Enter your Trading API Key"},
                            {"name": "api_secret", "label": "Trading API Secret", "type": "password", "placeholder": "Enter your Trading API Secret"},
                            {"name": "market_api_key", "label": "Market Data API Key", "type": "text", "placeholder": "Enter your Market Data API Key"},
                            {"name": "market_api_secret", "label": "Market Data API Secret", "type": "password", "placeholder": "Enter your Market Data API Secret"}
                        ]),
                        'supports_market_data': True,
                        'is_xts_broker': True
                    }
                ]
                
                for template in templates:
                    conn.execute(text("""
                        INSERT INTO broker_templates 
                        (broker_name, display_name, description, required_fields, supports_market_data, is_xts_broker)
                        VALUES (:broker_name, :display_name, :description, :required_fields, :supports_market_data, :is_xts_broker)
                    """), template)
                
                logger.info(f"Inserted {len(templates)} broker templates")
            else:
                logger.info("Broker templates already exist, skipping insert")
            
            # Commit the transaction
            conn.commit()
            
        logger.info("Migration 001 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration 001 failed: {e}")
        return False

def verify_migration():
    """Verify migration was successful"""
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        return False
    
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Check if tables exist
            tables = ['broker_templates', 'broker_configs', 'broker_config_audit']
            for table in tables:
                result = conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}';"))
                if not result.fetchone():
                    logger.error(f"Table {table} not found")
                    return False
            
            # Check if templates were inserted
            result = conn.execute(text("SELECT COUNT(*) as count FROM broker_templates;"))
            count = result.fetchone()[0]
            if count == 0:
                logger.error("No broker templates found")
                return False
            
            logger.info("Migration verification successful")
            return True
            
    except Exception as e:
        logger.error(f"Migration verification failed: {e}")
        return False

if __name__ == "__main__":
    print("Starting migration 001: Create broker configuration tables")
    
    success = run_migration()
    if success:
        print("Migration completed successfully")
        
        print("Verifying migration...")
        if verify_migration():
            print("Migration verification successful")
        else:
            print("Migration verification failed")
            sys.exit(1)
    else:
        print("Migration failed")
        sys.exit(1)