"""Automated coverage for the edge cases listed in the manual test guide (IDs E1..E17)."""
from datetime import date

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestSurchargeEdgeCases(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.term = cls.env.ref('account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge')
        cls.partner_a.early_discount_surcharge_terms = True

    def _invoice(self, invoice_date, amount=1000.0, taxes=None, post=True, partner=None):
        return self.init_invoice(
            'out_invoice', partner=partner or self.partner_a, invoice_date=invoice_date,
            amounts=[amount], taxes=taxes if taxes is not None else self.env['account.tax'], post=post,
        )

    def _wizard(self, inv, when, amount=None):
        vals = {'payment_date': when}
        if amount is not None:
            vals['amount'] = amount
        return self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids).create(vals)

    def test_E1_paid_exactly_on_the_10th_is_inclusive(self):
        inv = self._invoice(date(2026, 8, 5))
        with freeze_time('2026-09-10'):
            w = self._wizard(inv, date(2026, 9, 10))
            self.assertTrue(w.early_payment_discount_mode)
            self.assertEqual(w.amount, 980.0)
        inv2 = self._invoice(date(2026, 8, 5))
        with freeze_time('2026-09-11'):
            w = self._wizard(inv2, date(2026, 9, 11))
            self.assertFalse(w.early_payment_discount_mode)
            self.assertEqual(w.amount, 1000.0)

    def test_E2_month_end_and_year_rollover(self):
        inv = self._invoice(date(2026, 8, 31))
        self.assertEqual(inv.early_discount_deadline, date(2026, 9, 10))
        self.assertEqual(inv.invoice_date_due, date(2026, 9, 30))
        inv = self._invoice(date(2026, 12, 3))
        self.assertEqual(inv.early_discount_deadline, date(2027, 1, 10))
        self.assertEqual(inv.invoice_date_due, date(2027, 1, 31))

    def test_E3_partial_payment_inside_window_takes_no_discount(self):
        inv = self._invoice(date(2026, 9, 1))
        with freeze_time('2026-09-14'):
            self._wizard(inv, date(2026, 9, 14), 500.0)._create_payments()
            self.assertEqual(inv.amount_residual, 500.0)
            w = self._wizard(inv, date(2026, 9, 14))
            self.assertFalse(w.early_payment_discount_mode)
            self.assertEqual(w.amount, 500.0)

    def test_E5_full_credit_note_blocks_surcharge(self):
        inv = self._invoice(date(2026, 7, 15))
        reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=inv.ids).create({
                'date': date(2026, 8, 1), 'journal_id': inv.journal_id.id})
        reversal.modify_moves()  # full refund, reconciled
        self.assertEqual(inv.payment_state, 'reversed')
        with freeze_time('2026-09-14'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertFalse(inv.late_surcharge_date)

    def test_E5b_partial_credit_note_surcharges_the_remainder(self):
        inv = self._invoice(date(2026, 7, 15))
        credit = self.init_invoice('out_refund', partner=self.partner_a, invoice_date=date(2026, 8, 1),
                                   amounts=[300.0], taxes=self.env['account.tax'], post=True)
        (inv + credit).line_ids.filtered(lambda line: line.account_id.account_type == 'asset_receivable').reconcile()
        self.assertEqual(inv.amount_residual, 700.0)
        with freeze_time('2026-09-14'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.late_surcharge_applied_amount, 10.5)
        self.assertEqual(inv.amount_residual, 710.5)

    def test_E6_tax_discount_on_total_surcharge_untaxed(self):
        tax = self.env['account.tax'].create({'name': 'NJ 6.625%', 'amount': 6.625, 'type_tax_use': 'sale',
                                              'company_id': self.env.company.id})
        inv = self._invoice(date(2026, 9, 1), taxes=tax)
        self.assertEqual(inv.amount_total, 1066.25)
        self.assertEqual(inv.early_discount_amount_due, 1044.93)
        overdue = self._invoice(date(2026, 7, 15), taxes=tax)
        with freeze_time('2026-09-14'):
            overdue.action_apply_late_surcharge()
        self.assertEqual(overdue.late_surcharge_applied_amount, 15.99)
        self.assertFalse(overdue.late_surcharge_line_id.tax_ids)
        self.assertEqual(overdue.amount_tax, 66.25)  # unchanged: surcharge is untaxed
        self.assertEqual(overdue.amount_total, 1082.24)

    def test_E7_one_time_only(self):
        inv = self._invoice(date(2026, 7, 15))
        with freeze_time('2026-09-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        with freeze_time('2026-10-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        with freeze_time('2026-11-01'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.amount_total, 1015.0)
        self.assertEqual(len(inv.line_ids.filtered('is_late_surcharge')), 2)

    def test_E10_toggle_off_keeps_existing_invoices(self):
        existing = self._invoice(date(2026, 7, 15))
        self.partner_a.early_discount_surcharge_terms = False
        self.assertFalse(self.partner_a.property_payment_term_id)
        self.assertEqual(existing.invoice_payment_term_id, self.term)
        new = self._invoice(date(2026, 7, 15))
        self.assertFalse(new.invoice_payment_term_id)
        self.assertFalse(new.late_surcharge_applicable)
        with freeze_time('2026-09-14'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertTrue(existing.late_surcharge_date)
        self.assertFalse(new.late_surcharge_date)
        self.partner_a.early_discount_surcharge_terms = True

    def test_E11_other_term_on_one_invoice(self):
        immediate = self.env.ref('account.account_payment_term_immediate')
        inv = self._invoice(date(2026, 7, 15), post=False)
        inv.invoice_payment_term_id = immediate
        inv.action_post()
        self.assertFalse(inv.late_surcharge_applicable)
        self.assertFalse(inv.early_discount_deadline)
        with freeze_time('2026-09-14'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertFalse(inv.late_surcharge_date)

    def test_E12_invoice_from_sales_order(self):
        if 'sale.order' not in self.env:
            self.skipTest('sale not installed')
        so = self.env['sale.order'].sudo().create({
            'partner_id': self.partner_a.id,
            'order_line': [Command.create({'product_id': self.product_a.id, 'product_uom_qty': 1, 'price_unit': 1000.0,
                                           'tax_ids': [Command.clear()]})],
        })
        self.assertEqual(so.payment_term_id, self.term)
        so.action_confirm()
        inv = so._create_invoices()
        inv.invoice_date = date(2026, 7, 15)
        inv.action_post()
        self.assertEqual(inv.invoice_payment_term_id, self.term)
        self.assertEqual(inv.invoice_date_due, date(2026, 8, 31))
        with freeze_time('2026-09-14'):
            inv.action_apply_late_surcharge()
        self.assertEqual(inv.amount_total, 1015.0)

    def test_E13_draft_invoices_ignored(self):
        inv = self._invoice(date(2026, 7, 15), post=False)
        with freeze_time('2026-09-14'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertFalse(inv.late_surcharge_date)
        self.assertEqual(inv.state, 'draft')

    def test_E14_reset_to_draft_and_repost(self):
        inv = self._invoice(date(2026, 7, 15))
        with freeze_time('2026-09-14'):
            inv.action_apply_late_surcharge()
        inv.button_draft()
        inv.action_post()
        self.assertEqual(inv.amount_total, 1015.0)
        self.assertTrue(inv.late_surcharge_date)
        self.assertFalse(inv.late_surcharge_due)
        with freeze_time('2026-09-15'):
            self.env['account.move']._cron_apply_late_surcharges()
        self.assertEqual(inv.amount_total, 1015.0)

    def test_E15_bank_reconciliation_discount(self):
        inv = self._invoice(date(2026, 9, 1))
        bank = self.company_data['default_journal_bank']
        with freeze_time('2026-09-14'):
            st_line = self.env['account.bank.statement.line'].create({
                'journal_id': bank.id, 'date': date(2026, 9, 14), 'payment_ref': inv.name, 'amount': 980.0,
                'partner_id': self.partner_a.id})
            wizard = st_line._get_reconcile_wizard() if hasattr(st_line, '_get_reconcile_wizard') else None
        if wizard is None:
            self.skipTest('bank reconciliation widget not available in this build')
        term_line = inv.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        wizard._action_add_new_amls(term_line)
        wizard._action_validate()
        self.assertEqual(inv.payment_state, 'paid')
        self.assertEqual(inv.amount_residual, 0.0)

    def test_E17_missing_surcharge_product(self):
        self.env.company.late_surcharge_product_id = False
        inv = self._invoice(date(2026, 7, 15))
        with freeze_time('2026-09-14'), self.assertRaises(UserError):
            inv.action_apply_late_surcharge()
        self.assertEqual(inv.amount_total, 1000.0)
