import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from gemini_ai import extract_structured_fields, GeminiError

INFO_SHEET_TITLE = os.getenv("INFO_SHEET_TITLE") or "Loco Info"

def _ensure_info_sheet(book) -> "gspread.Worksheet":
    try:
        ws = book.worksheet(INFO_SHEET_TITLE)
        # Check if header exists; insert it if sheet was created without one
        first_row = ws.row_values(1)
        if not first_row or first_row[0].strip().lower() != "sr. no.":
            ws.insert_row(["Sr. No.", "Date", "Loco No.", "Information"], index=1)
    except Exception:
        ws = book.add_worksheet(title=INFO_SHEET_TITLE, rows=2000, cols=4)
        ws.append_row(["Sr. No.", "Date", "Loco No.", "Information"])
    return ws

def _format_summary(message_type: str, loco_info: dict) -> str:
    mt = (message_type or "").strip().lower()
    info = loco_info or {}

    def g(key: str) -> str:
        v = info.get(key, "")
        return "" if v is None else str(v).strip()

    parts = ["✅ Saved"]

    if mt == "dga_report":
        parts.append(f"Type: DGA Report")
    elif mt == "panto_status":
        parts.append(f"Type: Panto Status")
    elif mt == "main_equipment":
        parts.append(f"Type: Main Equipment")
    else:
        parts.append(f"Type: General Info")

    if g("date"):
        parts.append(f"Date: {g('date')}")
    if g("loco_no"):
        parts.append(f"Loco No: {g('loco_no')}")

    if g("summary"):
        parts.append(f"Info: {g('summary')}")

    return "\n".join(parts)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

app_telegram = ApplicationBuilder().token(BOT_TOKEN).build()

def _extract_identifier(text: str) -> tuple[str, str]:
    """
    Extract optional one-word identifier from message.
    If message starts with a word followed by colon or space, treat first word as identifier.
    Example: "dga: Date - ... " -> identifier="dga", remaining_text="Date - ..."
    """
    text = text.strip()
    if not text:
        return None, text

    if ":" in text:
        first_part = text.split(":")[0].strip()
        if len(first_part.split()) == 1 and len(first_part) > 1:
            identifier = first_part.lower()
            remaining = text[len(first_part):].lstrip(": ").strip()
            if remaining:
                return identifier, remaining

    parts = text.split()
    if len(parts) >= 2:
        first_word = parts[0].lower()
        if len(first_word) >= 3 and first_word not in ["date", "loco", "item", "status", "panto", "dga"]:
            return first_word, " ".join(parts[1:])

    return None, text

async def handle_message(update, context):
    if update.message and update.message.text:
        text = update.message.text.strip()

        identifier, message_text = _extract_identifier(text)

        try:
            result = extract_structured_fields(message_text, identifier)
        except GeminiError as e:
            await update.message.reply_text(
                f"Failed to parse message: {e}\n\n"
                "Please ensure the message contains:\n"
                "- Date (e.g., 15.04.2026)\n"
                "- Loco No (e.g., 70872)\n"
                "- Relevant fields for the type of report"
            )
            return
        except Exception as e:
            await update.message.reply_text(f"Error processing message: {e}")
            return

        message_type = result.get("message_type", "")
        worksheet_name = result.get("worksheet_name")
        row = result.get("row", [])
        loco_info = result.get("loco_info", {})

        try:
            book = client.open(SHEET_NAME)

            if message_type != "loco_info_only" and row:
                if worksheet_name:
                    target_sheet = book.worksheet(worksheet_name)
                else:
                    target_sheet = book.sheet1
                target_sheet.append_row(row)

            info_ws = _ensure_info_sheet(book)
            log_date = loco_info.get("date", "")
            log_loco = loco_info.get("loco_no", "")
            log_summary = loco_info.get("summary", "")

            if log_date or log_loco or log_summary:
                # Auto-increment Sr. No. (count data rows = total rows minus header)
                all_rows = info_ws.get_all_values()
                sr_no = len(all_rows)  # header is row 1, so len = next sr no
                info_ws.append_row([sr_no, log_date, log_loco, log_summary])

        except Exception as e:
            await update.message.reply_text(f"Failed to save to Google Sheet: {e}")
            return

        await update.message.reply_text(_format_summary(message_type, loco_info))

app_telegram.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    app_telegram.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
    )
