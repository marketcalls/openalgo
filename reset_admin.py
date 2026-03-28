
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(".").resolve()))

from database.user_db import User, db_session, add_user

def reset():
    print("🛠️  Attempting to reset Admin credentials...")
    
    # Check if admin exists
    user = User.query.filter_by(username='admin').first()
    
    if user:
        print(f"✅ Found user '{user.username}'. Resetting password to 'admin123'...")
        user.set_password('admin123')
        db_session.commit()
        print("🚀 SUCCESS: Password updated successfully!")
    else:
        print("⚠️  User 'admin' not found. Creating new admin user...")
        new_user = add_user('admin', 'admin@example.com', 'admin123', is_admin=True)
        if new_user:
            print("🚀 SUCCESS: Created new admin user with password 'admin123'!")
        else:
            print("❌ ERROR: Failed to create user. Check if database is locked.")

if __name__ == "__main__":
    try:
        reset()
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
