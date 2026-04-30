import asyncio
import logging
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config
from railway_parser import RailwayParser

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Health check server for Koyeb ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    server.serve_forever()

# ---------- Google Sheets initialization ----------
def init_google_sheets():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise Exception("GOOGLE_CREDENTIALS_JSON environment variable not set")
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(config.SHEET_NAME)
    return sheet

sheet = init_google_sheets()
parser = RailwayParser(use_ai=True)

# ---------- Helper to format dates ----------
def format_date(date_str):
    try:
        if not date_str:
            return "-"
        return datetime.strptime(str(date_str), "%Y-%m-%d").strftime("%d-%m-%Y")
    except:
        return str(date_str)

def parse_date_dmy(date_str):
    """Convert DD-MM-YYYY string to datetime object, or return None."""
    if not date_str or date_str in ['', '-', 'N/A']:
        return None
    try:
        return datetime.strptime(str(date_str).strip(), '%d-%m-%Y')
    except:
        return None

# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🚂 Railway Equipment Tracking Bot (Powered by Groq AI)

Commands:
/start - Show this menu
/help - Get help
/status <loco_no> - Get loco status
/equipment <serial_no> - Get equipment history
/addequipment <type> <serial> <make> <mfg_date> [loco] [fit_date] - Add new equipment

Just type naturally - AI understands:
• 22229: MPH TKD/2024/31 fitted on 19/09/2024
• SCHEDULE 22229 MAJOR TOH done 24/06/2025 next_due 24/06/2026
• remove MVRH 14623 from 22229 for POH
• status of 22229
• 31642 panto pt1 sr no 1280 mersen fitted
• 22721 panto failure AM-12 abnormal

All messages are automatically logged and tracked with AI understanding!
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
How to use this bot (AI understands natural language)

1. Log Equipment Fitment:
22229: MPH TKD/2024/31 fitted on 19/09/2024

2. Log Equipment Removal:
remove MVRH 14623 from 22229 for POH

3. Update Schedule:
SCHEDULE 22229 MAJOR TOH done 24/06/2025 next_due 24/06/2026

4. Update Minor Schedule:
SCHEDULE 22061 MINOR IA done 14/02/2025

5. Check Status:
status of 22229

6. General Notes (AI will extract info):
22229: Panto Pt1 Sr No. 1280 Mersen PCU fitted, TOH2

7. Equipment Search:
/equipment TKD/2024/31

8. Add New Equipment:
/addequipment MPH 19101578 Flowwell 17-09-2019

9. Failure Report:
22721 panto failure AM-12 abnormal

10. Repair Completion:
31450 PT2 repair attended due to air leakage

