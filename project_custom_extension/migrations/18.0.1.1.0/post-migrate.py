from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.project_custom_extension.hooks import configure_project_security

    configure_project_security(env)
