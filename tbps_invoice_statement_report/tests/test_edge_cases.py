"""Automated coverage for the manual test guide edge cases F2..F9 (invoice) and G1..G8 (statement)."""
import html as _html
import re
from datetime import date

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestReportEdgeCases(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.term = cls.env.ref('account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge')
        cls.partner_a.write({'early_discount_surcharge_terms': True, 'ref': 'C100'})
        cls.report = cls.env['report.tbps_invoice_statement_report.report_customer_statement']

    def _inv(self, invoice_date, amount=1000.0, partner=None, move_type='out_invoice', post=True, **kw):
        return self.init_invoice(move_type, partner=partner or self.partner_a, invoice_date=invoice_date,
                                 amounts=[amount], taxes=self.env['account.tax'], post=post, **kw)

    def _html(self, inv):
        return self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice_with_payments', inv.ids)[0].decode()

    @staticmethod
    def _text(html):
        return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)))

    def _statement(self, partner, statement_date, date_from, date_to):
        return self.report._get_report_values(partner.ids, {
            'statement_date': fields.Date.to_string(statement_date),
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'include_zero_balance': True})['statements'][0]

    # ---------------- invoice layout ----------------
    def test_F2_contact_person_under_company(self):
        person = self.env['res.partner'].create(
            {'name': 'Patrick Burke', 'parent_id': self.partner_a.id, 'type': 'contact'})
        inv = self._inv(date(2026, 9, 1), partner=person)
        d = inv._tbps_invoice_data()
        self.assertEqual(d['customer_no'], 'C100')          # company's number
        text = self._text(self._html(inv))
        self.assertIn(self.partner_a.name, text)
        self.assertIn('Patrick Burke', text)

    def test_F3_incomplete_address_prints_cleanly(self):
        bare = self.env['res.partner'].create({'name': 'Bare Customer'})
        inv = self._inv(date(2026, 9, 1), partner=bare)
        text = self._text(self._html(inv))
        self.assertNotIn('Phone #:', text)
        self.assertNotRegex(text, r'Bare Customer\s*,')

    def test_F4_no_internal_reference_sections_and_notes(self):
        self.product_a.default_code = False
        inv = self._inv(date(2026, 9, 1), post=False)
        inv.write({'invoice_line_ids': [
            Command.create({'display_type': 'line_section', 'name': 'PIPE & FITTINGS'}),
            Command.create({'display_type': 'line_note', 'name': 'Delivered to job site'}),
        ]})
        inv.action_post()
        html = self._html(inv)
        text = self._text(html)
        self.assertIn('PIPE & FITTINGS', text)
        self.assertIn('Delivered to job site', text)
        self.assertEqual(inv.amount_total, 1000.0)

    def test_F5_two_tax_groups(self):
        g1 = self.env['account.tax.group'].create({'name': 'NJ Sales Tax', 'company_id': self.env.company.id})
        g2 = self.env['account.tax.group'].create({'name': 'Exempt', 'company_id': self.env.company.id})
        t1 = self.env['account.tax'].create({'name': 'NJ 6.625%', 'amount': 6.625, 'type_tax_use': 'sale',
                                             'tax_group_id': g1.id, 'company_id': self.env.company.id})
        t2 = self.env['account.tax'].create({'name': 'Exempt 0%', 'amount': 0.0, 'type_tax_use': 'sale',
                                             'tax_group_id': g2.id, 'company_id': self.env.company.id})
        inv = self.init_invoice('out_invoice', partner=self.partner_a, invoice_date=date(2026, 9, 1),
                                amounts=[1000.0, 500.0], taxes=self.env['account.tax'], post=False)
        lines = inv.invoice_line_ids
        lines[0].tax_ids = t1
        lines[1].tax_ids = t2
        inv.action_post()
        d = inv._tbps_invoice_data()
        names = [g['name'] for g in d['tax_groups']]
        self.assertIn('NJ Sales Tax', names)
        self.assertEqual(d['items_subtotal'], 1500.0)
        self.assertEqual(sum(g['amount'] for g in d['tax_groups']), 66.25)

    def test_F6_credit_note_title(self):
        credit = self._inv(date(2026, 9, 1), move_type='out_refund')
        text = self._text(self._html(credit))
        self.assertIn('Credit Note #:', text)
        self.assertNotIn('Due Date:', text)

    def test_F7_two_payments_listed(self):
        inv = self._inv(date(2026, 8, 5))
        for when, amt in ((date(2026, 8, 20), 400.0), (date(2026, 9, 12), 600.0)):
            self.env['account.payment.register'].with_context(active_model='account.move', active_ids=inv.ids).create(
                {'payment_date': when, 'amount': amt})._create_payments()
        d = inv._tbps_invoice_data()
        self.assertEqual(len(d['payments']), 2)
        self.assertEqual(d['total_payments'], 1000.0)
        self.assertEqual(d['balance'], 0.0)
        self.assertEqual(inv.payment_state, 'paid')
        text = self._text(self._html(inv))
        self.assertNotIn('Early payment:', text)

    def test_F8_decimal_quantity_and_zero_line(self):
        inv = self._inv(date(2026, 9, 1), post=False)
        inv.invoice_line_ids[0].quantity = 2.5
        inv.write({'invoice_line_ids': [Command.create({
            'name': 'Free item', 'quantity': 1, 'price_unit': 0.0, 'tax_ids': [Command.clear()],
            'account_id': inv.invoice_line_ids[0].account_id.id})]})
        inv.action_post()
        text = self._text(self._html(inv))
        self.assertIn('2.5', text)
        self.assertIn('Free item', text)
        self.assertEqual(inv.amount_total, 2500.0)

    def test_F9_invoice_from_two_sales_orders(self):
        if 'sale.order' not in self.env:
            self.skipTest('sale not installed')
        SO = self.env['sale.order'].sudo()
        orders = SO
        for ref in ('PO-1', 'PO-2'):
            orders |= SO.create({'partner_id': self.partner_a.id, 'client_order_ref': ref,
                                 'order_line': [Command.create({'product_id': self.product_a.id, 'product_uom_qty': 1,
                                                                'price_unit': 100.0, 'tax_ids': [Command.clear()]})]})
        orders.action_confirm()
        inv = orders._create_invoices()
        inv.invoice_date = date(2026, 9, 1)
        inv.action_post()
        d = inv._tbps_invoice_data()
        self.assertEqual(sorted(d['order_names'].split(', ')), sorted(orders.mapped('name')))
        self.assertEqual(d['order_date'], min(orders.mapped('date_order')).date())

    # ---------------- statement ----------------
    def test_G1_payment_after_period_end(self):
        inv = self._inv(date(2026, 8, 10))
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=inv.ids).create(
            {'payment_date': date(2026, 9, 5)})._create_payments()
        aug = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(aug['rows'][0]['due'], 1000.0)
        self.assertEqual(aug['new_balance'], 1000.0)
        sep = self._statement(self.partner_a, date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(sep['previous_balance'], 1000.0)
        self.assertEqual(sep['payments'], 1000.0)
        self.assertEqual(sep['new_balance'], 0.0)
        self.assertFalse(sep['rows'])

    def test_G3_unapplied_payment_and_open_credit(self):
        self._inv(date(2026, 8, 10))
        payment = self.env['account.payment'].create({'partner_id': self.partner_a.id, 'amount': 200.0,
                                                      'payment_type': 'inbound',
                                                      'partner_type': 'customer', 'date': date(2026, 8, 15),
                                                      'journal_id': self.company_data['default_journal_bank'].id})
        payment.action_post()
        self._inv(date(2026, 8, 20), 50.0, move_type='out_refund')
        s = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        labels = [r['number'] for r in s['rows']]
        self.assertTrue(any(label.startswith('Payment ') for label in labels))
        misc = self.env['account.move'].create({
            'move_type': 'entry', 'date': date(2026, 8, 22), 'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                Command.create({'account_id': self.company_data['default_account_receivable'].id,
                                'partner_id': self.partner_a.id, 'debit': 30.0}),
                Command.create({'account_id': self.company_data['default_account_revenue'].id, 'credit': 30.0}),
            ]})
        misc.action_post()
        s = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        labels = [r['number'] for r in s['rows']]
        self.assertIn('Entry %s' % misc.name, labels)
        self.assertTrue(any(label.startswith('Credit ') for label in labels))
        self.assertEqual(s['payments'], 200.0)
        self.assertEqual(s['credits'], 50.0)
        self.assertEqual(s['new_balance'], 750.0)
        self.assertAlmostEqual(sum(r['due'] for r in s['rows']), 750.0)

    def test_G4_customer_po_number(self):
        inv = self._inv(date(2026, 8, 10), post=False)
        inv.ref = 'PO 55521'
        inv.action_post()
        s = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(s['rows'][0]['po'], 'PO 55521')
        inv2 = self._inv(date(2026, 8, 11), post=False)
        inv2.write({'invoice_origin': 'S00042', 'ref': 'S00042'})
        inv2.action_post()
        s = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual([r['po'] for r in s['rows'] if r['number'] == inv2.name], [''])

    def test_G5_aging_buckets(self):
        for d, amt in ((date(2026, 9, 5), 100.0), (date(2026, 7, 20), 200.0), (date(2026, 6, 10), 300.0),
                       (date(2026, 5, 5), 400.0), (date(2026, 3, 1), 500.0)):
            self._inv(d, amt)
        s = self._statement(self.partner_a, date(2026, 10, 1), date(2026, 9, 1), date(2026, 9, 30))
        aging = dict(s['aging'])
        self.assertEqual(aging['CURRENT'], 100.0)
        self.assertEqual(aging['31-60 DAYS'], 0.0)      # Jul 20 is 72 days old on Sep 30
        self.assertEqual(aging['61-90 DAYS'], 200.0)
        self.assertEqual(aging['91-120 DAYS'], 300.0)   # Jun 10 = 112 days
        self.assertEqual(aging['OVER 120 DAYS'], 900.0)  # May 5 (148) and Mar 1 (213)
        self.assertEqual(sum(aging.values()), s['new_balance'])

    def test_G7_contact_invoices_roll_up_to_company(self):
        person = self.env['res.partner'].create(
            {'name': 'Site Contact', 'parent_id': self.partner_a.id, 'type': 'contact'})
        self._inv(date(2026, 8, 10), 300.0)
        self._inv(date(2026, 8, 12), 200.0, partner=person)
        s = self._statement(self.partner_a, date(2026, 9, 1), date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(s['new_balance'], 500.0)
        self.assertEqual(len(s['rows']), 2)
        # printing from the contact record yields the company statement
        values = self.report._get_report_values(
            person.ids, {'statement_date': '2026-09-01', 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
        self.assertEqual(values['statements'][0]['partner'], self.partner_a)

    def test_G8_period_validation_and_override(self):
        with freeze_time('2026-09-14'):
            w = self.env['tbps.customer.statement.wizard'].create({'statement_date': date(2026, 9, 14)})
            self.assertEqual((w.date_from, w.date_to), (date(2026, 8, 1), date(2026, 8, 31)))
            w.date_to = date(2026, 9, 14)
            self.assertEqual(w.date_to, date(2026, 9, 14))
            with self.assertRaises(UserError):
                w.date_from = date(2026, 9, 20)

    def test_in_process_payment_listed_on_invoice(self):
        """With Enterprise Accounting, a journal without an outstanding account keeps payments 'in process'
        (no journal entry) until the bank statement is matched. The invoice must still print them as received.
        Community always posts an entry for a payment, so this only runs where Enterprise Accounting is installed."""
        if self.env['account.move']._get_invoice_in_payment_state() != 'in_payment':
            self.skipTest('requires Enterprise Accounting (in-process payments without journal entry)')
        bank = self.company_data['default_journal_bank']
        bank.inbound_payment_method_line_ids.write({'payment_account_id': False})
        inv = self._inv(date(2026, 9, 1))
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids).create(
            {'payment_date': date(2026, 9, 10), 'amount': 100.0, 'journal_id': bank.id})
        payment = wizard._create_payments()
        self.assertFalse(payment.move_id)
        self.assertEqual(inv.amount_residual, 1000.0)
        d = inv._tbps_invoice_data()
        self.assertEqual(len(d['payments']), 1)
        self.assertIn('pending bank reconciliation', d['payments'][0]['name'])
        self.assertEqual(d['total_payments'], 100.0)
        self.assertEqual(d['balance'], 900.0)
