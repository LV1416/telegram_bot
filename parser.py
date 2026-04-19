import re

def _norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\.\-_\/]+", " ", s)
    return s


def parse_key_values(text: str) -> dict:
    """
    Parse a free-form message into key/value pairs.

    Accepts separators like:
    - "Key - Value"
    - "Key: Value"
    - "Key = Value"
    Case/order/extra whitespace do not matter.
    """
    fields: dict[str, str] = {}
    if not text:
        return fields

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Skip obvious headers but keep everything else.
        if _norm_key(line) in {"dga report", "panto status"}:
            continue

        m = re.match(r"^\s*([^:=\-]{1,60}?)\s*(?:-|:|=)\s*(.*?)\s*$", line)
        if not m:
            continue

        key = _norm_key(m.group(1))
        value = (m.group(2) or "").strip()
        if key:
            fields[key] = value

    return fields


_ALIASES: dict[str, list[str]] = {
    # Common
    "date": ["date"],
    "loco no": ["loco no", "loco no.", "loco", "locono"],
    "schedule": ["schedule"],
    "remark": ["remark", "remarks"],

    # Main equipment
    "item": ["item"],
    "side": ["side"],
    "status": ["status"],
    "sr no": ["sr no", "sr. no", "srno", "serial no", "serial number"],
    "mfg": ["mfg", "manufacturer"],
    "make": ["make"],
    "type": ["type"],
    "reason": ["reason"],
    "oh date": ["o/h date", "oh date", "overhaul date"],
    "wo no": ["w/o no", "wo no", "work order no", "work order"],

    # Emp record
    "token no": ["token no", "token number"],
    "emp hrms id": ["emp hrms id", "hrms id", "employee hrms id"],
    "bill unit": ["bill unit"],
    "emp name": ["emp name", "employee name", "name"],
    "department": ["department", "dept"],
    "designation": ["designation", "post"],
    "aadhar number": ["aadhar number", "aadhaar number", "aadhar", "aadhaar"],
    "permanent address": ["permanent address", "address"],
    "place of posting": ["place of posting", "posting place"],
    "mobile no": ["mobile no", "mobile", "phone", "phone no"],
    "blood group": ["blood group", "blood"],

    # DGA report
    "loco no (dga)": ["loco no", "loco no."],
    "oil": ["oil"],
    "ch4": ["ch4"],
    "c2h4": ["c2h4"],
    "c2h6": ["c2h6"],
    "c2h2": ["c2h2"],
    "h2": ["h2"],
    "co": ["co"],
    "co2": ["co2"],
    "bdv": ["bdv"],

    # Panto status
    "pt1 pressure": ["pt1 pressure", "pt 1 pressure"],
    "pt2 pressure": ["pt2 pressure", "pt 2 pressure"],
    "pt1 ord": ["pt1 ord", "pt 1 ord"],
    "pt2 ord": ["pt2 ord", "pt 2 ord"],
    "pt1 add": ["pt1 add", "pt 1 add"],
    "pt2 add": ["pt2 add", "pt 2 add"],
}


def _get(fields: dict, canonical: str) -> str:
    canonical_n = _norm_key(canonical)
    for alias in _ALIASES.get(canonical_n, [canonical_n]):
        alias_n = _norm_key(alias)
        if alias_n in fields and fields[alias_n] != "":
            return fields[alias_n]
    return ""

