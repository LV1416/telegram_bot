import os
import json
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from parser import parse_message

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
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        row = parse_message(update.message.text)
        sheet.append_row(row)

telegram_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

# ===== FLASK APP =====
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "Bot is running", 200

@app.route("/", methods=["GET"])
def home():
    return "Telegram Bot Active", 200

# ===== START SERVER =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    # Auto-set webhook every time app starts
    import asyncio
    asyncio.run(
        telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    )

    app.run(host="0.0.0.0", port=port)
