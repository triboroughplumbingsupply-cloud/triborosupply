from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    early_discount_surcharge_term_id = fields.Many2one(
        related='company_id.early_discount_surcharge_term_id', readonly=False)
    late_surcharge_product_id = fields.Many2one(
        related='company_id.late_surcharge_product_id', readonly=False)
    late_surcharge_method = fields.Selection(
        related='company_id.late_surcharge_method', readonly=False)
    late_surcharge_auto_post = fields.Boolean(
        related='company_id.late_surcharge_auto_post', readonly=False)
