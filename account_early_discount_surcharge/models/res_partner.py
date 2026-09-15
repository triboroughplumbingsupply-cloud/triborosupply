from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    early_discount_surcharge_terms = fields.Boolean(
        string='Early Discount / Late Surcharge',
        compute='_compute_early_discount_surcharge_terms',
        inverse='_inverse_early_discount_surcharge_terms',
        help="Assign the company's discount / surcharge payment terms to this customer. "
             "The terms themselves (discount %, deadline, due date, surcharge %) are configured "
             "in Accounting Settings > Late payment surcharges.",
    )
    early_discount_surcharge_term_name = fields.Char(
        compute='_compute_early_discount_surcharge_terms',
        help="Technical: name of the payment terms applied by the toggle, shown on the form.",
    )

    def _get_early_discount_surcharge_term(self):
        return self.env.company.early_discount_surcharge_term_id

    @api.depends('property_payment_term_id')
    @api.depends_context('company')
    def _compute_early_discount_surcharge_terms(self):
        term = self._get_early_discount_surcharge_term()
        for partner in self:
            partner.early_discount_surcharge_terms = bool(term) and partner.property_payment_term_id == term
            partner.early_discount_surcharge_term_name = term.display_name or ''

    def _inverse_early_discount_surcharge_terms(self):
        term = self._get_early_discount_surcharge_term()
        for partner in self:
            if partner.early_discount_surcharge_terms:
                if not term:
                    raise UserError(_(
                        "No discount / surcharge payment terms are configured for %s. "
                        "Set them in Accounting Settings > Late payment surcharges first.",
                        self.env.company.display_name))
                partner.property_payment_term_id = term
            elif term and partner.property_payment_term_id == term:
                partner.property_payment_term_id = False
