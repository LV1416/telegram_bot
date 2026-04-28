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
        Parse any message using Groq AI first, then validate and enrich with regex
        """
        # Step 1: Try Groq AI parsing first
        if self.use_ai:
            ai_result = self._groq_parse_message(text)
            if ai_result and ai_result.get('confidence', 0) >= 0.6:
                # Step 2: Validate and enrich with regex
                validated_result = self._validate_and_enrich(ai_result, text)
                if validated_result:
                    return validated_result
        
        # Step 3: Fallback to regex-only parsing
        return self._regex_parse_message(text, username)
    
    def _groq_parse_message(self, text):
        """
        Use Groq AI (Llama 3.3) to understand any message format
        """
        prompt = f"""You are a railway equipment tracking assistant. Analyze this message from a railway workshop and extract structured data.

Message: "{text}"

Return ONLY valid JSON in this exact format (no other text, no markdown, no explanation):

{{
    "type": "FITMENT or REMOVAL or SCHEDULE or QUERY or GENERAL",
    "confidence": 0.0 to 1.0,
    "data": {{
        "loco_no": "5-digit number or null",
        "equipment_type": "MPH/MVRH/PANTO/GR/SMGR/TRANSFORMER or null",
        "serial_no": "equipment serial number or null",
        "date": "YYYY-MM-DD or null",
        "schedule_type": "MAJOR/MINOR or null",
        "schedule_name": "TOH1/TOH2/TOH3/TOH4/IOH/POH/MTR/IA/IC or null",
        "next_due": "YYYY-MM-DD or null",
        "workshop": "TKD/DBSI/DAHOD/BSL/LKO/ALD or null",
        "overhaul_type": "TOH1/TOH2/IOH/POH/MTR or null",
        "remarks": "extracted remarks or full message",
        "action": "fit/remove/replace/repair/overhaul/fail or null",
        "status": "fitted/removed/under_repair/overhauled/failed or null"
    }}
}}

Examples:
"22229: MPH TKD/2024/31 fitted on 19/09/2024"
-> {{"type":"FITMENT","confidence":0.95,"data":{{"loco_no":"22229","equipment_type":"MPH","serial_no":"TKD/2024/31","date":"2024-09-19","action":"fit","status":"fitted"}}}}

"remove MVRH 14623 from 22229 for POH"
-> {{"type":"REMOVAL","confidence":0.95,"data":{{"loco_no":"22229","equipment_type":"MVRH","serial_no":"14623","action":"remove","overhaul_type":"POH","status":"removed"}}}}

"31642 panto pt1 sr no 1280 mersen fitted with pcu"
-> {{"type":"FITMENT","confidence":0.85,"data":{{"loco_no":"31642","equipment_type":"PANTO","serial_no":"1280","remarks":"mersen with pcu","action":"fit","status":"fitted"}}}}

"22721 panto failure AM-12 abnormal"
-> {{"type":"GENERAL","confidence":0.9,"data":{{"loco_no":"22721","equipment_type":"PANTO","remarks":"failure AM-12 abnormal","action":"fail","status":"failed"}}}}

"Schedule 22229 TOH done 24/06/2025 next due 24/06/2026"
-> {{"type":"SCHEDULE","confidence":0.95,"data":{{"loco_no":"22229","schedule_type":"MAJOR","schedule_name":"TOH","date":"2025-06-24","next_due":"2026-06-24"}}}}

"status of 22229"
-> {{"type":"QUERY","confidence":0.95,"data":{{"loco_no":"22229","query_type":"LOCO_STATUS"}}}}

"what is history of TKD/2024/31"
-> {{"type":"QUERY","confidence":0.95,"data":{{"query_type":"EQUIPMENT_STATUS","serial_no":"TKD/2024/31"}}}}

