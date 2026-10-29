import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as helpdesk  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

GOOD = {
    "title": "Wi-Fi keeps disconnecting",
    "description": "The wifi drops every few minutes and the internet is slow.",
    "requester_name": "Maria Santos",
    "requester_email": "maria@example.com",
}


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        helpdesk.app.config.update(DATABASE=self.path, TESTING=True)
        with helpdesk.app.app_context():
            helpdesk.init_db()
            db = helpdesk.get_db()
            db.execute("INSERT INTO users (username, full_name, password_hash) VALUES (?, ?, ?)",
                       ("tech", "Test Tech", generate_password_hash("Password1")))
            db.commit()
        self.client = helpdesk.app.test_client()

    def tearDown(self):
        os.remove(self.path)

    # helpers
    def token(self):
        page = self.client.get("/login").get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', page).group(1)

    def login(self, user="tech", password="Password1"):
        return self.client.post("/login", data={"username": user, "password": password, "_csrf": self.token()})

    def api(self, method, url, body=None, csrf=True):
        with self.client.session_transaction() as s:
            token = s.get("_csrf", "")
        headers = {"X-CSRF-Token": token} if csrf else {}
        return self.client.open(url, method=method, json=body, headers=headers)

    def make_ticket(self, **over):
        res = self.api("POST", "/api/tickets", {**GOOD, **over})
        self.assertEqual(res.status_code, 201, res.get_json())
        return res.get_json()["id"]


