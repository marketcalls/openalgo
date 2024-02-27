# database/auth_db.py


import os


from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, UniqueConstraint
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from dotenv import load_dotenv
from database.db import db 

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your SQLite path

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class Auth(Base):
    __tablename__ = 'auth'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    auth = Column(String(1000), nullable=False)

class ApiKeys(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    api_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

def init_db():
    print("Initializing Auth DB")
    Base.metadata.create_all(bind=engine)

def upsert_auth(name, auth_token):
    auth_obj = Auth.query.filter_by(name=name).first()
    if auth_obj:
        auth_obj.auth = auth_token
    else:
        auth_obj = Auth(name=name, auth=auth_token)
        db_session.add(auth_obj)
    db_session.commit()
    return auth_obj.id

def get_auth_token(name):
    auth_obj = Auth.query.filter_by(name=name).first()
    return auth_obj.auth if auth_obj else None

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
    api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
    return api_key_obj.api_key if api_key_obj else None


