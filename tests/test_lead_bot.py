import os
import tempfile
import unittest

from lead_bot import Referral, ReferralBot, build_parser, draft_partner_intro, finder_fee_invoice_text


class ReferralBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.bot = ReferralBot(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_add_referral_and_ref_code(self):
        referral_id = self.bot.add_referral(
            Referral("reddit:r/personalfinance", "Asha", "asha@example.com", "Coverage?", "term-life"),
            owner="erin-brand",
        )
        referral = self.bot.get_referral(referral_id)
        self.assertTrue(referral["ref_code"].startswith("ERINBRAND-REF-"))
        self.assertIn("kiaconwell@gmail.com", draft_partner_intro(referral))

    def test_mark_partner_closed_and_invoice(self):
        referral_id = self.bot.add_referral(Referral("web", "Lina", "lina@example.com", "Need debt help", "debt"))
        referral = self.bot.get_referral(referral_id)
        self.assertTrue(self.bot.mark_partner_closed(referral["ref_code"], 2300.0, 50.0))
        closed = self.bot.get_referral(referral_id)
        self.assertEqual(closed["status"], "partner_closed")
        self.assertIn("Finder's Fee Due", finder_fee_invoice_text(closed, 50.0))
        self.assertIn("$50.00", finder_fee_invoice_text(closed, 50.0))

    def test_mark_finders_fee_paid_and_summary(self):
        referral_id = self.bot.add_referral(Referral("web", "Nia", "nia@example.com", "Savings", "invest"))
        referral = self.bot.get_referral(referral_id)
        self.bot.mark_partner_closed(referral["ref_code"], 2000.0, 50.0)
        self.assertTrue(self.bot.mark_finder_fee_paid(referral["ref_code"], 50.0))
        paid = self.bot.get_referral(referral_id)
        self.assertEqual(paid["status"], "fee_paid")
        summary = self.bot.referral_summary(days=7)
        self.assertIn("Finder's fees paid", summary)

    def test_new_cli_names(self):
        parser = build_parser()
        args = parser.parse_args(["referral-summary", "--days", "7", "--email", "--to", "me@example.com"])
        self.assertEqual(args.days, 7)
        self.assertTrue(args.email)
        self.assertEqual(args.to, "me@example.com")

    def test_legacy_cli_aliases_still_parse(self):
        parser = build_parser()
        args = parser.parse_args(["mark-sold", "--ref-code", "ERIN-REF-000001", "--sale-amount", "1200"])
        self.assertEqual(args.ref_code, "ERIN-REF-000001")


if __name__ == "__main__":
    unittest.main()
