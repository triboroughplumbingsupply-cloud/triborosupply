from odoo import _, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_print_customer_statement(self):
        """Open the statement wizard pre-filled with these customers."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Statement'),
            'res_model': 'tbps.customer.statement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_ids': [(6, 0, self.commercial_partner_id.ids)]},
        }
