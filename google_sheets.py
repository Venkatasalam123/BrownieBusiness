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
                    orders.append({
                        'id': i,
                        'variety_id': int(row[0]) if row[0] else None,
                        'shop_id': int(row[1]) if row[1] else None,
                        'quantity': int(float(row[2])) if row[2] else 0,  # Convert to float first to handle "5.0" strings
                        'price': Decimal(str(row[3])) if row[3] else Decimal('0'),
                        'delivery_date': datetime.strptime(row[4], '%Y-%m-%d').date() if row[4] else None,
                        'payment_status': row[5] if len(row) > 5 else 'unpaid',
                        'paid_amount': Decimal(str(row[6])) if len(row) > 6 and row[6] else Decimal('0'),
                        'created_at': (datetime.strptime(row[7], '%Y-%m-%d %H:%M:%S').replace(tzinfo=IST) if len(row) > 7 and row[7] else get_ist_now())
                    })
                except (ValueError, IndexError) as e:
                    print(f"Error parsing order row {i}: {e}")
                    continue
        return orders
    
    def add_order(self, variety_id, shop_id, quantity, price, delivery_date, payment_status='unpaid', paid_amount=0):
        """Add a new order"""
        values = [[
            str(variety_id),
            str(shop_id),
            str(quantity),
            str(price),
            delivery_date.strftime('%Y-%m-%d') if isinstance(delivery_date, date) else str(delivery_date),
            payment_status,
            str(paid_amount),
            get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        ]]
        self._append_sheet(SHEET_ORDERS, values)
    
    def update_order(self, row_id, variety_id, shop_id, quantity, price, delivery_date, payment_status, paid_amount):
        """Update an order"""
        values = [
            str(variety_id),
            str(shop_id),
            str(quantity),
            str(price),
            delivery_date.strftime('%Y-%m-%d') if isinstance(delivery_date, date) else str(delivery_date),
            payment_status,
            str(paid_amount),
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
    
    def initialize_sheets(self):
        """Initialize sheets with headers if they don't exist"""
        try:
            # Check if sheets exist and create headers
            varieties = self._read_sheet(SHEET_VARIETIES)
            if not varieties:
                self._write_sheet(SHEET_VARIETIES, [['Name', 'Default Price']], 'A1')
            
            shops = self._read_sheet(SHEET_SHOPS)
            if not shops:
                self._write_sheet(SHEET_SHOPS, [['Name']], 'A1')
            
            orders = self._read_sheet(SHEET_ORDERS)
            if not orders:
                self._write_sheet(SHEET_ORDERS, [['Variety ID', 'Shop ID', 'Quantity', 'Price', 'Delivery Date', 'Payment Status', 'Paid Amount', 'Created At']], 'A1')
            
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
