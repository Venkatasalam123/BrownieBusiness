<<<<<<< HEAD
"""
Configuration file - Set USE_GOOGLE_SHEETS to True to use Google Sheets
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Set to True to use Google Sheets, False to use SQLite
USE_GOOGLE_SHEETS = os.getenv('USE_GOOGLE_SHEETS', 'False').lower() == 'true'

=======
"""
Configuration file - Set USE_GOOGLE_SHEETS to True to use Google Sheets
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Set to True to use Google Sheets, False to use SQLite
USE_GOOGLE_SHEETS = os.getenv('USE_GOOGLE_SHEETS', 'False').lower() == 'true'

>>>>>>> 966fed7 (initial push)
