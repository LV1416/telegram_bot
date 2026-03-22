import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from parser import parse_message, parse_panto_status, parse_dga

# ===== ENV VARIABLES =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# ===== GOOGLE SHEETS SETUP =====
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# ===== TELEGRAM SETUP =====
app_telegram = ApplicationBuilder().token(BOT_TOKEN).build()



async def handle_message(update, context):
    if update.message and update.message.text:
        text = update.message.text.strip()

        if text.upper().startswith("PANTO STATUS"):
            sheet = client.open(SHEET_NAME).worksheet("Panto Status")
            row = parse_panto_status(text)

        elif text.upper().startswith("DGA REPORT"):
            sheet = client.open(SHEET_NAME).worksheet("DGA Report")
            row = parse_dga(text)

        else:
            sheet = client.open(SHEET_NAME).sheet1
            row = parse_message(text)

        sheet.append_row(row)

app_telegram.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

# ===== START WEBHOOK SERVER =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    app_telegram.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
    )
