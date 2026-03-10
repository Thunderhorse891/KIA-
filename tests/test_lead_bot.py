import os
import tempfile
import unittest

from lead_bot import Lead, LeadBot, draft_reply, invoice_text


class LeadBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.bot = LeadBot(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_add_and_ref_code(self):
        lead_id = self.bot.add_lead(
            Lead("reddit:r/personalfinance", "Asha", "asha@example.com", "Coverage?", "term-life"),
            owner="my-brand",
        )
        lead = self.bot.get_lead(lead_id)
        self.assertTrue(lead["ref_code"].startswith("MYBRAND-LEAD-"))
        self.assertIn("KIACONWELL@PRIMERICA.COM", draft_reply(lead))
        self.assertIn("https://livemore.net/o/kia_conwell", draft_reply(lead))

    def test_mark_sale_and_invoice(self):
        lead_id = self.bot.add_lead(Lead("web", "Lina", "lina@example.com", "Need debt help", "debt"))
        lead = self.bot.get_lead(lead_id)
        self.assertTrue(self.bot.mark_sale(lead["ref_code"], 2300.0))
        sold = self.bot.get_lead(lead_id)
        self.assertEqual(sold["status"], "sold")
        self.assertIn("$50.00", invoice_text(sold))

    def test_mark_paid_and_weekly_summary(self):
        lead_id = self.bot.add_lead(Lead("web", "Nia", "nia@example.com", "Savings", "invest"))
        lead = self.bot.get_lead(lead_id)
        self.bot.mark_sale(lead["ref_code"], 2000.0)
        self.assertTrue(self.bot.mark_paid(lead["ref_code"], 50.0))
        paid = self.bot.get_lead(lead_id)
        self.assertEqual(paid["status"], "paid")
        summary = self.bot.weekly_summary(days=7)
        self.assertIn("Referral invoices paid", summary)


if __name__ == "__main__":
    unittest.main()
