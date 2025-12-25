import pandas as pd
from flask import Flask
from config import USE_GOOGLE_SHEETS
from decimal import Decimal
from datetime import datetime, date
import os
import sys
import time

# Import appropriate models based on configuration
if USE_GOOGLE_SHEETS:
    from gs_models import db, Variety, Shop, Order, session as db_session
    from google_sheets import get_gs_db
    print("📊 Using Google Sheets for import")
else:
    from models import db, Variety, Shop, Order
    db_session = None
    print("💾 Using SQLite for import")

# Initialize Flask app with same config as main app
app = Flask(__name__)

if USE_GOOGLE_SHEETS:
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brownie_sales.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()

def import_from_excel(excel_file_path):
    """Import data from Excel file into database"""
    
    with app.app_context():
        # Delete all existing orders before importing
        print("\n=== Deleting All Existing Orders ===")
        if USE_GOOGLE_SHEETS:
            existing_orders_count = Order.query.count()
            if existing_orders_count > 0:
                gs = get_gs_db()
                gs.delete_all_orders()
                print(f"  ✓ Deleted {existing_orders_count} existing order(s)")
            else:
                print("  ✓ No existing orders to delete")
        else:
            existing_orders_count = Order.query.count()
            if existing_orders_count > 0:
                Order.query.delete()
                db.session.commit()
                print(f"  ✓ Deleted {existing_orders_count} existing order(s)")
            else:
                print("  ✓ No existing orders to delete")
        
        # Read Excel file
        print(f"\nReading Excel file: {excel_file_path}")
        excel_file = pd.ExcelFile(excel_file_path)
        
        print(f"Found sheets: {excel_file.sheet_names}")
        
        imported_counts = {
            'varieties': 0,
            'shops': 0,
            'orders': 0,
            'errors': []
        }
        
        # First, ensure there's at least a default variety (Classic Brownie)
        default_variety = Variety.query.filter_by(name='Classic Brownie').first()
        if not default_variety:
            default_variety = Variety(name='Classic Brownie', default_price=Decimal('25.00'))
            if USE_GOOGLE_SHEETS:
                gs = get_gs_db()
                gs.add_variety('Classic Brownie', Decimal('25.00'))
                # Reload to get the ID
                varieties = gs.get_varieties()
                default_variety = next((v for v in varieties if v['name'] == 'Classic Brownie'), None)
                if default_variety:
                    default_variety = Variety(id=default_variety['id'], name='Classic Brownie', default_price=Decimal('25.00'))
            else:
                db.session.add(default_variety)
                db.session.commit()
            imported_counts['varieties'] += 1
            print("✓ Created default variety: Classic Brownie")
        
        if USE_GOOGLE_SHEETS and isinstance(default_variety, dict):
            default_variety_id = default_variety['id']
        else:
            default_variety_id = default_variety.id if default_variety else None
        
        # Helper function to find shop case-insensitively
        def find_shop_case_insensitive(shop_name):
            """Find shop by name (case-insensitive)"""
            shops = Shop.query.all()
            for s in shops:
                if s.name.lower() == shop_name.lower():
                    return s
            return None
        
        # Before importing, merge existing duplicate shops (case-insensitive)
        print("\n=== Checking for duplicate shops (case-insensitive) ===")
        all_existing_shops = Shop.query.all()
        shop_name_map = {}  # lowercase -> Shop object
        shops_to_delete = []
        
        for shop in all_existing_shops:
            shop_lower = shop.name.lower()
            if shop_lower in shop_name_map:
                # Found duplicate - merge orders from duplicate to the first one
                duplicate_shop = shop_name_map[shop_lower]
                print(f"  ⚠ Found duplicate: '{duplicate_shop.name}' and '{shop.name}' (case-insensitive match)")
                
                # Update all orders from duplicate shop to use the first shop
                if USE_GOOGLE_SHEETS:
                    gs = get_gs_db()
                    orders = gs.get_orders()
                    orders_to_update = [o for o in orders if o['shop_id'] == shop.id]
                    if orders_to_update:
                        print(f"    → Merging {len(orders_to_update)} orders from '{shop.name}' to '{duplicate_shop.name}'")
                        for order_data in orders_to_update:
                            gs.update_order(
                                order_data['id'],
                                order_data['variety_id'],
                                duplicate_shop.id,
                                order_data['quantity'],
                                order_data['price'],
                                order_data['delivery_date'],
                                order_data['payment_status'],
                                order_data['paid_amount']
                            )
                else:
                    orders_to_update = Order.query.filter_by(shop_id=shop.id).all()
                    if orders_to_update:
                        print(f"    → Merging {len(orders_to_update)} orders from '{shop.name}' to '{duplicate_shop.name}'")
                        for order in orders_to_update:
                            order.shop_id = duplicate_shop.id
                
                shops_to_delete.append(shop)
            else:
                shop_name_map[shop_lower] = shop
        
        # Delete duplicate shops
        for shop in shops_to_delete:
            if USE_GOOGLE_SHEETS:
                gs = get_gs_db()
                gs.delete_shop(shop.id)
                print(f"    ✓ Deleted duplicate shop: '{shop.name}'")
            else:
                db.session.delete(shop)
                print(f"    ✓ Deleted duplicate shop: '{shop.name}'")
        
        if shops_to_delete:
            if not USE_GOOGLE_SHEETS:
                db.session.commit()
            print(f"  ✓ Merged {len(shops_to_delete)} duplicate shop(s)")
        else:
            print("  ✓ No duplicate shops found")
        
        # Check if there's a Varieties sheet
        if 'Varieties' in excel_file.sheet_names:
            print("\n=== Importing Varieties ===")
            df_varieties = pd.read_excel(excel_file, sheet_name='Varieties')
            
            if not df_varieties.empty:
                print(f"Columns found: {list(df_varieties.columns)}")
                name_col = None
                price_col = None
                
                for col in df_varieties.columns:
                    col_lower = str(col).lower()
                    if 'name' in col_lower:
                        name_col = col
                    if 'price' in col_lower and ('default' in col_lower or price_col is None):
                        price_col = col
                
                if name_col and price_col:
                    for idx, row in df_varieties.iterrows():
                        try:
                            name = str(row[name_col]).strip()
                            price = float(row[price_col])
                            if pd.notna(name) and name != 'nan' and price > 0:
                                existing = Variety.query.filter_by(name=name).first()
                                if not existing:
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_variety(name, Decimal(str(price)))
                                    else:
                                        variety = Variety(name=name, default_price=Decimal(str(price)))
                                        db.session.add(variety)
                                    imported_counts['varieties'] += 1
                                    print(f"  ✓ Added variety: {name} (₹{price:.2f})")
                                else:
                                    print(f"  - Skipped (exists): {name}")
                        except Exception as e:
                            error_msg = f"Variety row {idx+2}: {str(e)}"
                            imported_counts['errors'].append(error_msg)
                            print(f"  ✗ Error: {error_msg}")
                
                if not USE_GOOGLE_SHEETS:
                    db.session.commit()
        
        # Check if there's a Shops sheet
        if 'Shops' in excel_file.sheet_names:
            print("\n=== Importing Shops ===")
            df_shops = pd.read_excel(excel_file, sheet_name='Shops')
            
            if not df_shops.empty:
                print(f"Columns found: {list(df_shops.columns)}")
                name_col = None
                for col in df_shops.columns:
                    if 'name' in str(col).lower():
                        name_col = col
                        break
                
                if name_col:
                    for idx, row in df_shops.iterrows():
                        try:
                            name = str(row[name_col]).strip()
                            if pd.notna(name) and name != 'nan':
                                existing = find_shop_case_insensitive(name)
                                if not existing:
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_shop(name)
                                    else:
                                        shop = Shop(name=name)
                                        db.session.add(shop)
                                    imported_counts['shops'] += 1
                                    print(f"  ✓ Added shop: {name}")
                                else:
                                    # Merge: update existing shop name to the one from Excel (preserve first occurrence)
                                    print(f"  - Shop exists (case-insensitive): '{existing.name}' (keeping existing name)")
                        except Exception as e:
                            error_msg = f"Shop row {idx+2}: {str(e)}"
                            imported_counts['errors'].append(error_msg)
                            print(f"  ✗ Error: {error_msg}")
                    
                    if not USE_GOOGLE_SHEETS:
                        db.session.commit()
        
        # Import Orders from the main sheet (handle your actual format)
        print("\n=== Importing Orders ===")
        # Try to find the orders sheet - could be 'Orders', first sheet, or any sheet with Date column
        orders_df = None
        orders_sheet_name = None
        
        # First check for explicit Orders sheet
        if 'Orders' in excel_file.sheet_names:
            orders_df = pd.read_excel(excel_file, sheet_name='Orders')
            orders_sheet_name = 'Orders'
        else:
            # Check each sheet for Date column (indicating it's an orders sheet)
            for sheet_name in excel_file.sheet_names:
                df_check = pd.read_excel(excel_file, sheet_name=sheet_name)
                if 'Date' in df_check.columns or 'date' in [c.lower() for c in df_check.columns]:
                    orders_df = df_check
                    orders_sheet_name = sheet_name
                    break
        
        # If still no orders sheet found, use first sheet
        if orders_df is None and len(excel_file.sheet_names) > 0:
            orders_df = pd.read_excel(excel_file, sheet_name=0)
            orders_sheet_name = excel_file.sheet_names[0]
        
        if orders_df is not None and not orders_df.empty:
            print(f"Using sheet: {orders_sheet_name}")
            print(f"Columns found: {list(orders_df.columns)}")
            
            # Map columns (case insensitive, flexible matching)
            col_map = {}
            for col in orders_df.columns:
                col_lower = str(col).lower().strip()
                if 'date' in col_lower:
                    col_map['date'] = col
                elif 'shop' in col_lower and 'name' in col_lower:
                    col_map['shop'] = col
                elif 'shop' in col_lower:
                    col_map['shop'] = col
                elif 'pieces' in col_lower or 'quantity' in col_lower or 'qty' in col_lower:
                    col_map['quantity'] = col
                elif ('price' in col_lower and 'piec' in col_lower) or 'price/piec' in col_lower:
                    col_map['price_per_piece'] = col
                elif 'price' in col_lower and 'piec' not in col_lower:
                    col_map['total_price'] = col
                elif 'variety' in col_lower:
                    col_map['variety'] = col
                elif 'paid or not' in col_lower or ('paid' in col_lower and 'not' in col_lower):
                    col_map['paid_or_not'] = col
                elif 'temp paid' in col_lower or ('temp' in col_lower and 'paid' in col_lower):
                    col_map['temp_paid'] = col
                elif 'paid' in col_lower and 'amount' in col_lower:
                    col_map['paid_amount'] = col
            
            print(f"Mapped columns: {col_map}")
            
            if 'date' in col_map and 'shop' in col_map:
                # Get all varieties for lookup
                all_varieties = {v.name.lower(): v for v in Variety.query.all()}
                
                for idx, row in orders_df.iterrows():
                    try:
                        # Parse date (handle mixed formats)
                        date_val = row[col_map['date']]
                        if pd.isna(date_val):
                            continue
                        
                        # Try parsing the date (Excel format: dd-mm-yyyy)
                        delivery_date = None
                        try:
                            # If it's already a datetime/date object from pandas
                            if hasattr(date_val, 'date') and not isinstance(date_val, str):
                                delivery_date = date_val.date()
                            elif isinstance(date_val, str):
                                # Handle DD-MM-YYYY format explicitly (e.g., "21-2-2025", "25-2-2025")
                                date_str = str(date_val).strip()
                                # Try parsing as dd-mm-yyyy first (dayfirst=True interprets dd-mm-yyyy)
                                delivery_date = pd.to_datetime(date_str, dayfirst=True).date()
                            else:
                                # Numeric or other formats - pandas Excel reader handles these
                                delivery_date = pd.to_datetime(date_val, dayfirst=True).date()
                        except Exception as e:
                            print(f"  ✗ Could not parse date: {date_val} (Error: {str(e)})")
                            continue
                        
                        # Get shop name
                        shop_name = str(row[col_map['shop']]).strip()
                        if pd.isna(shop_name) or shop_name == 'nan':
                            continue
                        
                        # Find or create shop (case-insensitive matching)
                        shop = find_shop_case_insensitive(shop_name)
                        if not shop:
                            if USE_GOOGLE_SHEETS:
                                gs = get_gs_db()
                                gs.add_shop(shop_name)
                                # Reload to get the ID
                                shops = gs.get_shops()
                                shop_data = next((s for s in shops if s['name'].lower() == shop_name.lower()), None)
                                if shop_data:
                                    shop = Shop(id=shop_data['id'], name=shop_data['name'])
                                else:
                                    print(f"  ✗ Failed to create shop: {shop_name}")
                                    continue
                            else:
                                shop = Shop(name=shop_name)
                                db.session.add(shop)
                                db.session.flush()  # Get the ID
                            imported_counts['shops'] += 1
                            print(f"  ✓ Created shop: {shop_name}")
                        else:
                            # Use existing shop (case-insensitive match found)
                            if shop.name != shop_name:
                                print(f"  - Using existing shop: '{shop.name}' (matched '{shop_name}')")
                        
                        # Get quantity (pieces)
                        quantity = None
                        if 'quantity' in col_map:
                            qty_val = row[col_map['quantity']]
                            if pd.notna(qty_val):
                                quantity = int(float(qty_val))
                        
                        # Get price
                        price = None
                        if 'price_per_piece' in col_map:
                            # Use price per piece * quantity
                            price_per_piece_val = row[col_map['price_per_piece']]
                            if pd.notna(price_per_piece_val) and quantity:
                                price = Decimal(str(float(price_per_piece_val)))
                        elif 'total_price' in col_map:
                            # Use total price directly
                            total_price_val = row[col_map['total_price']]
                            if pd.notna(total_price_val):
                                total_price = float(total_price_val)
                                if quantity and quantity > 0:
                                    price = Decimal(str(total_price / quantity))
                                else:
                                    price = Decimal(str(total_price))
                        
                        # Get variety if specified, otherwise use default (Classic Brownie)
                        variety_id = default_variety_id
                        if 'variety' in col_map:
                            variety_name = str(row[col_map['variety']]).strip()
                            if pd.notna(variety_name) and variety_name != 'nan' and variety_name != '':
                                variety_lower = variety_name.lower()
                                if variety_lower in all_varieties:
                                    variety_id = all_varieties[variety_lower].id
                                else:
                                    # Create new variety if needed
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_variety(variety_name, price if price else Decimal('25.00'))
                                        # Reload to get the ID
                                        varieties = gs.get_varieties()
                                        variety_data = next((v for v in varieties if v['name'].lower() == variety_lower), None)
                                        if variety_data:
                                            variety_id = variety_data['id']
                                            all_varieties[variety_lower] = Variety(
                                                id=variety_data['id'],
                                                name=variety_data['name'],
                                                default_price=variety_data['default_price']
                                            )
                                    else:
                                        new_variety = Variety(name=variety_name, default_price=price if price else Decimal('25.00'))
                                        db.session.add(new_variety)
                                        db.session.flush()
                                        variety_id = new_variety.id
                                        all_varieties[variety_lower] = new_variety
                                    imported_counts['varieties'] += 1
                                    print(f"  ✓ Created variety: {variety_name}")
                        # If variety column is empty or not found, use default (Classic Brownie)
                        
                        # Get payment status (default: unpaid)
                        payment_status = 'unpaid'
                        paid_amount = Decimal('0.00')
                        total_amount = price * quantity if quantity and price else Decimal('0.00')
                        
                        # Handle 'Paid or not' column
                        # If value is "yes", then paid. Otherwise, not paid.
                        if 'paid_or_not' in col_map:
                            paid_or_not_val = str(row[col_map['paid_or_not']]).strip()
                            if pd.notna(paid_or_not_val) and paid_or_not_val != 'nan' and paid_or_not_val != '':
                                paid_or_not_lower = paid_or_not_val.lower()
                                if paid_or_not_lower == 'yes':
                                    payment_status = 'paid'
                                    paid_amount = total_amount
                                else:
                                    payment_status = 'unpaid'
                                    paid_amount = Decimal('0.00')
                        
                        # Handle 'Temp Paid' column (partial payment)
                        if 'temp_paid' in col_map:
                            temp_paid_val = row[col_map['temp_paid']]
                            if pd.notna(temp_paid_val):
                                try:
                                    temp_paid_amount = Decimal(str(float(temp_paid_val)))
                                    if temp_paid_amount > 0:
                                        payment_status = 'partial'
                                        paid_amount = temp_paid_amount
                                        # If temp paid equals or exceeds total, mark as fully paid
                                        if temp_paid_amount >= total_amount:
                                            payment_status = 'paid'
                                            paid_amount = total_amount
                                except (ValueError, TypeError):
                                    pass
                        
                        # Handle 'Paid Amount' column (if exists, takes precedence over temp_paid)
                        if 'paid_amount' in col_map:
                            paid_amt_val = row[col_map['paid_amount']]
                            if pd.notna(paid_amt_val):
                                try:
                                    paid_amount = Decimal(str(float(paid_amt_val)))
                                    if paid_amount >= total_amount:
                                        payment_status = 'paid'
                                        paid_amount = total_amount
                                    elif paid_amount > 0:
                                        payment_status = 'partial'
                                    else:
                                        payment_status = 'unpaid'
                                        paid_amount = Decimal('0.00')
                                except (ValueError, TypeError):
                                    pass
                        
                        # If 'Paid or not' says paid but no amount specified, assume full payment
                        if payment_status == 'paid' and paid_amount == Decimal('0.00') and total_amount > 0:
                            paid_amount = total_amount
                        
                        # Only create order if we have valid data
                        if quantity and quantity > 0 and price and price > 0:
                            if USE_GOOGLE_SHEETS:
                                gs = get_gs_db()
                                # Add small delay to avoid rate limiting when importing many orders
                                if imported_counts['orders'] > 0 and imported_counts['orders'] % 10 == 0:
                                    time.sleep(0.5)  # Small delay every 10 orders
                                gs.add_order(
                                    variety_id,
                                    shop.id,
                                    quantity,
                                    price,
                                    delivery_date,
                                    payment_status,
                                    paid_amount
                                )
                            else:
                                order = Order(
                                    variety_id=variety_id,
                                    shop_id=shop.id,
                                    quantity=quantity,
                                    price=price,
                                    delivery_date=delivery_date,
                                    payment_status=payment_status,
                                    paid_amount=paid_amount
                                )
                                db.session.add(order)
                            
                            imported_counts['orders'] += 1
                            variety_obj = Variety.query.get(variety_id) if not USE_GOOGLE_SHEETS else next((v for v in all_varieties.values() if v.id == variety_id), None)
                            variety_name_display = variety_obj.name if variety_obj else 'Unknown'
                            print(f"  ✓ Added order: {shop_name} - {variety_name_display} x{quantity} @ ₹{price} on {delivery_date} (Status: {payment_status}, Paid: ₹{paid_amount:.2f})")
                        else:
                            print(f"  - Skipped row {idx+2}: invalid quantity or price")
                    
                    except Exception as e:
                        error_msg = f"Order row {idx+2}: {str(e)}"
                        imported_counts['errors'].append(error_msg)
                        print(f"  ✗ Error: {error_msg}")
                        import traceback
                        traceback.print_exc()
            else:
                print(f"  ✗ Missing required columns (Date, Shop name). Found: {list(orders_df.columns)}")
        else:
            print("  ✗ No orders sheet found")
        
        # Commit all changes (only for SQLite)
        if not USE_GOOGLE_SHEETS:
            db.session.commit()
        
        # Print summary
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        print(f"✓ Varieties imported: {imported_counts['varieties']}")
        print(f"✓ Shops imported: {imported_counts['shops']}")
        print(f"✓ Orders imported: {imported_counts['orders']}")
        if imported_counts['errors']:
            print(f"\n⚠ Errors encountered: {len(imported_counts['errors'])}")
            for error in imported_counts['errors'][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(imported_counts['errors']) > 10:
                print(f"  ... and {len(imported_counts['errors']) - 10} more errors")
        print("="*60)
        
        return imported_counts

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("="*60)
        print("Excel Import Script for Brownie Sales Tracker")
        print("="*60)
        print("\nUsage: python import_excel.py <path_to_excel_file.xlsx>")
        print("\nExample:")
        print("  python import_excel.py sales_data.xlsx")
        print("  python import_excel.py \"C:/Users/username/Downloads/my_data.xlsx\"")
        print("\nExpected Excel Format:")
        print("  - Sheet with Date, Shop name, Pieces, Price/Piec columns")
        print("  - Optional 'Varieties' sheet with Name and Price columns")
        print("  - Optional 'Shops' sheet with Name column")
        print(f"\nCurrent mode: {'Google Sheets' if USE_GOOGLE_SHEETS else 'SQLite'}")
        print("="*60)
        sys.exit(1)
    
    excel_path = sys.argv[1]
    
    if not os.path.exists(excel_path):
        print(f"✗ Error: File not found: {excel_path}")
        sys.exit(1)
    
    if not excel_path.lower().endswith(('.xlsx', '.xls')):
        print(f"✗ Error: File must be .xlsx or .xls format")
        sys.exit(1)
    
    try:
        print("\nStarting import process...\n")
        import_from_excel(excel_path)
        print("\n✓ Import completed successfully!")
    except Exception as e:
        print(f"\n✗ Import failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    """Import data from Excel file into database"""
    
    with app.app_context():
        # Delete all existing orders before importing
        print("\n=== Deleting All Existing Orders ===")
        if USE_GOOGLE_SHEETS:
            existing_orders_count = Order.query.count()
            if existing_orders_count > 0:
                gs = get_gs_db()
                gs.delete_all_orders()
                print(f"  ✓ Deleted {existing_orders_count} existing order(s)")
            else:
                print("  ✓ No existing orders to delete")
        else:
            existing_orders_count = Order.query.count()
            if existing_orders_count > 0:
                Order.query.delete()
                db.session.commit()
                print(f"  ✓ Deleted {existing_orders_count} existing order(s)")
            else:
                print("  ✓ No existing orders to delete")
        
        # Read Excel file
        print(f"\nReading Excel file: {excel_file_path}")
        excel_file = pd.ExcelFile(excel_file_path)
        
        print(f"Found sheets: {excel_file.sheet_names}")
        
        imported_counts = {
            'varieties': 0,
            'shops': 0,
            'orders': 0,
            'errors': []
        }
        
        # First, ensure there's at least a default variety (Classic Brownie)
        default_variety = Variety.query.filter_by(name='Classic Brownie').first()
        if not default_variety:
            default_variety = Variety(name='Classic Brownie', default_price=Decimal('25.00'))
            if USE_GOOGLE_SHEETS:
                gs = get_gs_db()
                gs.add_variety('Classic Brownie', Decimal('25.00'))
                # Reload to get the ID
                varieties = gs.get_varieties()
                default_variety = next((v for v in varieties if v['name'] == 'Classic Brownie'), None)
                if default_variety:
                    default_variety = Variety(id=default_variety['id'], name='Classic Brownie', default_price=Decimal('25.00'))
            else:
                db.session.add(default_variety)
                db.session.commit()
            imported_counts['varieties'] += 1
            print("✓ Created default variety: Classic Brownie")
        
        if USE_GOOGLE_SHEETS and isinstance(default_variety, dict):
            default_variety_id = default_variety['id']
        else:
            default_variety_id = default_variety.id if default_variety else None
        
        # Helper function to find shop case-insensitively
        def find_shop_case_insensitive(shop_name):
            """Find shop by name (case-insensitive)"""
            shops = Shop.query.all()
            for s in shops:
                if s.name.lower() == shop_name.lower():
                    return s
            return None
        
        # Before importing, merge existing duplicate shops (case-insensitive)
        print("\n=== Checking for duplicate shops (case-insensitive) ===")
        all_existing_shops = Shop.query.all()
        shop_name_map = {}  # lowercase -> Shop object
        shops_to_delete = []
        
        for shop in all_existing_shops:
            shop_lower = shop.name.lower()
            if shop_lower in shop_name_map:
                # Found duplicate - merge orders from duplicate to the first one
                duplicate_shop = shop_name_map[shop_lower]
                print(f"  ⚠ Found duplicate: '{duplicate_shop.name}' and '{shop.name}' (case-insensitive match)")
                
                # Update all orders from duplicate shop to use the first shop
                if USE_GOOGLE_SHEETS:
                    gs = get_gs_db()
                    orders = gs.get_orders()
                    orders_to_update = [o for o in orders if o['shop_id'] == shop.id]
                    if orders_to_update:
                        print(f"    → Merging {len(orders_to_update)} orders from '{shop.name}' to '{duplicate_shop.name}'")
                        for order_data in orders_to_update:
                            gs.update_order(
                                order_data['id'],
                                order_data['variety_id'],
                                duplicate_shop.id,
                                order_data['quantity'],
                                order_data['price'],
                                order_data['delivery_date'],
                                order_data['payment_status'],
                                order_data['paid_amount']
                            )
                else:
                    orders_to_update = Order.query.filter_by(shop_id=shop.id).all()
                    if orders_to_update:
                        print(f"    → Merging {len(orders_to_update)} orders from '{shop.name}' to '{duplicate_shop.name}'")
                        for order in orders_to_update:
                            order.shop_id = duplicate_shop.id
                
                shops_to_delete.append(shop)
            else:
                shop_name_map[shop_lower] = shop
        
        # Delete duplicate shops
        for shop in shops_to_delete:
            if USE_GOOGLE_SHEETS:
                gs = get_gs_db()
                gs.delete_shop(shop.id)
                print(f"    ✓ Deleted duplicate shop: '{shop.name}'")
            else:
                db.session.delete(shop)
                print(f"    ✓ Deleted duplicate shop: '{shop.name}'")
        
        if shops_to_delete:
            if not USE_GOOGLE_SHEETS:
                db.session.commit()
            print(f"  ✓ Merged {len(shops_to_delete)} duplicate shop(s)")
        else:
            print("  ✓ No duplicate shops found")
        
        # Check if there's a Varieties sheet
        if 'Varieties' in excel_file.sheet_names:
            print("\n=== Importing Varieties ===")
            df_varieties = pd.read_excel(excel_file, sheet_name='Varieties')
            
            if not df_varieties.empty:
                print(f"Columns found: {list(df_varieties.columns)}")
                name_col = None
                price_col = None
                
                for col in df_varieties.columns:
                    col_lower = str(col).lower()
                    if 'name' in col_lower:
                        name_col = col
                    if 'price' in col_lower and ('default' in col_lower or price_col is None):
                        price_col = col
                
                if name_col and price_col:
                    for idx, row in df_varieties.iterrows():
                        try:
                            name = str(row[name_col]).strip()
                            price = float(row[price_col])
                            if pd.notna(name) and name != 'nan' and price > 0:
                                existing = Variety.query.filter_by(name=name).first()
                                if not existing:
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_variety(name, Decimal(str(price)))
                                    else:
                                        variety = Variety(name=name, default_price=Decimal(str(price)))
                                        db.session.add(variety)
                                    imported_counts['varieties'] += 1
                                    print(f"  ✓ Added variety: {name} (₹{price:.2f})")
                                else:
                                    print(f"  - Skipped (exists): {name}")
                        except Exception as e:
                            error_msg = f"Variety row {idx+2}: {str(e)}"
                            imported_counts['errors'].append(error_msg)
                            print(f"  ✗ Error: {error_msg}")
                
                if not USE_GOOGLE_SHEETS:
                    db.session.commit()
        
        # Check if there's a Shops sheet
        if 'Shops' in excel_file.sheet_names:
            print("\n=== Importing Shops ===")
            df_shops = pd.read_excel(excel_file, sheet_name='Shops')
            
            if not df_shops.empty:
                print(f"Columns found: {list(df_shops.columns)}")
                name_col = None
                for col in df_shops.columns:
                    if 'name' in str(col).lower():
                        name_col = col
                        break
                
                if name_col:
                    for idx, row in df_shops.iterrows():
                        try:
                            name = str(row[name_col]).strip()
                            if pd.notna(name) and name != 'nan':
                                existing = find_shop_case_insensitive(name)
                                if not existing:
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_shop(name)
                                    else:
                                        shop = Shop(name=name)
                                        db.session.add(shop)
                                    imported_counts['shops'] += 1
                                    print(f"  ✓ Added shop: {name}")
                                else:
                                    # Merge: update existing shop name to the one from Excel (preserve first occurrence)
                                    print(f"  - Shop exists (case-insensitive): '{existing.name}' (keeping existing name)")
                        except Exception as e:
                            error_msg = f"Shop row {idx+2}: {str(e)}"
                            imported_counts['errors'].append(error_msg)
                            print(f"  ✗ Error: {error_msg}")
                    
                    if not USE_GOOGLE_SHEETS:
                        db.session.commit()
        
        # Import Orders from the main sheet (handle your actual format)
        print("\n=== Importing Orders ===")
        # Try to find the orders sheet - could be 'Orders', first sheet, or any sheet with Date column
        orders_df = None
        orders_sheet_name = None
        
        # First check for explicit Orders sheet
        if 'Orders' in excel_file.sheet_names:
            orders_df = pd.read_excel(excel_file, sheet_name='Orders')
            orders_sheet_name = 'Orders'
        else:
            # Check each sheet for Date column (indicating it's an orders sheet)
            for sheet_name in excel_file.sheet_names:
                df_check = pd.read_excel(excel_file, sheet_name=sheet_name)
                if 'Date' in df_check.columns or 'date' in [c.lower() for c in df_check.columns]:
                    orders_df = df_check
                    orders_sheet_name = sheet_name
                    break
        
        # If still no orders sheet found, use first sheet
        if orders_df is None and len(excel_file.sheet_names) > 0:
            orders_df = pd.read_excel(excel_file, sheet_name=0)
            orders_sheet_name = excel_file.sheet_names[0]
        
        if orders_df is not None and not orders_df.empty:
            print(f"Using sheet: {orders_sheet_name}")
            print(f"Columns found: {list(orders_df.columns)}")
            
            # Map columns (case insensitive, flexible matching)
            col_map = {}
            for col in orders_df.columns:
                col_lower = str(col).lower().strip()
                if 'date' in col_lower:
                    col_map['date'] = col
                elif 'shop' in col_lower and 'name' in col_lower:
                    col_map['shop'] = col
                elif 'shop' in col_lower:
                    col_map['shop'] = col
                elif 'pieces' in col_lower or 'quantity' in col_lower or 'qty' in col_lower:
                    col_map['quantity'] = col
                elif ('price' in col_lower and 'piec' in col_lower) or 'price/piec' in col_lower:
                    col_map['price_per_piece'] = col
                elif 'price' in col_lower and 'piec' not in col_lower:
                    col_map['total_price'] = col
                elif 'variety' in col_lower:
                    col_map['variety'] = col
                elif 'paid or not' in col_lower or ('paid' in col_lower and 'not' in col_lower):
                    col_map['paid_or_not'] = col
                elif 'temp paid' in col_lower or ('temp' in col_lower and 'paid' in col_lower):
                    col_map['temp_paid'] = col
                elif 'paid' in col_lower and 'amount' in col_lower:
                    col_map['paid_amount'] = col
            
            print(f"Mapped columns: {col_map}")
            
            if 'date' in col_map and 'shop' in col_map:
                # Get all varieties for lookup
                all_varieties = {v.name.lower(): v for v in Variety.query.all()}
                
                for idx, row in orders_df.iterrows():
                    try:
                        # Parse date (handle mixed formats)
                        date_val = row[col_map['date']]
                        if pd.isna(date_val):
                            continue
                        
                        # Try parsing the date (Excel format: dd-mm-yyyy)
                        delivery_date = None
                        try:
                            # If it's already a datetime/date object from pandas
                            if hasattr(date_val, 'date') and not isinstance(date_val, str):
                                delivery_date = date_val.date()
                            elif isinstance(date_val, str):
                                # Handle DD-MM-YYYY format explicitly (e.g., "21-2-2025", "25-2-2025")
                                date_str = str(date_val).strip()
                                # Try parsing as dd-mm-yyyy first (dayfirst=True interprets dd-mm-yyyy)
                                delivery_date = pd.to_datetime(date_str, dayfirst=True).date()
                            else:
                                # Numeric or other formats - pandas Excel reader handles these
                                delivery_date = pd.to_datetime(date_val, dayfirst=True).date()
                        except Exception as e:
                            print(f"  ✗ Could not parse date: {date_val} (Error: {str(e)})")
                            continue
                        
                        # Get shop name
                        shop_name = str(row[col_map['shop']]).strip()
                        if pd.isna(shop_name) or shop_name == 'nan':
                            continue
                        
                        # Find or create shop (case-insensitive matching)
                        shop = find_shop_case_insensitive(shop_name)
                        if not shop:
                            if USE_GOOGLE_SHEETS:
                                gs = get_gs_db()
                                gs.add_shop(shop_name)
                                # Reload to get the ID
                                shops = gs.get_shops()
                                shop_data = next((s for s in shops if s['name'].lower() == shop_name.lower()), None)
                                if shop_data:
                                    shop = Shop(id=shop_data['id'], name=shop_data['name'])
                                else:
                                    print(f"  ✗ Failed to create shop: {shop_name}")
                                    continue
                            else:
                                shop = Shop(name=shop_name)
                                db.session.add(shop)
                                db.session.flush()  # Get the ID
                            imported_counts['shops'] += 1
                            print(f"  ✓ Created shop: {shop_name}")
                        else:
                            # Use existing shop (case-insensitive match found)
                            if shop.name != shop_name:
                                print(f"  - Using existing shop: '{shop.name}' (matched '{shop_name}')")
                        
                        # Get quantity (pieces)
                        quantity = None
                        if 'quantity' in col_map:
                            qty_val = row[col_map['quantity']]
                            if pd.notna(qty_val):
                                quantity = int(float(qty_val))
                        
                        # Get price
                        price = None
                        if 'price_per_piece' in col_map:
                            # Use price per piece * quantity
                            price_per_piece_val = row[col_map['price_per_piece']]
                            if pd.notna(price_per_piece_val) and quantity:
                                price = Decimal(str(float(price_per_piece_val)))
                        elif 'total_price' in col_map:
                            # Use total price directly
                            total_price_val = row[col_map['total_price']]
                            if pd.notna(total_price_val):
                                total_price = float(total_price_val)
                                if quantity and quantity > 0:
                                    price = Decimal(str(total_price / quantity))
                                else:
                                    price = Decimal(str(total_price))
                        
                        # Get variety if specified, otherwise use default (Classic Brownie)
                        variety_id = default_variety_id
                        if 'variety' in col_map:
                            variety_name = str(row[col_map['variety']]).strip()
                            if pd.notna(variety_name) and variety_name != 'nan' and variety_name != '':
                                variety_lower = variety_name.lower()
                                if variety_lower in all_varieties:
                                    variety_id = all_varieties[variety_lower].id
                                else:
                                    # Create new variety if needed
                                    if USE_GOOGLE_SHEETS:
                                        gs = get_gs_db()
                                        gs.add_variety(variety_name, price if price else Decimal('25.00'))
                                        # Reload to get the ID
                                        varieties = gs.get_varieties()
                                        variety_data = next((v for v in varieties if v['name'].lower() == variety_lower), None)
                                        if variety_data:
                                            variety_id = variety_data['id']
                                            all_varieties[variety_lower] = Variety(
                                                id=variety_data['id'],
                                                name=variety_data['name'],
                                                default_price=variety_data['default_price']
                                            )
                                    else:
                                        new_variety = Variety(name=variety_name, default_price=price if price else Decimal('25.00'))
                                        db.session.add(new_variety)
                                        db.session.flush()
                                        variety_id = new_variety.id
                                        all_varieties[variety_lower] = new_variety
                                    imported_counts['varieties'] += 1
                                    print(f"  ✓ Created variety: {variety_name}")
                        # If variety column is empty or not found, use default (Classic Brownie)
                        
                        # Get payment status (default: unpaid)
                        payment_status = 'unpaid'
                        paid_amount = Decimal('0.00')
                        total_amount = price * quantity if quantity and price else Decimal('0.00')
                        
                        # Handle 'Paid or not' column
                        # If value is "yes", then paid. Otherwise, not paid.
                        if 'paid_or_not' in col_map:
                            paid_or_not_val = str(row[col_map['paid_or_not']]).strip()
                            if pd.notna(paid_or_not_val) and paid_or_not_val != 'nan' and paid_or_not_val != '':
                                paid_or_not_lower = paid_or_not_val.lower()
                                if paid_or_not_lower == 'yes':
                                    payment_status = 'paid'
                                    paid_amount = total_amount
                                else:
                                    payment_status = 'unpaid'
                                    paid_amount = Decimal('0.00')
                        
                        # Handle 'Temp Paid' column (partial payment)
                        if 'temp_paid' in col_map:
                            temp_paid_val = row[col_map['temp_paid']]
                            if pd.notna(temp_paid_val):
                                try:
                                    temp_paid_amount = Decimal(str(float(temp_paid_val)))
                                    if temp_paid_amount > 0:
                                        payment_status = 'partial'
                                        paid_amount = temp_paid_amount
                                        # If temp paid equals or exceeds total, mark as fully paid
                                        if temp_paid_amount >= total_amount:
                                            payment_status = 'paid'
                                            paid_amount = total_amount
                                except (ValueError, TypeError):
                                    pass
                        
                        # Handle 'Paid Amount' column (if exists, takes precedence over temp_paid)
                        if 'paid_amount' in col_map:
                            paid_amt_val = row[col_map['paid_amount']]
                            if pd.notna(paid_amt_val):
                                try:
                                    paid_amount = Decimal(str(float(paid_amt_val)))
                                    if paid_amount >= total_amount:
                                        payment_status = 'paid'
                                        paid_amount = total_amount
                                    elif paid_amount > 0:
                                        payment_status = 'partial'
                                    else:
                                        payment_status = 'unpaid'
                                        paid_amount = Decimal('0.00')
                                except (ValueError, TypeError):
                                    pass
                        
                        # If 'Paid or not' says paid but no amount specified, assume full payment
                        if payment_status == 'paid' and paid_amount == Decimal('0.00') and total_amount > 0:
                            paid_amount = total_amount
                        
                        # Only create order if we have valid data
                        if quantity and quantity > 0 and price and price > 0:
                            if USE_GOOGLE_SHEETS:
                                gs = get_gs_db()
                                # Add small delay to avoid rate limiting when importing many orders
                                if imported_counts['orders'] > 0 and imported_counts['orders'] % 10 == 0:
                                    time.sleep(0.5)  # Small delay every 10 orders
                                gs.add_order(
                                    variety_id,
                                    shop.id,
                                    quantity,
                                    price,
                                    delivery_date,
                                    payment_status,
                                    paid_amount
                                )
                            else:
                                order = Order(
                                    variety_id=variety_id,
                                    shop_id=shop.id,
                                    quantity=quantity,
                                    price=price,
                                    delivery_date=delivery_date,
                                    payment_status=payment_status,
                                    paid_amount=paid_amount
                                )
                                db.session.add(order)
                            
                            imported_counts['orders'] += 1
                            variety_obj = Variety.query.get(variety_id) if not USE_GOOGLE_SHEETS else next((v for v in all_varieties.values() if v.id == variety_id), None)
                            variety_name_display = variety_obj.name if variety_obj else 'Unknown'
                            print(f"  ✓ Added order: {shop_name} - {variety_name_display} x{quantity} @ ₹{price} on {delivery_date} (Status: {payment_status}, Paid: ₹{paid_amount:.2f})")
                        else:
                            print(f"  - Skipped row {idx+2}: invalid quantity or price")
                    
                    except Exception as e:
                        error_msg = f"Order row {idx+2}: {str(e)}"
                        imported_counts['errors'].append(error_msg)
                        print(f"  ✗ Error: {error_msg}")
                        import traceback
                        traceback.print_exc()
            else:
                print(f"  ✗ Missing required columns (Date, Shop name). Found: {list(orders_df.columns)}")
        else:
            print("  ✗ No orders sheet found")
        
        # Commit all changes (only for SQLite)
        if not USE_GOOGLE_SHEETS:
            db.session.commit()
        
        # Print summary
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        print(f"✓ Varieties imported: {imported_counts['varieties']}")
        print(f"✓ Shops imported: {imported_counts['shops']}")
        print(f"✓ Orders imported: {imported_counts['orders']}")
        if imported_counts['errors']:
            print(f"\n⚠ Errors encountered: {len(imported_counts['errors'])}")
            for error in imported_counts['errors'][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(imported_counts['errors']) > 10:
                print(f"  ... and {len(imported_counts['errors']) - 10} more errors")
        print("="*60)
        
        return imported_counts

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("="*60)
        print("Excel Import Script for Brownie Sales Tracker")
        print("="*60)
        print("\nUsage: python import_excel.py <path_to_excel_file.xlsx>")
        print("\nExample:")
        print("  python import_excel.py sales_data.xlsx")
        print("  python import_excel.py \"C:/Users/username/Downloads/my_data.xlsx\"")
        print("\nExpected Excel Format:")
        print("  - Sheet with Date, Shop name, Pieces, Price/Piec columns")
        print("  - Optional 'Varieties' sheet with Name and Price columns")
        print("  - Optional 'Shops' sheet with Name column")
        print(f"\nCurrent mode: {'Google Sheets' if USE_GOOGLE_SHEETS else 'SQLite'}")
        print("="*60)
        sys.exit(1)
    
    excel_path = sys.argv[1]
    
    if not os.path.exists(excel_path):
        print(f"✗ Error: File not found: {excel_path}")
        sys.exit(1)
    
    if not excel_path.lower().endswith(('.xlsx', '.xls')):
        print(f"✗ Error: File must be .xlsx or .xls format")
        sys.exit(1)
    
    try:
        print("\nStarting import process...\n")
        import_from_excel(excel_path)
        print("\n✓ Import completed successfully!")
    except Exception as e:
        print(f"\n✗ Import failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
