from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    is_late_surcharge = fields.Boolean(
        string='Late Surcharge Item', default=False, copy=False, index=True,
        help="Technical: this journal item was generated for a late payment surcharge "
             "(used by customer statements to report service charges separately).",
    )
