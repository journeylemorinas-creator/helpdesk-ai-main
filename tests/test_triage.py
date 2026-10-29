import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from triage import triage  # noqa: E402


class TriageTests(unittest.TestCase):
    def test_network_ticket(self):
        r = triage("Wi-Fi keeps disconnecting", "The internet is slow and the router restarts.")
        self.assertEqual(r["category"], "Network")
        self.assertIn("wi-fi", r["keywords"])

    def test_account_ticket_high_when_locked(self):
        r = triage("Cannot log in", "My account is locked and I forgot my password.")
        self.assertEqual(r["category"], "Account")
        self.assertEqual(r["priority"], "High")

    def test_security_is_never_below_high(self):
        r = triage("Odd email", "I received a spam message with a scam link.")
        self.assertEqual(r["category"], "Security")
        self.assertIn(r["priority"], ("High", "Critical"))

    def test_critical_keywords(self):
        r = triage("Lab PCs", "Ransomware message on all users computers.")
        self.assertEqual(r["priority"], "Critical")

    def test_low_priority_request(self):
        r = triage("Question about printing", "How to print double sided? No rush.")
        self.assertEqual(r["priority"], "Low")

    def test_unknown_text_is_general_medium(self):
        r = triage("Hello there", "Something odd happened yesterday afternoon.")
        self.assertEqual(r["category"], "General")
        self.assertEqual(r["priority"], "Medium")
        self.assertEqual(r["confidence"], 0)

    def test_title_counts_double(self):
        # one Hardware word in the title outweighs one Software word in the body
        r = triage("Printer", "please install it")
        self.assertEqual(r["category"], "Hardware")

    def test_whole_word_matching(self):
        # "app" must not match inside "happened"; "ram" must not match inside "program"
        r = triage("Hello", "It happened during the programme")
        self.assertEqual(r["category"], "General")

    def test_case_insensitive(self):
        self.assertEqual(triage("WIFI DOWN", "")["category"], "Network")

    def test_empty_and_none_input(self):
        self.assertEqual(triage("", "")["category"], "General")
        self.assertEqual(triage(None, None)["category"], "General")

    def test_result_always_explains_itself(self):
        r = triage("Monitor", "no display")
        self.assertTrue(r["reasons"])
        self.assertTrue(r["suggestions"])


if __name__ == "__main__":
    unittest.main()
