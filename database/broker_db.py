from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
from database.user_db import Base, User  # Import Base and User from user_db

class BrokerConfig(Base):  # Use the same Base as User
    __tablename__ = 'broker_configs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    broker_name = Column(String(50), nullable=False)
    api_key = Column(String(100), nullable=False)
    api_secret = Column(String(100), nullable=False)
    redirect_url = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Create a relationship to the User model
    user = relationship("User", back_populates="broker_configs")

    # Create a unique constraint to ensure one config per user per broker
    __table_args__ = (UniqueConstraint('user_id', 'broker_name', name='_user_broker_uc'),)

def init_db():
    engine = create_engine(os.getenv('DATABASE_URL'))
    Base.metadata.create_all(engine)
    return engine

def get_broker_config(user_id, broker_name):
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        config = session.query(BrokerConfig).filter_by(
            user_id=user_id,
            broker_name=broker_name
        ).first()
        return config
    finally:
        session.close()

def save_broker_config(user_id, broker_name, api_key, api_secret, redirect_url):
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        config = session.query(BrokerConfig).filter_by(
            user_id=user_id,
            broker_name=broker_name
        ).first()
        
        if config:
            # Update existing config
            config.api_key = api_key
            config.api_secret = api_secret
            config.redirect_url = redirect_url
            config.updated_at = datetime.utcnow()
        else:
            # Create new config
            config = BrokerConfig(
                user_id=user_id,
                broker_name=broker_name,
                api_key=api_key,
                api_secret=api_secret,
                redirect_url=redirect_url
            )
            session.add(config)
        
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def delete_broker_config(user_id, broker_name):
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        config = session.query(BrokerConfig).filter_by(
            user_id=user_id,
            broker_name=broker_name
        ).first()
        
        if config:
            session.delete(config)
            session.commit()
            return True
        return False
    finally:
        session.close()
