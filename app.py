import asyncio
import logging
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config
from railway_parser import RailwayParser

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Health check server ----------
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

# ---------- Google Sheets ----------
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

# ---------- Helper ----------
def format_date(date_str):
    try:
        if not date_str:
            return "-"
        return datetime.strptime(str(date_str), "%Y-%m-%d").strftime("%d-%m-%Y")
    except:
        return str(date_str)

# ---------- Pending actions storage ----------
pending_actions = {}

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

# ---------- Process functions (actual updates) ----------
async def process_add_equipment(data, username):
    try:
        equip_type = data.get('equipment_type', '').upper()
        serial_no = data.get('serial_no', '')
        make = data.get('make', '')
        mfg_date = data.get('mfg_date', '')
        remarks = data.get('remarks', '')
        loc_serial = data.get('loc_serial', '')

        if not equip_type or not serial_no:
            return "❌ Missing equipment type or serial number"

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        all_records = equip_master.get_all_records(head=1)
        for rec in all_records:
            if rec.get('Serial_No_MFG') == serial_no or rec.get('Serial_No_LOC') == serial_no:
                return f"❌ Equipment {serial_no} already exists."

        new_row = [
            serial_no,      # A
            loc_serial,     # B
            equip_type,     # C
            make,           # D
            mfg_date,       # E
            "",             # F
            "",             # G
            "",             # H
            "",             # I
            "",             # J
            "STORAGE",      # K
            remarks[:200] if remarks else ""
        ]
        equip_master.append_row(new_row)

        return f"✅ Equipment added to **STORAGE**\n🔧 Type: {equip_type}\n📌 Serial: {serial_no}\n🏭 Make: {make or '-'}\n📅 Mfg Date: {mfg_date or '-'}\n📍 LOC Serial: {loc_serial or '-'}"
    except Exception as e:
        logger.error(f"Error adding equipment: {e}")
        return f"❌ Error adding equipment: {str(e)}"

async def process_fitment(data, timestamp):
    try:
        loco_no = data.get('loco_no')
        equipment_type = data.get('equipment_type', 'UNKNOWN')
        serial_no = data.get('serial_no')
        fitment_date = data.get('date') or timestamp.strftime('%d-%m-%Y')
        remarks = data.get('remarks', '')
        make = data.get('make', '')
        mfg_date = data.get('mfg_date', '')
        loc_serial = data.get('loc_serial', '')
        last_overhaul_date = data.get('last_overhaul_date', '')
        schedule_name = data.get('schedule_name', '')

        if not loco_no or not serial_no:
            return "❌ Missing loco number or equipment serial number"

        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        all_records = equip_master.get_all_records(head=1)
        found_row = None
        for idx, rec in enumerate(all_records, start=2):
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found_row = idx
                break

        created = False
        if not found_row:
            new_row = [
                serial_no, loc_serial, equipment_type, make, mfg_date,
                "", "", last_overhaul_date, schedule_name, "",
                "STORAGE", f"Auto-created: {remarks[:100]}"
            ]
            equip_master.append_row(new_row)
            created = True
            all_records = equip_master.get_all_records(head=1)
            for idx, rec in enumerate(all_records, start=2):
                # Use str() to handle Sheets returning numeric cells as int
                if str(rec.get('Serial_No_MFG', '')) == str(serial_no) or str(rec.get('Serial_No_LOC', '')) == str(serial_no):
                    found_row = idx
                    break
            if not found_row:
                # Fallback: newly appended row is always the last one
                found_row = len(all_records) + 1

        # Update loco fields and status
        equip_master.update_cell(found_row, 6, loco_no)          # Current_Loco
        equip_master.update_cell(found_row, 7, fitment_date)    # Fitment_Date
        equip_master.update_cell(found_row, 11, "IN_SERVICE")   # Status

        if loc_serial:
            equip_master.update_cell(found_row, 2, loc_serial)

        if last_overhaul_date:
            equip_master.update_cell(found_row, 8, last_overhaul_date)   # Last_Overhaul_Date
            equip_master.update_cell(found_row, 9, schedule_name)        # Last_Overhaul_Type
            try:
                due = datetime.strptime(last_overhaul_date, '%d-%m-%Y') + timedelta(days=365)
                equip_master.update_cell(found_row, 10, due.strftime('%d-%m-%Y'))
            except:
                pass

        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        history_sheet.append_row([
            serial_no, fitment_date, "FIT", "STORAGE", loco_no, "", schedule_name, remarks
        ])

        if created:
            return f"✅ **Equipment created and fitted successfully!**\n\n🔧 Type: {equipment_type}\n📌 Serial: {serial_no}\n📍 LOC Serial: {loc_serial or '-'}\n🏭 Make: {make or '-'}\n📅 Mfg Date: {mfg_date or '-'}\n🚂 Fitted to Loco: {loco_no}\n📅 Fitment Date: {fitment_date}\n📝 Notes: {remarks[:100]}\n\nStatus: **IN_SERVICE**"
        else:
            return f"✅ **Equipment fitted successfully!**\n\n🔧 Equipment: {equipment_type} ({serial_no})\n🚂 Loco: {loco_no}\n📅 Fitment Date: {fitment_date}\n📝 Notes: {remarks[:100]}\n\nStatus updated to **IN_SERVICE**."
    except Exception as e:
        logger.error(f"Error in fitment: {e}")
        return f"❌ Error during fitment: {str(e)}"

