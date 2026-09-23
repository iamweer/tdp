from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .project_project import (
    DASHBOARD_HEALTH_DEFAULTS,
    DASHBOARD_HEALTH_PARAMETERS,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    project_dashboard_progress_weight = fields.Integer(
        string="Peso del avance",
        config_parameter=DASHBOARD_HEALTH_PARAMETERS["progress_weight"],
        default=DASHBOARD_HEALTH_DEFAULTS["progress_weight"],
    )
    project_dashboard_status_weight = fields.Integer(
        string="Peso del estado",
        config_parameter=DASHBOARD_HEALTH_PARAMETERS["status_weight"],
        default=DASHBOARD_HEALTH_DEFAULTS["status_weight"],
    )
    project_dashboard_operations_weight = fields.Integer(
        string="Peso de la operación",
        config_parameter=DASHBOARD_HEALTH_PARAMETERS["operations_weight"],
        default=DASHBOARD_HEALTH_DEFAULTS["operations_weight"],
    )
    project_dashboard_healthy_threshold = fields.Integer(
        string="Umbral saludable",
        config_parameter=DASHBOARD_HEALTH_PARAMETERS["healthy_threshold"],
        default=DASHBOARD_HEALTH_DEFAULTS["healthy_threshold"],
    )
    project_dashboard_attention_threshold = fields.Integer(
        string="Umbral de atención",
        config_parameter=DASHBOARD_HEALTH_PARAMETERS["attention_threshold"],
        default=DASHBOARD_HEALTH_DEFAULTS["attention_threshold"],
    )

    @api.constrains(
        "project_dashboard_progress_weight",
        "project_dashboard_status_weight",
        "project_dashboard_operations_weight",
        "project_dashboard_healthy_threshold",
        "project_dashboard_attention_threshold",
    )
    def _check_project_dashboard_health_configuration(self):
        for settings in self:
            weights = (
                settings.project_dashboard_progress_weight,
                settings.project_dashboard_status_weight,
                settings.project_dashboard_operations_weight,
            )
            if any(weight < 0 or weight > 100 for weight in weights):
                raise ValidationError(
                    _("Los pesos de salud deben estar entre 0 y 100.")
                )
            if sum(weights) != 100:
                raise ValidationError(
                    _("Los pesos de salud deben sumar exactamente 100.")
                )

            attention = settings.project_dashboard_attention_threshold
            healthy = settings.project_dashboard_healthy_threshold
            if not 0 <= attention < healthy <= 100:
                raise ValidationError(_(
                    "Los umbrales deben estar entre 0 y 100, y el umbral "
                    "saludable debe ser mayor que el umbral de atención."
                ))
