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

# ---------- Helper to parse DD-MM-YYYY from sheet ----------
def parse_date_dmy(date_str):
    """Convert DD-MM-YYYY string to datetime object, or return None."""
    if not date_str or date_str in ['', '-', 'N/A']:
        return None
    try:
        # Handle possible Excel serial numbers? Assume string.
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

8. Failure Report:
22721 panto failure AM-12 abnormal

9. Repair Completion:
31450 PT2 repair attended due to air leakage

Simply type your message naturally - the AI will understand and update the sheets automatically!
    """
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    text = message.text
    timestamp = datetime.now()
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()
    
    parsed = parser.parse_message(text, user.id, username)
    messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])
    
    loco_no = None
    loco_match = re.search(r'\b(\d{5})\b', text)
    if loco_match:
        loco_no = loco_match.group(1)
    
    # Always save message
    messages_sheet.append_row([
        timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        loco_no or 'N/A',
        text,
        username
    ])
    
    if parsed['type'] == 'SCHEDULE':
        result = await process_schedule(parsed['data'])
        await update.message.reply_text(result)
    elif parsed['type'] == 'FITMENT':
        result = await process_fitment(parsed['data'], timestamp)
        await update.message.reply_text(result)
    elif parsed['type'] == 'REMOVAL':
        result = await process_removal(parsed['data'], timestamp)
        await update.message.reply_text(result)
    elif parsed['type'] == 'QUERY':
        result = await process_query(parsed['data'])
        await update.message.reply_text(result)
    else:
        if loco_no:
            await update.message.reply_text(f"✅ Message logged for Loco {loco_no}")
        else:
            await update.message.reply_text("✅ Message logged (No loco number found)")

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
        schedule_date = data.get('schedule_date', '')  # expected DD-MM-YYYY
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
    try:
        loco_no = data.get('loco_no')
        equipment_type = data.get('equipment_type')
        serial_no = data.get('serial_no')
        fitment_date = data.get('date') or data.get('fitment_date') or timestamp.strftime('%d-%m-%Y')
        remarks = data.get('remarks', '')
        if not loco_no or not serial_no:
            return f"❌ Missing loco number or equipment serial number"
        
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        # Search in both serial columns (A and B)
        all_records = equip_master.get_all_records(head=1)
        found_row = None
        for idx, rec in enumerate(all_records, start=2):
            if str(rec.get('Serial_No_MFG', '')) == serial_no or str(rec.get('Serial_No_LOC', '')) == serial_no:
                found_row = idx
                break
        if not found_row:
            return f"❌ Equipment {serial_no} not found. Please add it first"
        
        # Update Current_Loco (column F), Fitment_Date (G), Status (K)
        equip_master.update_cell(found_row, 6, loco_no)   # Current_Loco
        equip_master.update_cell(found_row, 7, fitment_date)  # Fitment_Date
        equip_master.update_cell(found_row, 11, "IN_SERVICE")  # Status (col K)
        if remarks:
            equip_master.update_cell(found_row, 12, remarks)   # Notes (col L)
        
        # Log to equipment_history
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        history_sheet.append_row([
            serial_no,
            fitment_date,
            "FIT",
            "STORAGE",
            loco_no,
            "",
            "",
            remarks
        ])
        
        return f"""✅ Equipment Fitted Successfully

📍 Loco: {loco_no}
🔧 Equipment: {equipment_type or 'Unknown'} ({serial_no})
📅 Fitment Date: {fitment_date}
📝 Notes: {remarks[:100]}...

