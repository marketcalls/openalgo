import os
import sqlite3
import glob
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def add_user_id_column():
    """Add user_id column to the auth table in the database."""
    logger.info("Starting to add user_id column to auth table")
    
    # Search for SQLite database files in the db directory
    db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'db')
    logger.info(f"Searching for database files in: {db_dir}")

    # Look for db files (assuming SQLite databases have .db extension)
    db_files = glob.glob(os.path.join(db_dir, '*.db'))

    if not db_files:
        logger.info("No database files found in the db directory.")
        # Also look in the current directory
        db_files = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '*.db'))
        if db_files:
            logger.info(f"Found database files in current directory: {db_files}")

    success = False
    for db_file in db_files:
        logger.info(f"Processing database: {db_file}")
        if _add_column_to_database(db_file):
            success = True

    if not success:
        logger.warning("Could not automatically find or update any databases.")
        
    logger.info("User ID column addition process completed")
    return success

def _add_column_to_database(db_path):
    """Add the user_id column to the auth table in the specified database."""
    try:
        # Check if the file exists and is a database
        if not os.path.exists(db_path):
            logger.error(f"Database file does not exist: {db_path}")
            return False

        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the auth table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auth'")
        if not cursor.fetchone():
            logger.warning(f"The auth table does not exist in: {db_path}")
            conn.close()
            return False
            
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(auth)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'user_id' not in column_names:
            # Add the user_id column to the auth table
            cursor.execute("ALTER TABLE auth ADD COLUMN user_id VARCHAR(255)")
            conn.commit()
            logger.info(f"Successfully added user_id column to auth table in: {db_path}")
            result = True
        else:
            logger.info(f"Column user_id already exists in auth table in: {db_path}")
            result = True
        
        conn.close()
        return result
        
    except Exception as e:
        logger.error(f"Error processing database {db_path}: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    add_user_id_column()
