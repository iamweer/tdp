from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTask(models.Model):
    _inherit = "project.task"

    planned_date_begin = fields.Datetime(
        string="Fecha inicial",
        tracking=True,
    )

    @api.constrains("planned_date_begin", "date_deadline")
    def _check_planned_dates(self):
        for task in self:
            if (
                task.planned_date_begin
                and task.date_deadline
                and task.planned_date_begin > task.date_deadline
            ):
                raise ValidationError(
                    _("La fecha inicial no puede ser posterior a la fecha límite.")
                )
