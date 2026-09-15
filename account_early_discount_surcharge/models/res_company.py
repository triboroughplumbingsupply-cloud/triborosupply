from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    early_discount_surcharge_term_id = fields.Many2one(
        comodel_name='account.payment.term',
        string='Discount / Surcharge Payment Terms',
        check_company=True,
        default=lambda self: self.env.ref(
            'account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge', raise_if_not_found=False),
        help="Payment terms assigned to a customer when the 'Early Discount / Late Surcharge' "
             "toggle is enabled on the customer form. The discount %, discount deadline, due date "
             "and surcharge % are all configured on these payment terms.",
    )
    late_surcharge_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Late Surcharge Product',
        domain="[('type', '=', 'service')]",
        default=lambda self: self.env.ref(
            'account_early_discount_surcharge.product_late_payment_surcharge', raise_if_not_found=False),
        help="Service product used on the surcharge invoices generated for overdue invoices.",
    )
    late_surcharge_method = fields.Selection(
        selection=[
            ('invoice_line', 'Add the surcharge to the overdue invoice'),
            ('separate_invoice', 'Issue a separate surcharge invoice'),
        ],
        string='Late Surcharge Method',
        default='invoice_line',
        required=True,
        help="Add the surcharge to the overdue invoice: the invoice total and amount due increase by the "
             "surcharge; the customer keeps a single invoice.\n"
             "Issue a separate surcharge invoice: the overdue invoice is untouched and a new invoice is "
             "created for the surcharge.",
    )
    late_surcharge_auto_post = fields.Boolean(
        string='Post Surcharge Invoices Automatically',
        default=True,
        help="If unchecked, surcharge invoices are created in draft for review.",
    )
