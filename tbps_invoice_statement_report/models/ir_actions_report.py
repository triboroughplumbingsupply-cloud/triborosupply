from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    TBPS_INVOICE_REPORTS = (
        'account.report_invoice_with_payments',
        'account.report_invoice',
    )

    def get_paperformat(self):
        if self.report_name in self.TBPS_INVOICE_REPORTS and self.env.company.tbps_invoice_layout:
            paperformat = self.env.ref('tbps_invoice_statement_report.paperformat_tbps', raise_if_not_found=False)
            if paperformat:
                return paperformat
        return super().get_paperformat()
