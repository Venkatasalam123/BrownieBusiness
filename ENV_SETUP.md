# Setting Up Google Credentials in .env File

This guide explains how to store your Google service account credentials in the `.env` file instead of using a `credentials.json` file. This is recommended for hosting your application.

## Steps to Convert credentials.json to .env

### Option 1: Using Python (Recommended)

1. **Read your credentials.json file** and convert it to a single-line JSON string:

```python
import json

# Read your credentials.json file
with open('credentials.json', 'r') as f:
    creds = json.load(f)

# Convert to single-line JSON string
creds_string = json.dumps(creds)
print(creds_string)
```

2. **Copy the output** and add it to your `.env` file:

```env
GOOGLE_CREDENTIALS_JSON='{"type":"service_account","project_id":"your-project-id",...}'
```

### Option 2: Manual Conversion

1. **Open your `credentials.json` file** - it should look like this:
```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-service-account@project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}
```

2. **Convert it to a single line** by removing all line breaks and extra spaces. You can use an online JSON minifier or do it manually.

3. **Add to your `.env` file** using single quotes:
```env
GOOGLE_CREDENTIALS_JSON='{"type":"service_account","project_id":"your-project-id","private_key_id":"key-id","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"your-service-account@project.iam.gserviceaccount.com","client_id":"123456789","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/..."}'
```

### Option 3: Using Command Line (Linux/Mac)

```bash
# Convert credentials.json to single-line JSON and add to .env
echo "GOOGLE_CREDENTIALS_JSON='$(cat credentials.json | jq -c .)'" >> .env
```

Or without jq:
```bash
echo "GOOGLE_CREDENTIALS_JSON='$(cat credentials.json | tr -d '\n' | tr -d ' ')'" >> .env
```

## Complete .env File Example

Your `.env` file should look like this:

```env
# Google Sheets Configuration
USE_GOOGLE_SHEETS=true
GOOGLE_SHEET_ID=your-spreadsheet-id-here

# Google Service Account Credentials (entire JSON as single line)
GOOGLE_CREDENTIALS_JSON='{"type":"service_account","project_id":"your-project","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"..."}'
```

## Multi-line JSON Support

Yes! You can use multi-line JSON in your `.env` file. The `python-dotenv` library supports this. Here are two formats:

### Option 1: Multi-line with quotes (Recommended for readability)

The `python-dotenv` library supports multi-line values when wrapped in quotes. Format it like this:

```env
GOOGLE_CREDENTIALS_JSON='{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-service-account@project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}'
```

**Important**: The opening quote `'` must be on the same line as `GOOGLE_CREDENTIALS_JSON=`, and the closing quote `'` must be on its own line after the JSON.

### Option 2: Single-line (Compact)

```env
GOOGLE_CREDENTIALS_JSON='{"type":"service_account","project_id":"your-project-id",...}'
```

Both formats work! Use multi-line for better readability, or single-line for compactness.

## Important Notes

1. **Use single quotes** around the JSON string in `.env` to prevent issues with special characters
2. **Keep the private_key intact** - it contains `\n` characters that should be preserved
3. **Multi-line is supported** - You can format the JSON across multiple lines for better readability
4. **Backward compatibility** - The code still supports `credentials.json` file as a fallback if `GOOGLE_CREDENTIALS_JSON` is not set

## Verification

After setting up your `.env` file, run your application. You should see:
```
✓ Loaded Google credentials from environment variable
✓ Connected to Google Sheets API
```

If you see an error, check:
- The JSON is valid (use a JSON validator)
- All quotes are properly escaped
- The entire JSON is on a single line
- You're using single quotes around the JSON string in `.env`

