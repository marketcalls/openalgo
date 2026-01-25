"""
Clear all data from Action Center database

This script completely resets the Action Center by deleting all pending orders.
Use this for testing purposes to start with a clean slate.

Run with: python test/test_clear_action_center.py
"""

import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func

from database.action_center_db import PendingOrder, db_session


def log(message, level="INFO"):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def get_statistics():
    """Get current statistics before deletion"""
    try:
        total_count = db_session.query(func.count(PendingOrder.id)).scalar()

        # Count by status
        pending_count = (
            db_session.query(func.count(PendingOrder.id))
            .filter(PendingOrder.status == "pending")
            .scalar()
        )

        approved_count = (
            db_session.query(func.count(PendingOrder.id))
            .filter(PendingOrder.status == "approved")
            .scalar()
        )

        rejected_count = (
            db_session.query(func.count(PendingOrder.id))
            .filter(PendingOrder.status == "rejected")
            .scalar()
        )

        return {
            "total": total_count,
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count,
        }
    except Exception as e:
        log(f"Error getting statistics: {e}", "ERROR")
        return None


def clear_action_center():
    """Clear all data from Action Center"""
    log("=" * 80)
    log("Action Center Database Reset Utility")
    log("=" * 80)
    log("")

    # Get current statistics
    log("Fetching current statistics...")
    stats = get_statistics()

    if stats:
        log("Current Action Center Status:")
        log(f"  Total Orders: {stats['total']}")
        log(f"  - Pending: {stats['pending']}")
        log(f"  - Approved: {stats['approved']}")
        log(f"  - Rejected: {stats['rejected']}")
        log("")

    if not stats or stats["total"] == 0:
        log("Action Center is already empty. Nothing to clear.", "INFO")
        log("=" * 80)
        return

    # Confirm deletion
    log("WARNING: This will permanently delete all orders from Action Center!", "WARNING")
    log("This action cannot be undone.", "WARNING")
    log("")

    confirmation = input("Type 'YES' to confirm deletion: ")

    if confirmation != "YES":
        log("Deletion cancelled by user.", "INFO")
        log("=" * 80)
        return

    log("")
    log("Starting deletion process...")

    try:
        # Delete all pending orders
        deleted_count = db_session.query(PendingOrder).delete()
        db_session.commit()

        log(f"Successfully deleted {deleted_count} orders from Action Center", "SUCCESS")
        log("")

        # Verify deletion
        log("Verifying deletion...")
        remaining_count = db_session.query(func.count(PendingOrder.id)).scalar()

        if remaining_count == 0:
            log("Verification successful: Action Center is now empty", "SUCCESS")
        else:
            log(f"Warning: {remaining_count} orders still remain in database", "WARNING")

    except Exception as e:
        db_session.rollback()
        log(f"Error during deletion: {e}", "ERROR")
        log("Database rolled back. No changes were made.", "ERROR")

    log("")
    log("=" * 80)
    log("Action Center Reset Complete")
    log("=" * 80)


def clear_by_status(status):
    """Clear orders by specific status"""
    log("=" * 80)
    log(f"Clearing {status.upper()} orders from Action Center")
    log("=" * 80)
    log("")

    try:
        count = (
            db_session.query(func.count(PendingOrder.id))
            .filter(PendingOrder.status == status)
            .scalar()
        )

        if count == 0:
            log(f"No {status} orders found to delete.", "INFO")
            return

        log(f"Found {count} {status} orders")
        log("")

        confirmation = input(f"Type 'YES' to delete {count} {status} orders: ")

        if confirmation != "YES":
            log("Deletion cancelled by user.", "INFO")
            return

        log("")
        log("Deleting...")

        deleted_count = (
            db_session.query(PendingOrder).filter(PendingOrder.status == status).delete()
        )
        db_session.commit()

        log(f"Successfully deleted {deleted_count} {status} orders", "SUCCESS")

    except Exception as e:
        db_session.rollback()
        log(f"Error during deletion: {e}", "ERROR")

    log("")
    log("=" * 80)


def show_menu():
    """Show interactive menu"""
    while True:
        log("")
        log("=" * 80)
        log("Action Center Database Management")
        log("=" * 80)
        log("")
        log("Options:")
        log("  1. Clear ALL orders (pending, approved, rejected)")
        log("  2. Clear PENDING orders only")
        log("  3. Clear APPROVED orders only")
        log("  4. Clear REJECTED orders only")
        log("  5. View current statistics")
        log("  6. Exit")
        log("")

        choice = input("Select option (1-6): ").strip()

        if choice == "1":
            clear_action_center()
        elif choice == "2":
            clear_by_status("pending")
        elif choice == "3":
            clear_by_status("approved")
        elif choice == "4":
            clear_by_status("rejected")
        elif choice == "5":
            stats = get_statistics()
            if stats:
                log("")
                log("Current Action Center Statistics:")
                log(f"  Total Orders: {stats['total']}")
                log(f"  - Pending: {stats['pending']}")
                log(f"  - Approved: {stats['approved']}")
                log(f"  - Rejected: {stats['rejected']}")
        elif choice == "6":
            log("")
            log("Exiting...")
            break
        else:
            log("Invalid option. Please select 1-6.", "ERROR")


if __name__ == "__main__":
    try:
        # Check if running with command-line arguments
        if len(sys.argv) > 1:
            if sys.argv[1] == "--all":
                # Non-interactive mode: clear everything
                stats = get_statistics()
                if stats and stats["total"] > 0:
                    deleted_count = db_session.query(PendingOrder).delete()
                    db_session.commit()
                    log(f"Deleted {deleted_count} orders from Action Center", "SUCCESS")
                else:
                    log("Action Center is already empty", "INFO")
            elif sys.argv[1] == "--pending":
                # Clear only pending orders
                deleted_count = (
                    db_session.query(PendingOrder).filter(PendingOrder.status == "pending").delete()
                )
                db_session.commit()
                log(f"Deleted {deleted_count} pending orders", "SUCCESS")
            elif sys.argv[1] == "--approved":
                # Clear only approved orders
                deleted_count = (
                    db_session.query(PendingOrder)
                    .filter(PendingOrder.status == "approved")
                    .delete()
                )
                db_session.commit()
                log(f"Deleted {deleted_count} approved orders", "SUCCESS")
            elif sys.argv[1] == "--rejected":
                # Clear only rejected orders
                deleted_count = (
                    db_session.query(PendingOrder)
                    .filter(PendingOrder.status == "rejected")
                    .delete()
                )
                db_session.commit()
                log(f"Deleted {deleted_count} rejected orders", "SUCCESS")
            elif sys.argv[1] == "--help":
                print("\nUsage:")
                print("  python test/test_clear_action_center.py           # Interactive menu")
                print("  python test/test_clear_action_center.py --all     # Clear all orders")
                print("  python test/test_clear_action_center.py --pending # Clear pending only")
                print("  python test/test_clear_action_center.py --approved # Clear approved only")
                print("  python test/test_clear_action_center.py --rejected # Clear rejected only")
                print("  python test/test_clear_action_center.py --help    # Show this help")
                print("")
            else:
                log(f"Unknown option: {sys.argv[1]}", "ERROR")
                log("Use --help to see available options", "INFO")
        else:
            # Interactive mode
            show_menu()

    except KeyboardInterrupt:
        log("\n\nOperation cancelled by user (Ctrl+C)", "WARNING")
    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        import traceback

        traceback.print_exc()
    finally:
        db_session.close()