async def process_schedule(data):
    try:
        loco_master = sheet.worksheet(config.SHEETS["LOCO_MASTER"])
        loco_no = data.get('loco_no')
        if not loco_no:
            return "❌ No loco number found"
        cell = loco_master.find(loco_no)
        if not cell:
            return f"❌ Loco {loco_no} not found"
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
            return "⚠️ Could not parse schedule information"
    except Exception as e:
        logger.error(f"Error processing schedule: {e}")
        return f"❌ Error updating schedule: {str(e)}"

async def process_removal(data, timestamp):
    try:
        loco_no = data.get('loco_no')
        serial_no = data.get('serial_no')
        removal_date = data.get('date') or timestamp.strftime('%d-%m-%Y')
        overhaul_type = data.get('overhaul_type', '')
        workshop = data.get('workshop', '')
        remarks = data.get('remarks', '')
        if not serial_no:
            return "❌ No equipment serial number found"
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        all_records = equip_master.get_all_records(head=1)
        found_row = None
        for idx, rec in enumerate(all_records, start=2):
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found_row = idx
                break
        if not found_row:
            return f"❌ Equipment {serial_no} not found"
        equip_master.update_cell(found_row, 8, removal_date)      # H
        equip_master.update_cell(found_row, 9, overhaul_type)     # I
        try:
            due = datetime.strptime(removal_date, '%d-%m-%Y') + timedelta(days=365)
            equip_master.update_cell(found_row, 10, due.strftime('%d-%m-%Y'))
        except:
            pass
        equip_master.update_cell(found_row, 6, "")   # Clear Current_Loco
        equip_master.update_cell(found_row, 7, "")   # Clear Fitment_Date
        equip_master.update_cell(found_row, 11, "UNDER_OVERHAUL")
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        history_sheet.append_row([serial_no, removal_date, "REMOVE", loco_no or "", "WORKSHOP", workshop, overhaul_type, remarks])
        return f"✅ Equipment Removed Successfully\n🔧 Serial: {serial_no}\n📍 From Loco: {loco_no or 'Unknown'}\n📅 Removal Date: {removal_date}\n🔨 Overhaul: {overhaul_type or 'Not specified'}\nStatus: UNDER_OVERHAUL"
    except Exception as e:
        logger.error(f"Error processing removal: {e}")
        return f"❌ Error recording removal: {str(e)}"

async def process_query(data):
    query_type = data.get('query_type', '')
    query_value = data.get('query_value', '')
    if query_type == 'LOCO_STATUS':
        return await get_loco_status(query_value)
    elif query_type == 'EQUIPMENT_STATUS':
        return await get_equipment_history(query_value)
    else:
        return "❌ Please specify a loco number or equipment serial number"

