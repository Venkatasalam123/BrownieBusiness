<<<<<<< HEAD
"""
Migration script to add payment_status and paid_amount fields to existing orders table.
Run this once to update the database schema.
"""

from flask import Flask
from models import db
import sqlite3
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownie_sales.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def migrate_database():
    """Add payment_status and paid_amount columns to orders table"""
    
    with app.app_context():
        db_path = 'instance/brownie_sales.db'
        if not os.path.exists(db_path):
            db_path = 'brownie_sales.db'
        
        if not os.path.exists(db_path):
            print(f"Database file not found at {db_path}")
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # Check if payment_status column exists
            cursor.execute("PRAGMA table_info(orders)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'payment_status' not in columns:
                print("Adding payment_status column...")
                cursor.execute("ALTER TABLE orders ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'")
                # Update existing rows
                cursor.execute("UPDATE orders SET payment_status = 'unpaid' WHERE payment_status IS NULL")
                print("✓ Added payment_status column")
            else:
                print("✓ payment_status column already exists")
            
            if 'paid_amount' not in columns:
                print("Adding paid_amount column...")
                cursor.execute("ALTER TABLE orders ADD COLUMN paid_amount NUMERIC(10, 2) DEFAULT 0")
                # Update existing rows
                cursor.execute("UPDATE orders SET paid_amount = 0 WHERE paid_amount IS NULL")
                print("✓ Added paid_amount column")
            else:
                print("✓ paid_amount column already exists")
            
            conn.commit()
            print("\n✓ Database migration completed successfully!")
            
        except Exception as e:
            conn.rollback()
            print(f"\n✗ Migration failed: {str(e)}")
        finally:
            conn.close()

if __name__ == '__main__':
    print("Running database migration...")
    migrate_database()

=======
"""
Migration script to add payment_status and paid_amount fields to existing orders table.
Run this once to update the database schema.
"""

from flask import Flask
from models import db
import sqlite3
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownie_sales.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def migrate_database():
    """Add payment_status and paid_amount columns to orders table"""
    
    with app.app_context():
        db_path = 'instance/brownie_sales.db'
        if not os.path.exists(db_path):
            db_path = 'brownie_sales.db'
        
        if not os.path.exists(db_path):
            print(f"Database file not found at {db_path}")
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # Check if payment_status column exists
            cursor.execute("PRAGMA table_info(orders)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'payment_status' not in columns:
                print("Adding payment_status column...")
                cursor.execute("ALTER TABLE orders ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'")
                # Update existing rows
                cursor.execute("UPDATE orders SET payment_status = 'unpaid' WHERE payment_status IS NULL")
                print("✓ Added payment_status column")
            else:
                print("✓ payment_status column already exists")
            
            if 'paid_amount' not in columns:
                print("Adding paid_amount column...")
                cursor.execute("ALTER TABLE orders ADD COLUMN paid_amount NUMERIC(10, 2) DEFAULT 0")
                # Update existing rows
                cursor.execute("UPDATE orders SET paid_amount = 0 WHERE paid_amount IS NULL")
                print("✓ Added paid_amount column")
            else:
                print("✓ paid_amount column already exists")
            
            conn.commit()
            print("\n✓ Database migration completed successfully!")
            
        except Exception as e:
            conn.rollback()
            print(f"\n✗ Migration failed: {str(e)}")
        finally:
            conn.close()

if __name__ == '__main__':
    print("Running database migration...")
    migrate_database()

>>>>>>> 966fed7 (initial push)
