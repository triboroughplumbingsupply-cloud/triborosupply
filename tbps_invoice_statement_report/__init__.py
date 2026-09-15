from . import models, report, wizard

RETURN_POLICY = """<p>We accept general returns up to 30 days after receipt. Buyer may return any Products which
Seller stocks and which are not special-order items if: (i) the Products are in new condition, suitable for resale
in undamaged original packaging and with all original parts; and (ii) the Products have not been used, installed,
modified, rebuilt, reconditioned, repaired, altered, or damaged.</p>
<p>However, the following items may not be returned:</p>
<ul>
<li>Water heater(s), water heater parts and accessories will not be accepted if opened</li>
<li>Boiler(s), boiler parts and accessories will not be accepted if opened</li>
<li>Tools</li>
<li>Electrical items</li>
<li>Toilet seats</li>
<li>Special order items (case by case basis, some may be returned with a 25% restocking fee)</li>
<li>Clearance/liquidation/closeout item</li>
</ul>
<p>All non-defective returns are subject to inspection, and items deemed not new in the box may be denied or
issued a reduced credit.</p>"""


def _post_init_hook(env):
    """Seed the default invoice terms (return policy) on companies that have none yet.
    The text stays editable in Accounting Settings > Default Terms & Conditions."""
    env['ir.config_parameter'].sudo().set_param('account.use_invoice_terms', True)
    for company in env['res.company'].sudo().search([]):
        if not company.invoice_terms or not company.invoice_terms.strip():
            company.write({'terms_type': 'plain', 'invoice_terms': RETURN_POLICY})