Simply type your message naturally - the AI will understand and update the sheets automatically!
    """
    await update.message.reply_text(help_text)

# ---------- Add Equipment Command ----------

async def process_add_equipment(data, username):
    """Add new equipment to equipment_master sheet (status = STORAGE)."""
    try:
        equip_type = data.get('equipment_type', '').upper()
        serial_no = data.get('serial_no', '')
        make = data.get('make', '')
        mfg_date = data.get('mfg_date', '')
        remarks = data.get('remarks', '')

        if not equip_type or not serial_no:
            return "❌ Missing equipment type or serial number"

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])

        # Check if equipment already exists (by MFG serial or LOC serial)
        all_records = equip_master.get_all_records(head=1)
        for rec in all_records:
            if rec.get('Serial_No_MFG') == serial_no or rec.get('Serial_No_LOC') == serial_no:
                return f"❌ Equipment {serial_no} already exists in master sheet."

        # Prepare new row (12 columns)
        new_row = [
            serial_no,      # A: Serial_No_MFG
            "",             # B: Serial_No_LOC (can be filled later)
            equip_type,     # C: Equipment_Type
            make,           # D: Make
            mfg_date,       # E: Mfg_Date
            "",             # F: Current_Loco (empty – shopfloor)
            "",             # G: Fitment_Date (empty)
            "",             # H: Last_Overhaul_Date
            "",             # I: Last_Overhaul_Type
            "",             # J: Next_Overhaul_Due
            "STORAGE",      # K: Status (shopfloor)
            remarks[:200]   # L: Notes (trimmed)
        ]

        equip_master.append_row(new_row)

        response = f"✅ Equipment added to **STORAGE** (shopfloor)\n\n"
        response += f"🔧 Type: {equip_type}\n"
        response += f"📌 Serial: {serial_no}\n"
        response += f"🏭 Make: {make or '-'}\n"
        response += f"📅 Mfg Date: {mfg_date or '-'}\n"
        response += f"📍 Location: STORAGE\n"
        response += f"✅ Status: STORAGE (not yet fitted)\n\n"
        response += f"➡️ To fit it to a loco, send e.g.:\n`fit {equip_type} {serial_no} on LOCO_NUMBER fitted on DD-MM-YYYY`"

        return response

    except Exception as e:
        logger.error(f"Error adding equipment: {e}")
        return f"❌ Error adding equipment: {str(e)}"


async def addequipment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add new equipment to equipment_master sheet."""
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /addequipment <type> <serial_no> <make> <mfg_date> [loco_no] [fitment_date]\n\n"
            "Examples:\n"
            "/addequipment MPH 19101578 Flowwell 17-09-2019\n"
            "/addequipment MPH 19101578 Flowwell 17-09-2019 22292 15-09-2024"
        )
        return

    try:
        equip_type = context.args[0].upper()
        serial_no = context.args[1]
        make = context.args[2]
        mfg_date = context.args[3]

        # Optional parameters
        loco_no = context.args[4] if len(context.args) > 4 else ""
        fitment_date = context.args[5] if len(context.args) > 5 else ""

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])

        # Check if equipment already exists
        all_records = equip_master.get_all_records(head=1)
        for rec in all_records:
            if rec.get('Serial_No_MFG') == serial_no or rec.get('Serial_No_LOC') == serial_no:
                await update.message.reply_text(f"❌ Equipment {serial_no} already exists!")
                return

        # Prepare new row (12 columns)
        new_row = [
            serial_no,      # A: Serial_No_MFG
            "",             # B: Serial_No_LOC (can be filled later)
            equip_type,     # C: Equipment_Type
            make,           # D: Make
            mfg_date,       # E: Mfg_Date
            loco_no,        # F: Current_Loco (if provided)
            fitment_date,   # G: Fitment_Date (if provided)
            "",             # H: Last_Overhaul_Date
            "",             # I: Last_Overhaul_Type
            "",             # J: Next_Overhaul_Due
            "IN_SERVICE" if loco_no else "STORAGE",  # K: Status
            ""              # L: Notes
        ]

        equip_master.append_row(new_row)

        response = f"✅ Equipment added successfully!\n\n"
        response += f"🔧 Type: {equip_type}\n"
        response += f"📌 Serial: {serial_no}\n"
        response += f"🏭 Make: {make}\n"
        response += f"📅 Mfg Date: {mfg_date}\n"
        response += f"📍 Current Loco: {loco_no or 'STORAGE'}\n"
        response += f"✅ Status: {'IN_SERVICE' if loco_no else 'STORAGE'}"

        # Optionally log to loco_messages
        if loco_no and fitment_date:
            messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])
            messages_sheet.append_row([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                loco_no,
                f"Equipment added and fitted: {equip_type} {serial_no} on {fitment_date}",
                update.message.from_user.username or "user"
            ])

        await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Error adding equipment: {e}")
        await update.message.reply_text(f"❌ Error adding equipment: {str(e)}")

# ---------- General Message Handler ----------
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler

# Store pending actions in memory (or use context.user_data)
pending_actions = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    text = message.text
    system_time = datetime.now()
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()
    
    parsed = parser.parse_message(text, user.id, username)
    messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])
    
    loco_no = None
    loco_match = re.search(r'\b(\d{5})\b', text)
    if loco_match:
        loco_no = loco_match.group(1)
    
    # Determine log timestamp
    extracted_date = parsed.get('data', {}).get('date')
    if extracted_date:
        try:
            date_obj = datetime.strptime(extracted_date, '%d-%m-%Y')
            log_timestamp = date_obj.strftime('%Y-%m-%d')
        except:
            log_timestamp = system_time.strftime('%Y-%m-%d %H:%M:%S')
    else:
        log_timestamp = system_time.strftime('%Y-%m-%d %H:%M:%S')
    
    messages_sheet.append_row([
        log_timestamp,
        loco_no or 'N/A',
        text,
        username
    ])
    
    # For FITMENT or ADD_EQUIPMENT, show preview and ask for confirmation
    if parsed['type'] in ['FITMENT', 'ADD_EQUIPMENT']:
        # Store the parsed data temporarily
        user_id = str(user.id)
        pending_actions[user_id] = {
            'type': parsed['type'],
            'data': parsed['data'],
            'original_text': text
        }
        
        # Build preview message
        preview = await build_preview(parsed['type'], parsed['data'])
        
        # Create inline keyboard
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{user_id}"),
             InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{user_id}")]
        ])
        
        await message.reply_text(preview, reply_markup=keyboard)
    elif parsed['type'] == 'SCHEDULE':
        result = await process_schedule(parsed['data'])
        await update.message.reply_text(result)
    elif parsed['type'] == 'REMOVAL':
        result = await process_removal(parsed['data'], system_time)
        await update.message.reply_text(result)
    elif parsed['type'] == 'QUERY':
        result = await process_query(parsed['data'])
        await update.message.reply_text(result)
    else:
        if loco_no:
            await update.message.reply_text(f"✅ Message logged for Loco {loco_no}")
        else:
            await update.message.reply_text("✅ Message logged (No loco number found)")

