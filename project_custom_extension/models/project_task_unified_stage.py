from odoo import api, fields, models

from .project_task import is_resolved_stage_name, normalize_stage_name

# Nombre normalizado de la etapa de proyecto -> etapa unificada.
UNIFIED_STAGE_BY_NAME = {
    "nuevo": "unified_stage_new",
    "nueva": "unified_stage_new",
    "nuevos": "unified_stage_new",
    "nuevas": "unified_stage_new",
    "en curso": "unified_stage_in_progress",
    "validacion interna": "unified_stage_internal_validation",
    "validacion cliente": "unified_stage_client_validation",
}
RESOLVED_UNIFIED_STAGE = "unified_stage_resolved"


class ProjectTaskUnifiedStage(models.Model):
    _name = "project.task.unified.stage"
    _description = "Etapa unificada de tareas"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(string="Orden", default=10)
    fold = fields.Boolean(string="Plegada en el kanban")
    active = fields.Boolean(string="Activa", default=True)
    stage_ids = fields.One2many(
        "project.task.type",
        "unified_stage_id",
        string="Etapas de proyecto",
    )


class ProjectTaskType(models.Model):
    _inherit = "project.task.type"

    unified_stage_id = fields.Many2one(
        "project.task.unified.stage",
        string="Etapa unificada",
        compute="_compute_unified_stage_id",
        store=True,
        readonly=False,
        index=True,
        ondelete="set null",
        help="Columna de \"Mis tareas\" en la que se muestran las tareas de "
        "esta etapa. Se asigna automáticamente según el nombre.",
    )

    @api.depends("name", "user_id")
    def _compute_unified_stage_id(self):
        for stage in self:
            stage.unified_stage_id = stage._get_default_unified_stage()

    def _get_default_unified_stage(self):
        """Return the unified stage matching the stage name, if any."""
        self.ensure_one()
        Unified = self.env["project.task.unified.stage"]
        if self.user_id or not self.name:
            return Unified
        xmlid = UNIFIED_STAGE_BY_NAME.get(normalize_stage_name(self.name))
        if not xmlid and is_resolved_stage_name(self.name):
            xmlid = RESOLVED_UNIFIED_STAGE
        if not xmlid:
            return Unified
        # During install the catalog is not loaded yet: the hook recomputes.
        return self.env.ref(
            f"project_custom_extension.{xmlid}",
            raise_if_not_found=False,
        ) or Unified
