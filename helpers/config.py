import os
import json
from dotenv import load_dotenv

# Load .env only if running locally
if os.path.exists(".env"):
    load_dotenv()

# Create the credential file from env var (only on Heroku)
if os.getenv("GOOGLE_CREDENTIALS_JSON"):
    with open("google-credentials.json", "w") as f:
        f.write(os.getenv("GOOGLE_CREDENTIALS_JSON"))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-credentials.json"

# Optional: do the same for the web client if needed
if os.getenv("GOOGLE_WEB_CLIENT_JSON"):
    with open("client_secret.json", "w") as f:
        f.write(os.getenv("GOOGLE_WEB_CLIENT_JSON"))
    os.environ["GOOGLE_WEB_CLIENT_SECRETS_FILE"] = "client_secret.json"

# Read other config vars
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
GOOGLE_WEB_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_WEB_CLIENT_SECRETS_FILE")
GOOGLE_WEB_CLIENT_ID = os.getenv("GOOGLE_WEB_CLIENT_ID")
GOOGLE_WEB_CLIENT_SECRET = os.getenv("GOOGLE_WEB_CLIENT_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")
EXTERNAL_DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