async def build_preview(action_type, data):
    """Build a formatted preview of extracted data."""
    preview = f"📋 **Extracted Information for {action_type}**\n\n"
    preview += f"🔹 **Loco No:** {data.get('loco_no', '-')}\n"
    preview += f"🔹 **Equipment Type:** {data.get('equipment_type', '-')}\n"
    preview += f"🔹 **MFG Serial:** {data.get('serial_no', '-')}\n"
    preview += f"🔹 **LOC Serial:** {data.get('loc_serial', '-')}\n"
    preview += f"🔹 **Make:** {data.get('make', '-')}\n"
    preview += f"🔹 **Mfg Date:** {data.get('mfg_date', '-')}\n"
    preview += f"🔹 **Fitment/Event Date:** {data.get('date', '-')}\n"
    preview += f"🔹 **Schedule:** {data.get('schedule_name', '-')}\n"
    preview += f"🔹 **Last Overhaul Date:** {data.get('last_overhaul_date', '-')}\n"
    preview += f"🔹 **Remarks:** {data.get('remarks', '-')[:100]}\n"
    preview += f"\n✅ **Do you want to proceed with this data?**"
    return preview


# ---------- Schedule Processing ----------
async def process_schedule(data):
    try:
        loco_master = sheet.worksheet(config.SHEETS["LOCO_MASTER"])
        loco_no = data.get('loco_no')
        if not loco_no:
            return "❌ No loco number found in schedule update"
        cell = loco_master.find(loco_no)
        if not cell:
            return f"❌ Loco {loco_no} not found in master sheet"
        row_num = cell.row
        schedule_type = data.get('schedule_type', '')
        schedule_name = data.get('schedule_name', '')
        schedule_date = data.get('schedule_date', '')
        next_due = data.get('next_due', '')
        updates = []
        if schedule_type == 'MAJOR' and schedule_name:
            loco_master.update_cell(row_num, 4, schedule_name)
            if schedule_date:
                loco_master.update_cell(row_num, 5, schedule_date)
            if next_due:
                loco_master.update_cell(row_num, 8, next_due)
            updates.append(f"Major {schedule_name} on {schedule_date}")
        elif schedule_type == 'MINOR' and schedule_name:
            loco_master.update_cell(row_num, 6, schedule_name)
            if schedule_date:
                loco_master.update_cell(row_num, 7, schedule_date)
            updates.append(f"Minor {schedule_name} on {schedule_date}")
        if updates:
            return f"✅ Loco {loco_no} schedule updated: {', '.join(updates)}"
        else:
            return f"⚠️ Could not parse schedule information"
    except Exception as e:
        logger.error(f"Error processing schedule: {e}")
        return f"❌ Error updating schedule: {str(e)}"

