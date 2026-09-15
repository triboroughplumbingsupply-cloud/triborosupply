from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomerStatementWizard(models.TransientModel):
    _name = 'tbps.customer.statement.wizard'
    _description = 'Print Customer Statements'

    def _default_statement_date(self):
        return fields.Date.context_today(self).replace(day=1)

    partner_ids = fields.Many2many(
        comodel_name='res.partner', string='Customers',
        domain="[('is_company', '=', True)]",
        help="Leave empty to print a statement for every customer with a balance.")
    statement_date = fields.Date(
        string='Statement Date', required=True, default=_default_statement_date,
        help="Date printed on the statement. The statement covers activity up to the end of the previous "
             "month by default.")
    date_from = fields.Date(string='Period From', compute='_compute_period', store=True, readonly=False)
    date_to = fields.Date(string='Period To', compute='_compute_period', store=True, readonly=False)
    include_zero_balance = fields.Boolean(
        string='Include Zero Balances', default=False,
        help="Also print statements for customers whose new balance is zero.")

    @api.depends('statement_date')
    def _compute_period(self):
        for wizard in self:
            if wizard.statement_date:
                first_of_month = wizard.statement_date.replace(day=1)
                wizard.date_to = first_of_month - relativedelta(days=1)
                wizard.date_from = wizard.date_to.replace(day=1)

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for wizard in self:
            if not wizard.date_from or not wizard.date_to:
                raise UserError(_("The statement period is required."))
            if wizard.date_from > wizard.date_to:
                raise UserError(_("The statement period start must be before its end."))

    def _get_partners(self):
        self.ensure_one()
        if self.partner_ids:
            return self.partner_ids.commercial_partner_id
        lines = self.env['account.move.line'].search([
            ('company_id', '=', self.env.company.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('date', '<=', self.date_to),
            ('partner_id', '!=', False),
        ])
        return lines.partner_id.commercial_partner_id.sorted('name')

    def action_print(self):
        self.ensure_one()
        partners = self._get_partners()
        if not partners:
            raise UserError(_("No customers to print."))
        data = {
            'partner_ids': partners.ids,
            'statement_date': fields.Date.to_string(self.statement_date),
            'date_from': fields.Date.to_string(self.date_from),
            'date_to': fields.Date.to_string(self.date_to),
            'include_zero_balance': self.include_zero_balance,
        }
        return self.env.ref('tbps_invoice_statement_report.action_report_customer_statement').report_action(
            partners, data=data, config=False)
