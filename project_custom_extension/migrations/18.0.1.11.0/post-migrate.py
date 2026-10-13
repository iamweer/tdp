from odoo import SUPERUSER_ID, api
from odoo.addons.project_custom_extension.hooks import (
    assign_unified_stages,
    mark_resolved_stage_tasks_done,
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Etapas sinónimas de "Resuelto" (Completado, Terminado...).
    assign_unified_stages(env)
    mark_resolved_stage_tasks_done(env)
