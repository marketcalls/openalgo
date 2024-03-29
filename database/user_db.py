# database/user_db.py

import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from cachetools import TTLCache

# Load environment variables
load_dotenv()

# Database connection details
DATABASE_URL = os.getenv('DATABASE_URL')  # Replace with your database connection string

# Engine and session setup
engine = create_engine(DATABASE_URL, echo=False)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Define a cache for the usernames with a max size and a 30-second TTL
username_cache = TTLCache(maxsize=1024, ttl=30)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    mobile_number = Column(String(15), unique=True, nullable=False)
    is_admin = Column(Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

def init_db():
    print("Initializing User DB")
    Base.metadata.create_all(bind=engine)

def add_user(username, email, password, mobile_number, is_admin=False):
    try:
        user = User(username=username, email=email, mobile_number=mobile_number, is_admin=is_admin)
        user.set_password(password)
        db_session.add(user)
        db_session.commit()
        return True
    except IntegrityError:
        db_session.rollback()
        return False

def authenticate_user(username, password):
    cache_key = f"user-{username}"
    if cache_key in username_cache:
        user = username_cache[cache_key]
        # Ensure that user is an instance of User, not a string
        if isinstance(user, User) and user.check_password(password):
            return True
        else:
            del username_cache[cache_key]  # Remove invalid cache entry
            return False
    else:
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            username_cache[cache_key] = user  # Cache the User object
            return True
        return False

def find_user_by_username():
    return User.query.filter_by(is_admin=True).first()
