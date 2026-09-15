{
    'name': 'Early Payment Discount & Late Surcharge',
    'summary': '2% discount if paid by the 10th of the following month, net by end of month, 1.5% surcharge after',
    'description': """
Payment terms extension for customer statements / invoices:

* Early payment discount deadline can be set to a fixed day of the following month
  (e.g. the 10th) instead of a number of days after the invoice date.
* Full amount is due at the end of the following month (standard Odoo due terms).
* Balances still open after the due date receive a late payment surcharge
  (e.g. 1.5%), applied automatically by a daily cron either on the overdue invoice
  itself (default) or as a separate surcharge invoice.
* A toggle on the customer enables these terms in one click.
""",
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Tri Borough Plumbing Supply',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'data/product_data.xml',
        'data/payment_term_data.xml',
        'data/ir_cron_data.xml',
        'views/account_payment_term_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'report/report_invoice.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'account_early_discount_surcharge/static/src/scss/payment_term.scss',
        ],
    },
    'post_init_hook': '_set_company_defaults',
    'installable': True,
    'application': False,
}
