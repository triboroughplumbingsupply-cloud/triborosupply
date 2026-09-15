from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.company_id.tbps_invoice_layout and self.move_type in ('out_invoice', 'out_refund'):
            return 'tbps_invoice_statement_report.report_invoice_document_tbps'
        return super()._get_name_invoice_report()

    # -------------------------------------------------------------------------
    # Data used by the Tri Borough invoice layout
    # -------------------------------------------------------------------------
    def _tbps_is_shipping_line(self, line):
        return bool(line.sale_line_ids and any(line.sale_line_ids.mapped('is_delivery')))

    def _tbps_invoice_data(self):
        """Everything the invoice template needs, computed once per invoice."""
        self.ensure_one()
        currency = self.currency_id
        product_lines = self.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
        shipping_lines = product_lines.filtered(self._tbps_is_shipping_line)
        item_lines = product_lines - shipping_lines

        orders = self.invoice_line_ids.sale_line_ids.order_id.sorted('date_order')
        pickings = orders.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done').sorted('date_done')
        warehouse = orders.warehouse_id[:1]
        carrier = orders.carrier_id[:1]

        discounts = sum(
            currency.round(line.price_unit * line.quantity * line.discount / 100.0)
            for line in product_lines if line.discount
        )
        tax_groups = []
        for subtotal in (self.tax_totals or {}).get('subtotals', []):
            for group in subtotal.get('tax_groups', []):
                tax_groups.append({'name': group['group_name'], 'amount': group['tax_amount_currency']})

        # One row per payment: an invoice with several receivable lines (e.g. after a late
        # surcharge) reconciles the same payment against each line, which the widget lists
        # separately.
        payments, by_payment = [], {}
        widget = self.sudo().invoice_payments_widget
        for vals in (widget or {}).get('content', []):
            key = vals.get('account_payment_id') or vals.get('move_id') or vals.get('partial_id')
            if key in by_payment:
                by_payment[key]['amount'] += vals.get('amount', 0.0)
                continue
            row = {
                'name': vals.get('journal_name') or vals.get('name') or '',
                'date': vals.get('date'),
                'amount': vals.get('amount', 0.0),
            }
            by_payment[key] = row
            payments.append(row)
        total_payments = currency.round(self.amount_total - self.amount_residual)
        # Payments registered without a journal entry (journal has no outstanding account) stay
        # "in process" until the bank statement is matched. They are still money received.
        for payment in self.sudo().matched_payment_ids.filtered(lambda p: p.state == 'in_process' and not p.move_id):
            amount = payment.currency_id._convert(payment.amount, currency, self.company_id, payment.date)
            payments.append({
                'name': _("%(journal)s (pending bank reconciliation)", journal=payment.journal_id.name),
                'date': payment.date,
                'amount': amount,
            })
            total_payments += amount
        total_payments = currency.round(total_payments)

        partner = self.partner_id
        commercial = partner.commercial_partner_id
        return {
            'order_names': ', '.join(orders.mapped('name')),
            'order_date': orders[:1].date_order.date() if orders else False,
            'source': warehouse.name or self.company_id.name,
            'customer_no': commercial.ref or str(commercial.id),
            'sales_rep': self.invoice_user_id.name or '',
            'ship_date': pickings[-1:].date_done.date() if pickings else False,
            'ship_method': carrier.name or '',
            'ship_from': warehouse.name or self.company_id.name,
            'item_lines': item_lines,
            'discounts': discounts,
            'items_subtotal': sum(item_lines.mapped('price_subtotal')),
            'shipping': sum(shipping_lines.mapped('price_subtotal')),
            'tax_groups': tax_groups,
            'payments': payments,
            'total_payments': total_payments,
            'balance': currency.round(self.amount_total - total_payments),
            'bill_to': partner,
            'ship_to': self.partner_shipping_id or partner,
        }