async def get_loco_status(loco_no):
    try:
        loco_master = sheet.worksheet(config.SHEETS["LOCO_MASTER"])
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])
        cell = loco_master.find(loco_no)
        if not cell:
            return f"❌ Loco {loco_no} not found"
        row = loco_master.row_values(cell.row)
        response = f"🚂 LOCO {loco_no} STATUS\n────────────────────────\nType: {row[1]}\nDOC: {format_date(row[2])}\nLast Major: {row[3]} ({format_date(row[4])})\nLast Minor: {row[5]} ({format_date(row[6])})\nNext Major: {format_date(row[7])}\nStatus: {row[8]}\n\n🔧 EQUIPMENT FITTED\n────────────────────────\n"
        all_eq = equip_master.get_all_records(head=1)
        fitted = [e for e in all_eq if str(e.get('Current_Loco', '')) == str(loco_no)]
        if fitted:
            for eq in fitted:
                response += f"{eq.get('Equipment_Type')}:\n  MFG Serial: {eq.get('Serial_No_MFG')}\n  LOC Serial: {eq.get('Serial_No_LOC')}\n  Make: {eq.get('Make')}\n  Mfg Date: {format_date(eq.get('Mfg_Date'))}\n  Fitment: {format_date(eq.get('Fitment_Date'))}\n  Last OH: {eq.get('Last_Overhaul_Type')} ({format_date(eq.get('Last_Overhaul_Date'))})\n  Next Due: {format_date(eq.get('Next_Overhaul_Due'))}\n  Status: {eq.get('Status')}\n  Notes: {eq.get('Notes', '-')}\n\n"
        else:
            response += "No equipment fitted\n"
        response += "📝 RECENT MESSAGES\n────────────────────────\n"
        all_msgs = messages_sheet.get_all_records()
        loco_msgs = [m for m in all_msgs if str(m.get('Loco_No', '')) == str(loco_no)]
        if loco_msgs:
            for msg in loco_msgs[-5:]:
                response += f"{msg.get('Timestamp', '')[:10]} | {msg.get('Message', '')[:80]}\n"
        else:
            response += "No recent messages\n"
        return response
    except Exception as e:
        logger.error(f"Error getting loco status: {e}")
        return f"❌ Error: {str(e)}"

async def get_equipment_history(serial_no):
    try:
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        all_records = equip_master.get_all_records(head=1)
        found = None
        for rec in all_records:
            if str(rec.get('Serial_No_MFG')) == serial_no or str(rec.get('Serial_No_LOC')) == serial_no:
                found = rec
                break
        if not found:
            return f"❌ Equipment {serial_no} not found"
        response = f"🔩 EQUIPMENT DETAILS\n────────────────────────\nSerial MFG: {found.get('Serial_No_MFG')}\nSerial LOC: {found.get('Serial_No_LOC')}\nType: {found.get('Equipment_Type')}\nMake: {found.get('Make')}\nMfg Date: {format_date(found.get('Mfg_Date'))}\nCurrent Loco: {found.get('Current_Loco', 'STORAGE')}\nFitment Date: {format_date(found.get('Fitment_Date'))}\nLast OH: {found.get('Last_Overhaul_Type')} ({format_date(found.get('Last_Overhaul_Date'))})\nNext Due: {format_date(found.get('Next_Overhaul_Due'))}\nStatus: {found.get('Status')}\nNotes: {found.get('Notes', '-')}\n\n📜 HISTORY (Last 10)\n────────────────────────\n"
        all_history = history_sheet.get_all_records()
        eq_history = [h for h in all_history if h.get('Serial_No') == serial_no]
        if eq_history:
            for hist in eq_history[-10:]:
                date = format_date(hist.get('Event_Date')) if hist.get('Event_Date') else ''
                response += f"{date} | {hist.get('Event_Type')} | {hist.get('From_Loco')} -> {hist.get('To_Loco')} | {hist.get('Remarks', '')[:60]}\n"
        else:
            response += "No history\n"
        return response
    except Exception as e:
        logger.error(f"Error getting equipment history: {e}")
        return f"❌ Error: {str(e)}"

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚂 Railway Equipment Tracking Bot. Send /help for commands.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commands:\n/status <loco_no>\n/equipment <serial>\n/schedule ...\n/addequipment ...\nOr just type natural language messages.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <loco_no>")
        return
    result = await get_loco_status(context.args[0])
    await update.message.reply_text(result)