For any message, try your best to extract information. If uncertain, set confidence lower.
Only respond with valid JSON. Do not include any markdown formatting or explanations."""

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
            
            # Clean response (remove markdown if any)
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            result = json.loads(result_text)
            return result
            
        except Exception as e:
            print(f"Groq AI parsing error: {e}")
            return None
    
    def _validate_and_enrich(self, ai_result, original_text):
        """
        Validate Groq results and enrich with regex for missing fields
        """
        if not ai_result or not isinstance(ai_result, dict):
            return None
        
        data = ai_result.get('data', {})
        
        # Validate loco number (must be 5 digits)
        if data.get('loco_no'):
            loco_match = re.search(r'\b(\d{5})\b', str(data['loco_no']))
            if loco_match:
                data['loco_no'] = loco_match.group(1)
            else:
                loco_match = re.search(r'\b(\d{5})\b', original_text)
                data['loco_no'] = loco_match.group(1) if loco_match else None
        
        # Validate serial number format
        if data.get('serial_no'):
            serial_str = str(data['serial_no'])
            if not re.search(r'[A-Z0-9]{3,}[-/][A-Z0-9/]+', serial_str):
                serial_match = re.search(r'([A-Z0-9]{3,}[-/][A-Z0-9/]+)', original_text.upper())
                if serial_match:
                    data['serial_no'] = serial_match.group(1)
        
        # Validate equipment type
        if data.get('equipment_type'):
            eq_type = str(data['equipment_type']).upper()
            if eq_type not in self.equipment_types:
                for eq in self.equipment_types:
                    if eq in original_text.upper():
                        data['equipment_type'] = eq
                        break
        
        # Validate schedule type
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
        
        # Normalize dates
        if data.get('date'):
            data['date'] = self._normalize_date(str(data['date']))
        if data.get('next_due'):
            data['next_due'] = self._normalize_date(str(data['next_due']))
        
        # Add original message for logging
        data['original_message'] = original_text
        
        # Set default type if missing
        if not ai_result.get('type'):
            if data.get('action') == 'fit':
                ai_result['type'] = 'FITMENT'
            elif data.get('action') == 'remove':
                ai_result['type'] = 'REMOVAL'
            elif data.get('schedule_name'):
                ai_result['type'] = 'SCHEDULE'
            else:
                ai_result['type'] = 'GENERAL'
        
        ai_result['data'] = data
        return ai_result
    
    def _regex_parse_message(self, text, username):
        """
        Fallback: Regex-only parsing when Groq AI fails
        """
        text_lower = text.lower()
        
        if 'schedule' in text_lower:
            return self._regex_parse_schedule(text)
        elif 'fit' in text_lower or 'fitted' in text_lower or 'laga' in text_lower:
            return self._regex_parse_fitment(text)
        elif 'remove' in text_lower or 'removed' in text_lower or 'nikal' in text_lower:
            return self._regex_parse_removal(text)
        elif 'status' in text_lower or 'batao' in text_lower:
            return self._regex_parse_query(text)
        else:
            return self._regex_parse_general(text, username)
    
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
        date_match = self._extract_date(text)
        if date_match:
            result['data']['fitment_date'] = date_match
        else:
            result['data']['fitment_date'] = datetime.now().strftime('%Y-%m-%d')
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
            result['data']['removal_date'] = datetime.now().strftime('%Y-%m-%d')
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
        serial_pattern = r'([A-Z0-9]{3,}[-/][A-Z0-9/]+)'
        match = re.search(serial_pattern, text_upper)
        if match:
            return {'type': 'UNKNOWN', 'serial': match.group(1)}
        return None
    
    def _extract_date(self, text):
        pattern = r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})'
        match = re.search(pattern, text)
        if match:
            day, month, year = match.groups()
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        months = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                  'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
        for month_name, month_num in months.items():
            pattern = rf'(\d{{1,2}})\s+{month_name}[a-z]*\s+(\d{{4}})'
            match = re.search(pattern, text.lower())
            if match:
                day, year = match.groups()
                return f"{year}-{month_num}-{day.zfill(2)}"
        if 'today' in text.lower():
            return datetime.now().strftime('%Y-%m-%d')
        if 'yesterday' in text.lower():
            return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        return None
    
    def _normalize_date(self, date_str):
        if not date_str or date_str == 'null':
            return None
        patterns = [
            (r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', lambda d,m,y: f"{y}-{m.zfill(2)}-{d.zfill(2)}"),
            (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda y,m,d: f"{y}-{m.zfill(2)}-{d.zfill(2)}"),
        ]
        for pattern, formatter in patterns:
            match = re.search(pattern, str(date_str))
            if match:
                return formatter(*match.groups())
        return str(date_str)