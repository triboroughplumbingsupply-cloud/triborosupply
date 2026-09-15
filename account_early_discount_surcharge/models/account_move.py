import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    late_surcharge_applicable = fields.Boolean(
        compute='_compute_late_surcharge_applicable', store=True,
        help="Technical: the payment terms of this invoice carry a late payment surcharge.",
    )
    late_surcharge_percentage = fields.Float(
        related='invoice_payment_term_id.late_surcharge_percentage', string='Late Surcharge %')
    early_discount_deadline = fields.Date(
        compute='_compute_early_discount_info', string='Discount Deadline')
    early_discount_amount_due = fields.Monetary(
        compute='_compute_early_discount_info', string='Amount Due with Discount',
        currency_field='currency_id')
    late_surcharge_amount = fields.Monetary(
        compute='_compute_late_surcharge_amount', string='Late Surcharge Amount',
        currency_field='currency_id',
        help="Surcharge that would be charged on the current unpaid balance.")
    late_surcharge_date = fields.Date(
        string='Late Surcharge Applied On', readonly=True, copy=False,
        help="Date on which the late payment surcharge was applied to this invoice.")
    late_surcharge_applied_amount = fields.Monetary(
        string='Late Surcharge Applied', readonly=True, copy=False, currency_field='currency_id')
    late_surcharge_line_id = fields.Many2one(
        comodel_name='account.move.line', string='Late Surcharge Line',
        readonly=True, copy=False, index='btree_not_null',
        help="Invoice line added to this invoice for the late payment surcharge.")
    late_surcharge_move_id = fields.Many2one(
        comodel_name='account.move', string='Late Surcharge Invoice',
        readonly=True, copy=False, index='btree_not_null')
    late_surcharge_origin_move_id = fields.Many2one(
        comodel_name='account.move', string='Surcharge for Invoice',
        readonly=True, copy=False, index='btree_not_null')
    late_surcharge_due = fields.Boolean(
        compute='_compute_late_surcharge_due', string='Late Surcharge Due',
        help="Invoice is overdue and eligible for a late payment surcharge that was not applied yet.")

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('invoice_payment_term_id.late_surcharge', 'move_type')
    def _compute_late_surcharge_applicable(self):
        for move in self:
            move.late_surcharge_applicable = (
                move.move_type == 'out_invoice'
                and move.invoice_payment_term_id.late_surcharge
            )

    @api.depends('invoice_payment_term_id', 'invoice_date', 'amount_total', 'amount_tax', 'currency_id')
    def _compute_early_discount_info(self):
        for move in self:
            term = move.invoice_payment_term_id
            if term.early_discount and move.invoice_date:
                move.early_discount_deadline = term._get_last_discount_date(move.invoice_date)
                move.early_discount_amount_due = term._get_amount_due_after_discount(
                    move.amount_total, move.amount_tax)
            else:
                move.early_discount_deadline = False
                move.early_discount_amount_due = 0.0

    @api.depends('invoice_payment_term_id', 'amount_residual', 'currency_id')
    def _compute_late_surcharge_amount(self):
        for move in self:
            term = move.invoice_payment_term_id
            if term.late_surcharge and move.currency_id:
                move.late_surcharge_amount = term._get_late_surcharge_amount(
                    move.amount_residual, move.currency_id)
            else:
                move.late_surcharge_amount = 0.0

    @api.depends('late_surcharge_applicable', 'state', 'payment_state', 'invoice_date_due',
                 'late_surcharge_date', 'late_surcharge_move_id', 'amount_residual')
    def _compute_late_surcharge_due(self):
        today = fields.Date.context_today(self)
        for move in self:
            move.late_surcharge_due = move._is_late_surcharge_due(today)

    # -------------------------------------------------------------------------
    # Eligibility
    # -------------------------------------------------------------------------
    def _is_late_surcharge_due(self, today):
        self.ensure_one()
        return (
            self.late_surcharge_applicable
            and self.state == 'posted'
            and self.payment_state in ('not_paid', 'partial')
            and bool(self.invoice_date_due) and self.invoice_date_due < today
            and not self.late_surcharge_date
            and not self.late_surcharge_move_id
            and not self.late_surcharge_origin_move_id
            and self.currency_id.compare_amounts(self.amount_residual, 0.0) > 0
        )

    def _get_late_surcharge_domain(self, today):
        return [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('late_surcharge_applicable', '=', True),
            ('invoice_date_due', '<', today),
            ('late_surcharge_date', '=', False),
            ('late_surcharge_move_id', '=', False),
            ('late_surcharge_origin_move_id', '=', False),
        ]

    def _get_late_surcharge_product(self):
        self.ensure_one()
        product = self.company_id.late_surcharge_product_id
        if not product:
            raise UserError(_("No late surcharge product is configured for company %s. "
                              "Set it in Accounting Settings.", self.company_id.display_name))
        return product

    def _get_late_surcharge_line_name(self):
        self.ensure_one()
        return _(
            "%(percent)s%% late payment surcharge on %(invoice)s (due %(due)s, unpaid balance %(balance)s)",
            percent=('%g' % self.invoice_payment_term_id.late_surcharge_percentage),
            invoice=self.name,
            due=fields.Date.to_string(self.invoice_date_due),
            balance=self.currency_id.format(self.amount_residual),
        )

    # -------------------------------------------------------------------------
    # Method 1: add the surcharge to the overdue invoice itself
    # -------------------------------------------------------------------------
    def _apply_late_surcharge_on_invoice(self, today):
        """Add a surcharge revenue line and a matching receivable line to the posted invoice.

        The existing receivable line is left untouched (it may already be partially reconciled),
        so a second payment-term line carries the surcharge. Odoo's automatic line
        synchronisation is disabled for this write; the two lines are balanced explicitly.
        The surcharge is not taxed.
        """
        self.ensure_one()
        amount = self.late_surcharge_amount
        product = self._get_late_surcharge_product()
        company = self.company_id
        company_currency = company.currency_id
        income_account = (
            product.with_company(company)._get_product_accounts()['income']
            or self.journal_id.default_account_id
        )
        if not income_account:
            raise UserError(_("No income account found for the late surcharge product %s.", product.display_name))
        existing_term_line = self.line_ids.filtered(lambda line: line.display_type == 'payment_term')[:1]
        receivable_account = existing_term_line.account_id or self.partner_id.property_account_receivable_id
        balance = self.currency_id._convert(amount, company_currency, company, today)
        # Editing a posted move in a locked period is not allowed.
        self._check_fiscal_lock_dates()
        line_name = self._get_late_surcharge_line_name()
        self.with_context(skip_readonly_check=True, skip_invoice_sync=True).write({'line_ids': [
            fields.Command.create({
                'display_type': 'product',
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'name': line_name,
                'quantity': 1.0,
                'price_unit': amount,
                'tax_ids': [fields.Command.clear()],
                'account_id': income_account.id,
                'amount_currency': -amount,
                'balance': -balance,
                'is_late_surcharge': True,
            }),
            fields.Command.create({
                'display_type': 'payment_term',
                'name': _("Late payment surcharge"),
                'account_id': receivable_account.id,
                'amount_currency': amount,
                'balance': balance,
                # The balance is already overdue, so the surcharge is due at once: give it the
                # invoice's due date so the payment wizard proposes it with the overdue amount.
                'date_maturity': self.invoice_date_due or today,
                'is_late_surcharge': True,
            }),
        ]})
        surcharge_line = self.line_ids.filtered(
            lambda line: line.display_type == 'product' and line.product_id == product and line.name == line_name)[-1:]
        self.write({
            'late_surcharge_date': today,
            'late_surcharge_applied_amount': amount,
            'late_surcharge_line_id': surcharge_line.id,
        })
        self.message_post(body=_(
            "Late payment surcharge of %(amount)s added to the invoice. New amount due: %(due)s.",
            amount=self.currency_id.format(amount),
            due=self.currency_id.format(self.amount_residual),
        ))
        return self

    # -------------------------------------------------------------------------
    # Method 2: separate surcharge invoice
    # -------------------------------------------------------------------------
    def _prepare_late_surcharge_move_vals(self, today):
        self.ensure_one()
        company = self.company_id
        product = self._get_late_surcharge_product()
        return {
            'move_type': 'out_invoice',
            'company_id': company.id,
            'journal_id': self.journal_id.id,
            'partner_id': self.partner_id.id,
            'partner_shipping_id': self.partner_shipping_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': today,
            'invoice_date_due': today,
            'invoice_payment_term_id': False,
            'invoice_origin': self.name,
            'late_surcharge_origin_move_id': self.id,
            'invoice_line_ids': [fields.Command.create({
                'product_id': product.id,
                'is_late_surcharge': True,
                'name': self._get_late_surcharge_line_name(),
                'quantity': 1.0,
                'price_unit': self.late_surcharge_amount,
                'tax_ids': [fields.Command.set(product.taxes_id.filtered(
                    lambda t: t.company_id == company).ids)],
            })],
        }

    def _apply_late_surcharge_separate_invoice(self, today):
        self.ensure_one()
        amount = self.late_surcharge_amount
        surcharge = self.env['account.move'].create(self._prepare_late_surcharge_move_vals(today))
        surcharge.line_ids.write({'is_late_surcharge': True})
        if self.company_id.late_surcharge_auto_post:
            surcharge.action_post()
        self.write({
            'late_surcharge_date': today,
            'late_surcharge_applied_amount': amount,
            'late_surcharge_move_id': surcharge.id,
        })
        self.message_post(body=_(
            "Late payment surcharge of %(amount)s applied: %(link)s",
            amount=surcharge.currency_id.format(surcharge.amount_total),
            link=surcharge._get_html_link(),
        ))
        return surcharge

    # -------------------------------------------------------------------------
    # Entry points
    # -------------------------------------------------------------------------
    def action_apply_late_surcharge(self):
        """Apply the late payment surcharge to each overdue invoice in self, using the company method."""
        today = fields.Date.context_today(self)
        results = self.env['account.move']
        for move in self:
            if not move._is_late_surcharge_due(today):
                continue
            if move.currency_id.is_zero(move.late_surcharge_amount):
                continue
            if move.company_id.late_surcharge_method == 'separate_invoice':
                results |= move._apply_late_surcharge_separate_invoice(today)
            else:
                results |= move._apply_late_surcharge_on_invoice(today)
        return results

    def action_open_late_surcharge_move(self):
        self.ensure_one()
        target = self.late_surcharge_move_id or self.late_surcharge_origin_move_id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': target.id,
            'view_mode': 'form',
        }

    @api.model
    def _cron_apply_late_surcharges(self):
        today = fields.Date.context_today(self)
        moves = self.search(self._get_late_surcharge_domain(today))
        _logger.info("Late surcharge cron: %s overdue invoice(s) to process", len(moves))
        for move in moves:
            try:
                with self.env.cr.savepoint():
                    move.action_apply_late_surcharge()
            except Exception:  # noqa: BLE001 - keep the cron running for the other invoices
                _logger.exception("Failed to apply late surcharge on %s", move.name)