Equipment has been marked as IN_SERVICE."""
    except Exception as e:
        logger.error(f"Error processing fitment: {e}")
        return f"❌ Error recording fitment: {str(e)}"

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
        
        if overhaul_type:
            equip_master.update_cell(found_row, 8, overhaul_type)   # Last_Overhaul_Type (col I)
            equip_master.update_cell(found_row, 7, removal_date)    # Last_Overhaul_Date (col H? Wait careful)
            # Actually after your 12-col layout:
            # H = Last_Overhaul_Date, I = Last_Overhaul_Type, J = Next_Overhaul_Due
            equip_master.update_cell(found_row, 8, removal_date)      # H
            equip_master.update_cell(found_row, 9, overhaul_type)     # I
            # Calculate next due (add 1 year) - store as DD-MM-YYYY
            try:
                due_date_obj = datetime.strptime(removal_date, '%d-%m-%Y') + timedelta(days=365)
                next_due = due_date_obj.strftime('%d-%m-%Y')
                equip_master.update_cell(found_row, 10, next_due)     # J
            except:
                pass
        
        equip_master.update_cell(found_row, 11, "UNDER_OVERHAUL")   # Status (K)
        equip_master.update_cell(found_row, 6, "")   # Clear Current_Loco (F)
        equip_master.update_cell(found_row, 7, "")   # Clear Fitment_Date (G)
        
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

# ---------- Loco Status (Fixed equipment display) ----------
async def get_loco_status(loco_no):
    try:
        loco_master = sheet.worksheet(config.SHEETS["LOCO_MASTER"])
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        messages_sheet = sheet.worksheet(config.SHEETS["LOCO_MESSAGES"])
        
        # Find loco in master
        cell = loco_master.find(loco_no)
        if not cell:
            return f"❌ Loco {loco_no} not found"
        row = loco_master.row_values(cell.row)
        # Columns: A:Loco_No, B:Type, C:DOC, D:Last_Major_Sch_Type, E:Last_Major_Sch_Date, F:Last_Minor_Sch_Type, G:Last_Minor_Sch_Date, H:Next_Major_Due, I:Status
        response = f"🚂 LOCO {loco_no} STATUS\n\n"
        response += f"📌 Type: {row[1]}\n"
        response += f"📅 DOC: {row[2]}\n"
        response += f"🔧 Last Major: {row[3]} ({row[4]})\n"
        response += f"⚙️ Last Minor: {row[5]} ({row[6]})\n"
        response += f"📊 Next Major Due: {row[7]}\n"
        response += f"✅ Status: {row[8]}\n\n"
        
        # Get equipment fitted to this loco
        response += "🔧 Equipment Fitted:\n"
        all_equipment = equip_master.get_all_records(head=1)  # returns list of dicts with keys from row 1
        fitted = []
        for eq in all_equipment:
            # Current_Loco is column F (index 5 in zero-based list)
            current_loco = eq.get('Current_Loco')
            if current_loco and str(current_loco).strip() == str(loco_no):
                fitted.append(eq)
        
        if fitted:
            for eq in fitted:
                equip_type = eq.get('Equipment_Type', '')
                serial_mfg = eq.get('Serial_No_MFG', '')
                serial_loc = eq.get('Serial_No_LOC', '')
                serial_display = serial_loc if serial_loc else serial_mfg
                status_icon = "✅" if eq.get('Status') == 'IN_SERVICE' else "⚠️"
                response += f"{status_icon} {equip_type}: {serial_display}"
                next_overhaul = eq.get('Next_Overhaul_Due')
                if next_overhaul:
                    response += f" (Overhaul due: {next_overhaul})"
                response += "\n"
        else:
            response += "No equipment fitted\n"
        
        # Recent messages
        response += f"\n📝 Recent Messages (last 5):\n"
        all_messages = messages_sheet.get_all_records()
        loco_messages = [m for m in all_messages if str(m.get('Loco_No', '')) == str(loco_no)]
        for msg in loco_messages[-5:]:
            date = msg.get('Timestamp', '')[:10]
            response += f"• {date}: {msg.get('Message', '')[:80]}...\n"
        return response
    except Exception as e:
        logger.error(f"Error getting loco status: {e}")
        return f"❌ Error retrieving status: {str(e)}"

# ---------- Equipment History (12 columns) ----------
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
        
        response = f"🔧 EQUIPMENT: {serial_no}\n\n"
        response += f"📌 MFG Serial: {found.get('Serial_No_MFG', '')}\n"
        response += f"📍 LOC Serial: {found.get('Serial_No_LOC', '')}\n"
        response += f"🔧 Type: {found.get('Equipment_Type', '')}\n"
        response += f"🏭 Make: {found.get('Make', '')}\n"
        response += f"📅 Mfg Date: {found.get('Mfg_Date', '')}\n"
        response += f"🚂 Current Loco: {found.get('Current_Loco', 'STORAGE')}\n"
        response += f"📅 Fitment Date: {found.get('Fitment_Date', '')}\n"
        response += f"🔨 Last Overhaul: {found.get('Last_Overhaul_Type', '')} ({found.get('Last_Overhaul_Date', '')})\n"
        response += f"📊 Next Overhaul Due: {found.get('Next_Overhaul_Due', '')}\n"
        response += f"✅ Status: {found.get('Status', '')}\n"
        if found.get('Notes'):
            response += f"📝 Notes: {found.get('Notes', '')}\n"
        
        # History from equipment_history sheet (based on serial_no)
        response += "\n📜 Complete History:\n"
        all_history = history_sheet.get_all_records()
        eq_history = [h for h in all_history if h.get('Serial_No') == serial_no]
        if eq_history:
            for hist in eq_history[-10:]:
                response += f"• {hist.get('Event_Date')}: {hist.get('Event_Type')} "
                if hist.get('From_Loco'):
                    response += f"from {hist.get('From_Loco')} "
                if hist.get('To_Loco'):
                    response += f"to {hist.get('To_Loco')} "
                response += f"- {hist.get('Remarks', '')[:50]}\n"
        else:
            response += "No history found\n"
        return response
    except Exception as e:
        logger.error(f"Error getting equipment history: {e}")
        return f"❌ Error retrieving history: {str(e)}"

# ---------- Command handlers ----------
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
    sch_date = context.args[3]   # Expected DD-MM-YYYY
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot started with polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
