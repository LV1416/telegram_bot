import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME", "Railway_Equipment_Tracking_TKD")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Google Sheets credentials
CREDENTIALS_FILE = "credentials.json"

# Sheet names
SHEETS = {
    "LOCO_MASTER": "loco_master",
    "EQUIPMENT_MASTER": "equipment_master",
    "LOCO_MESSAGES": "loco_messages",
    "EQUIPMENT_HISTORY": "equipment_history",
    "DASHBOARD": "dashboard_data"
}