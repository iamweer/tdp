from odoo import SUPERUSER_ID, api
from odoo.addons.project_custom_extension.hooks import assign_unified_stages


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    assign_unified_stages(env)
