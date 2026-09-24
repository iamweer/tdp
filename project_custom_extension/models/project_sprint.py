from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectSprint(models.Model):
    _name = "project.sprint"
    _description = "Sprint de proyecto"
    _order = "project_id, sequence, name, id"

    name = fields.Char(string="Nombre", required=True)
    project_id = fields.Many2one(
        "project.project",
        string="Proyecto",
        required=True,
        index=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Orden", default=10, index=True)
    task_ids = fields.One2many("project.task", "sprint_id", string="Tareas")
    task_count = fields.Integer(
        string="Cantidad de actividades",
        compute="_compute_task_count",
    )

    @api.depends("task_ids")
    def _compute_task_count(self):
        for sprint in self:
            sprint.task_count = len(sprint.task_ids)

    @api.constrains("project_id")
    def _check_project_access(self):
        for sprint in self:
            sprint.project_id.check_access("read")

    def unlink(self):
        if self.with_context(active_test=False).mapped("task_ids"):
            raise UserError(_(
                "No se puede eliminar un Sprint que tiene actividades asignadas."
            ))
        return super().unlink()


class ProjectTaskSprint(models.Model):
    _inherit = "project.task"

    sprint_id = fields.Many2one(
        "project.sprint",
        string="Sprint",
        index=True,
        ondelete="set null",
        domain="[('project_id', '=', project_id)]",
        tracking=True,
    )
    sprint_sequence_order = fields.Integer(
        compute="_compute_sprint_sequence_order",
        store=True,
        index=True,
    )

    @api.depends("sprint_id", "sprint_id.sequence")
    def _compute_sprint_sequence_order(self):
        for task in self:
            task.sprint_sequence_order = (
                task.sprint_id.sequence if task.sprint_id else 2147483647
            )

    @api.constrains("project_id", "sprint_id")
    def _check_sprint_project(self):
        for task in self:
            if task.sprint_id and task.sprint_id.project_id != task.project_id:
                raise ValidationError(_(
                    "El Sprint debe pertenecer al mismo proyecto de la actividad."
                ))
