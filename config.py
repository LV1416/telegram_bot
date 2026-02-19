import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

GOOGLE_CREDENTIALS_FILE = "credentials.json"
