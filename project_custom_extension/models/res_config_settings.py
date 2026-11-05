from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .project_project import (
    DASHBOARD_HEALTH_DEFAULTS,
    DASHBOARD_HEALTH_PARAMETERS,
    SCHEDULE_RISK_DEVIATION_DEFAULT,
    SCHEDULE_RISK_DEVIATION_PARAMETER,
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
    project_schedule_risk_deviation = fields.Integer(
        string="Desviación para En riesgo de atraso",
        config_parameter=SCHEDULE_RISK_DEVIATION_PARAMETER,
        default=SCHEDULE_RISK_DEVIATION_DEFAULT,
    )

    # Weekly time alerts: each switch turns its scheduled action on or off.
    project_time_alert_reminder = fields.Boolean(
        string="Recordatorio semanal de registro de horas",
        help="Viernes: correo a cada persona con los días de la semana sin horas.",
    )
    project_time_alert_summary = fields.Boolean(
        string="Resumen semanal de faltantes para gerentes y PM",
        help="Lunes: correo a gerentes y PM con quién no registró horas la "
        "semana anterior.",
    )

    TIME_ALERT_CRONS = {
        "project_time_alert_reminder":
            "project_custom_extension.ir_cron_remind_missing_hours",
        "project_time_alert_summary":
            "project_custom_extension.ir_cron_notify_missing_hours_summary",
    }

    @api.model
    def get_values(self):
        values = super().get_values()
        for field_name, xmlid in self.TIME_ALERT_CRONS.items():
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            values[field_name] = bool(cron and cron.sudo().active)
        return values

    def set_values(self):
        super().set_values()
        if not self.env.user.has_group("base.group_system"):
            return
        for field_name, xmlid in self.TIME_ALERT_CRONS.items():
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron and cron.sudo().active != self[field_name]:
                cron.sudo().active = self[field_name]

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

    @api.constrains("project_schedule_risk_deviation")
    def _check_project_schedule_risk_deviation(self):
        for settings in self:
            if not 0 <= settings.project_schedule_risk_deviation <= 100:
                raise ValidationError(
                    _("La desviación para En riesgo de atraso debe estar entre 0 y 100.")
                )
