from odoo import SUPERUSER_ID, api

from odoo.addons.project_custom_extension.hooks import configure_project_security


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Las reglas nativas de reportes son noupdate: se actualizan aquí para que
    # el responsable del proyecto también tenga acceso a ellos.
    configure_project_security(env)
