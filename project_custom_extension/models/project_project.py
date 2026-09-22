from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = "project.project"

    warranty_start_date = fields.Date(
        string="Inicio garantía",
        tracking=True,
    )
    warranty_end_date = fields.Date(
        string="Fin garantía",
        tracking=True,
    )
    warranty_period_display = fields.Char(
        string="Periodo de garantía",
        compute="_compute_warranty_period_display",
    )

    @api.depends("warranty_start_date", "warranty_end_date")
    def _compute_warranty_period_display(self):
        for project in self:
            start_date = project.warranty_start_date
            end_date = project.warranty_end_date
            if start_date and end_date:
                project.warranty_period_display = _(
                    "Garantía: %(start)s > %(end)s",
                    start=start_date.strftime("%d-%m-%Y"),
                    end=end_date.strftime("%d-%m-%Y"),
                )
            elif start_date:
                project.warranty_period_display = _(
                    "Garantía: %(start)s >",
                    start=start_date.strftime("%d-%m-%Y"),
                )
            elif end_date:
                project.warranty_period_display = _(
                    "Garantía: > %(end)s",
                    end=end_date.strftime("%d-%m-%Y"),
                )
            else:
                project.warranty_period_display = False

    @api.constrains("warranty_start_date", "warranty_end_date")
    def _check_warranty_dates(self):
        for project in self:
            if (
                project.warranty_start_date
                and project.warranty_end_date
                and project.warranty_start_date > project.warranty_end_date
            ):
                raise ValidationError(
                    _("El inicio de la garantía no puede ser posterior a su fin.")
                )
