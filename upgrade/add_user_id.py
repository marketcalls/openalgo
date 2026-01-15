import os
import glob
import logging
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import text

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
    """Add the user_id column to the auth table in the specified database using SQLAlchemy."""
    try:
        if not os.path.exists(db_path):
            logger.error(f"Database file does not exist: {db_path}")
            return False

        engine = create_engine(f'sqlite:///{db_path}')
        inspector = inspect(engine)

        with engine.connect() as connection:
            # Check if the auth table exists
            if not inspector.has_table('auth'):
                logger.warning(f"The auth table does not exist in: {db_path}")
                return False

            # Check if the column already exists
            columns = inspector.get_columns('auth')
            column_names = [col['name'] for col in columns]

            if 'user_id' not in column_names:
                # Use a text construct for the DDL statement for safety
                alter_statement = text("ALTER TABLE auth ADD COLUMN user_id VARCHAR(255)")
                connection.execute(alter_statement)
                logger.info(f"Successfully added user_id column to auth table in: {db_path}")
            else:
                logger.info(f"Column user_id already exists in auth table in: {db_path}")
            
            return True

    except SQLAlchemyError as e:
        logger.error(f"SQLAlchemy error processing database {db_path}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Generic error processing database {db_path}: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    add_user_id_column()
