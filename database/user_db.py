# database/user_db.py

import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError
from cachetools import TTLCache
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import pyotp
from datetime import datetime

# Initialize Argon2 hasher
ph = PasswordHasher()

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
    password = Column(String(255), nullable=False)  # For storing Argon2 hash
    totp_secret = Column(String(32), nullable=True)  # For TOTP-based 2FA
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Add relationship to BrokerConfig
    broker_configs = relationship("BrokerConfig", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        """Hash password using Argon2 with pepper"""
        peppered_password = password + PASSWORD_PEPPER
        self.password = ph.hash(peppered_password)

    def check_password(self, password):
        """Verify password using Argon2 with pepper"""
        peppered_password = password + PASSWORD_PEPPER
        try:
            return ph.verify(self.password, peppered_password)
        except VerifyMismatchError:
            return False

    def get_totp_uri(self):
        """Get the TOTP URI for QR code generation"""
        if not self.totp_secret:
            self.totp_secret = pyotp.random_base32()
            db_session.commit()
        return pyotp.totp.TOTP(self.totp_secret).provisioning_uri(
            name=self.email,
            issuer_name="OpenAlgo"
        )

    def verify_totp(self, code):
        """Verify TOTP code for 2FA"""
        if not self.totp_secret:
            return False
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(code)

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)

def add_user(username, email, password, is_admin=False):
    """Add a new user to the database"""
    try:
        user = User(username=username, email=email, is_admin=is_admin)
        user.set_password(password)
        db_session.add(user)
        db_session.commit()
        return user
    except IntegrityError:
        db_session.rollback()
        return None

def authenticate_user(username, password):
    """Authenticate a user"""
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        return user
    return None

def find_user_by_email(email):
    """Find a user by email"""
    return User.query.filter_by(email=email).first()

def find_user_by_username():
    """Find admin user"""
    return User.query.filter_by(is_admin=True).first()

def rehash_all_passwords():
    """
    Utility function to rehash all existing passwords with Argon2.
    This should be called once when upgrading from the old hashing method.
    Requires knowing the original passwords or having users reset them.
    """
    users = User.query.all()
    for user in users:
        if user.password and not user.password.startswith('$argon2'):
            # This assumes you have access to the original password
            # In practice, you might need users to reset their passwords
            user.set_password(user.password)
    db_session.commit()

# Initialize the database
init_db()