# ---------- Fitment Processing ----------
async def process_fitment(data, timestamp):
    """Process equipment fitment: if equipment not found, create it first (using AI data), then fit."""
    try:
        loco_no = data.get('loco_no')
        equipment_type = data.get('equipment_type', 'UNKNOWN')
        serial_no = data.get('serial_no')
        fitment_date = data.get('date') or data.get('fitment_date') or timestamp.strftime('%d-%m-%Y')
        remarks = data.get('remarks', '')
        make = data.get('make', '')
        mfg_date = data.get('mfg_date', '')
        
        if not loco_no or not serial_no:
            return f"❌ Missing loco number or equipment serial number"

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        all_records = equip_master.get_all_records(head=1)
        found_row = None
        
        # Search for existing equipment
        for idx, rec in enumerate(all_records, start=2):
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found_row = idx
                break
        
        created = False
        # If not found, create new equipment
        if not found_row:
            # Prepare minimal data for new equipment
            new_row = [
                serial_no,           # A: Serial_No_MFG
                "",                  # B: Serial_No_LOC
                equipment_type,      # C: Equipment_Type
                make,                # D: Make
                mfg_date,            # E: Mfg_Date
                "",                  # F: Current_Loco (will set after creation)
                "",                  # G: Fitment_Date (will set after creation)
                "",                  # H: Last_Overhaul_Date
                "",                  # I: Last_Overhaul_Type
                "",                  # J: Next_Overhaul_Due
                "STORAGE",           # K: Status (temporary)
                f"Auto-created from fitment: {remarks[:100]}"   # L: Notes
            ]
            equip_master.append_row(new_row)
            # Re-fetch to get the new row index
            all_records = equip_master.get_all_records(head=1)
            for idx, rec in enumerate(all_records, start=2):
                if rec.get('Serial_No_MFG') == serial_no or rec.get('Serial_No_LOC') == serial_no:
                    found_row = idx
                    break
            created = True
        
        # Now fit the equipment (update Current_Loco, Fitment_Date, Status)
        equip_master.update_cell(found_row, 6, loco_no)          # F: Current_Loco
        equip_master.update_cell(found_row, 7, fitment_date)    # G: Fitment_Date
        equip_master.update_cell(found_row, 11, "IN_SERVICE")   # K: Status
        if remarks:
            # Append to existing notes if any, or replace?
            current_notes = equip_master.cell(found_row, 12).value or ""
            if current_notes:
                new_notes = f"{current_notes} | Fitment: {remarks[:100]}"
            else:
                new_notes = f"Fitment: {remarks[:100]}"
            equip_master.update_cell(found_row, 12, new_notes)
        
        # Log to equipment_history (always log the fitment)
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        history_sheet.append_row([
            serial_no,
            fitment_date,
            "FIT",
            "STORAGE" if created else "PREVIOUS_LOCATION",   # From location: if created, STORAGE; else we could fetch previous loco but optional
            loco_no,
            "",
            "",
            f"Fitted on {fitment_date}. {remarks[:100]}"
        ])
        
        # Build response message
        if created:
            response = f"✅ **Equipment created and fitted successfully!**\n\n"
            response += f"🔧 **New Equipment Details:**\n"
            response += f"   Type: {equipment_type}\n"
            response += f"   Serial: {serial_no}\n"
            response += f"   Make: {make or '-'}\n"
            response += f"   Mfg Date: {mfg_date or '-'}\n\n"
            response += f"🚂 **Fitted to Loco:** {loco_no}\n"
            response += f"📅 **Fitment Date:** {fitment_date}\n"
            response += f"📝 **Notes:** {remarks[:100]}\n\n"
            response += f"Equipment status is now **IN_SERVICE**."
        else:
            response = f"✅ **Equipment fitted successfully!**\n\n"
            response += f"🔧 Equipment: {equipment_type} ({serial_no})\n"
            response += f"🚂 Loco: {loco_no}\n"
            response += f"📅 Fitment Date: {fitment_date}\n"
            response += f"📝 Notes: {remarks[:100]}\n\n"
            response += f"Status updated to **IN_SERVICE**."
        
        return response
        
    except Exception as e:
        logger.error(f"Error processing fitment: {e}")
        return f"❌ Error during fitment process: {str(e)}"
        
