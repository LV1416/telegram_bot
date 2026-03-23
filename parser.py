import re

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
