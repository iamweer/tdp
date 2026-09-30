from odoo import SUPERUSER_ID, api
from odoo.addons.project_custom_extension.hooks import mark_resolved_stage_tasks_done


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    mark_resolved_stage_tasks_done(env)
