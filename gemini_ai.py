import json
import os
import urllib.request
import urllib.error


class GeminiError(Exception):
    pass


def _to_iso_date(date_str: str) -> str:
    s = (date_str or "").strip()
    if not s:
        return ""
    import re
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", s)
    if not m:
        return s
    dd, mm, yyyy = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def extract_structured_fields(raw_text: str, identifier: str = None) -> dict:
    """
    Use Groq API (Llama) to extract fields from arbitrary text.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GeminiError("GROQ_API_KEY is not set")

    model = os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant"

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
        "  * 'main_equipment' - Generic equipment like TSC, Clutch, etc.\n"
        "  * 'loco_info_only' - General info that should ONLY go to Loco Info sheet (not the 3 main sheets)\n"
        "- Use the one-word identifier hint to help classify if provided.\n"
        "- For loco_info_only: create a brief one-line summary of the information.\n"
        "- For the other types: also create a one-line summary for Loco Info.\n"
        "- Date format: convert to DD.MM.YYYY (e.g., 15.04.2026)\n"
        "- Loco No: extract the locomotive number (3-6 digits)\n"
        "- summary: create a concise one-line description for Loco Info sheet (max 50 chars, include key info like item, status, sr no)\n\n"
        "Output format:\n"
        "{\n"
        '  "message_type": "...",\n'
        '  "worksheet_name": "DGA Report" | "Panto Status" | null,\n'
        '  "row": [values in correct column order for the sheet],\n'
        '  "loco_info": {\n'
        '    "date": "DD.MM.YYYY",\n'
        '    "loco_no": "XXXXX",\n'
        '    "summary": "brief one-line summary"\n'
        "  }\n"
        "}\n\n"
        "Sheet column orders:\n"
        "- DGA Report: [Date, Loco No, Schedule, Oil, CH4, C2H4, C2H6, C2H2, H2, CO, CO2, BDV, Remark]\n"
        "- Panto Status: [Date, Loco No, PT1 Pressure, PT2 Pressure, PT1 ORD, PT2 ORD, PT1 ADD, PT2 ADD]\n"
        "- Main Equipment (sheet1): [Date, Loco No, Item, Side, Status, Sr No, Mfg, Make, Type, Reason, Schedule, O/H Date, W/O No]"
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
                "date": _to_iso_date(loco_info.get("date", "")),
                "loco_no": str(loco_info.get("loco_no", "")).strip(),
                "summary": str(loco_info.get("summary", "")).strip(),
            }
        }
    except Exception as e:
        raise GeminiError(f"Groq returned unreadable JSON: {e}") from e