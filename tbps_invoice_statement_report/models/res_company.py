from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    tbps_invoice_layout = fields.Boolean(
        string='Use Tri Borough Invoice Layout', default=True,
        help="Print customer invoices and credit notes with the Tri Borough layout "
             "(Bill To / Ship To, order details, item numbers, payments and balance).",
    )
    tbps_statement_note = fields.Text(
        string='Statement Note',
        default="Should you have any questions or concerns regarding discrepancies, please contact us right away.",
        help="Text printed under the Remit To block on customer statements.",
    )
