import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from parser import (
    parse_any,
    format_template,
    infer_message_type,
    parse_key_values,
    validate_fields,
    fields_to_row,
    normalize_fields,
    extract_free_text_fields,
)
from gemini_ai import extract_structured_fields, GeminiError

def _format_summary(message_type: str, fields: dict) -> str:
    mt = (message_type or "").strip().lower()
    f = fields or {}

    def g(key: str) -> str:
        v = f.get(key, "")
        return "" if v is None else str(v).strip()

    if mt == "dga_report":
        parts = [
            "✅ Saved",
            f"Type: DGA Report",
            f"Date: {g('date')}",
            f"Loco No: {g('loco no')}",
            f"Schedule: {g('schedule')}",
        ]
        return "\n".join(parts)

    if mt == "panto_status":
        parts = [
            "✅ Saved",
            f"Type: Panto Status",
            f"Date: {g('date')}",
            f"Loco No: {g('loco no')}",
            f"PT1 Pressure: {g('pt1 pressure')}",
            f"PT2 Pressure: {g('pt2 pressure')}",
        ]
        if g("pt1 ord"):
            parts.append(f"PT1 Height: {g('pt1 ord')}")
        if g("pt2 ord"):
            parts.append(f"PT2 Height: {g('pt2 ord')}")
        if g("pt1 add"):
            parts.append(f"PT1 ADD: {g('pt1 add')}")
        if g("pt2 add"):
            parts.append(f"PT2 ADD: {g('pt2 add')}")
        return "\n".join(parts)

    # main_equipment
    parts = [
        "✅ Saved",
        f"Type: Main Equipment",
        f"Date: {g('date')}",
        f"Loco No: {g('loco no')}",
        f"Item: {g('item')}",
        f"Status: {g('status')}",
    ]
    if g("sr no"):
        parts.append(f"Sr No: {g('sr no')}")
    if g("make"):
        parts.append(f"Make: {g('make')}")
    if g("type"):
        parts.append(f"Type: {g('type')}")
    if g("reason"):
        parts.append(f"Reason: {g('reason')}")
    return "\n".join(parts)

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
        extracted_fields: dict | None = None
        try:
            worksheet_name, row, message_type = parse_any(text)
            # For formatting only (parse_any returns rows, not a fields dict).
            f = parse_key_values(text)
            # If the user sent free-text, parse_key_values will be mostly empty.
            # Merge a heuristic extraction so the Telegram reply shows values.
            if message_type == "main_equipment":
                merged = dict(f)
                merged.update(extract_free_text_fields(text))
                extracted_fields = normalize_fields(message_type, merged)
            else:
                extracted_fields = normalize_fields(message_type, f)
        except ValueError as e:
            # Fallback: try Gemini extraction when local validation fails.
            try:
                mt, fields = extract_structured_fields(text)
                fields = normalize_fields(mt, fields)
                missing = validate_fields(mt, fields)
                if missing:
                    await update.message.reply_text(
                        "Invalid message.\nMissing required fields: "
                        + ", ".join(missing)
                        + "\n\nCopy-paste template:\n\n"
                        + format_template(mt)
                    )
                    return
                worksheet_name, row = fields_to_row(mt, fields)
                message_type = mt
                extracted_fields = fields
            except GeminiError:
                guessed_type = infer_message_type(text, parse_key_values(text))
                await update.message.reply_text(
                    f"Invalid message.\n{e}\n\nCopy-paste template:\n\n{format_template(guessed_type)}"
                )
                return
        except Exception:
            await update.message.reply_text(
                "Couldn't understand this message. Please send in key-value format like:\n\n"
                + format_template("main_equipment")
            )
            return

        try:
            book = client.open(SHEET_NAME)
            sheet = book.worksheet(worksheet_name) if worksheet_name else book.sheet1
            sheet.append_row(row)
        except Exception as e:
            await update.message.reply_text(f"Failed to save to Google Sheet: {e}")
            return

        if extracted_fields is not None:
            await update.message.reply_text(_format_summary(message_type, extracted_fields))
        else:
            await update.message.reply_text("Saved to Google Sheet.")

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
