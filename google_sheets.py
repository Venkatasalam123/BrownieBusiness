"""
Google Sheets integration for Brownie Sales Tracker
Replaces SQLite database with Google Sheets
"""
import os
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
import json
import time

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    """Get current datetime in IST timezone"""
    return datetime.now(IST)

# Google Sheets API configuration
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # Service account JSON file (fallback)
# Get and clean spreadsheet ID - strip whitespace and validate
_raw_id = os.getenv('GOOGLE_SHEET_ID', '').strip()
SPREADSHEET_ID = _raw_id if _raw_id else ''

# Sheet names
SHEET_VARIETIES = 'Varieties'
SHEET_SHOPS = 'Shops'
SHEET_ORDERS = 'Orders'
SHEET_INGREDIENT_PRICES = 'IngredientPrices'

class GoogleSheetsDB:
    """Google Sheets database interface"""
    
    # Cache expiry time in seconds (default: 5 minutes)
    CACHE_TTL = int(os.getenv('GOOGLE_SHEETS_CACHE_TTL', 300))  # 5 minutes default
    
    def __init__(self):
        self.service = None
        # Cache for sheet data to avoid repeated API calls
        self._cache = {}
        self._cache_timestamp = {}
        # Clean and validate spreadsheet ID
        raw_id = str(SPREADSHEET_ID).strip()
        
        # Remove any accidental suffixes that might get appended
        # Google Sheet IDs are exactly 44 characters long
        # Common accidental suffixes: 'cls', '.cls', etc.
        if len(raw_id) > 44:
            # Try to extract just the 44-character ID (most common length)
            import re
            # Google Sheet IDs pattern: alphanumeric, hyphens, underscores, exactly 44 chars
            # Look for a 44-character valid ID pattern
            match_44 = re.search(r'([a-zA-Z0-9_-]{44})(?:cls|\.cls|\.|$)', raw_id)
            if match_44:
                raw_id = match_44.group(1)
            else:
                # If no 44-char match, try to extract the longest valid ID part
                match = re.match(r'^([a-zA-Z0-9_-]{40,44})', raw_id)
                if match:
                    raw_id = match.group(1)
        
        self.spreadsheet_id = raw_id
        self._connect()
    
    def _clear_cache(self, sheet_name=None):
        """Clear cache for a specific sheet or all sheets"""
        if sheet_name:
            # Clear all cache entries that start with the sheet name
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"{sheet_name}_")]
            for key in keys_to_remove:
                self._cache.pop(key, None)
                self._cache_timestamp.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamp.clear()
    
    def refresh_cache(self, sheet_name=None):
        """Public method to manually refresh/clear cache for a specific sheet or all sheets"""
        self._clear_cache(sheet_name)
        print(f"✓ Cache refreshed{' for ' + sheet_name if sheet_name else ' (all sheets)'}")
    
    def _is_cache_valid(self, cache_key):
        """Check if cache entry is still valid (not expired)"""
        if cache_key not in self._cache_timestamp:
            return False
        cache_age = time.time() - self._cache_timestamp[cache_key]
        return cache_age < self.CACHE_TTL
    
    def _connect(self):
        """Connect to Google Sheets API"""
        try:
            creds = None
            
            # First, try to load credentials from environment variable (preferred for hosting)
            google_creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '').strip()
            if google_creds_json:
                try:
                    # Handle multi-line JSON (python-dotenv preserves newlines in quoted strings)
                    # Remove any leading/trailing quotes if present
                    if google_creds_json.startswith("'") and google_creds_json.endswith("'"):
                        google_creds_json = google_creds_json[1:-1]
                    elif google_creds_json.startswith('"') and google_creds_json.endswith('"'):
                        google_creds_json = google_creds_json[1:-1]
                    
                    # Parse the JSON string from environment variable (supports both single-line and multi-line)
                    creds_info = json.loads(google_creds_json)
                    creds = service_account.Credentials.from_service_account_info(
                        creds_info, scopes=SCOPES)
                    print("✓ Loaded Google credentials from environment variable")
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid JSON in GOOGLE_CREDENTIALS_JSON environment variable: {e}\n"
                        "Please ensure the credentials JSON is properly formatted.\n"
                        "The JSON can be single-line or multi-line in your .env file."
                    )
            # Fallback to credentials.json file (for backward compatibility)
            elif os.path.exists(SERVICE_ACCOUNT_FILE):
                creds = service_account.Credentials.from_service_account_file(
                    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                print("✓ Loaded Google credentials from credentials.json file")
            else:
                # No credentials found
                error_msg = (
                    "Google service account credentials not found.\n\n"
                    "To use Google Sheets, provide credentials in one of these ways:\n"
                    "1. Set GOOGLE_CREDENTIALS_JSON environment variable in .env file (recommended for hosting)\n"
                    "   - Copy the entire contents of your credentials.json file\n"
                    "   - Paste it as a single-line JSON string in .env: GOOGLE_CREDENTIALS_JSON='{...}'\n"
                    "2. OR create a credentials.json file in the project root\n\n"
                    "Also set GOOGLE_SHEET_ID environment variable.\n\n"
                    "OR set USE_GOOGLE_SHEETS=false in .env file to use SQLite instead."
                )
                raise FileNotFoundError(error_msg)
            
            if not self.spreadsheet_id:
                raise ValueError(
                    "GOOGLE_SHEET_ID environment variable not set.\n"
                    "Please set it in your .env file or environment variables."
                )
            
            # Validate spreadsheet ID format
            id_len = len(self.spreadsheet_id)
            if id_len != 44:
                print(f"⚠ Warning: Spreadsheet ID length is {id_len} (expected 44): {self.spreadsheet_id[:20]}...{self.spreadsheet_id[-10:]}")
                print("  If you're getting 404 errors, verify your GOOGLE_SHEET_ID in .env file.")
                print("  Make sure there are no extra characters or suffixes in the ID.")
            
            self.service = build('sheets', 'v4', credentials=creds)
            print(f"✓ Connected to Google Sheets API (ID: {self.spreadsheet_id[:20]}...{self.spreadsheet_id[-4:]})")
        except Exception as e:
            print(f"✗ Error connecting to Google Sheets: {str(e)}")
            raise
    
    def _read_sheet(self, sheet_name, range_name=None, retry_count=3, use_cache=True):
        """Read data from a sheet with retry logic for rate limiting and caching"""
        # Create cache key
        cache_key = f"{sheet_name}_{range_name or 'full'}"
        
        # Check cache first (only for full sheet reads, not specific ranges)
        # Also check if cache is still valid (not expired)
        if use_cache and range_name is None and cache_key in self._cache:
            if self._is_cache_valid(cache_key):
                return self._cache[cache_key]
            else:
                # Cache expired, remove it
                self._cache.pop(cache_key, None)
                self._cache_timestamp.pop(cache_key, None)
        
        try:
            if range_name:
                range_str = f"{sheet_name}!{range_name}"
            else:
                range_str = sheet_name
            
            for attempt in range(retry_count):
                try:
                    result = self.service.spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_str
                    ).execute()
                    
                    values = result.get('values', [])
                    
                    # Cache the result if it's a full sheet read
                    if use_cache and range_name is None:
                        self._cache[cache_key] = values
                        self._cache_timestamp[cache_key] = time.time()
                    
                    return values
                except (HttpError, ConnectionError, OSError, Exception) as error:
                    # Handle sheet not found (404) - return empty list
                    if isinstance(error, HttpError) and error.resp.status == 400:
                        error_str = str(error)
                        if 'Unable to parse range' in error_str or 'does not exist' in error_str.lower():
                            # Sheet doesn't exist, return empty list
                            return []
                    
                    # Handle rate limiting
                    if isinstance(error, HttpError) and error.resp.status == 429:
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                            print(f"  ⚠ Rate limit hit. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            continue
                        else:
                            raise
                    # Handle SSL/connection errors
                    elif 'SSL' in str(error) or 'EOF' in str(error) or 'connection' in str(error).lower():
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 3  # Longer wait for connection issues: 3s, 6s, 9s
                            print(f"  ⚠ Connection error. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            # Rebuild connection on retry
                            try:
                                self._connect()
                            except:
                                pass
                            continue
                        else:
                            raise
                    else:
                        raise
            
        except Exception as error:
            print(f"Error reading sheet {sheet_name}: {error}")
            return []
    
    def _write_sheet(self, sheet_name, values, range_name='A1'):
        """Write data to a sheet"""
        try:
            range_str = f"{sheet_name}!{range_name}"
            body = {'values': values}
            
            result = self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_str,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            return result
        except HttpError as error:
            print(f"Error writing to sheet {sheet_name}: {error}")
            raise
    
    def _append_sheet(self, sheet_name, values, retry_count=3):
        """Append data to a sheet with retry logic for rate limiting and connection errors"""
        try:
            range_str = sheet_name
            body = {'values': values}
            
            for attempt in range(retry_count):
                try:
                    result = self.service.spreadsheets().values().append(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_str,
                        valueInputOption='USER_ENTERED',
                        insertDataOption='INSERT_ROWS',
                        body=body
                    ).execute()
                    
                    # Clear cache for this sheet since we modified it
                    self._clear_cache(sheet_name)
                    
                    return result
                except (HttpError, ConnectionError, OSError, Exception) as error:
                    # Handle rate limiting
                    if isinstance(error, HttpError) and error.resp.status == 429:
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                            print(f"  ⚠ Rate limit hit. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            continue
                        else:
                            raise
                    # Handle SSL/connection errors
                    elif 'SSL' in str(error) or 'EOF' in str(error) or 'connection' in str(error).lower():
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 3  # Longer wait for connection issues: 3s, 6s, 9s
                            print(f"  ⚠ Connection error. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            # Rebuild connection on retry
                            try:
                                self._connect()
                            except:
                                pass
                            continue
                        else:
                            raise
                    else:
                        raise
        except Exception as error:
            print(f"Error appending to sheet {sheet_name}: {error}")
            raise
    
    def _delete_row(self, sheet_name, row_index):
        """Delete a row from a sheet"""
        try:
            # Get sheet ID
            sheet_metadata = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            sheet_id = None
            for sheet in sheet_metadata.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break
            
            if sheet_id is None:
                raise ValueError(f"Sheet '{sheet_name}' not found")
            
            # Delete row
            request_body = {
                'requests': [{
                    'deleteDimension': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'ROWS',
                            'startIndex': row_index - 1,  # 0-indexed
                            'endIndex': row_index
                        }
                    }
                }]
            }
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=request_body
            ).execute()
            
            # Clear cache for this sheet since we modified it
            self._clear_cache(sheet_name)
            
        except HttpError as error:
            print(f"Error deleting row from sheet {sheet_name}: {error}")
            raise
    
    def _update_row(self, sheet_name, row_index, values, retry_count=3):
        """Update a row in a sheet with retry logic"""
        try:
            range_str = f"{sheet_name}!A{row_index}"
            body = {'values': [values]}
            
            for attempt in range(retry_count):
                try:
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=range_str,
                        valueInputOption='USER_ENTERED',
                        body=body
                    ).execute()
                    
                    # Clear cache for this sheet since we modified it
                    self._clear_cache(sheet_name)
                    return
                except (HttpError, ConnectionError, OSError, Exception) as error:
                    # Handle rate limiting
                    if isinstance(error, HttpError) and error.resp.status == 429:
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 2
                            print(f"  ⚠ Rate limit hit. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            continue
                        else:
                            raise
                    # Handle SSL/connection errors
                    elif 'SSL' in str(error) or 'EOF' in str(error) or 'connection' in str(error).lower():
                        if attempt < retry_count - 1:
                            wait_time = (attempt + 1) * 3
                            print(f"  ⚠ Connection error. Waiting {wait_time}s before retry {attempt + 2}/{retry_count}...")
                            time.sleep(wait_time)
                            # Rebuild connection on retry
                            try:
                                self._connect()
                            except:
                                pass
                            continue
                        else:
                            raise
                    else:
                        raise
        except Exception as error:
            print(f"Error updating row in sheet {sheet_name}: {error}")
            raise
    
    def _sheet_exists(self, sheet_name):
        """Check if a sheet exists in the spreadsheet"""
        try:
            sheet_metadata = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            for sheet in sheet_metadata.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    return True
            return False
        except Exception as error:
            print(f"Error checking if sheet {sheet_name} exists: {error}")
            return False
    
    def _create_sheet(self, sheet_name):
        """Create a new sheet if it doesn't exist"""
        try:
            if self._sheet_exists(sheet_name):
                return  # Sheet already exists
            
            request_body = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': sheet_name
                        }
                    }
                }]
            }
            
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body=request_body
            ).execute()
            
            print(f"✓ Created sheet: {sheet_name}")
        except Exception as error:
            print(f"Error creating sheet {sheet_name}: {error}")
            raise
    
    # Varieties operations
    def get_varieties(self):
        """Get all varieties"""
        rows = self._read_sheet(SHEET_VARIETIES)
        if not rows:
            return []
        
        varieties = []
        for i, row in enumerate(rows[1:], start=2):  # Skip header
            if len(row) >= 2:
                varieties.append({
                    'id': i,
                    'name': row[0],
                    'default_price': Decimal(str(row[1])) if len(row) > 1 else Decimal('25.00')
                })
        return varieties
    
    def add_variety(self, name, default_price):
        """Add a new variety"""
        values = [[name, str(default_price)]]
        self._append_sheet(SHEET_VARIETIES, values)
    
    def update_variety(self, row_id, name, default_price):
        """Update a variety"""
        values = [name, str(default_price)]
        self._update_row(SHEET_VARIETIES, row_id, values)
    
    def delete_variety(self, row_id):
        """Delete a variety"""
        self._delete_row(SHEET_VARIETIES, row_id)
    
    # Shops operations
    def get_shops(self):
        """Get all shops"""
        rows = self._read_sheet(SHEET_SHOPS)
        if not rows:
            return []
        
        shops = []
        for i, row in enumerate(rows[1:], start=2):  # Skip header
            if len(row) >= 1:
                shops.append({
                    'id': i,
                    'name': row[0]
                })
        return shops
    
    def add_shop(self, name):
        """Add a new shop"""
        values = [[name]]
        self._append_sheet(SHEET_SHOPS, values)
    
    def update_shop(self, row_id, name):
        """Update a shop"""
        values = [name]
        self._update_row(SHEET_SHOPS, row_id, values)
    
    def delete_shop(self, row_id):
        """Delete a shop"""
        self._delete_row(SHEET_SHOPS, row_id)
    
    # Orders operations
    def get_orders(self):
        """Get all orders"""
        rows = self._read_sheet(SHEET_ORDERS)
        if not rows:
            return []
        
        orders = []
        for i, row in enumerate(rows[1:], start=2):  # Skip header
            if len(row) >= 8:
                try:
                    # Handle backward compatibility:
                    # Old format (8 cols): variety_id, shop_id, quantity, price, delivery_date, payment_status, paid_amount, created_at
                    # Medium format (9 cols): adds courier_price before created_at
                    # New format (10 cols): adds returns after quantity
                    # Current format (10 cols): variety_id, shop_id, quantity, returns, price, delivery_date, payment_status, paid_amount, courier_price, created_at
                    
                    # Detect format based on column count
                    if len(row) >= 10:
                        # New format with returns
                        variety_id = int(row[0]) if row[0] else None
                        shop_id = int(row[1]) if row[1] else None
                        quantity = int(float(row[2])) if row[2] else 0
                        returns = int(float(row[3])) if row[3] else 0
                        price = Decimal(str(row[4])) if row[4] else Decimal('0')
                        delivery_date_idx = 5
                        payment_status_idx = 6
                        paid_amount_idx = 7
                        courier_price_idx = 8
                        created_at_idx = 9
                    elif len(row) == 9:
                        # Medium format with courier_price but no returns
                        variety_id = int(row[0]) if row[0] else None
                        shop_id = int(row[1]) if row[1] else None
                        quantity = int(float(row[2])) if row[2] else 0
                        returns = 0  # Default for old rows
                        price = Decimal(str(row[3])) if row[3] else Decimal('0')
                        delivery_date_idx = 4
                        payment_status_idx = 5
                        paid_amount_idx = 6
                        courier_price_idx = 7
                        created_at_idx = 8
                    else:
                        # Old format (8 cols) without courier_price and returns
                        variety_id = int(row[0]) if row[0] else None
                        shop_id = int(row[1]) if row[1] else None
                        quantity = int(float(row[2])) if row[2] else 0
                        returns = 0  # Default for old rows
                        price = Decimal(str(row[3])) if row[3] else Decimal('0')
                        delivery_date_idx = 4
                        payment_status_idx = 5
                        paid_amount_idx = 6
                        courier_price_idx = None
                        created_at_idx = 7
                    
                    orders.append({
                        'id': i,
                        'variety_id': variety_id,
                        'shop_id': shop_id,
                        'quantity': quantity,
                        'returns': returns,
                        'price': price,
                        'delivery_date': datetime.strptime(row[delivery_date_idx], '%Y-%m-%d').date() if len(row) > delivery_date_idx and row[delivery_date_idx] else None,
                        'payment_status': row[payment_status_idx] if len(row) > payment_status_idx else 'unpaid',
                        'paid_amount': Decimal(str(row[paid_amount_idx])) if len(row) > paid_amount_idx and row[paid_amount_idx] else Decimal('0'),
                        'courier_price': Decimal(str(row[courier_price_idx])) if courier_price_idx is not None and len(row) > courier_price_idx and row[courier_price_idx] else Decimal('0'),
                        'created_at': (datetime.strptime(row[created_at_idx], '%Y-%m-%d %H:%M:%S').replace(tzinfo=IST) if len(row) > created_at_idx and row[created_at_idx] else get_ist_now())
                    })
                except (ValueError, IndexError) as e:
                    print(f"Error parsing order row {i}: {e}")
                    continue
        return orders
    
    def add_order(self, variety_id, shop_id, quantity, price, delivery_date, payment_status='unpaid', paid_amount=0, courier_price=0, returns=0):
        """Add a new order"""
        values = [[
            str(variety_id),
            str(shop_id),
            str(quantity),
            str(returns or 0),
            str(price),
            delivery_date.strftime('%Y-%m-%d') if isinstance(delivery_date, date) else str(delivery_date),
            payment_status,
            str(paid_amount),
            str(courier_price),
            get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        ]]
        self._append_sheet(SHEET_ORDERS, values)
    
    def update_order(self, row_id, variety_id, shop_id, quantity, price, delivery_date, payment_status, paid_amount, courier_price=0, returns=0):
        """Update an order"""
        values = [
            str(variety_id),
            str(shop_id),
            str(quantity),
            str(returns or 0),
            str(price),
            delivery_date.strftime('%Y-%m-%d') if isinstance(delivery_date, date) else str(delivery_date),
            payment_status,
            str(paid_amount),
            str(courier_price),
            get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        ]
        self._update_row(SHEET_ORDERS, row_id, values)
    
    def delete_all_orders(self):
        """Delete all orders (keep header)"""
        rows = self._read_sheet(SHEET_ORDERS)
        if len(rows) > 1:
            # Delete all rows except header
            for i in range(len(rows), 1, -1):
                self._delete_row(SHEET_ORDERS, i)
    
    # Ingredient Prices operations
    def get_ingredient_prices(self):
        """Get all ingredient prices"""
        rows = self._read_sheet(SHEET_INGREDIENT_PRICES)
        if not rows:
            return []
        
        ingredients = []
        for i, row in enumerate(rows[1:], start=2):  # Skip header
            if len(row) >= 5:
                ingredients.append({
                    'id': i,
                    'name': row[0],
                    'price': Decimal(str(row[1])) if row[1] else Decimal('0'),
                    'unit': row[2] if len(row) > 2 else '',
                    'package_size': Decimal(str(row[3])) if len(row) > 3 and row[3] else Decimal('1'),
                    'package_unit': row[4] if len(row) > 4 else 'g',
                    'updated_at': (datetime.strptime(row[5], '%Y-%m-%d %H:%M:%S').replace(tzinfo=IST) if len(row) > 5 and row[5] else get_ist_now())
                })
        return ingredients
    
    def add_ingredient_price(self, name, price, unit, package_size, package_unit):
        """Add a new ingredient price"""
        values = [[
            name,
            str(price),
            unit,
            str(package_size),
            package_unit,
            get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        ]]
        self._append_sheet(SHEET_INGREDIENT_PRICES, values)
    
    def update_ingredient_price(self, row_id, name, price, unit, package_size, package_unit):
        """Update an ingredient price"""
        values = [
            name,
            str(price),
            unit,
            str(package_size),
            package_unit,
            get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        ]
        self._update_row(SHEET_INGREDIENT_PRICES, row_id, values)
    
    def initialize_sheets(self):
        """Initialize sheets with headers if they don't exist"""
        try:
            # Create sheets if they don't exist
            if not self._sheet_exists(SHEET_VARIETIES):
                self._create_sheet(SHEET_VARIETIES)
            
            if not self._sheet_exists(SHEET_SHOPS):
                self._create_sheet(SHEET_SHOPS)
            
            if not self._sheet_exists(SHEET_ORDERS):
                self._create_sheet(SHEET_ORDERS)
            
            if not self._sheet_exists(SHEET_INGREDIENT_PRICES):
                self._create_sheet(SHEET_INGREDIENT_PRICES)
            
            # Check if sheets have headers and create them if needed
            varieties = self._read_sheet(SHEET_VARIETIES)
            if not varieties:
                self._write_sheet(SHEET_VARIETIES, [['Name', 'Default Price']], 'A1')
            
            shops = self._read_sheet(SHEET_SHOPS)
            if not shops:
                self._write_sheet(SHEET_SHOPS, [['Name']], 'A1')
            
            orders = self._read_sheet(SHEET_ORDERS)
            if not orders:
                self._write_sheet(SHEET_ORDERS, [['Variety ID', 'Shop ID', 'Quantity', 'Returns', 'Price', 'Delivery Date', 'Payment Status', 'Paid Amount', 'Courier Price', 'Created At']], 'A1')
            
            ingredient_prices = self._read_sheet(SHEET_INGREDIENT_PRICES)
            if not ingredient_prices:
                self._write_sheet(SHEET_INGREDIENT_PRICES, [['Name', 'Price', 'Unit', 'Package Size', 'Package Unit', 'Updated At']], 'A1')
                # Initialize with default prices
                default_prices = [
                    ['Dark Compound', '165', '500g', '500', 'g'],
                    ['Butter', '100', '500g', '500', 'g'],
                    ['Egg', '7', '1pc', '1', 'pc'],
                    ['White Sugar', '50', '1kg', '1', 'kg'],
                    ['Brown Sugar', '80', '1kg', '1', 'kg'],
                    ['Vanilla Essence', '50', '100ml', '100', 'ml'],
                    ['Maida/Ragi', '50', '1kg', '1', 'kg'],
                    ['Mango Compound', '205', '500g', '500', 'g'],
                    ['Pista Compound', '205', '500g', '500', 'g'],
                    ['Pista Nuts', '445', '250g', '250', 'g'],
                    ['Milk Compound', '190', '500g', '500', 'g'],
                    ['White Compound', '205', '500g', '500', 'g'],
                    ['Oven Charges', '20', '16 brownies', '16', 'pc'],
                    ['Miscellaneous', '15', '16 brownies', '16', 'pc'],
                    ['Packing', '28.8', '16 brownies', '16', 'pc'],
                    ['Transportation', '20', '16 brownies', '16', 'pc'],
                ]
                for ing_data in default_prices:
                    self.add_ingredient_price(ing_data[0], Decimal(ing_data[1]), ing_data[2], Decimal(ing_data[3]), ing_data[4])
            
            print("✓ Sheets initialized")
        except Exception as e:
            print(f"Error initializing sheets: {e}")


# Global instance
gs_db = None

def get_gs_db():
    """Get or create Google Sheets DB instance"""
    global gs_db
    if gs_db is None:
        gs_db = GoogleSheetsDB()
        gs_db.initialize_sheets()
    return gs_db
