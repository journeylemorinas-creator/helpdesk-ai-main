"""Ticket triage: the "AI-assisted" part of HelpDesk AI.

This is a transparent, rule-based classifier (not a machine-learning model and
it calls no external AI service). It reads a ticket's title and description,
finds known keywords, and returns:

  * a suggested category      (Network, Hardware, Software, Account, Security, General)
  * a suggested priority      (Low, Medium, High, Critical)
  * the keywords that triggered each decision
  * first-line troubleshooting steps for the category

Every decision can be traced to a keyword, so a technician can check it. The
result is only a suggestion: a technician can always change it.
"""
import re

CATEGORIES = ("Network", "Hardware", "Software", "Account", "Security", "General")
PRIORITIES = ("Low", "Medium", "High", "Critical")

# category -> keywords / phrases (matched as whole words, case-insensitive)
KEYWORDS = {
    "Network": [
        "wifi", "wi-fi", "internet", "network", "dns", "ip address", "router",
        "ethernet", "lan", "vpn", "ping", "no connection", "cannot connect",
        "can't connect", "disconnects", "dhcp", "gateway", "bandwidth", "slow internet",
    ],
    "Hardware": [
        "screen", "monitor", "keyboard", "mouse", "printer", "battery", "overheating",
        "fan", "beeping", "beep", "won't turn on", "wont turn on", "not turning on",
        "power", "usb", "hard drive", "ram", "laptop", "charger", "display", "speaker",
        "webcam", "cable", "flickering", "broken",
    ],
    "Software": [
        "install", "installation", "crash", "crashes", "crashing", "freezes", "frozen",
        "error", "update", "application", "app", "excel", "word", "browser", "chrome",
        "slow", "license", "driver", "windows", "software", "program", "blue screen",
        "not responding", "uninstall",
    ],
    "Account": [
        "password", "login", "log in", "locked", "account", "email", "access",
        "permission", "reset", "2fa", "otp", "username", "sign in", "forgot",
        "mailbox", "authentication",
    ],
    "Security": [
        "virus", "malware", "phishing", "ransomware", "suspicious", "hacked", "breach",
        "spam", "spyware", "unauthorized", "stolen", "scam", "encrypted files",
    ],
}

# priority rules, checked from the most severe down
CRITICAL_WORDS = [
    "ransomware", "breach", "data loss", "lost all data", "server down", "all users",
    "everyone", "smoke", "burning", "fire", "hacked", "stolen", "encrypted files",
]
HIGH_WORDS = [
    "urgent", "asap", "cannot work", "can't work", "unable to work", "deadline",
    "not working", "won't turn on", "wont turn on", "not turning on", "crash",
    "crashes", "crashing", "blue screen", "locked out", "locked", "phishing",
    "malware", "virus", "no internet", "cannot connect", "can't connect",
]
LOW_WORDS = [
    "question", "how to", "how do i", "request", "when possible", "minor",
    "cosmetic", "suggestion", "no rush", "whenever",
]

SUGGESTIONS = {
    "Network": [
        "Check that the cable or Wi-Fi switch is on and other devices can connect.",
        "Restart the device, then the router or access point.",
        "Run 'ipconfig /all' (Windows) and check for a valid IP address and gateway.",
        "Ping the gateway, then 8.8.8.8, then a domain name to separate a link, internet or DNS fault.",
        "Run 'ipconfig /flushdns', and renew the IP address with 'ipconfig /release' then '/renew'.",
    ],
    "Hardware": [
        "Check power, cables and connections, and try another outlet or port.",
        "Test the device on another computer, or test another device on this computer.",
        "Listen for beep codes and look for lights, heat or damage.",
        "Remove external devices and try again with only the essentials connected.",
        "If it is still faulty, record the model and serial number and escalate for repair.",
    ],
    "Software": [
        "Ask for the exact error message and when it started.",
        "Restart the application, then the computer.",
        "Check for pending updates and for recent installs that match the start of the problem.",
        "Repair or reinstall the application; try a safe-mode or clean-boot start for system issues.",
        "Check Event Viewer or the application log for the matching error.",
    ],
    "Account": [
        "Verify the user's identity before any change.",
        "Check whether the account is locked, disabled or expired.",
        "Reset the password through the approved process and require a change at next login.",
        "Check group membership and permissions for the resource.",
        "Confirm multi-factor authentication is set up on the right device.",
    ],
    "Security": [
        "Tell the user to disconnect the device from the network but NOT to power it off.",
        "Do not open links or attachments; report the message to the security contact.",
        "Change affected passwords from a clean device and enable multi-factor authentication.",
        "Run a full antivirus scan and preserve evidence (screenshots, message headers).",
        "Escalate to the security lead and record the incident.",
    ],
    "General": [
        "Ask the user for more detail: what happened, when, and what changed.",
        "Ask for screenshots or error messages.",
        "Reproduce the problem if possible, then re-categorize the ticket.",
    ],
}


def _q(word):
    return "'" + word + "'"


def _find(text, words):
    """Return the words from `words` that appear in `text` as whole words/phrases."""
    found = []
    for w in words:
        if re.search(r"(?<![\w'-])" + re.escape(w) + r"(?![\w'-])", text):
            found.append(w)
    return found


def triage(title, description):
    """Analyse a ticket and return a dict with category, priority and reasons."""
    title_t = (title or "").lower()
    body_t = (description or "").lower()
    combined = title_t + " \n " + body_t

    # --- category: keyword score, title matches count double ---
    scores, matched = {}, {}
    for cat, words in KEYWORDS.items():
        in_title = _find(title_t, words)
        in_body = [w for w in _find(body_t, words) if w not in in_title]
        score = 2 * len(in_title) + len(in_body)
        if score:
            scores[cat] = score
            matched[cat] = in_title + in_body

    # on a tie, safety first: Security wins, then the order below
    order = {c: i for i, c in enumerate(
        ("Security", "Network", "Hardware", "Software", "Account", "General"))}
    if scores:
        category = sorted(scores, key=lambda c: (-scores[c], order[c]))[0]
        total = sum(scores.values())
        confidence = int(scores[category] / total * 100 + 0.5)  # round half up
        keywords = matched[category]
    else:
        category, confidence, keywords = "General", 0, []

    # --- priority: strongest matching rule wins ---
    critical = _find(combined, CRITICAL_WORDS)
    high = _find(combined, HIGH_WORDS)
    low = _find(combined, LOW_WORDS)

    if critical:
        priority, trigger = "Critical", critical
    elif high or category == "Security":
        priority, trigger = "High", high
    elif low:
        priority, trigger = "Low", low
    else:
        priority, trigger = "Medium", []

    reasons = []
    if keywords:
        reasons.append(f"Category {category}: matched {', '.join(_q(k) for k in keywords)} ({confidence}% of keyword matches).")
    else:
        reasons.append("No known keywords were found, so the ticket is General. A technician should re-categorize it.")
    if priority == "Critical":
        reasons.append(f"Priority Critical: contains {', '.join(_q(k) for k in trigger)}.")
    elif priority == "High":
        if trigger:
            reasons.append(f"Priority High: contains {', '.join(_q(k) for k in trigger)}.")
        else:
            reasons.append("Priority High: security issues are never ranked below High.")
    elif priority == "Low":
        reasons.append(f"Priority Low: looks like a request or question ({', '.join(_q(k) for k in trigger)}).")
    else:
        reasons.append("Priority Medium: no urgent or low-priority wording found.")

    return {
        "category": category,
        "priority": priority,
        "confidence": confidence,
        "keywords": keywords,
        "reasons": reasons,
        "suggestions": SUGGESTIONS[category],
    }