# ---------- Removal Processing ----------
async def process_removal(data, timestamp):
    try:
        loco_no = data.get('loco_no')
        serial_no = data.get('serial_no')
        removal_date = data.get('date') or data.get('removal_date') or timestamp.strftime('%d-%m-%Y')
        overhaul_type = data.get('overhaul_type', '')
        workshop = data.get('workshop', '')
        remarks = data.get('remarks', '')
        if not serial_no:
            return f"❌ No equipment serial number found"

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        all_records = equip_master.get_all_records(head=1)
        found_row = None
        for idx, rec in enumerate(all_records, start=2):
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found_row = idx
                break
        if not found_row:
            return f"❌ Equipment {serial_no} not found"

        # Update overhaul fields (H, I, J)
        equip_master.update_cell(found_row, 8, removal_date)       # H: Last_Overhaul_Date
        equip_master.update_cell(found_row, 9, overhaul_type)      # I: Last_Overhaul_Type
        try:
            due_date_obj = datetime.strptime(removal_date, '%d-%m-%Y') + timedelta(days=365)
            next_due = due_date_obj.strftime('%d-%m-%Y')
            equip_master.update_cell(found_row, 10, next_due)      # J: Next_Overhaul_Due
        except:
            pass

        # Clear loco association and set status
        equip_master.update_cell(found_row, 6, "")                 # F: Current_Loco
        equip_master.update_cell(found_row, 7, "")                 # G: Fitment_Date
        equip_master.update_cell(found_row, 11, "UNDER_OVERHAUL")  # K: Status

        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        history_sheet.append_row([
            serial_no,
            removal_date,
            "REMOVE",
            loco_no or "",
            "WORKSHOP",
            workshop,
            overhaul_type,
            remarks
        ])

        return f"""✅ Equipment Removed Successfully

🔧 Equipment: {serial_no}
📍 Removed from Loco: {loco_no or 'Unknown'}
📅 Removal Date: {removal_date}
🔨 Overhaul Type: {overhaul_type or 'Not specified'}
🏭 Workshop: {workshop or 'Not specified'}

Equipment status: UNDER_OVERHAUL"""
    except Exception as e:
        logger.error(f"Error processing removal: {e}")
        return f"❌ Error recording removal: {str(e)}"

# ---------- Query Processing ----------
async def process_query(data):
    query_type = data.get('query_type', '')
    query_value = data.get('query_value', '')
    if query_type == 'LOCO_STATUS':
        return await get_loco_status(query_value)
    elif query_type == 'EQUIPMENT_STATUS':
        return await get_equipment_history(query_value)
    else:
        return "❌ Please specify a loco number or equipment serial number"

# ---------- Loco Status ----------
async def get_loco_status(loco_no):
    try:
        loco_master = sheet.worksheet(config.SHEETS["LOCO_MASTER"])
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])

        cell = loco_master.find(loco_no)
        if not cell:
            return f"❌ Loco {loco_no} not found"

        row = loco_master.row_values(cell.row)

        response = f"🚂 LOCO {loco_no} STATUS\n"
        response += f"────────────────────────\n"
        response += f"Type        : {row[1]}\n"
        response += f"DOC         : {format_date(row[2])}\n"
        response += f"Last Major  : {row[3]} ({format_date(row[4])})\n"
        response += f"Last Minor  : {row[5]} ({format_date(row[6])})\n"
        response += f"Next Major  : {format_date(row[7])}\n"
        response += f"Status      : {row[8]}\n"

        response += f"\n🔧 EQUIPMENT FITTED\n"
        response += f"────────────────────────\n"

        all_equipment = equip_master.get_all_records(head=1)
        fitted = []
        for eq in all_equipment:
            current_loco = eq.get('Current_Loco')
            if current_loco and str(current_loco).strip() == str(loco_no):
                fitted.append(eq)

        if fitted:
            for eq in fitted:
                response += f"{eq.get('Equipment_Type', '-')}\n"
                response += f"  MFG Serial : {eq.get('Serial_No_MFG', '-')}\n"
                response += f"  LOC Serial : {eq.get('Serial_No_LOC', '-')}\n"
                response += f"  Make       : {eq.get('Make', '-')}\n"
                # ✅ NEW LINE: Mfg Date
                mfg_date_raw = eq.get('Mfg_Date', '')
                mfg_date_display = format_date(mfg_date_raw) if mfg_date_raw else '-'
                response += f"  Mfg Date   : {mfg_date_display}\n"
                response += f"  Fitment    : {format_date(eq.get('Fitment_Date'))}\n"
                response += f"  Last OH    : {eq.get('Last_Overhaul_Type', '-')} ({format_date(eq.get('Last_Overhaul_Date'))})\n"
                response += f"  Next Due   : {format_date(eq.get('Next_Overhaul_Due'))}\n"
                response += f"  Status     : {eq.get('Status', '-')}\n"
                if eq.get('Notes'):
                    response += f"  Notes      : {eq.get('Notes')}\n"
                response += "\n"
        else:
            response += "No equipment fitted\n"

        response += f"📝 RECENT MESSAGES\n"
        response += f"────────────────────────\n"
        all_messages = messages_sheet.get_all_records()
        loco_messages = [m for m in all_messages if str(m.get('Loco_No', '')) == str(loco_no)]
        if loco_messages:
            for msg in loco_messages[-5:]:
                date = msg.get('Timestamp', '')[:10]
                text = msg.get('Message', '')[:80]
                response += f"{date} | {text}\n"
        else:
            response += "No recent messages\n"

        return response

    except Exception as e:
        logger.error(f"Error getting loco status: {e}")
        return f"❌ Error retrieving status: {str(e)}"

