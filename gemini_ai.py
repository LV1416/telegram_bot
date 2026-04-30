import json
import os
import urllib.request
import urllib.error


class GeminiError(Exception):
    pass


def _to_display_date(date_str: str) -> str:
    s = (date_str or "").strip()
    if not s:
        return ""
    import re
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", s)
    if not m:
        return s
    dd, mm, yyyy = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    return f"{dd}.{mm}.{yyyy}"


def extract_structured_fields(raw_text: str, identifier: str = None) -> dict:
    """
    Use Groq API (Llama) to extract fields from arbitrary text.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GeminiError("GROQ_API_KEY is not set")

    model = os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"

    url = "https://api.groq.com/openai/v1/chat/completions"

    identifier_hint = ""
    if identifier:
        identifier_hint = f"\n- User provided ONE-WORD identifier: '{identifier}' - use this to help classify the message type."

    system_prompt = (
        "You are a data extraction system for locomotive maintenance logs.\n"
        "Analyze the message and extract structured data.\n"
        "Rules:\n"
        "- Return ONLY valid JSON (no markdown, no extra text).\n"
        "- message_type options:\n"
        "  * 'dga_report' - DGA oil/gas analysis report\n"
        "  * 'panto_status' - Pantograph pressure/height status\n"
        "  * 'main_equipment' - Generic equipment like TSC, Clutch, MPH, etc.\n"
        "  * 'loco_info_only' - General info that should ONLY go to Loco Info sheet (not the 3 main sheets)\n"
        "- Use the one-word identifier hint to help classify if provided.\n"
        "- For loco_info_only: write a complete description capturing ALL key information from the message.\n"
        "- For the other types: write a detailed summary for Loco Info covering all relevant fields.\n"
        "- Date format: convert to DD.MM.YYYY (e.g., 15.04.2026). Short year like '13/02/26' means 2026.\n"
        "- Loco No: extract the locomotive number (3-6 digits)\n"
        "- summary: write a COMPLETE, detailed description. Include ALL of: item name, side (L/R), status, Sr No, Make, Type, Mfg, Reason, Schedule, O/H Date, W/O No — whichever fields are present in the message. Do NOT truncate. No character limit.\n"
        "\n"
        "FIELD EXTRACTION RULES for Main Equipment:\n"
        "- 'Sr No' column: match any of these labels: 'Sr. No.', 'Sr No', 'Sr. No', 'S.No', 'S. No.', 'Serial No', 'Sr.No.'. ALWAYS populate this field when any serial number is present.\n"
        "- 'Mfg' column: the manufacturing date/year. Labels: 'Mfg', 'Mfg.', 'Manufacture', 'Manufactured'. A line like 'Mfg 10/2013' means Mfg = '10/2013'.\n"
        "- 'O/H Date' column: overhaul date. Labels: 'O/h', 'O/H Date', 'OH Date', 'Overhaul Date'. A line like 'O/h 13/02/26' means O/H Date = '13.02.2026'.\n"
        "- 'W/O No' column: work order number. Labels: 'W/O No', 'WO No', 'Tkd/...'. A code like 'Tkd/2026/05' should be placed in W/O No.\n"
        "- 'Type' column: type/model code (e.g., R-3, DBSI 3011). A line like 'INFO. DBSI 3011' means Type = 'DBSI 3011'.\n"
        "- Lines WITHOUT a separator (dash/colon/equals) may still carry field values — infer the field from context.\n"
        "\n"
        "Output format:\n"
        "{\n"
        '  "message_type": "...",\n'
        '  "worksheet_name": "DGA Report" | "Panto Status" | null,\n'
        '  "row": [values in correct column order for the sheet],\n'
        '  "loco_info": {\n'
        '    "date": "DD.MM.YYYY",\n'
        '    "loco_no": "XXXXX",\n'
        '    "summary": "complete detailed summary with all extracted fields"\n'
        "  }\n"
        "}\n\n"
        "Sheet column orders:\n"
        "- DGA Report: [Date, Loco No, Schedule, Oil, CH4, C2H4, C2H6, C2H2, H2, CO, CO2, BDV, Remark]\n"
        "- Panto Status: [Date, Loco No, PT1 Pressure, PT2 Pressure, PT1 ORD, PT2 ORD, PT1 ADD, PT2 ADD]\n"
        "- Main Equipment (sheet1): [Date, Loco No, Item, Side, Status, Sr No, Mfg, Make, Type, Reason, Schedule, O/H Date, W/O No]\n"
        "  NOTE: Sr No is column index 5 (0-based). Never leave it empty if any serial number appears in the message."
    )

    user_prompt = f"Message to parse:{identifier_hint}\n{raw_text}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0 (compatible; GroqClient/1.0)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise GeminiError(f"Groq HTTP error {e.code}: {body}") from e
    except Exception as e:
        raise GeminiError(f"Groq request failed: {e}") from e

    try:
        text = data["choices"][0]["message"]["content"]
        
        try:
            extracted = json.loads(text)
        except json.JSONDecodeError:
            content_start = text.find('{')
            content_end = text.rfind('}') + 1
            if content_start >= 0 and content_end > content_start:
                extracted = json.loads(text[content_start:content_end])
            else:
                raise ValueError("No JSON found in response")

        message_type = extracted.get("message_type", "").strip().lower()
        worksheet_name = extracted.get("worksheet_name")
        row = extracted.get("row", [])
        loco_info = extracted.get("loco_info", {})

        if not message_type:
            raise ValueError("Missing message_type")

        return {
            "message_type": message_type,
            "worksheet_name": worksheet_name,
            "row": row if isinstance(row, list) else [],
            "loco_info": {
                "date": _to_display_date(loco_info.get("date", "")),
                "loco_no": str(loco_info.get("loco_no", "")).strip(),
                "summary": str(loco_info.get("summary", "")).strip(),
            }
        }
    except Exception as e:
        raise GeminiError(f"Groq returned unreadable JSON: {e}") from e