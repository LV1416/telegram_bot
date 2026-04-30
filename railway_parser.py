import re
import json
import os
from datetime import datetime, timedelta
from groq import Groq

class RailwayParser:
    def __init__(self, use_ai=True):
        self.use_ai = use_ai
        self.equipment_types = ['MPH', 'MVRH', 'PANTO', 'GR', 'SMGR', 'TRANSFORMER']
        self.major_sch_types = ['TOH1', 'TOH2', 'TOH3', 'TOH4', 'IOH', 'POH', 'MTR']
        self.minor_sch_types = ['IA', 'IC']
        
        # Initialize Groq AI
        if use_ai:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                print("WARNING: GROQ_API_KEY not set. AI features disabled.")
                self.use_ai = False
            else:
                self.client = Groq(api_key=api_key)
                self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    def parse_message(self, text, user_id=None, username=None):
        """
        Parse any message using:
        1) Structured key-value parser (for multi‑line forms)
        2) Groq AI (if available)
        3) Regex fallback
        """
        # 1) Try structured parser (e.g., multi‑line "Fit\nDate - ...")
        structured_result = self._parse_structured_fitment(text)
        if structured_result and structured_result.get('data', {}).get('serial_no'):
            return structured_result
        
        # 2) Try Groq AI
        if self.use_ai:
            ai_result = self._groq_parse_message(text)
            if ai_result and ai_result.get('confidence', 0) >= 0.6:
                validated_result = self._validate_and_enrich(ai_result, text)
                if validated_result:
                    return validated_result
        
        # 3) Fallback to regex-only parsing
        return self._regex_parse_message(text, username)
    
    # ---------- Structured key-value parser (for forms) ----------
    def _parse_structured_fitment(self, text):
        """Handle messages like:
        Fit
        Date - 30/04/2026
        Loco No - 22292
        Item - MPH
        ...
        """
        result = {'type': 'FITMENT', 'data': {}, 'confidence': 0.9}
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Date
            if 'Date' in line or 'date' in line:
                date_match = re.search(r'[\d]{1,2}[/-][\d]{1,2}[/-][\d]{2,4}', line)
                if date_match:
                    result['data']['date'] = self._normalize_date_to_dd_mm_yyyy(date_match.group())
            # Loco No
            elif 'Loco No' in line or 'loco' in line.lower():
                loco_match = re.search(r'\b(\d{5})\b', line)
                if loco_match:
                    result['data']['loco_no'] = loco_match.group(1)
            # Item / Equipment Type
            elif 'Item' in line:
                for eq in self.equipment_types:
                    if eq.upper() in line.upper():
                        result['data']['equipment_type'] = eq.upper()
                        break
            # Sr. No. / serial
            elif 'Sr. No.' in line or 'Sr.' in line or 'Serial' in line or 'sr no' in line.lower():
                # Extract value AFTER the '-' separator (e.g. "Sr. No. - 14050354" -> "14050354")
                serial_match = re.search(r'[-:]\s*([\dA-Za-z/]+)\s*$', line)
                if serial_match:
                    result['data']['serial_no'] = serial_match.group(1)
            # Make
            elif 'Make' in line:
                make_match = re.search(r'Make\s*-\s*(\w+)', line, re.IGNORECASE)
                if make_match:
                    result['data']['make'] = make_match.group(1)
            # Mfg date
            elif 'Mfg' in line:
                mfg_match = re.search(r'Mfg\s*[\s-]*(\d{2}/\d{4}|\d{2}-\d{4}|\d{4})', line, re.IGNORECASE)
                if mfg_match:
                    result['data']['mfg_date'] = mfg_match.group(1)
            # Overhaul date (O/h)
            elif 'O/h' in line or 'overhaul' in line.lower():
                oh_match = re.search(r'[\d]{1,2}[/-][\d]{1,2}[/-][\d]{2,4}', line)
                if oh_match:
                    result['data']['last_overhaul_date'] = self._normalize_date_to_dd_mm_yyyy(oh_match.group())
            # Schedule
            elif 'Schedule' in line:
                for sch in self.major_sch_types + self.minor_sch_types:
                    if sch.upper() in line.upper():
                        result['data']['schedule_name'] = sch.upper()
                        result['data']['schedule_type'] = 'MAJOR' if sch.upper() in self.major_sch_types else 'MINOR'
                        break
            # LOC serial (Tkd/...)
            elif 'Tkd' in line or 'TKD' in line:
                loc_match = re.search(r'(Tkd[/][\d]{4}/[\d]{2}|TKD[/][\d]{4}/[\d]{2})', line, re.IGNORECASE)
                if loc_match:
                    result['data']['loc_serial'] = loc_match.group(1)
            # Other info (remarks)
            else:
                if 'INFO' in line or 'DBSI' in line or 'remarks' not in result['data']:
                    if 'remarks' not in result['data']:
                        result['data']['remarks'] = line
                    else:
                        result['data']['remarks'] += " " + line
        return result if result['data'].get('serial_no') and result['data'].get('loco_no') else None
    
    # ---------- Groq AI parsing ----------
    def _groq_parse_message(self, text):
        prompt = f"""You are a railway equipment tracking assistant. Analyze this message from a railway workshop and extract structured data.

Message: "{text}"

Return ONLY valid JSON in this exact format (no other text, no markdown, no explanation):

{{
    "type": "FITMENT or REMOVAL or SCHEDULE or QUERY or GENERAL or ADD_EQUIPMENT",
    "confidence": 0.0 to 1.0,
    "data": {{
        "loco_no": "5-digit number or null",
        "equipment_type": "MPH/MVRH/PANTO/GR/SMGR/TRANSFORMER or null",
        "serial_no": "equipment serial number or null",
        "loc_serial": "location serial like Tkd/2026/05 or null",
        "date": "DD-MM-YYYY or null",
        "schedule_type": "MAJOR/MINOR or null",
        "schedule_name": "TOH1/TOH2/TOH3/TOH4/IOH/POH/MTR/IA/IC or null",
        "next_due": "DD-MM-YYYY or null",
        "workshop": "TKD/DBSI/DAHOD/BSL/LKO/ALD or null",
        "overhaul_type": "TOH1/TOH2/IOH/POH/MTR or null",
        "remarks": "extracted remarks or full message",
        "action": "fit/remove/replace/repair/overhaul/fail/add or null",
        "status": "fitted/removed/under_repair/overhauled/failed/storage or null",
        "make": "manufacturer name or null",
        "mfg_date": "manufacturing date (DD-MM-YYYY or MM/YYYY) or null",
        "last_overhaul_date": "last overhaul date DD-MM-YYYY or null"
    }}
}}

Additional instructions:
- For ADD_EQUIPMENT, set status = "storage".
- For FITMENT, extract loc_serial if present (e.g., Tkd/2026/05).
- Convert all dates to DD-MM-YYYY format.
- If a field is not present, use null.
- Only respond with valid JSON.

Examples:
"22292: MPH 19101578 fitted on 15-09-2024 for TOH, Make Flowwell, Mfg 17-09-2019, Tkd/2026/05"
-> {{"type":"FITMENT","confidence":0.95,"data":{{"loco_no":"22292","equipment_type":"MPH","serial_no":"19101578","loc_serial":"Tkd/2026/05","date":"15-09-2024","make":"Flowwell","mfg_date":"17-09-2019","action":"fit","status":"fitted","remarks":"TOH"}}}}

"Add equipment MPH serial 19101578, Make Flowwell, Mfg 17-09-2019"
-> {{"type":"ADD_EQUIPMENT","confidence":0.95,"data":{{"equipment_type":"MPH","serial_no":"19101578","make":"Flowwell","mfg_date":"17-09-2019","status":"storage","action":"add"}}}}

"remove MPH 19101578 from 22292 to storage"
-> {{"type":"REMOVAL","confidence":0.95,"data":{{"loco_no":"22292","equipment_type":"MPH","serial_no":"19101578","action":"remove","status":"removed","remarks":"to storage"}}}}

"Schedule 22229 MAJOR TOH 24-06-2025 next_due 24-06-2026"
-> {{"type":"SCHEDULE","confidence":0.95,"data":{{"loco_no":"22229","schedule_type":"MAJOR","schedule_name":"TOH","date":"24-06-2025","next_due":"24-06-2026"}}}}

"status of 22229"
-> {{"type":"QUERY","confidence":0.95,"data":{{"loco_no":"22229","query_type":"LOCO_STATUS"}}}}

For any message, try your best to extract information. If uncertain, set confidence lower.
Only respond with valid JSON."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a JSON-only railway data extractor. Never output anything except valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            result_text = response.choices[0].message.content.strip()
            # Clean markdown
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            return json.loads(result_text)
        except Exception as e:
            print(f"Groq AI parsing error: {e}")
            return None
    
    def _validate_and_enrich(self, ai_result, original_text):
        if not ai_result or not isinstance(ai_result, dict):
            return None
        data = ai_result.get('data', {})
        
        # Loco number
        if data.get('loco_no'):
            loco_match = re.search(r'\b(\d{5})\b', str(data['loco_no']))
            if loco_match:
                data['loco_no'] = loco_match.group(1)
            else:
                loco_match = re.search(r'\b(\d{5})\b', original_text)
                data['loco_no'] = loco_match.group(1) if loco_match else None
        
        # Serial numbers
        if data.get('serial_no'):
            # Accept as is
            pass
        else:
            serial_match = re.search(r'([A-Z0-9]{3,}[-/]?[A-Z0-9/]+|[0-9]+)', original_text.upper())
            if serial_match:
                data['serial_no'] = serial_match.group(1)
        
        # LOC serial
        loc_serial_match = re.search(r'(Tkd[/][\d]{4}/[\d]{2}|TKD[/][\d]{4}/[\d]{2})', original_text, re.IGNORECASE)
        if loc_serial_match:
            data['loc_serial'] = loc_serial_match.group(1)
        
        # Equipment type
        if data.get('equipment_type'):
            eq_type = str(data['equipment_type']).upper()
            if eq_type not in self.equipment_types:
                for eq in self.equipment_types:
                    if eq in original_text.upper():
                        data['equipment_type'] = eq
                        break
        
        # Schedule name
        if data.get('schedule_name'):
            sch_name = str(data['schedule_name']).upper()
            if sch_name not in self.major_sch_types + self.minor_sch_types:
                for sch in self.major_sch_types + self.minor_sch_types:
                    if sch in original_text.upper():
                        data['schedule_name'] = sch
                        if sch in self.major_sch_types:
                            data['schedule_type'] = 'MAJOR'
                        else:
                            data['schedule_type'] = 'MINOR'
                        break
        
        # Normalise all date fields to DD-MM-YYYY
        for field in ['date', 'next_due', 'mfg_date', 'last_overhaul_date', 'fitment_date', 'removal_date', 'schedule_date']:
            if field in data and data[field]:
                data[field] = self._normalize_date_to_dd_mm_yyyy(str(data[field]))
        
        data['original_message'] = original_text
        
        # Set type if missing
        if not ai_result.get('type'):
            if data.get('action') == 'fit':
                ai_result['type'] = 'FITMENT'
            elif data.get('action') == 'remove':
                ai_result['type'] = 'REMOVAL'
            elif data.get('action') == 'add':
                ai_result['type'] = 'ADD_EQUIPMENT'
            elif data.get('schedule_name'):
                ai_result['type'] = 'SCHEDULE'
            else:
                ai_result['type'] = 'GENERAL'
        
        # For ADD_EQUIPMENT, ensure status STORAGE
        if ai_result['type'] == 'ADD_EQUIPMENT':
            if not data.get('status'):
                data['status'] = 'STORAGE'
            if not data.get('action'):
                data['action'] = 'add'
        
        # For FITMENT, if status missing, set to 'fitted'
        if ai_result['type'] == 'FITMENT' and not data.get('status'):
            data['status'] = 'fitted'
        
        ai_result['data'] = data
        return ai_result
    
    # ---------- Regex fallback (unchanged but improved) ----------
    def _regex_parse_message(self, text, username):
        text_lower = text.lower()
        if 'add equipment' in text_lower or 'new equipment' in text_lower or 'create equipment' in text_lower:
            return self._regex_parse_add_equipment(text)
        elif 'schedule' in text_lower:
            return self._regex_parse_schedule(text)
        elif 'fit' in text_lower or 'fitted' in text_lower or 'laga' in text_lower:
            return self._regex_parse_fitment(text)
        elif 'remove' in text_lower or 'removed' in text_lower or 'nikal' in text_lower:
            return self._regex_parse_removal(text)
        elif 'status' in text_lower or 'batao' in text_lower:
            return self._regex_parse_query(text)
        else:
            return self._regex_parse_general(text, username)
    
    def _regex_parse_add_equipment(self, text):
        result = {'type': 'ADD_EQUIPMENT', 'data': {}, 'confidence': 0.8}
        for eq in self.equipment_types:
            if eq in text.upper():
                result['data']['equipment_type'] = eq
                break
        serial_match = re.search(r'serial\s+[#:]?\s*([A-Z0-9\-/]+)', text, re.IGNORECASE)
        if serial_match:
            result['data']['serial_no'] = serial_match.group(1)
        else:
            words = re.findall(r'[A-Z0-9\-/]+', text.upper())
            if words:
                result['data']['serial_no'] = words[-1]
        make_match = re.search(r'make\s+([A-Za-z0-9]+)', text, re.IGNORECASE)
        if make_match:
            result['data']['make'] = make_match.group(1)
        date_match = self._extract_date(text)
        if date_match:
            result['data']['mfg_date'] = date_match
        result['data']['status'] = 'STORAGE'
        result['data']['action'] = 'add'
        return result
    
    def _regex_parse_schedule(self, text):
        result = {'type': 'SCHEDULE', 'data': {}, 'confidence': 0.7}
        loco_match = re.search(r'\b(\d{5})\b', text)
        if loco_match:
            result['data']['loco_no'] = loco_match.group(1)
        text_upper = text.upper()
        for sch_type in self.major_sch_types:
            if sch_type in text_upper:
                result['data']['schedule_type'] = 'MAJOR'
                result['data']['schedule_name'] = sch_type
                break
        else:
            for sch_type in self.minor_sch_types:
                if sch_type in text_upper:
                    result['data']['schedule_type'] = 'MINOR'
                    result['data']['schedule_name'] = sch_type
                    break
        date_match = self._extract_date(text)
        if date_match:
            result['data']['schedule_date'] = date_match
        return result
    
    def _regex_parse_fitment(self, text):
        result = {'type': 'FITMENT', 'data': {}, 'confidence': 0.7}
        loco_match = re.search(r'\b(\d{5})\b', text)
        if loco_match:
            result['data']['loco_no'] = loco_match.group(1)
        equip_match = self._extract_equipment(text)
        if equip_match:
            result['data']['equipment_type'] = equip_match['type']
            result['data']['serial_no'] = equip_match['serial']
        # LOC serial
        loc_serial_match = re.search(r'(Tkd[/][\d]{4}/[\d]{2}|TKD[/][\d]{4}/[\d]{2})', text, re.IGNORECASE)
        if loc_serial_match:
            result['data']['loc_serial'] = loc_serial_match.group(1)
        date_match = self._extract_date(text)
        if date_match:
            result['data']['fitment_date'] = date_match
        else:
            result['data']['fitment_date'] = datetime.now().strftime('%d-%m-%Y')
        result['data']['remarks'] = text
        return result
    
    def _regex_parse_removal(self, text):
        result = {'type': 'REMOVAL', 'data': {}, 'confidence': 0.7}
        loco_match = re.search(r'\b(\d{5})\b', text)
        if loco_match:
            result['data']['loco_no'] = loco_match.group(1)
        equip_match = self._extract_equipment(text)
        if equip_match:
            result['data']['equipment_type'] = equip_match['type']
            result['data']['serial_no'] = equip_match['serial']
        for sch_type in self.major_sch_types + self.minor_sch_types:
            if sch_type.lower() in text.lower():
                result['data']['overhaul_type'] = sch_type
                break
        date_match = self._extract_date(text)
        if date_match:
            result['data']['removal_date'] = date_match
        else:
            result['data']['removal_date'] = datetime.now().strftime('%d-%m-%Y')
        result['data']['remarks'] = text
        return result
    
    def _regex_parse_query(self, text):
        result = {'type': 'QUERY', 'data': {}, 'confidence': 0.7}
        loco_match = re.search(r'\b(\d{5})\b', text)
        if loco_match:
            result['data']['query_type'] = 'LOCO_STATUS'
            result['data']['query_value'] = loco_match.group(1)
        equip_match = self._extract_equipment(text)
        if equip_match:
            result['data']['query_type'] = 'EQUIPMENT_STATUS'
            result['data']['query_value'] = equip_match['serial']
        return result
    
    def _regex_parse_general(self, text, username):
        result = {'type': 'GENERAL', 'data': {'message': text, 'user': username or 'unknown'}, 'confidence': 0.5}
        loco_match = re.search(r'\b(\d{5})\b', text)
        if loco_match:
            result['data']['loco_no'] = loco_match.group(1)
        return result
    
    def _extract_equipment(self, text):
        text_upper = text.upper()
        for eq_type in self.equipment_types:
            pattern = rf'{eq_type}\s+([A-Z0-9/]+\s*[A-Z0-9/]*)'
            match = re.search(pattern, text_upper)
            if match:
                return {'type': eq_type, 'serial': match.group(1).strip()}
        serial_pattern = r'([A-Z0-9]{3,}[-/][A-Z0-9/]+|[0-9]+)'
        match = re.search(serial_pattern, text_upper)
        if match:
            return {'type': 'UNKNOWN', 'serial': match.group(1)}
        return None
    
    def _extract_date(self, text):
        # DD/MM/YYYY or DD-MM-YYYY
        pattern = r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})'
        match = re.search(pattern, text)
        if match:
            day, month, year = match.groups()
            return f"{day.zfill(2)}-{month.zfill(2)}-{year}"
        # DD Month YYYY
        months = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                  'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
        for month_name, month_num in months.items():
            pattern = rf'(\d{{1,2}})\s+{month_name}[a-z]*\s+(\d{{4}})'
            match = re.search(pattern, text.lower())
            if match:
                day, year = match.groups()
                return f"{day.zfill(2)}-{month_num}-{year}"
        if 'today' in text.lower():
            return datetime.now().strftime('%d-%m-%Y')
        if 'yesterday' in text.lower():
            return (datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')
        return None
    
    def _normalize_date_to_dd_mm_yyyy(self, date_str):
        if not date_str or date_str in ['', '-', 'N/A', 'null']:
            return ''
        # Already DD-MM-YYYY
        if re.match(r'^\d{2}-\d{2}-\d{4}$', date_str):
            return date_str
        # YYYY-MM-DD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            parts = date_str.split('-')
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        # DD/MM/YYYY
        if re.match(r'^\d{2}/\d{2}/\d{4}$', date_str):
            parts = date_str.split('/')
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
        # MM/YYYY (e.g., 10/2013) – keep as is, will be stored as string
        if re.match(r'^\d{2}/\d{4}$', date_str):
            return date_str
        # Try extraction
        extracted = self._extract_date(date_str)
        if extracted:
            return extracted
        return date_str
