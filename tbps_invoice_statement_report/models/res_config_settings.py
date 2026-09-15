from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tbps_invoice_layout = fields.Boolean(related='company_id.tbps_invoice_layout', readonly=False)
    tbps_statement_note = fields.Text(related='company_id.tbps_statement_note', readonly=False)
