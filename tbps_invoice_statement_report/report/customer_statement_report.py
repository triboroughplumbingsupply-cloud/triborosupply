from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomerStatementReport(models.AbstractModel):
    _name = 'report.tbps_invoice_statement_report.report_customer_statement'
    _description = 'Customer Statement Report'

    AGING_BUCKETS = (
        ('current', 'CURRENT', 0, 30),
        ('b31_60', '31-60 DAYS', 31, 60),
        ('b61_90', '61-90 DAYS', 61, 90),
        ('b91_120', '91-120 DAYS', 91, 120),
        ('over120', 'OVER 120 DAYS', 121, None),
    )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    @api.model
    def _receivable_lines(self, partner, company, date_to):
        return self.env['account.move.line'].search([
            ('company_id', '=', company.id),
            ('partner_id', 'child_of', partner.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('date', '<=', date_to),
        ], order='date, id')

    @api.model
    def _line_date(self, line):
        """Statement date of a receivable line. Surcharge items are added to the original
        invoice (which keeps its own date), so they are reported on the day the surcharge
        was applied, not on the invoice date."""
        if line.is_late_surcharge and line.move_id.late_surcharge_date:
            return line.move_id.late_surcharge_date
        return line.date

    @api.model
    def _residual_at(self, line, date_to):
        """Company-currency residual of a receivable line as of ``date_to``,
        counting only reconciliations whose latest counterpart is dated on or before that day."""
        residual = line.balance
        for partial in line.matched_credit_ids:
            if partial.max_date <= date_to:
                residual -= partial.amount
        for partial in line.matched_debit_ids:
            if partial.max_date <= date_to:
                residual += partial.amount
        return line.company_currency_id.round(residual)

    @api.model
    def _statement_terms(self, partner, company):
        return partner.property_payment_term_id

    @api.model
    def _partner_values(self, partner, company, statement_date, date_from, date_to):
        currency = company.currency_id
        lines = self._receivable_lines(partner, company, date_to).filtered(
            lambda line: self._line_date(line) <= date_to)

        previous_balance = sum(lines.filtered(lambda line: self._line_date(line) < date_from).mapped('balance'))
        period_lines = lines.filtered(lambda line: date_from <= self._line_date(line) <= date_to)
        service_charges = sum(period_lines.filtered('is_late_surcharge').mapped('balance'))
        purchases = sum(period_lines.filtered(
            lambda line: line.move_id.move_type == 'out_invoice' and not line.is_late_surcharge).mapped('balance'))
        credits = -sum(period_lines.filtered(lambda line: line.move_id.move_type == 'out_refund').mapped('balance'))
        payments = -sum(period_lines.filtered(
            lambda line: line.move_id.move_type not in ('out_invoice', 'out_refund')).mapped('balance'))
        new_balance = sum(lines.mapped('balance'))

        # Open items as of date_to, grouped by journal entry
        residual_by_move, amount_by_move = defaultdict(float), defaultdict(float)
        for line in lines:
            amount_by_move[line.move_id] += line.balance
            residual = self._residual_at(line, date_to)
            if not currency.is_zero(residual):
                residual_by_move[line.move_id] += residual
        term = self._statement_terms(partner, company)
        rows, aging = [], {key: 0.0 for key, *_ in self.AGING_BUCKETS}
        discount_total, discount_dates = 0.0, []
        for move in sorted(residual_by_move, key=lambda m: (m.date, m.name or '')):
            residual = currency.round(residual_by_move[move])
            is_invoice = move.move_type == 'out_invoice'
            if is_invoice:
                label = move.name
                po = move.ref if move.ref and move.ref != move.invoice_origin else ''
                amount = currency.round(amount_by_move[move])
            elif move.move_type == 'out_refund':
                label = _("Credit %s", move.name)
                po = ''
                amount = currency.round(amount_by_move[move])
            elif move.journal_id.type in ('bank', 'cash'):
                label = _("Payment %s", move.name)
                po = ''
                amount = residual
            else:
                label = _("Entry %s", move.name)
                po = ''
                amount = residual
            rows.append({
                'date': move.invoice_date or move.date,
                'number': label,
                'po': po,
                'amount': amount,
                'due': residual,
            })
            # Aging by document date
            age = (date_to - (move.invoice_date or move.date)).days
            for key, _label, lo, hi in self.AGING_BUCKETS:
                if age >= lo and (hi is None or age <= hi):
                    aging[key] += residual
                    break
            # Early-payment deduction: open invoices whose discount deadline is still ahead
            move_term = move.invoice_payment_term_id
            if is_invoice and move_term.early_discount and residual > 0:
                deadline = move_term._get_last_discount_date(move.invoice_date or move.date)
                if deadline and deadline >= statement_date:
                    discount_total += currency.round(residual * move_term.discount_percentage / 100.0)
                    discount_dates.append(deadline)

        discount_total = currency.round(discount_total)
        return {
            'partner': partner,
            'customer_no': partner.ref or str(partner.id),
            'terms': term,
            'terms_name': term.name if term else '',
            'rows': rows,
            'previous_balance': currency.round(previous_balance),
            'payments': currency.round(payments),
            'credits': currency.round(credits),
            'purchases': currency.round(purchases),
            'service_charges': currency.round(service_charges),
            'new_balance': currency.round(new_balance),
            'aging': [(label, currency.round(aging[key])) for key, label, *_ in self.AGING_BUCKETS],
            'surcharge_percentage': term.late_surcharge_percentage if term and term.late_surcharge else 0.0,
            'discount_percentage': term.discount_percentage if term and term.early_discount else 0.0,
            'discount_total': discount_total,
            'discount_date': min(discount_dates) if discount_dates else False,
            'total_due': currency.round(new_balance - discount_total),
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        company = self.env.company
        statement_date = (
            fields.Date.to_date(data.get('statement_date'))
            or fields.Date.context_today(self).replace(day=1)
        )
        date_to = fields.Date.to_date(data.get('date_to')) or statement_date
        date_from = fields.Date.to_date(data.get('date_from')) or date_to.replace(day=1)
        include_zero = data.get('include_zero_balance', True)
        # When launched with data, the PDF route does not carry the ids in the URL.
        docids = docids or data.get('partner_ids') or self.env.context.get('active_ids') or []
        partners = self.env['res.partner'].browse(docids).commercial_partner_id
        if not partners:
            raise UserError(_("No customer selected."))
        statements = []
        for partner in partners:
            values = self._partner_values(partner, company, statement_date, date_from, date_to)
            if include_zero or not company.currency_id.is_zero(values['new_balance']) or values['rows']:
                statements.append(values)
        return {
            'doc_ids': docids,
            'doc_model': 'res.partner',
            'docs': partners,
            'company': company,
            'currency': company.currency_id,
            'statement_date': statement_date,
            'date_from': date_from,
            'date_to': date_to,
            'statements': statements,
        }
