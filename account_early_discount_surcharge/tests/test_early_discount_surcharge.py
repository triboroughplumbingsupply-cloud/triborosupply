import re
from datetime import date

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestEarlyDiscountSurcharge(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.term = cls.env.ref('account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge')
        cls.partner_a.early_discount_surcharge_terms = True

    def _invoice(self, invoice_date, amount=1000.0, post=True):
        return self.init_invoice(
            'out_invoice', partner=self.partner_a, invoice_date=invoice_date,
            amounts=[amount], taxes=self.env['account.tax'], post=post,
        )

    def test_partner_toggle_sets_payment_term(self):
        self.assertEqual(self.partner_a.property_payment_term_id, self.term)
        self.partner_a.early_discount_surcharge_terms = False
        self.assertFalse(self.partner_a.property_payment_term_id)

    def test_deadlines(self):
        inv = self._invoice(date(2026, 1, 15))
        self.assertEqual(inv.invoice_payment_term_id, self.term)
        self.assertEqual(inv.early_discount_deadline, date(2026, 2, 10))
        self.assertEqual(inv.invoice_date_due, date(2026, 2, 28))
        term_line = inv.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        self.assertEqual(term_line.discount_date, date(2026, 2, 10))
        self.assertEqual(inv.early_discount_amount_due, 980.0)
        self.assertEqual(inv.late_surcharge_amount, 15.0)

    def test_deadlines_end_of_year(self):
        inv = self._invoice(date(2026, 12, 3))
        self.assertEqual(inv.early_discount_deadline, date(2027, 1, 10))
        self.assertEqual(inv.invoice_date_due, date(2027, 1, 31))

    def test_early_payment_takes_discount(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-02-05'):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids,
            ).create({'payment_date': date(2026, 2, 5)})
            self.assertTrue(wizard.early_payment_discount_mode)
            self.assertEqual(wizard.amount, 980.0)
            wizard._create_payments()
        self.assertEqual(inv.payment_state, 'paid')
        self.assertEqual(inv.amount_residual, 0.0)

    def test_payment_after_deadline_is_full_amount(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-02-20'):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids,
            ).create({'payment_date': date(2026, 2, 20)})
            self.assertFalse(wizard.early_payment_discount_mode)
            self.assertEqual(wizard.amount, 1000.0)

    def test_surcharge_not_due_before_due_date(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-02-28'):
            self.assertFalse(inv._is_late_surcharge_due(fields.Date.context_today(inv)))
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertFalse(inv.late_surcharge_move_id)

    def test_surcharge_added_to_invoice_after_due_date(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.late_surcharge_date, date(2026, 3, 1))
        self.assertEqual(inv.late_surcharge_applied_amount, 15.0)
        self.assertEqual(inv.amount_total, 1015.0)
        self.assertEqual(inv.amount_residual, 1015.0)
        self.assertEqual(inv.state, 'posted')
        self.assertEqual(inv.payment_state, 'not_paid')
        self.assertFalse(inv.late_surcharge_move_id)
        self.assertTrue(inv.late_surcharge_line_id)
        self.assertEqual(inv.late_surcharge_line_id.price_subtotal, 15.0)
        self.assertEqual(inv.late_surcharge_line_id.product_id, self.env.company.late_surcharge_product_id)
        self.assertAlmostEqual(sum(inv.line_ids.mapped('balance')), 0.0)
        term_lines = inv.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        self.assertEqual(len(term_lines), 2)
        self.assertEqual(sum(term_lines.mapped('amount_residual')), 1015.0)
        self.assertFalse(inv.late_surcharge_due)
        # Idempotent: a second run does nothing
        with freeze_time('2026-03-02'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.amount_total, 1015.0)
        # Paying the same day the surcharge was applied already proposes the full 1015
        with freeze_time('2026-03-01'):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids,
            ).create({'payment_date': date(2026, 3, 1)})
            self.assertEqual(wizard.amount, 1015.0)
            surcharge_term = inv.line_ids.filtered(
                lambda line: line.is_late_surcharge and line.display_type == 'payment_term')
            self.assertEqual(surcharge_term.date_maturity, date(2026, 2, 28))
        # Full payment afterwards settles the surcharge too
        with freeze_time('2026-03-05'):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids,
            ).create({'payment_date': date(2026, 3, 5)})
            self.assertEqual(wizard.amount, 1015.0)
            self.assertFalse(wizard.early_payment_discount_mode)
            wizard._create_payments()
        self.assertEqual(inv.payment_state, 'paid')
        self.assertEqual(inv.amount_residual, 0.0)

    def test_surcharge_on_partial_balance_added_to_invoice(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-02-20'):
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids,
            ).create({'payment_date': date(2026, 2, 20), 'amount': 600.0})._create_payments()
        self.assertEqual(inv.amount_residual, 400.0)
        with freeze_time('2026-03-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.late_surcharge_applied_amount, 6.0)
        self.assertEqual(inv.amount_total, 1006.0)
        self.assertEqual(inv.amount_residual, 406.0)
        self.assertEqual(inv.payment_state, 'partial')

    def test_surcharge_blocked_by_lock_date(self):
        inv = self._invoice(date(2026, 1, 15))
        self.env.company.fiscalyear_lock_date = date(2026, 1, 31)
        with freeze_time('2026-03-01'), self.assertRaises(UserError):
            inv.action_apply_late_surcharge()
        self.assertFalse(inv.late_surcharge_date)
        self.assertEqual(inv.amount_total, 1000.0)

    def _report_text(self, inv):
        html = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', inv.ids)[0].decode()
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html))

    def test_invoice_report_renders_terms(self):
        inv = self._invoice(date(2026, 1, 15))
        text = self._report_text(inv)
        self.assertIn('Early payment:', text)
        self.assertIn('2% discount', text)
        self.assertIn('Late payment:', text)
        self.assertIn('1.5% surcharge', text)
        # native early-discount line is replaced by our block, not duplicated
        self.assertEqual(text.count('980.00'), 1)

    def test_report_after_surcharge_applied(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            inv.action_apply_late_surcharge()
        text = self._report_text(inv)
        self.assertNotIn('Early payment:', text)
        self.assertIn('was applied on', text)
        self.assertIn('1,015.00', text)

    # ---- separate invoice method ----
    def test_separate_invoice_method(self):
        self.env.company.late_surcharge_method = 'separate_invoice'
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        surcharge = inv.late_surcharge_move_id
        self.assertTrue(surcharge)
        self.assertEqual(inv.amount_total, 1000.0)
        self.assertEqual(inv.late_surcharge_date, date(2026, 3, 1))
        self.assertEqual(surcharge.state, 'posted')
        self.assertEqual(surcharge.partner_id, self.partner_a)
        self.assertEqual(surcharge.amount_total, 15.0)
        self.assertEqual(surcharge.late_surcharge_origin_move_id, inv)
        self.assertEqual(surcharge.invoice_date, date(2026, 3, 1))
        self.assertFalse(surcharge.late_surcharge_applicable)
        with freeze_time('2026-03-02'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(self.env['account.move'].search_count(
            [('late_surcharge_origin_move_id', '=', inv.id)]), 1)

    def test_separate_invoice_draft_when_auto_post_disabled(self):
        self.env.company.late_surcharge_method = 'separate_invoice'
        self.env.company.late_surcharge_auto_post = False
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            inv.action_apply_late_surcharge()
        self.assertEqual(inv.late_surcharge_move_id.state, 'draft')

    # ------------------------------------------------------------------
    # Configurability: nothing hard-coded
    # ------------------------------------------------------------------
    def test_rates_come_from_payment_term(self):
        self.term.write({
            'discount_percentage': 3.0,
            'discount_day_of_next_month': 15,
            'late_surcharge_percentage': 2.5,
        })
        inv = self._invoice(date(2026, 1, 15))
        self.assertEqual(inv.early_discount_deadline, date(2026, 2, 15))
        self.assertEqual(inv.early_discount_amount_due, 970.0)
        self.assertEqual(inv.late_surcharge_amount, 25.0)
        with freeze_time('2026-03-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.late_surcharge_applied_amount, 25.0)
        self.assertEqual(inv.amount_total, 1025.0)
        inv2 = self._invoice(date(2026, 1, 15))
        text = self._report_text(inv2)
        self.assertIn('3% discount', text)
        self.assertIn('2.5% surcharge', text)
        self.assertIn('970.00', text)

    def test_toggle_uses_company_configured_term(self):
        other_term = self.term.copy({'name': 'Custom 5% by the 5th', 'discount_percentage': 5.0,
                                     'discount_day_of_next_month': 5})
        self.env.company.early_discount_surcharge_term_id = other_term
        partner = self.env['res.partner'].create({'name': 'Toggle Customer'})
        self.assertFalse(partner.early_discount_surcharge_terms)
        self.assertEqual(partner.early_discount_surcharge_term_name, other_term.display_name)
        partner.early_discount_surcharge_terms = True
        self.assertEqual(partner.property_payment_term_id, other_term)
        partner.early_discount_surcharge_terms = False
        self.assertFalse(partner.property_payment_term_id)

    def test_toggle_without_configured_term_raises(self):
        self.env.company.early_discount_surcharge_term_id = False
        partner = self.env['res.partner'].create({'name': 'No Term Customer'})
        with self.assertRaises(UserError):
            partner.early_discount_surcharge_terms = True

    def test_toggle_via_form_view(self):
        partner = self.env['res.partner'].create({'name': 'Form Customer'})
        with Form(partner) as f:
            f.early_discount_surcharge_terms = True
        self.assertEqual(partner.property_payment_term_id, self.term)
        with Form(partner) as f:
            f.early_discount_surcharge_terms = False
        self.assertFalse(partner.property_payment_term_id)

    def test_views_load(self):
        """All inherited views compile with the current field set (catches broken xpaths / invisible expressions)."""
        for model, xmlid in [
            ('res.partner', 'base.view_partner_form'),
            ('account.move', 'account.view_move_form'),
            ('account.move', 'account.view_invoice_tree'),
            ('account.move', 'account.view_account_invoice_filter'),
            ('account.payment.term', 'account.view_payment_term_form'),
            ('res.config.settings', 'account.res_config_settings_view_form'),
        ]:
            view = self.env.ref(xmlid)
            arch = self.env[model].get_view(view.id, view.type)['arch']
            self.assertTrue(arch, f"{xmlid} did not render")
        settings = self.env['res.config.settings'].create({})
        self.assertEqual(settings.early_discount_surcharge_term_id, self.term)
        self.assertTrue(settings.late_surcharge_product_id)
        with Form(self.env['account.payment.term']) as f:
            f.name = 'UI term'
            f.early_discount = True
            f.discount_deadline_type = 'day_of_next_month'
            f.discount_day_of_next_month = 12
            f.late_surcharge = True
            f.late_surcharge_percentage = 2.0
        self.assertEqual(f.record.discount_day_of_next_month, 12)

    def test_surcharge_lines_are_flagged(self):
        inv = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            inv.action_apply_late_surcharge()
        flagged = inv.line_ids.filtered('is_late_surcharge')
        self.assertEqual(len(flagged), 2)
        self.assertAlmostEqual(sum(flagged.mapped('balance')), 0.0)
        self.assertFalse((inv.line_ids - flagged).filtered('is_late_surcharge'))
        self.env.company.late_surcharge_method = 'separate_invoice'
        inv2 = self._invoice(date(2026, 1, 15))
        with freeze_time('2026-03-01'):
            inv2.action_apply_late_surcharge()
        self.assertTrue(all(inv2.late_surcharge_move_id.line_ids.mapped('is_late_surcharge')))
