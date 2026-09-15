from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    discount_deadline_type = fields.Selection(
        selection=[
            ('days', 'within'),
            ('day_of_next_month', 'on or before day'),
        ],
        string='Discount Deadline',
        default='days',
        required=True,
        help="How the early payment discount deadline is computed.\n"
             "* Days after invoice date: standard Odoo behaviour (Discount Days).\n"
             "* Day of the following month: the discount applies if paid on or before "
             "the given day of the month following the invoice date (e.g. the 10th).",
    )
    discount_day_of_next_month = fields.Integer(
        string='Discount Day (next month)',
        default=10,
        help="Day of the month following the invoice date until which the early payment "
             "discount applies (inclusive).",
    )
    late_surcharge = fields.Boolean(
        string='Late Payment Surcharge',
        help="Apply a surcharge on the balance still unpaid after the due date.",
    )
    late_surcharge_percentage = fields.Float(
        string='Surcharge %',
        default=1.5,
        help="Percentage of the unpaid balance charged when the invoice is not paid by its due date.",
    )

    @api.constrains('early_discount', 'discount_deadline_type', 'discount_day_of_next_month')
    def _check_discount_day_of_next_month(self):
        for term in self:
            if term.early_discount and term.discount_deadline_type == 'day_of_next_month' \
                    and not 1 <= term.discount_day_of_next_month <= 28:
                raise ValidationError(_("The discount day of the following month must be between 1 and 28."))

    @api.constrains('late_surcharge', 'late_surcharge_percentage')
    def _check_late_surcharge(self):
        for term in self:
            if term.late_surcharge and term.late_surcharge_percentage <= 0.0:
                raise ValidationError(_("The late payment surcharge must be strictly positive."))

    # -------------------------------------------------------------------------
    # Discount deadline
    # -------------------------------------------------------------------------
    def _get_last_discount_date(self, date_ref):
        self.ensure_one()
        if self.early_discount and self.discount_deadline_type == 'day_of_next_month' and date_ref:
            return date_ref + relativedelta(months=1, day=self.discount_day_of_next_month)
        return super()._get_last_discount_date(date_ref)

    def _compute_terms(self, date_ref, currency, company, tax_amount, tax_amount_currency, sign,
                       untaxed_amount, untaxed_amount_currency, cash_rounding=None):
        pay_term = super()._compute_terms(
            date_ref, currency, company, tax_amount, tax_amount_currency, sign,
            untaxed_amount, untaxed_amount_currency, cash_rounding=cash_rounding,
        )
        if self.early_discount and self.discount_deadline_type == 'day_of_next_month':
            pay_term['discount_date'] = self._get_last_discount_date(date_ref)
        return pay_term

    @api.depends('discount_deadline_type', 'discount_day_of_next_month')
    def _compute_example_preview(self):
        super()._compute_example_preview()

    # -------------------------------------------------------------------------
    # Helpers used by invoices / reports
    # -------------------------------------------------------------------------
    def _get_late_surcharge_amount(self, amount, currency):
        self.ensure_one()
        if not self.late_surcharge:
            return 0.0
        return currency.round(amount * self.late_surcharge_percentage / 100.0)
