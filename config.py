import os
import json
import tempfile
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME", "Railway_Equipment_Tracking_TKD")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
XAI_API_KEY = os.getenv("XAI_API_KEY")

# Handle Google credentials from environment variable
CREDENTIALS_FILE = "credentials.json"

# If credentials.json doesn't exist but GOOGLE_CREDENTIALS_JSON env var exists, create the file
if not os.path.exists(CREDENTIALS_FILE):
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        with open(CREDENTIALS_FILE, 'w') as f:
            f.write(creds_json)
        print("✅ Created credentials.json from GOOGLE_CREDENTIALS_JSON")
    else:
        print("❌ GOOGLE_CREDENTIALS_JSON not found!")

# Sheet names
SHEETS = {
    "LOCO_MASTER": "loco_master",
    "EQUIPMENT_MASTER": "equipment_master",
    "LOCO_MESSAGES": "loco_messages",
    "EQUIPMENT_HISTORY": "equipment_history",
    "DASHBOARD": "dashboard_data"
}