async def equipment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /equipment <serial>")
        return
    result = await get_equipment_history(' '.join(context.args))
    await update.message.reply_text(result)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text("Usage: /schedule <loco_no> <MAJOR/MINOR> <type> <date> [next_due]")
        return
    data = {
        'loco_no': context.args[0],
        'schedule_type': context.args[1].upper(),
        'schedule_name': context.args[2].upper(),
        'schedule_date': context.args[3]
    }
    if len(context.args) > 4 and context.args[4] == 'next_due' and len(context.args) > 5:
        data['next_due'] = context.args[5]
    result = await process_schedule(data)
    await update.message.reply_text(result)

async def addequipment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please use natural language: 'Add equipment MPH serial 123 Make Flowwell Mfg 01-2020'")

# ---------- Main message handler with edit mode ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    # Edit mode: user is responding to an edit request
    if context.user_data.get('awaiting_edit') and context.user_data.get('user_id') == user_id:
        await receive_edit_value(update, context)
        return

    text = update.message.text
    username = update.message.from_user.username or "user"
    system_time = datetime.now()

    parsed = parser.parse_message(text, user_id, username)
    messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])

    # Log message
    loco_no = None
    loco_match = re.search(r'\b(\d{5})\b', text)
    if loco_match:
        loco_no = loco_match.group(1)
    extracted_date = parsed.get('data', {}).get('date')
    if extracted_date:
        try:
            log_dt = datetime.strptime(extracted_date, '%d-%m-%Y')
            log_ts = log_dt.strftime('%Y-%m-%d')
        except:
            log_ts = system_time.strftime('%Y-%m-%d %H:%M:%S')
    else:
        log_ts = system_time.strftime('%Y-%m-%d %H:%M:%S')
    messages_sheet.append_row([log_ts, loco_no or 'N/A', text, username])

    # For FITMENT or ADD_EQUIPMENT, show preview and ask confirmation
    if parsed['type'] in ['FITMENT', 'ADD_EQUIPMENT']:
        pending_actions[user_id] = {
            'type': parsed['type'],
            'data': parsed['data'],
            'original_text': text
        }
        preview = await build_preview(parsed['type'], parsed['data'])
        keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{user_id}"),
         InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{user_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]
        ])
        await update.message.reply_text(preview, reply_markup=keyboard)
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

async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_edit'):
        return
    
    user_id = context.user_data.get('user_id')
    if not user_id:
        await update.message.reply_text("❌ Session expired. Please send the message again.")
        context.user_data['awaiting_edit'] = False
        return
    
    pending = pending_actions.get(user_id)
    if not pending:
        await update.message.reply_text("❌ Action expired. Please send the message again.")
        context.user_data['awaiting_edit'] = False
        return
    
    field = pending.get('editing_field')
    if not field:
        await update.message.reply_text("❌ No field selected for editing.")
        context.user_data['awaiting_edit'] = False
        return
    
    new_value = update.message.text.strip()
    
    # Update the pending data with new value
    pending['data'][field] = new_value
    
    # Build updated preview
    preview = await build_preview(pending['type'], pending['data'])
    
    # Create keyboard with Confirm and Edit More buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{user_id}"),
         InlineKeyboardButton("✏️ Edit More", callback_data=f"edit_{user_id}")]
    ])
    
    safe_field = escape_markdown(field.replace('_', ' ').title(), version=1)
    safe_value = escape_markdown(new_value, version=1)
    await update.message.reply_text(
        f"✅ Field *{safe_field}* updated to: `{safe_value}`\n\n{preview}",
        reply_markup=keyboard, parse_mode='Markdown'
    )
    
    # Reset edit mode
    context.user_data['awaiting_edit'] = False
    context.user_data['user_id'] = None

