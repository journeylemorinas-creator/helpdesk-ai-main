"""Load demo data so the dashboard has something to show.

    python seed.py

Creates a demo technician account and 12 sample tickets (fictional).
Safe to run twice: it does nothing if tickets already exist.
Delete the demo account before any real use.
"""
from werkzeug.security import generate_password_hash

from app import app, get_db, init_db
from triage import triage

DEMO_USER = ("tech", "Demo Technician", "HelpDesk123!")

# (title, description, requester, status)
TICKETS = [
    ("Wi-Fi keeps disconnecting in Room 204",
     "The wifi drops every few minutes and the internet is very slow. Other laptops in the room have the same problem.",
     "Maria Santos", "Open"),
    ("Cannot log in to student portal",
     "I forgot my password and now my account is locked after three tries. Please reset it.",
     "Juan Dela Cruz", "In Progress"),
    ("Possible phishing email received",
     "I got a suspicious email asking me to verify my email password. I clicked the link before I noticed. Please help.",
     "Angela Reyes", "Open"),
    ("Printer in the library is not working",
     "The printer shows a paper jam error and the screen is flickering. Nothing prints.",
     "Mark Garcia", "Open"),
    ("Excel crashes when opening the grading sheet",
     "Excel freezes and crashes every time I open the grading file. I have a deadline tomorrow and cannot work.",
     "Joan Mendoza", "In Progress"),
    ("Laptop won't turn on after update",
     "My laptop will not turn on since the Windows update last night. The charger light is on but the screen stays black.",
     "Paolo Bautista", "Open"),
    ("Question: how to connect to campus VPN",
     "How do I connect to the campus VPN from home? No rush, whenever you have time.",
     "Liza Ramos", "Resolved"),
    ("Computer lab PCs show ransomware message",
     "All users in Lab 3 see a message that our files are encrypted files and demands payment. The whole lab is affected.",
     "Carlo Villanueva", "In Progress"),
    ("Request: install Python on lab computers",
     "Request to install Python 3 and VS Code on the lab computers when possible for the new programming class.",
     "Nina Aquino", "Resolved"),
    ("Monitor has no display",
     "The monitor on desk 12 shows no display. The power light is on and the cable seems fine.",
     "Ken Torres", "Closed"),
    ("Email mailbox is full",
     "My email says the mailbox is full and I cannot receive new messages. I need more space or access to the archive.",
     "Bea Lopez", "Open"),
    ("Something is wrong with my computer",
     "It is acting strange since yesterday and I am not sure what happened.",
     "Rico Navarro", "Open"),
]

COMMENTS = {
    2: ["Verified identity at the front desk. Password reset sent to the registered email."],
    5: ["Reproduced the crash. Repairing the Office installation now."],
    8: ["Lab network isolated from the campus network. Security lead informed."],
    7: ["Sent the VPN setup guide. Closing as resolved."],
}


def main():
    with app.app_context():
        init_db()
        db = get_db()

        if not db.execute("SELECT 1 FROM users WHERE username = ?", (DEMO_USER[0],)).fetchone():
            db.execute("INSERT INTO users (username, full_name, password_hash) VALUES (?, ?, ?)",
                       (DEMO_USER[0], DEMO_USER[1], generate_password_hash(DEMO_USER[2])))

        if db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            for i, (title, desc, who, status) in enumerate(TICKETS, start=1):
                t = triage(title, desc)
                tid = db.execute(
                    "INSERT INTO tickets (title, description, requester_name, requester_email,"
                    " category, priority, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', ?), datetime('now', ?))",
                    (title, desc, who, who.replace(" ", ".").lower() + "@example.com",
                     t["category"], t["priority"], status,
                     f"-{(len(TICKETS) - i) * 5} hours", f"-{(len(TICKETS) - i) * 5} hours"),
                ).lastrowid
                for body in COMMENTS.get(i, []):
                    db.execute("INSERT INTO comments (ticket_id, author_name, body) VALUES (?, ?, ?)",
                               (tid, DEMO_USER[1], body))
            print(f"Added {len(TICKETS)} demo tickets.")
        else:
            print("Tickets already exist, so no demo tickets were added.")
        db.commit()
    print(f"Demo login -> username: {DEMO_USER[0]}   password: {DEMO_USER[2]}")


if __name__ == "__main__":
    main()
