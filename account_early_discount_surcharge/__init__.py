from . import models


def _set_company_defaults(env):
    """Fill the company-level settings for companies that existed before the data files were loaded."""
    term = env.ref('account_early_discount_surcharge.payment_term_2_10th_net_eom_surcharge', raise_if_not_found=False)
    product = env.ref('account_early_discount_surcharge.product_late_payment_surcharge', raise_if_not_found=False)
    for company in env['res.company'].sudo().search([]):
        vals = {}
        term_ok = term and (not term.company_id or term.company_id == company)
        if term_ok and not company.early_discount_surcharge_term_id:
            vals['early_discount_surcharge_term_id'] = term.id
        if product and not company.late_surcharge_product_id:
            vals['late_surcharge_product_id'] = product.id
        if vals:
            company.write(vals)