# ---------- Callback handlers ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split('_')
    if len(parts) < 2:
        return
    user_id = parts[1]
    action = parts[0]

    pending = pending_actions.get(user_id)
    if not pending:
        await query.edit_message_text("❌ Action expired. Please send message again.")
        return

    if action == 'confirm':
        if pending['type'] == 'FITMENT':
            result = await process_fitment(pending['data'], datetime.now())
        else:
            result = await process_add_equipment(pending['data'], query.from_user.username)
        await query.edit_message_text(result)
        del pending_actions[user_id]
    elif action == 'edit':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Loco No", callback_data=f"editfield_{user_id}_loco_no"),
             InlineKeyboardButton("Equipment Type", callback_data=f"editfield_{user_id}_equipment_type")],
            [InlineKeyboardButton("MFG Serial", callback_data=f"editfield_{user_id}_serial_no"),
             InlineKeyboardButton("LOC Serial", callback_data=f"editfield_{user_id}_loc_serial")],
            [InlineKeyboardButton("Make", callback_data=f"editfield_{user_id}_make"),
             InlineKeyboardButton("Mfg Date", callback_data=f"editfield_{user_id}_mfg_date")],
            [InlineKeyboardButton("Fitment Date", callback_data=f"editfield_{user_id}_date"),
             InlineKeyboardButton("Schedule", callback_data=f"editfield_{user_id}_schedule_name")],
            [InlineKeyboardButton("Overhaul Date", callback_data=f"editfield_{user_id}_last_overhaul_date"),
             InlineKeyboardButton("Remarks", callback_data=f"editfield_{user_id}_remarks")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{user_id}")]
        ])
        await query.edit_message_text("✏️ Which field would you like to edit?", reply_markup=keyboard)
    elif action == 'cancel':
        del pending_actions[user_id]
        await query.edit_message_text("❌ Action cancelled.")

async def edit_field_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid edit request.")
        return
    
    user_id = parts[1]
    # Join all remaining parts to reconstruct field names that contain underscores
    # e.g. 'editfield_12345_loco_no'.split('_') = ['editfield','12345','loco','no']
    # so we must join parts[2:] -> 'loco_no'
    field = '_'.join(parts[2:])
    
    # Map display names to actual field keys
    field_mapping = {
        'loco_no': 'loco_no',
        'equipment_type': 'equipment_type',
        'serial_no': 'serial_no',
        'loc_serial': 'loc_serial',
        'make': 'make',
        'mfg_date': 'mfg_date',
        'date': 'date',
        'schedule_name': 'schedule_name',
        'last_overhaul_date': 'last_overhaul_date',
        'remarks': 'remarks'
    }
    
    actual_field = field_mapping.get(field, field)
    
    pending = pending_actions.get(user_id)
    if not pending:
        await query.edit_message_text("❌ Action expired. Please send the message again.")
        return
    
    pending['editing_field'] = actual_field
    
    await query.edit_message_text(
        f"✏️ **Editing: {field.replace('_', ' ').title()}**\n\n"
        f"Current value: `{pending['data'].get(actual_field, '-')}`\n\n"
        f"Please send the new value for this field.",
        parse_mode='Markdown'
    )
    
    context.user_data['awaiting_edit'] = True
    context.user_data['user_id'] = user_id
    
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    if len(parts) < 2:
        return
    user_id = parts[1]
    if user_id in pending_actions:
        del pending_actions[user_id]
    await query.edit_message_text("❌ Action cancelled.")

# ---------- Main ----------
def main():
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print("✅ Health check server running on port 8000")

    application = Application.builder().token(config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("equipment", equipment_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("addequipment", addequipment_command))

    application.add_handler(CallbackQueryHandler(callback_handler, pattern='^(confirm|edit|cancel)_.*'))
    application.add_handler(CallbackQueryHandler(edit_field_handler, pattern='^editfield_.*'))

    # Only ONE message handler – it handles both normal messages and edit responses
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started with polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
