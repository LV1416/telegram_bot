import json
import os
import urllib.request
import urllib.error


class GeminiError(Exception):
    pass


def _endpoint_for_model(model: str) -> str:
    model = (model or "").strip()
    if not model:
        model = "gemini-2.5-flash"
    # Gemini API expects: /v1beta/models/{model}:generateContent
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def extract_structured_fields(raw_text: str) -> tuple[str, dict]:
    """
    Use Gemini to extract fields from arbitrary text.

    Returns: (message_type, fields_dict)
      - message_type: one of dga_report, panto_status, main_equipment
      - fields_dict: normalized key/value dictionary (string -> string)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GEMINI_API_KEY is not set")

    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    url = _endpoint_for_model(model)

    # IMPORTANT: We provide separate schemas per message type so the model can
    # differentiate correctly instead of mixing fields across formats.
    schemas = {
        "dga_report": {
            "description": "DGA oil/gas report",
            "required": ["date", "loco no", "schedule"],
            "fields": [
                "date",
                "loco no",
                "schedule",
                "oil",
                "ch4",
                "c2h4",
                "c2h6",
                "c2h2",
                "h2",
                "co",
                "co2",
                "bdv",
                "remark",
            ],
        },
        "panto_status": {
            "description": "Pantograph status / pressure report",
            "required": ["date", "loco no", "pt1 pressure", "pt2 pressure"],
            "fields": [
                "date",
                "loco no",
                "pt1 pressure",
                "pt2 pressure",
                "pt1 ord",
                "pt2 ord",
                "pt1 add",
                "pt2 add",
            ],
        },
        "main_equipment": {
            "description": "Main equipment report",
            "required": ["date", "loco no", "item", "status"],
            "fields": [
                "date",
                "loco no",
                "item",
                "side",
                "status",
                "sr no",
                "mfg",
                "make",
                "type",
                "reason",
                "schedule",
                "oh date",
                "wo no",
            ],
        },
    }

    prompt = (
        "You convert messy Telegram messages into structured data for Google Sheets.\n"
        "Determine which ONE message_type it matches, extract only fields for that type, and normalize keys.\n"
        "Rules:\n"
        "- Return ONLY valid JSON (no markdown, no extra text).\n"
        "- message_type must be one of: dga_report, panto_status, main_equipment.\n"
        "- fields must be an object of string->string values.\n"
        "- Use only canonical keys listed in the chosen schema.\n"
        "- Do NOT invent values. If a field is missing, omit it.\n"
        "- For panto_status: if a line includes height (e.g. 'PT1 pressure 4.6 & height 3760mm'), put the height into 'pt1 ord'/'pt2 ord'. If BOTH heights are present, set 'pt1 add' and 'pt2 add' to 'Active'.\n"
        "- Pick message_type by evidence: keywords (e.g. 'DGA', 'PANTO') and/or which required fields are present.\n\n"
        f"Message type schemas:\n{json.dumps(schemas, ensure_ascii=False)}\n\n"
        f"Raw message:\n{raw_text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise GeminiError(f"Gemini HTTP error {e.code}: {body}") from e
    except Exception as e:
        raise GeminiError(f"Gemini request failed: {e}") from e

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        extracted = json.loads(text)
        message_type = extracted.get("message_type", "")
        fields = extracted.get("fields", {}) or {}
        if not isinstance(message_type, str) or not isinstance(fields, dict):
            raise ValueError("Invalid JSON shape")
        # Force all values to strings for downstream logic.
        clean_fields = {}
        for k, v in fields.items():
            if k is None:
                continue
            ks = str(k).strip().lower()
            if ks == "":
                continue
            clean_fields[ks] = "" if v is None else str(v).strip()
        return message_type.strip().lower(), clean_fields
    except Exception as e:
        raise GeminiError(f"Gemini returned unreadable JSON: {e}") from e