def normalize_fields(message_type: str, fields: dict) -> dict:
    """
    Normalize extracted fields for downstream validation/saving.

    This is mainly used for Gemini-extracted free text where users use
    inconsistent abbreviations.
    """
    mt = (message_type or "").strip().lower()
    if not isinstance(fields, dict):
        return {}

    # Keep keys normalized to match _get/aliases expectations.
    f: dict[str, str] = {}
    for k, v in fields.items():
        if k is None:
            continue
        ks = _norm_key(str(k))
        if not ks:
            continue
        f[ks] = "" if v is None else str(v).strip()

    if mt != "main_equipment":
        return f

    def _format_sr_no(sr_text: str) -> str:
        s = re.sub(r"\s+", " ", (sr_text or "").strip())
        if not s:
            return ""

        # Normalize common SR formats into a consistent spacing.
        #
        # Turbo SR example:
        # - Input: "I12201518 GMR3" or "I 12201518 GMR3"
        # - Output: "I 12 2015 18 GMR3"
        m = re.match(r"^(i)\s*([0-9]{8})\s*([a-z0-9]+)?$", s, re.IGNORECASE)
        if m:
            prefix = "I"
            digits = m.group(2)
            suffix = (m.group(3) or "").upper()
            part1, part2, part3 = digits[0:2], digits[2:6], digits[6:8]
            return (f"{prefix} {part1} {part2} {part3}" + (f" {suffix}" if suffix else "")).strip()

        # Clutch SR example:
        # - Input: "MOD12102025" or "MOD 12102025"
        # - Output: "MOD 12 10 2025"
        m = re.match(r"^(mod)\s*([0-9]{8})$", s, re.IGNORECASE)
        if m:
            prefix = "MOD"
            digits = m.group(2)
            part1, part2, part3 = digits[0:2], digits[2:4], digits[4:8]
            return f"{prefix} {part1} {part2} {part3}"

        return s

    item_raw = _get(f, "item")
    item_n = _norm_key(item_raw)

    # Turbo / TSC / HHP Turbo variants => canonical "TSC HHP Turbo"
    if item_n and any(tok in item_n for tok in ["turbo", "tsc", "hhp"]):
        if "clutch" not in item_n:
            f[_norm_key("item")] = "TSC HHP Turbo"

    # Clutch variants => canonical "Clutch Assembly"
    if "clutch" in item_n:
        f[_norm_key("item")] = "Clutch Assembly"

    # Sr No: keep the full string (e.g. "I 12 2015 18 GMR3", "MOD 12 10 2025")
    sr = _get(f, "sr no")
    if sr:
        f[_norm_key("sr no")] = _format_sr_no(sr)

    # Default make BLW for Turbo/TSC and Clutch when not provided.
    make = _get(f, "make")
    item_final = _norm_key(_get(f, "item"))
    if (not make) and (("turbo" in item_final) or ("tsc" in item_final) or ("clutch" in item_final)):
        f[_norm_key("make")] = "BLW"

    # Side is optional; if user doesn't provide it, leave blank.
    return f


def infer_message_type(text: str, fields: dict | None = None) -> str:
    """
    Infer which parser to use for an arbitrary message.

    Returns one of: dga_report, panto_status, main_equipment
    """
    text_n = _norm_key(text)
    if "dga report" in text_n:
        return "dga_report"
    if "panto status" in text_n:
        return "panto_status"

    f = fields or parse_key_values(text)
    keys = set(f.keys())

    if any(k in keys for k in {_norm_key("ch4"), _norm_key("c2h2"), _norm_key("bdv"), _norm_key("co2")}):
        return "dga_report"
    if any(k in keys for k in {_norm_key("pt1 pressure"), _norm_key("pt2 pressure"), _norm_key("pt1 ord")}):
        return "panto_status"
    return "main_equipment"


def validate_fields(message_type: str, fields: dict) -> list[str]:
    required_by_type: dict[str, list[str]] = {
        "dga_report": ["date", "loco no", "schedule"],
        "panto_status": ["date", "loco no", "pt1 pressure", "pt2 pressure"],
        "main_equipment": ["date", "loco no", "item", "status"],
    }
    required = required_by_type.get(message_type, [])
    missing: list[str] = []
    for canonical in required:
        if _get(fields, canonical) == "":
            missing.append(canonical)
    return missing


def format_template(message_type: str) -> str:
    templates: dict[str, str] = {
        "dga_report": "\n".join([
            "DGA REPORT",
            "Date -",
            "Loco No -",
            "Schedule -",
            "Oil -",
            "CH4 -",
            "C2H4 -",
            "C2H6 -",
            "C2H2 -",
            "H2 -",
            "CO -",
            "CO2 -",
            "BDV -",
            "Remark -",
        ]),
        "panto_status": "\n".join([
            "PANTO STATUS",
            "Date -",
            "Loco No -",
            "PT1 Pressure -",
            "PT2 Pressure -",
            "PT1 ORD -",
            "PT2 ORD -",
            "PT1 ADD -",
            "PT2 ADD -",
        ]),
        "main_equipment": "\n".join([
            "Date -",
            "Loco No -",
            "Item -",
            "Side -",
            "Status -",
            "Sr No -",
            "Mfg -",
            "Make -",
            "Type -",
            "Reason -",
            "Schedule -",
            "O/H Date -",
            "W/O No -",
        ]),
    }
    return templates.get(message_type, templates["main_equipment"])


