from odoo import SUPERUSER_ID, api
from odoo.addons.project_custom_extension.hooks import configure_project_security


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configure_project_security(env)
    env["project.project"]._ensure_warranty_automation_activation_date()
