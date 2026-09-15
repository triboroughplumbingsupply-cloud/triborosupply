import re
from datetime import date

from freezegun import freeze_time

from odoo import fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.tbps_invoice_statement_report import _post_init_hook


@tagged('post_install', '-at_install')
class TestTbpsReports(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.term = cls.env.ref('account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge')
        cls.partner_a.write({'early_discount_surcharge_terms': True, 'ref': 'C100', 'phone': '201-555-0100'})
        cls.product_a.default_code = 'BC000693'

    def _invoice(self, invoice_date, amount=1000.0, move_type='out_invoice', post=True, with_product=False):
        kwargs = {'products': self.product_a} if with_product else {'amounts': [amount]}
        return self.init_invoice(
            move_type, partner=self.partner_a, invoice_date=invoice_date,
            taxes=self.env['account.tax'], post=post, **kwargs,
        )

    def _pay(self, inv, when, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=inv.ids,
        ).create({'payment_date': when, **({'amount': amount} if amount else {})})
        wizard._create_payments()

    @staticmethod
    def _text(html):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))

    def _statement_values(self, statement_date, date_from, date_to):
        report = self.env['report.tbps_invoice_statement_report.report_customer_statement']
        return report._get_report_values(self.partner_a.ids, {
            'statement_date': fields.Date.to_string(statement_date),
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'include_zero_balance': True,
        })['statements'][0]

    # ------------------------------------------------------------------
    # Invoice layout
    # ------------------------------------------------------------------
    def test_invoice_uses_tbps_layout(self):
        inv = self._invoice(date(2026, 1, 15), with_product=True)
        self.assertEqual(inv._get_name_invoice_report(), 'tbps_invoice_statement_report.report_invoice_document_tbps')
        html = self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice_with_payments', inv.ids)[0].decode()
        text = self._text(html)
        for expected in ('Bill To:', 'Ship To:', 'Customer #: C100', 'Item #', 'BC000693', 'Ext Price',
                         'Items Subtotal:', 'Total Payments:', 'Balance:', 'Phone #: 201-555-0100', inv.name):
            self.assertIn(expected, text)
        self.assertIn('/report/barcode/?barcode_type=Code128&amp;value=%s' % inv.name, html)

    def test_invoice_layout_can_be_disabled(self):
        self.env.company.tbps_invoice_layout = False
        inv = self._invoice(date(2026, 1, 15))
        self.assertEqual(inv._get_name_invoice_report(), 'account.report_invoice_document')

    def test_invoice_payments_and_balance(self):
        inv = self._invoice(date(2026, 1, 15))
        self._pay(inv, date(2026, 2, 20), 600.0)
        d = inv._tbps_invoice_data()
        self.assertEqual(d['total_payments'], 600.0)
        self.assertEqual(d['balance'], 400.0)
        self.assertEqual(len(d['payments']), 1)
        self.assertEqual(d['payments'][0]['amount'], 600.0)
        self.assertEqual(d['items_subtotal'], 1000.0)
        self.assertEqual(d['discounts'], 0.0)

    def test_invoice_terms_seeded(self):
        self.env.company.invoice_terms = False
        _post_init_hook(self.env)
        self.assertIn('We accept general returns', self.env.company.invoice_terms)
        inv = self._invoice(date(2026, 1, 15))
        html = self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice_with_payments', inv.ids)[0].decode()
        self.assertIn('We accept general returns', html)

    # ------------------------------------------------------------------
    # Customer statement
    # ------------------------------------------------------------------
    def test_statement_open_items_and_summary(self):
        old = self._invoice(date(2025, 12, 10), 500.0)          # previous balance
        inv1 = self._invoice(date(2026, 1, 15), 1000.0)         # net purchases
        inv2 = self._invoice(date(2026, 1, 20), 300.0)
        self._pay(inv2, date(2026, 1, 25))                      # paid in period
        self._pay(inv1, date(2026, 1, 28), 200.0)               # partial payment
        credit = self._invoice(date(2026, 1, 30), 50.0, move_type='out_refund')
        s = self._statement_values(date(2026, 2, 1), date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(s['previous_balance'], 500.0)
        self.assertEqual(s['purchases'], 1300.0)
        self.assertEqual(s['payments'], 500.0)
        self.assertEqual(s['credits'], 50.0)
        self.assertEqual(s['service_charges'], 0.0)
        self.assertEqual(s['new_balance'], 1250.0)
        self.assertEqual(s['previous_balance'] + s['purchases'] - s['payments'] - s['credits'] + s['service_charges'],
                         s['new_balance'])
        rows = {r['number']: r for r in s['rows']}
        self.assertEqual(rows[old.name]['due'], 500.0)
        self.assertEqual(rows[inv1.name]['due'], 800.0)
        self.assertEqual(rows[inv1.name]['amount'], 1000.0)
        self.assertNotIn(inv2.name, rows)                        # fully paid
        self.assertEqual(rows['Credit %s' % credit.name]['due'], -50.0)
        # Discount: only January invoices qualify (deadline Feb 10 >= statement date Feb 1)
        self.assertEqual(s['discount_percentage'], 2.0)
        self.assertEqual(s['discount_total'], 16.0)              # 2% of 800
        self.assertEqual(s['discount_date'], date(2026, 2, 10))
        self.assertEqual(s['total_due'], 1234.0)
        self.assertEqual(s['surcharge_percentage'], 1.5)
        self.assertEqual(s['customer_no'], 'C100')
        self.assertEqual(s['terms_name'], self.term.name)
        aging = dict(s['aging'])
        self.assertEqual(aging['CURRENT'], 750.0)               # 800 - 50 credit, both January
        self.assertEqual(aging['31-60 DAYS'], 500.0)             # Dec 10 invoice is 52 days old on Jan 31

    def test_statement_residual_as_of_date_ignores_later_payments(self):
        inv = self._invoice(date(2026, 1, 15), 1000.0)
        self._pay(inv, date(2026, 2, 15))                        # paid after the period
        s = self._statement_values(date(2026, 2, 1), date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(s['new_balance'], 1000.0)
        self.assertEqual(s['rows'][0]['due'], 1000.0)
        s2 = self._statement_values(date(2026, 3, 1), date(2026, 2, 1), date(2026, 2, 28))
        self.assertEqual(s2['new_balance'], 0.0)
        self.assertEqual(s2['payments'], 1000.0)
        self.assertEqual(s2['previous_balance'], 1000.0)

    def test_statement_service_charges(self):
        inv = self._invoice(date(2026, 1, 15), 1000.0)
        with freeze_time('2026-03-01'):
            inv.action_apply_late_surcharge()
        # January statement: surcharge did not exist yet
        s = self._statement_values(date(2026, 2, 1), date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(s['service_charges'], 0.0)
        self.assertEqual(s['purchases'], 1000.0)
        self.assertEqual(s['new_balance'], 1000.0)
        self.assertEqual(s['rows'][0]['amount'], 1000.0)
        self.assertEqual(s['rows'][0]['due'], 1000.0)
        # March statement: surcharge reported in the month it was applied
        s = self._statement_values(date(2026, 4, 1), date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(s['previous_balance'], 1000.0)
        self.assertEqual(s['service_charges'], 15.0)
        self.assertEqual(s['purchases'], 0.0)
        self.assertEqual(s['new_balance'], 1015.0)
        self.assertEqual(s['rows'][0]['amount'], 1015.0)
        self.assertEqual(s['rows'][0]['due'], 1015.0)

    def test_statement_customer_not_on_program(self):
        self.partner_b.property_payment_term_id = False
        self.init_invoice('out_invoice', partner=self.partner_b, invoice_date=date(2026, 1, 15),
                          amounts=[100.0], taxes=self.env['account.tax'], post=True)
        report = self.env['report.tbps_invoice_statement_report.report_customer_statement']
        s = report._get_report_values(self.partner_b.ids, {
            'statement_date': '2026-02-01', 'date_from': '2026-01-01', 'date_to': '2026-01-31'})['statements'][0]
        self.assertEqual(s['terms_name'], '')
        self.assertEqual(s['discount_percentage'], 0.0)
        self.assertEqual(s['surcharge_percentage'], 0.0)
        self.assertEqual(s['total_due'], 100.0)

    def test_statement_wizard_defaults_and_render(self):
        self._invoice(date(2026, 1, 15), 1000.0)
        with freeze_time('2026-02-05'):
            wizard = self.env['tbps.customer.statement.wizard'].create({'partner_ids': [(6, 0, self.partner_a.ids)]})
            self.assertEqual(wizard.statement_date, date(2026, 2, 1))
            self.assertEqual(wizard.date_from, date(2026, 1, 1))
            self.assertEqual(wizard.date_to, date(2026, 1, 31))
            action = wizard.action_print()
        self.assertEqual(action['report_name'], 'tbps_invoice_statement_report.report_customer_statement')
        html = self.env['ir.actions.report']._render_qweb_html(
            'tbps_invoice_statement_report.report_customer_statement', self.partner_a.ids, data=action['data'],
        )[0].decode()
        text = self._text(html)
        for expected in ('STATEMENT', 'STATEMENT DATE:', 'CUSTOMER #: C100', 'REMIT TO:', 'TERMS:',
                         'PREVIOUS BALANCE', 'SERVICE CHARGES', 'NEW BALANCE', 'OVER 120 DAYS',
                         'ACCOUNT NUMBER:', 'TOTAL AMOUNT DUE:', '1.5% SERVICE CHARGE ON UNPAID BALANCE',
                         'Pay by check by 02/10/2026 and save 2%'):
            self.assertIn(expected, text)

    def test_statement_all_customers_skips_zero_balance(self):
        self._invoice(date(2026, 1, 15), 1000.0)
        with freeze_time('2026-02-05'):
            wizard = self.env['tbps.customer.statement.wizard'].create({})
            partners = wizard._get_partners()
        self.assertIn(self.partner_a, partners)
        self.assertNotIn(self.partner_b, partners)

    def test_views_load(self):
        for model, xmlid in [
            ('res.config.settings', 'account.res_config_settings_view_form'),
            ('tbps.customer.statement.wizard', 'tbps_invoice_statement_report.view_customer_statement_wizard_form'),
        ]:
            view = self.env.ref(xmlid)
            self.assertTrue(self.env[model].get_view(view.id, view.type)['arch'])

    def test_statement_ids_from_data(self):
        self._invoice(date(2026, 1, 15), 1000.0)
        report = self.env['report.tbps_invoice_statement_report.report_customer_statement']
        values = report._get_report_values([], {
            'partner_ids': self.partner_a.ids,
            'statement_date': '2026-02-01', 'date_from': '2026-01-01', 'date_to': '2026-01-31',
        })
        self.assertEqual(values['docs'], self.partner_a)
        self.assertEqual(values['statements'][0]['new_balance'], 1000.0)

    def test_paperformats(self):
        tight = self.env.ref('tbps_invoice_statement_report.paperformat_tbps')
        statement_report = self.env.ref('tbps_invoice_statement_report.action_report_customer_statement')
        self.assertEqual(statement_report.get_paperformat(), tight)
        inv_report = self.env.ref('account.account_invoices')
        self.assertEqual(inv_report.get_paperformat(), tight)
        self.env.company.tbps_invoice_layout = False
        self.assertNotEqual(inv_report.get_paperformat(), tight)