def parse_any(text: str) -> tuple[str, list, str]:
    """
    Parse any message.

    Returns: (worksheet_name, row, message_type)
    Raises ValueError when required fields are missing.
    """
    fields = parse_key_values(text)
    message_type = infer_message_type(text, fields)
    missing = validate_fields(message_type, fields)
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))

    if message_type == "dga_report":
        worksheet = "DGA Report"
        row = parse_dga(text)
    elif message_type == "panto_status":
        worksheet = "Panto Status"
        row = parse_panto_status(text)
    else:
        worksheet = None  # default sheet1
        row = parse_message(text)

    return worksheet, row, message_type


def fields_to_row(message_type: str, fields: dict) -> tuple[str | None, list]:
    """
    Convert normalized fields dict into the exact Google Sheet row format.

    Returns (worksheet_name_or_none_for_sheet1, row_list)
    """
    mt = (message_type or "").strip().lower()

    if mt == "dga_report":
        worksheet = "DGA Report"
        row = [
            _get(fields, "date"),
            _get(fields, "loco no"),
            _get(fields, "schedule"),
            _get(fields, "oil"),
            _get(fields, "ch4"),
            _get(fields, "c2h4"),
            _get(fields, "c2h6"),
            _get(fields, "c2h2"),
            _get(fields, "h2"),
            _get(fields, "co"),
            _get(fields, "co2"),
            _get(fields, "bdv"),
            _get(fields, "remark"),
        ]
        return worksheet, row

    if mt == "panto_status":
        worksheet = "Panto Status"
        row = [
            _get(fields, "date"),
            _get(fields, "loco no"),
            _get(fields, "pt1 pressure"),
            _get(fields, "pt2 pressure"),
            _get(fields, "pt1 ord"),
            _get(fields, "pt2 ord"),
            _get(fields, "pt1 add"),
            _get(fields, "pt2 add"),
        ]
        return worksheet, row

    # main_equipment default sheet1
    row = [
        _get(fields, "date"),
        _get(fields, "loco no"),
        _get(fields, "item"),
        _get(fields, "side"),
        _get(fields, "status"),
        _get(fields, "sr no"),
        _get(fields, "mfg"),
        _get(fields, "make"),
        _get(fields, "type"),
        _get(fields, "reason"),
        _get(fields, "schedule"),
        _get(fields, "oh date"),
        _get(fields, "wo no"),
    ]
    return None, row

def parse_emp_record(text):
    patterns = {
        "Token No": r"^Token No\s*-\s*(.*)$",
        "Emp HRMS ID": r"^Emp HRMS ID\s*-\s*(.*)$",
        "Bill Unit": r"^Bill Unit\s*-\s*(.*)$",
        "Emp Name": r"^Emp Name\s*-\s*(.*)$",
        "Department": r"^Department\s*-\s*(.*)$",
        "Designation": r"^Designation\s*-\s*(.*)$",
        "Aadhar Number": r"^Aadhar Number\s*-\s*(.*)$",
        "Permanent Address": r"^Permanent Address\s*-\s*(.*)$",
        "Place of Posting": r"^Place of Posting\s*-\s*(.*)$",
        "Mobile No": r"^Mobile No\s*-\s*(.*)$",
        "Blood Group": r"^Blood Group\s*-\s*(.*)$",
    }

    data = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        data[key] = match.group(1).strip() if match else ""

    return [
        "",  # S.No (auto in sheet)
        data.get("Token No", ""),
        data.get("Emp HRMS ID", ""),
        data.get("Bill Unit", ""),
        data.get("Emp Name", ""),
        data.get("Department", ""),
        data.get("Designation", ""),
        "",  # Photo
        "",  # Signature
        data.get("Aadhar Number", ""),
        data.get("Permanent Address", ""),
        data.get("Place of Posting", ""),
        data.get("Mobile No", ""),
        "",  # Return Mobile
        data.get("Blood Group", ""),
        "", "", "", "", "", "", ""  # remaining fields
    ]



