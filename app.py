import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import BOT_TOKEN, SHEET_NAME, WEBHOOK_URL, GOOGLE_CREDENTIALS_FILE
from parser import parse_message
import json

# ====== GOOGLE SHEETS SETUP ======

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]



google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

creds_dict = json.loads(google_creds_json)

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict, scope
)


client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

# ====== TELEGRAM SETUP ======

app_telegram = ApplicationBuilder().token(BOT_TOKEN).build()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        row = parse_message(update.message.text)
        sheet.append_row(row)

app_telegram.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

# ====== FLASK WEBHOOK ======

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), app_telegram.bot)
    await app_telegram.process_update(update)
    return "ok"

@app.route("/")
def home():
    return "Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app_telegram.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
    )
