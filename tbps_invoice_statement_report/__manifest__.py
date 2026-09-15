{
    'name': 'Tri Borough Invoice & Customer Statement Layouts',
    'summary': 'Invoice PDF and monthly Customer Statement matching the Tri Borough reference documents',
    'description': """
* Customer invoice PDF laid out like the reference invoice: Bill To / Ship To, order and shipping
  details, item numbers, payments, discounts, tax, shipping, total payments and balance, terms and
  a barcode of the invoice number.
* Customer Statement report (PDF): open invoices with amount due, previous balance / payments /
  credits / net purchases / service charges / new balance, aging buckets, early-payment deduction
  and total amount due. Printed from a wizard for one or many customers.
""",
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Tri Borough Plumbing Supply',
    'license': 'LGPL-3',
    'depends': ['account', 'sale_stock', 'delivery', 'account_early_discount_surcharge'],
    'data': [
        'security/ir.model.access.csv',
        'report/report_paperformat.xml',
        'report/report_invoice_templates.xml',
        'report/report_customer_statement_templates.xml',
        'report/report_actions.xml',
        'wizard/customer_statement_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
}