# =========================
# 🔵 DGA PARSER
# =========================
def parse_dga(text):
    patterns = {
        "Loco No": r"^Loco No\s*-\s*(.*)$",
        "Schedule": r"^Schedule\s*-\s*(.*)$",
        "Date": r"^Date\s*-\s*(.*)$",
        "Oil": r"^Oil\s*-\s*(.*)$",
        "CH4": r"^CH4\s*-\s*(.*)$",
        "C2H4": r"^C2H4\s*-\s*(.*)$",
        "C2H6": r"^C2H6\s*-\s*(.*)$",
        "C2H2": r"^C2H2\s*-\s*(.*)$",
        "H2": r"^H2\s*-\s*(.*)$",
        "CO": r"^CO\s*-\s*(.*)$",
        "CO2": r"^CO2\s*-\s*(.*)$",
        "BDV": r"^BDV\s*-\s*(.*)$",
        "Remark": r"^Remark\s*-\s*(.*)$",
    }

    data = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        data[key] = match.group(1).strip() if match else ""

    return [
        data.get("Date", ""),
        data.get("Loco No", ""),
        data.get("Schedule", ""),
        data.get("Oil", ""),
        data.get("CH4", ""),
        data.get("C2H4", ""),
        data.get("C2H6", ""),
        data.get("C2H2", ""),
        data.get("H2", ""),
        data.get("CO", ""),
        data.get("CO2", ""),
        data.get("BDV", ""),
        data.get("Remark", ""),
    ]


# =========================
# 🟢 MAIN EQUIPMENT PARSER
# =========================
def parse_message(text):
    patterns = {
        "Date": r"^Date\s*-\s*(.*)$",
        "Loco No": r"^Loco No\.?\s*-\s*(.*)$",
        "Item": r"^Item\s*-\s*(.*)$",
        "Side": r"^Side\s*-\s*(.*)$",
        "Status": r"^Status\s*-\s*(.*)$",
        "Sr No": r"^Sr\.?\s*No\.?\s*-\s*(.*)$",
        "Mfg": r"^Mfg\s*-\s*(.*)$",
        "Make": r"^Make\s*-\s*(.*)$",
        "Type": r"^Type\s*-\s*(.*)$",
        "Reason": r"^Reason\s*-\s*(.*)$",
        "Schedule": r"^Schedule\s*-\s*(.*)$",
        "OH Date": r"^O\/H Date\s*-\s*(.*)$",
        "WO No": r"^W\/O No\.?\s*-\s*(.*)$",
    }

    data = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        data[key] = match.group(1).strip() if match else ""

    return [
        data.get("Date", ""),
        data.get("Loco No", ""),
        data.get("Item", ""),
        data.get("Side", ""),
        data.get("Status", ""),
        data.get("Sr No", ""),
        data.get("Mfg", ""),
        data.get("Make", ""),
        data.get("Type", ""),
        data.get("Reason", ""),
        data.get("Schedule", ""),
        data.get("OH Date", ""),
        data.get("WO No", ""),
    ]


# =========================
# 🟡 PANTO STATUS PARSER
# =========================
def parse_panto_status(text):
    patterns = {
        "Date": r"^Date\s*-\s*(.*)$",
        "Loco No": r"^Loco No\.?\s*-\s*(.*)$",
        "PT1 Pressure": r"^PT1 Pressure\s*-\s*(.*)$",
        "PT2 Pressure": r"^PT2 Pressure\s*-\s*(.*)$",
        "PT1 ORD": r"^PT1 ORD\s*-\s*(.*)$",
        "PT2 ORD": r"^PT2 ORD\s*-\s*(.*)$",
        "PT1 ADD": r"^PT1 ADD\s*-\s*(.*)$",
        "PT2 ADD": r"^PT2 ADD\s*-\s*(.*)$",
    }

    data = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        data[key] = match.group(1).strip() if match else ""

    return [
        data.get("Date", ""),
        data.get("Loco No", ""),
        data.get("PT1 Pressure", ""),
        data.get("PT2 Pressure", ""),
        data.get("PT1 ORD", ""),
        data.get("PT2 ORD", ""),
        data.get("PT1 ADD", ""),
        data.get("PT2 ADD", ""),
    ]