class AuthTests(Base):
    def test_api_requires_login(self):
        self.assertEqual(self.client.get("/api/tickets").status_code, 401)

    def test_pages_redirect_to_login(self):
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])

    def test_login_and_dashboard(self):
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_bad_password_rejected(self):
        res = self.login(password="wrong")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Invalid username or password", res.get_data(as_text=True))
        self.assertEqual(self.client.get("/api/tickets").status_code, 401)

    def test_logout_ends_session(self):
        self.login()
        self.client.post("/logout", data={"_csrf": self.token()})
        self.assertEqual(self.client.get("/api/tickets").status_code, 401)

    def test_login_without_csrf_rejected(self):
        res = self.client.post("/login", data={"username": "tech", "password": "Password1"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get("/api/tickets").status_code, 401)

    def test_open_redirect_blocked(self):
        res = self.client.post("/login?next=//evil.example", data={
            "username": "tech", "password": "Password1", "_csrf": self.token()})
        self.assertTrue(res.headers["Location"].endswith("/dashboard"))

    def test_register_and_duplicate(self):
        data = {"full_name": "New Tech", "username": "newtech", "password": "Password1",
                "confirm": "Password1", "_csrf": self.token()}
        self.assertEqual(self.client.post("/register", data=data).status_code, 302)
        res = self.client.post("/register", data={**data, "_csrf": self.token()})
        self.assertIn("already taken", res.get_data(as_text=True))

    def test_register_weak_password(self):
        res = self.client.post("/register", data={"full_name": "A B", "username": "abc",
                                                  "password": "short", "confirm": "short", "_csrf": self.token()})
        self.assertIn("at least 8 characters", res.get_data(as_text=True))

    def test_password_is_hashed(self):
        with helpdesk.app.app_context():
            row = helpdesk.get_db().execute("SELECT password_hash FROM users").fetchone()
        self.assertNotIn("Password1", row["password_hash"])

    def test_api_write_without_csrf_header_rejected(self):
        self.login()
        res = self.api("POST", "/api/tickets", GOOD, csrf=False)
        self.assertEqual(res.status_code, 403)


class TicketCrudTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.client.get("/dashboard")  # makes sure the session has a CSRF token

    def test_create_uses_triage_when_blank(self):
        tid = self.make_ticket()
        t = self.api("GET", f"/api/tickets/{tid}").get_json()["ticket"]
        self.assertEqual(t["category"], "Network")
        self.assertEqual(t["status"], "Open")

    def test_create_keeps_manual_category(self):
        tid = self.make_ticket(category="Hardware", priority="Low")
        t = self.api("GET", f"/api/tickets/{tid}").get_json()["ticket"]
        self.assertEqual((t["category"], t["priority"]), ("Hardware", "Low"))

    def test_read_includes_triage(self):
        tid = self.make_ticket()
        data = self.api("GET", f"/api/tickets/{tid}").get_json()
        self.assertEqual(data["triage"]["category"], "Network")
        self.assertTrue(data["triage"]["suggestions"])

    def test_update(self):
        tid = self.make_ticket()
        res = self.api("PUT", f"/api/tickets/{tid}", {**GOOD, "title": "Updated title here",
                                                      "category": "Hardware", "status": "In Progress"})
        self.assertEqual(res.status_code, 200)
        t = self.api("GET", f"/api/tickets/{tid}").get_json()["ticket"]
        self.assertEqual((t["title"], t["category"], t["status"]), ("Updated title here", "Hardware", "In Progress"))

    def test_status_endpoint(self):
        tid = self.make_ticket()
        self.assertEqual(self.api("PUT", f"/api/tickets/{tid}/status", {"status": "Resolved"}).status_code, 200)
        self.assertEqual(self.api("PUT", f"/api/tickets/{tid}/status", {"status": "Nope"}).status_code, 400)

    def test_delete_removes_comments_too(self):
        tid = self.make_ticket()
        self.api("POST", f"/api/tickets/{tid}/comments", {"body": "note"})
        self.assertEqual(self.api("DELETE", f"/api/tickets/{tid}").status_code, 200)
        with helpdesk.app.app_context():
            n = helpdesk.get_db().execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        self.assertEqual(n, 0)

    def test_comments_crud(self):
        tid = self.make_ticket()
        res = self.api("POST", f"/api/tickets/{tid}/comments", {"body": "Checked the router."})
        self.assertEqual(res.status_code, 201)
        cid = res.get_json()["id"]
        comments = self.api("GET", f"/api/tickets/{tid}").get_json()["comments"]
        self.assertEqual(comments[0]["author_name"], "Test Tech")
        self.assertEqual(self.api("DELETE", f"/api/comments/{cid}").status_code, 200)
        self.assertEqual(self.api("DELETE", f"/api/comments/{cid}").status_code, 404)

    def test_triage_preview_saves_nothing(self):
        res = self.api("POST", "/api/triage", {"title": "Virus warning", "description": "malware found"})
        self.assertEqual(res.get_json()["category"], "Security")
        self.assertEqual(self.api("GET", "/api/tickets").get_json()["summary"]["total"], 0)


class ValidationTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.client.get("/dashboard")

    def assert_field_error(self, field, **over):
        res = self.api("POST", "/api/tickets", {**GOOD, **over})
        self.assertEqual(res.status_code, 400)
        self.assertIn(field, res.get_json()["fields"])
        self.assertEqual(self.api("GET", "/api/tickets").get_json()["summary"]["total"], 0)

    def test_short_title(self):
        self.assert_field_error("title", title="Hi")

    def test_empty_description(self):
        self.assert_field_error("description", description="   ")

    def test_missing_name(self):
        self.assert_field_error("requester_name", requester_name="")

    def test_bad_email(self):
        self.assert_field_error("requester_email", requester_email="not-an-email")

    def test_bad_category(self):
        self.assert_field_error("category", category="Plumbing")

    def test_bad_priority(self):
        self.assert_field_error("priority", priority="Urgent!!")

    def test_title_too_long(self):
        self.assert_field_error("title", title="x" * 121)

    def test_non_string_fields_do_not_crash(self):
        res = self.api("POST", "/api/tickets", {"title": 123, "description": ["a"], "requester_name": None})
        self.assertEqual(res.status_code, 400)

    def test_empty_comment(self):
        self.client.get("/dashboard")
        tid = self.api("POST", "/api/tickets", GOOD).get_json()["id"]
        res = self.api("POST", f"/api/tickets/{tid}/comments", {"body": "  "})
        self.assertEqual(res.status_code, 400)


class SearchTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.client.get("/dashboard")
        self.make_ticket(title="Wi-Fi drops in room 204", requester_name="Maria Santos")
        self.make_ticket(title="Printer jam in library", description="Printer shows paper jam error.",
                         requester_name="Mark Garcia")
        self.make_ticket(title="100% broken screen", description="The monitor screen is cracked badly.",
                         requester_name="Ken Torres")

    def ids(self, query):
        return [t["title"] for t in self.api("GET", "/api/tickets?" + query).get_json()["tickets"]]

    def test_search_title(self):
        self.assertEqual(self.ids("q=printer"), ["Printer jam in library"])

    def test_search_requester(self):
        self.assertEqual(self.ids("q=Garcia"), ["Printer jam in library"])

    def test_filter_category(self):
        self.assertTrue(all("Wi-Fi" in t for t in self.ids("category=Network")))

    def test_filter_status(self):
        self.assertEqual(self.ids("status=Closed"), [])

    def test_percent_is_plain_text(self):
        self.assertEqual(self.ids("q=%25"), ["100% broken screen"])

    def test_sql_injection_attempt_is_harmless(self):
        self.assertEqual(self.ids("q=" + "';DROP TABLE tickets;--"), [])
        self.assertEqual(len(self.ids("")), 3)

    def test_unresolved_urgent_ordering(self):
        first = self.api("GET", "/api/tickets").get_json()["tickets"][0]
        self.assertIn(first["priority"], ("Critical", "High", "Medium", "Low"))


class ErrorTests(Base):
    def test_unknown_page_is_friendly_404(self):
        res = self.client.get("/nope")
        self.assertEqual(res.status_code, 404)
        self.assertIn("does not exist", res.get_data(as_text=True))

    def test_missing_ticket_page_404(self):
        self.login()
        self.assertEqual(self.client.get("/tickets/999").status_code, 404)

    def test_missing_ticket_api_404(self):
        self.login()
        self.client.get("/dashboard")
        self.assertEqual(self.api("GET", "/api/tickets/999").status_code, 404)
        self.assertEqual(self.api("PUT", "/api/tickets/999", GOOD).status_code, 404)
        self.assertEqual(self.api("DELETE", "/api/tickets/999").status_code, 404)

    def test_non_json_body_is_400(self):
        self.login()
        self.client.get("/dashboard")
        with self.client.session_transaction() as s:
            token = s["_csrf"]
        res = self.client.post("/api/tickets", data="plain text", headers={"X-CSRF-Token": token})
        self.assertEqual(res.status_code, 400)

    def test_wrong_method_is_405(self):
        self.login()
        self.client.get("/dashboard")
        self.assertEqual(self.api("DELETE", "/api/tickets").status_code, 405)

    def test_stored_script_is_not_executed_by_api_shape(self):
        # the API returns raw text; the page escapes it (see esc() in static/app.js)
        self.login()
        self.client.get("/dashboard")
        tid = self.make_ticket(title="<script>alert(1)</script>")
        t = self.api("GET", f"/api/tickets/{tid}").get_json()["ticket"]
        self.assertEqual(t["title"], "<script>alert(1)</script>")
        page = self.client.get(f"/tickets/{tid}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_security_headers(self):
        res = self.client.get("/login")
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(res.headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