# ---------- Equipment History ----------
async def get_equipment_history(serial_no):
    try:
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])

        all_records = equip_master.get_all_records(head=1)
        found = None
        for rec in all_records:
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found = rec
                break
        if not found:
            return f"❌ Equipment {serial_no} not found"

        response = f"🔩 EQUIPMENT DETAILS\n"
        response += f"────────────────────────\n"
        response += f"Serial MFG   : {found.get('Serial_No_MFG', '-')}\n"
        response += f"Serial LOC   : {found.get('Serial_No_LOC', '-')}\n"
        response += f"Type         : {found.get('Equipment_Type', '-')}\n"
        response += f"Make         : {found.get('Make', '-')}\n"
        response += f"Mfg Date     : {format_date(found.get('Mfg_Date'))}\n\n"
        response += f"Current Loco : {found.get('Current_Loco', 'STORAGE')}\n"
        response += f"Fitment Date : {format_date(found.get('Fitment_Date'))}\n\n"
        response += f"Last OH      : {found.get('Last_Overhaul_Type', '-')} ({format_date(found.get('Last_Overhaul_Date'))})\n"
        response += f"Next Due     : {format_date(found.get('Next_Overhaul_Due'))}\n"
        response += f"Status       : {found.get('Status', '-')}\n"
        if found.get('Notes'):
            response += f"Notes        : {found.get('Notes')}\n"

        response += f"\n📜 HISTORY (Last 10)\n"
        response += f"────────────────────────\n"
        all_history = history_sheet.get_all_records()
        equipment_history = [h for h in all_history if h.get('Serial_No') == serial_no]
        if equipment_history:
            for hist in equipment_history[-10:]:
                date = format_date(hist.get('Event_Date')) if hist.get('Event_Date') else ''
                event = hist.get('Event_Type', '-')
                from_loco = hist.get('From_Loco', '')
                to_loco = hist.get('To_Loco', '')
                remarks = hist.get('Remarks', '')
                line = f"{date} | {event}"
                if from_loco or to_loco:
                    line += f" | {from_loco} -> {to_loco}"
                response += line + "\n"
                if remarks:
                    response += f"   {remarks[:60]}\n"
        else:
            response += "No history available\n"

        return response

    except Exception as e:
        logger.error(f"Error getting equipment history: {e}")
        return f"❌ Error retrieving history: {str(e)}"

# ---------- Command Handlers for /equipment, /status, /schedule ----------
async def equipment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /equipment <serial_no>\nExample: /equipment TKD/2024/31")
        return
    serial_no = ' '.join(context.args)
    result = await get_equipment_history(serial_no)
    await update.message.reply_text(result)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <loco_no>\nExample: /status 22229")
        return
    loco_no = context.args[0]
    result = await get_loco_status(loco_no)
    await update.message.reply_text(result)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /schedule <loco_no> <MAJOR/MINOR> <type> <date> [next_due]\n\n"
            "Examples:\n"
            "/schedule 22229 MAJOR TOH 24-06-2025\n"
            "/schedule 22229 MAJOR TOH 24-06-2025 next_due 24-06-2026\n"
            "/schedule 22061 MINOR IA 14-02-2025"
        )
        return
    loco_no = context.args[0]
    sch_type = context.args[1].upper()
    sch_name = context.args[2].upper()
    sch_date = context.args[3]
    data = {
        'loco_no': loco_no,
        'schedule_type': sch_type,
        'schedule_name': sch_name,
        'schedule_date': sch_date
    }
    if len(context.args) > 4 and context.args[4] == 'next_due' and len(context.args) > 5:
        data['next_due'] = context.args[5]
    result = await process_schedule(data)
    await update.message.reply_text(result)

# ---------- Main ----------
def main():
    # Start health check server (required for Koyeb)
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print("✅ Health check server running on port 8000 (Koyeb)")

    application = Application.builder().token(config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("equipment", equipment_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("addequipment", addequipment_command))  # NEW
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started with polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
