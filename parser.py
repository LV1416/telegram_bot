import re

def parse_message(text):
    patterns = {
        "Date": r"date\s*-\s*(.*)",
        "Loco No": r"Loco no\.\s*-\s*(.*)",
        "Item": r"Item\s*-\s*(.*)",
        "Status": r"Status\s*-\s*(.*)",
        "Sr No": r"Sr\. no\.\s*-\s*(.*)",
        "Mfg": r"Mfg\s*-\s*(.*)",
        "Make": r"make\s*-\s*(.*)",
        "Type": r"type\s*-\s*(.*)",
        "Reason": r"reason\s*-\s*(.*)",
        "Schedule": r"Schedule\s*-\s*(.*)",
        "OH Date": r"O\/H Date\s*-\s*(.*)",
        "WO No": r"W\/O No\.\s*-\s*(.*)",
    }

    data = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        data[key] = match.group(1).strip() if match else ""

    return [
        data.get("Date", ""),
        data.get("Loco No", ""),
        data.get("Item", ""),
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
