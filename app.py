import asyncio
import logging
import re
import os
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config
from railway_parser import RailwayParser

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Google Sheets
def init_google_sheets():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # Check if credentials.json exists (created by config.py)
    if os.path.exists(config.CREDENTIALS_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(config.CREDENTIALS_FILE, scope)
    else:
        # Try to get from environment variable directly
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds_dict = json.loads(creds_json)
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scope)
        else:
            raise Exception("No Google credentials found! Set GOOGLE_CREDENTIALS_JSON")
    
    client = gspread.authorize(creds)
    sheet = client.open(config.SHEET_NAME)
    return sheet

sheet = init_google_sheets()
parser = RailwayParser(use_ai=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🚂 **Railway Equipment Tracking Bot** (Powered by Grok AI)

**Commands:**
/start - Show this menu
/help - Get help
/status <loco_no> - Get loco status
/equipment <serial_no> - Get equipment history

**Just type naturally - AI understands:**
• "22229: MPH TKD/2024/31 fitted on 19/09/2024"
• "SCHEDULE 22229 MAJOR TOH done 24/06/2025 next_due 24/06/2026"
• "remove MVRH 14623 from 22229 for POH"
• "status of 22229"
• "31642 panto pt1 sr no 1280 mersen fitted"
• "22721 panto failure AM-12 abnormal"

All messages are automatically logged and tracked with AI understanding!
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 **How to use this bot** (AI understands natural language)

**1. Log Equipment Fitment:**
`22229: MPH TKD/2024/31 fitted on 19/09/2024`

**2. Log Equipment Removal:**
`remove MVRH 14623 from 22229 for POH`

**3. Update Schedule:**
`SCHEDULE 22229 MAJOR TOH done 24/06/2025 next_due 24/06/2026`

**4. Update Minor Schedule:**
`SCHEDULE 22061 MINOR IA done 14/02/2025`

**5. Check Status:**
`status of 22229`

**6. General Notes (AI will extract info):**
`22229: Panto Pt1 Sr No. 1280 Mersen PCU fitted, TOH2`

**7. Equipment Search:**
`/equipment TKD/2024/31`

**8. Failure Report:**
`22721 panto failure AM-12 abnormal`

**9. Repair Completion:**
`31450 PT2 repair attended due to air leakage`

Simply type your message naturally - the AI will understand and update the sheets automatically!
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
        await update.message.reply_text(result, parse_mode='Markdown')
    else:
        if loco_no:
            await update.message.reply_text(f"✅ Message logged for Loco {loco_no}")
        else:
            await update.message.reply_text("✅ Message logged (No loco number found)")

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

async def process_fitment(data, timestamp):
    try:
        loco_no = data.get('loco_no')
        equipment_type = data.get('equipment_type')
        serial_no = data.get('serial_no')
        fitment_date = data.get('date') or data.get('fitment_date') or timestamp.strftime('%Y-%m-%d')
        remarks = data.get('remarks', '')
        if not loco_no or not serial_no:
            return f"❌ Missing loco number or equipment serial number"
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        try:
            cell = equip_master.find(serial_no)
            if cell:
                row_num = cell.row
                equip_master.update_cell(row_num, 5, loco_no)
                equip_master.update_cell(row_num, 6, fitment_date)
                equip_master.update_cell(row_num, 10, "IN_SERVICE")
                if remarks:
                    equip_master.update_cell(row_num, 11, remarks)
            else:
                return f"❌ Equipment {serial_no} not found. Please add it first"
        except gspread.exceptions.CellNotFound:
            return f"❌ Equipment {serial_no} not found. Please add it first"
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
        return f"""✅ **Equipment Fitted Successfully**
📍 Loco: {loco_no}
🔧 Equipment: {equipment_type or 'Unknown'} ({serial_no})
📅 Fitment Date: {fitment_date}
📝 Notes: {remarks[:100]}...
Equipment has been marked as IN_SERVICE."""
    except Exception as e:
        logger.error(f"Error processing fitment: {e}")
        return f"❌ Error recording fitment: {str(e)}"

async def process_removal(data, timestamp):
    try:
        loco_no = data.get('loco_no')
        serial_no = data.get('serial_no')
        removal_date = data.get('date') or data.get('removal_date') or timestamp.strftime('%Y-%m-%d')
        overhaul_type = data.get('overhaul_type', '')
        workshop = data.get('workshop', '')
        remarks = data.get('remarks', '')
        if not serial_no:
            return f"❌ No equipment serial number found"
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        try:
            cell = equip_master.find(serial_no)
            if not cell:
                return f"❌ Equipment {serial_no} not found"
            row_num = cell.row
            if overhaul_type:
                equip_master.update_cell(row_num, 8, overhaul_type)
                equip_master.update_cell(row_num, 7, removal_date)
                due_date = datetime.strptime(removal_date, '%Y-%m-%d') + timedelta(days=365)
                equip_master.update_cell(row_num, 9, due_date.strftime('%Y-%m-%d'))
            equip_master.update_cell(row_num, 10, "UNDER_OVERHAUL")
            equip_master.update_cell(row_num, 5, "")
            equip_master.update_cell(row_num, 6, "")
        except gspread.exceptions.CellNotFound:
            return f"❌ Equipment {serial_no} not found"
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
        return f"""✅ **Equipment Removed Successfully**
🔧 Equipment: {serial_no}
📍 Removed from Loco: {loco_no or 'Unknown'}
📅 Removal Date: {removal_date}
🔨 Overhaul Type: {overhaul_type or 'Not specified'}
🏭 Workshop: {workshop or 'Not specified'}
Equipment status: UNDER_OVERHAUL"""
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
        response = f"🚂 **LOCO {loco_no} STATUS**\n\n"
        response += f"📌 **Type:** {row[1]}\n"
        response += f"📅 **DOC:** {row[2]}\n"
        response += f"🔧 **Last Major:** {row[3]} ({row[4]})\n"
        response += f"⚙️ **Last Minor:** {row[5]} ({row[6]})\n"
        response += f"📊 **Next Major Due:** {row[7]}\n"
        response += f"✅ **Status:** {row[8]}\n\n"
        response += "**🔧 Equipment Fitted:**\n"
        all_equipment = equip_master.get_all_records()
        fitted = [e for e in all_equipment if str(e.get('Current_Loco', '')) == str(loco_no)]
        if fitted:
            for eq in fitted:
                status_icon = "✅" if eq.get('Status') == 'IN_SERVICE' else "⚠️"
                response += f"{status_icon} **{eq.get('Equipment_Type')}:** {eq.get('Serial_No')} "
                if eq.get('Next_Overhaul_Due'):
                    response += f"(Overhaul due: {eq.get('Next_Overhaul_Due')})\n"
                else:
                    response += "\n"
        else:
            response += "No equipment fitted\n"
        response += f"\n**📝 Recent Messages (last 5):**\n"
        all_messages = messages_sheet.get_all_records()
        loco_messages = [m for m in all_messages if str(m.get('Loco_No', '')) == str(loco_no)]
        for msg in loco_messages[-5:]:
            date = msg.get('Timestamp', '')[:10]
            response += f"• {date}: {msg.get('Message', '')[:80]}...\n"
        return response
    except Exception as e:
        logger.error(f"Error getting loco status: {e}")
        return f"❌ Error retrieving status: {str(e)}"

async def get_equipment_history(serial_no):
    try:
        equip_master = sheet.worksheet(config.SHEETS["EQUIPMENT_MASTER"])
        history_sheet = sheet.worksheet(config.SHEETS["EQUIPMENT_HISTORY"])
        cell = equip_master.find(serial_no)
        if not cell:
            return f"❌ Equipment {serial_no} not found"
        row = equip_master.row_values(cell.row)
        response = f"🔧 **EQUIPMENT: {serial_no}**\n\n"
        response += f"📌 **Type:** {row[1]}\n"
        response += f"🏭 **Make:** {row[2]}\n"
        response += f"📅 **Mfg Date:** {row[3]}\n"
        response += f"📍 **Current Loco:** {row[4] or 'STORAGE'}\n"
        response += f"📅 **Fitment Date:** {row[5]}\n"
        response += f"🔨 **Last Overhaul:** {row[7]} ({row[6]})\n"
        response += f"📊 **Next Overhaul Due:** {row[8]}\n"
        response += f"✅ **Status:** {row[9]}\n\n"
        response += "**📜 Complete History:**\n"
        all_history = history_sheet.get_all_records()
        equipment_history = [h for h in all_history if h.get('Serial_No') == serial_no]
        if equipment_history:
            for hist in equipment_history[-10:]:
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

async def equipment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /equipment <serial_no>\nExample: /equipment TKD/2024/31")
        return
    serial_no = ' '.join(context.args)
    result = await get_equipment_history(serial_no)
    await update.message.reply_text(result, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <loco_no>\nExample: /status 22229")
        return
    loco_no = context.args[0]
    result = await get_loco_status(loco_no)
    await update.message.reply_text(result, parse_mode='Markdown')

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: /schedule <loco_no> <MAJOR/MINOR> <type> <date> [next_due]\n\n"
            "Examples:\n"
            "/schedule 22229 MAJOR TOH 2025-06-24\n"
            "/schedule 22229 MAJOR TOH 2025-06-24 next_due 2026-06-24\n"
            "/schedule 22061 MINOR IA 2025-02-14"
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

def main():
    application = Application.builder().token(config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("equipment", equipment_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    if config.WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
            webhook_url=config.WEBHOOK_URL
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()