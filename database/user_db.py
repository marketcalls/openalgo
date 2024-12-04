# database/user_db.py

import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from cachetools import TTLCache
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Initialize Argon2 hasher
ph = PasswordHasher()

# Load environment variables
load_dotenv()

# Database connection details
DATABASE_URL = os.getenv('DATABASE_URL')
PASSWORD_PEPPER = os.getenv('API_KEY_PEPPER')  # We'll use the same pepper for consistency

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
    password_hash = Column(String(255), nullable=False)  # Increased length for Argon2 hash
    mobile_number = Column(String(15), unique=True, nullable=False)
    is_admin = Column(Boolean, default=False)

    def set_password(self, password):
        """Hash password using Argon2 with pepper"""
        peppered_password = password + PASSWORD_PEPPER
        self.password_hash = ph.hash(peppered_password)

    def check_password(self, password):
        """Verify password using Argon2 with pepper"""
        peppered_password = password + PASSWORD_PEPPER
        try:
            ph.verify(self.password_hash, peppered_password)
            # Check if the hash needs to be updated
            if ph.check_needs_rehash(self.password_hash):
                self.set_password(password)
                db_session.commit()
            return True
        except VerifyMismatchError:
            return False

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
    """Authenticate user with Argon2 hashed password"""
    cache_key = f"user-{username}"
    if cache_key in username_cache:
        user = username_cache[cache_key]
        # Ensure that user is an instance of User
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

def rehash_all_passwords():
    """
    Utility function to rehash all existing passwords with Argon2.
    This should be called once when upgrading from the old hashing method.
    Requires knowing the original passwords or having users reset them.
    """
    users = User.query.all()
    for user in users:
        if user.password_hash.startswith('pbkdf2:sha256'):  # Old Werkzeug format
            # At this point, you would either:
            # 1. Have users reset their passwords
            # 2. Or if you have access to original passwords (during migration):
            #    user.set_password(original_password)
            pass
    db_session.commit()
