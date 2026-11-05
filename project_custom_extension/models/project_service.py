from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PROJECT_TYPE_SELECTION = [
    ("project", "Proyecto"),
    ("staffing", "Staffing"),
    ("support", "Soporte"),
]


class ProjectProject(models.Model):
    _inherit = "project.project"

    project_type = fields.Selection(
        PROJECT_TYPE_SELECTION,
        string="Tipo de servicio",
        default="project",
        required=True,
        tracking=True,
        help="Staffing y Soporte son servicios continuos: se siguen con "
        "observaciones del servicio más que con tareas puntuales.",
    )
    service_observation_ids = fields.One2many(
        "project.service.observation",
        "project_id",
        string="Observaciones del servicio",
    )
    service_observation_count = fields.Integer(
        string="Observaciones",
        compute="_compute_service_observation_count",
    )

    @api.depends("service_observation_ids")
    def _compute_service_observation_count(self):
        counts = {
            project.id: count
            for project, count in self.env["project.service.observation"]._read_group(
                [("project_id", "in", self.ids)], ["project_id"], ["__count"]
            )
        }
        for project in self:
            project.service_observation_count = counts.get(project.id, 0)

    def action_open_service_observations(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project_custom_extension.project_service_observation_action"
        )
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id}
        return action


class ProjectServiceObservation(models.Model):
    """Histórico de observaciones de un servicio (tarea 2657).

    Los servicios de staffing o soporte no se gestionan con tareas puntuales:
    se registran observaciones fechadas (seguimiento, novedades, incidentes,
    reconocimientos) que forman el histórico del servicio.
    """

    _name = "project.service.observation"
    _description = "Observación del servicio"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Resumen", required=True, tracking=True)
    project_id = fields.Many2one(
        "project.project",
        string="Servicio / proyecto",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        related="project_id.partner_id",
        string="Cliente",
        store=True,
        index=True,
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    observation_type = fields.Selection(
        [
            ("follow_up", "Seguimiento"),
            ("novelty", "Novedad"),
            ("incident", "Incidente"),
            ("recognition", "Reconocimiento"),
        ],
        string="Tipo",
        required=True,
        default="follow_up",
        tracking=True,
    )
    resource_user_id = fields.Many2one(
        "res.users",
        string="Recurso",
        help="Persona asignada al servicio a la que se refiere la observación.",
        tracking=True,
    )
    author_id = fields.Many2one(
        "res.users",
        string="Registrado por",
        default=lambda self: self.env.user,
        readonly=True,
    )
    description = fields.Html(string="Observación")


class ProjectSystem(models.Model):
    """Sistema o producto que se implementa a los clientes (tarea 2658)."""

    _name = "project.system"
    _description = "Sistema"
    _order = "name"

    name = fields.Char(string="Sistema", required=True)
    description = fields.Text(string="Descripción")
    active = fields.Boolean(default=True)
    module_ids = fields.One2many("project.system.module", "system_id", string="Módulos")

    _sql_constraints = [
        ("name_unique", "unique(name)", "Ya existe un sistema con ese nombre."),
    ]


class ProjectSystemModule(models.Model):
    _name = "project.system.module"
    _description = "Módulo de sistema"
    _order = "system_id, sequence, name"

    name = fields.Char(string="Módulo", required=True)
    sequence = fields.Integer(default=10)
    system_id = fields.Many2one(
        "project.system", string="Sistema", required=True, ondelete="cascade", index=True
    )
    is_base = fields.Boolean(
        string="Módulo base",
        default=True,
        help="Módulo estándar del sistema (no una personalización).",
    )
    description = fields.Text(string="Descripción")
    active = fields.Boolean(default=True)


class ProjectClientSystem(models.Model):
    """Apertura de un sistema para un cliente: módulos activados y
    personalizaciones solicitadas, con su trazabilidad."""

    _name = "project.client.system"
    _description = "Sistema del cliente"
    _inherit = ["mail.thread"]
    _order = "partner_id, system_id"
    _rec_names_search = ["partner_id", "system_id"]

    partner_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        required=True,
        index=True,
        tracking=True,
        domain="[('is_company', '=', True)]",
    )
    system_id = fields.Many2one(
        "project.system", string="Sistema", required=True, index=True, tracking=True
    )
    date_opened = fields.Date(
        string="Fecha de apertura", default=fields.Date.context_today, tracking=True
    )
    project_id = fields.Many2one(
        "project.project",
        string="Proyecto de implementación",
        domain="[('partner_id', 'child_of', partner_id)]",
    )
    module_line_ids = fields.One2many(
        "project.client.system.module", "client_system_id", string="Módulos activados"
    )
    customization_ids = fields.One2many(
        "project.system.customization", "client_system_id", string="Personalizaciones"
    )
    active_module_count = fields.Integer(
        string="Módulos activos", compute="_compute_counts"
    )
    open_customization_count = fields.Integer(
        string="Personalizaciones abiertas", compute="_compute_counts"
    )
    notes = fields.Html(string="Notas")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "partner_system_unique",
            "unique(partner_id, system_id)",
            "El cliente ya tiene una apertura de ese sistema.",
        ),
    ]

    @api.depends("partner_id", "system_id")
    def _compute_display_name(self):
        for record in self:
            record.display_name = " · ".join(
                name for name in (record.partner_id.name, record.system_id.name) if name
            )

    @api.depends("module_line_ids.state", "customization_ids.state")
    def _compute_counts(self):
        for record in self:
            record.active_module_count = len(
                record.module_line_ids.filtered(lambda line: line.state == "active")
            )
            record.open_customization_count = len(
                record.customization_ids.filtered(
                    lambda customization: customization.state
                    not in ("delivered", "rejected")
                )
            )


class ProjectClientSystemModule(models.Model):
    _name = "project.client.system.module"
    _description = "Módulo activado para un cliente"
    _order = "client_system_id, activation_date, id"

    client_system_id = fields.Many2one(
        "project.client.system",
        string="Sistema del cliente",
        required=True,
        ondelete="cascade",
        index=True,
    )
    system_id = fields.Many2one(related="client_system_id.system_id", store=True)
    partner_id = fields.Many2one(
        related="client_system_id.partner_id", string="Cliente", store=True
    )
    module_id = fields.Many2one(
        "project.system.module",
        string="Módulo",
        required=True,
        domain="[('system_id', '=', system_id)]",
    )
    is_base = fields.Boolean(related="module_id.is_base")
    activation_date = fields.Date(
        string="Fecha de activación", default=fields.Date.context_today
    )
    state = fields.Selection(
        [("active", "Activo"), ("inactive", "Inactivo")],
        string="Estado",
        required=True,
        default="active",
    )
    notes = fields.Char(string="Notas")

    _sql_constraints = [
        (
            "client_module_unique",
            "unique(client_system_id, module_id)",
            "El módulo ya está registrado para este cliente.",
        ),
    ]

    @api.constrains("module_id", "client_system_id")
    def _check_module_system(self):
        for line in self:
            if line.module_id.system_id != line.client_system_id.system_id:
                raise ValidationError(_(
                    "El módulo %(module)s no pertenece al sistema %(system)s.",
                    module=line.module_id.name,
                    system=line.client_system_id.system_id.name,
                ))


class ProjectSystemCustomization(models.Model):
    _name = "project.system.customization"
    _description = "Personalización solicitada"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "request_date desc, id desc"

    name = fields.Char(string="Personalización", required=True, tracking=True)
    client_system_id = fields.Many2one(
        "project.client.system",
        string="Sistema del cliente",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        related="client_system_id.partner_id", string="Cliente", store=True, index=True
    )
    system_id = fields.Many2one(
        related="client_system_id.system_id", string="Sistema", store=True
    )
    module_id = fields.Many2one(
        "project.system.module",
        string="Módulo relacionado",
        domain="[('system_id', '=', system_id)]",
    )
    request_date = fields.Date(
        string="Fecha de solicitud", default=fields.Date.context_today, tracking=True
    )
    state = fields.Selection(
        [
            ("requested", "Solicitada"),
            ("analysis", "En análisis"),
            ("development", "En desarrollo"),
            ("delivered", "Entregada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado",
        required=True,
        default="requested",
        tracking=True,
        group_expand="_read_group_state",
    )
    user_id = fields.Many2one("res.users", string="Responsable", tracking=True)
    project_id = fields.Many2one(
        "project.project",
        string="Proyecto",
        domain="[('partner_id', 'child_of', partner_id)]",
    )
    task_id = fields.Many2one(
        "project.task",
        string="Tarea",
        domain="[('project_id', '=', project_id)]",
    )
    delivery_date = fields.Date(string="Fecha de entrega", tracking=True)
    description = fields.Html(string="Descripción")

    @api.model
    def _read_group_state(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    @api.onchange("task_id")
    def _onchange_task_id(self):
        if self.task_id and not self.project_id:
            self.project_id = self.task_id.project_id

    def write(self, vals):
        if vals.get("state") == "delivered" and "delivery_date" not in vals:
            undated = self.filtered(lambda customization: not customization.delivery_date)
            result = super().write(vals)
            if undated:
                undated.delivery_date = fields.Date.context_today(self)
            return result
        return super().write(vals)


class ResPartner(models.Model):
    _inherit = "res.partner"

    client_system_count = fields.Integer(
        string="Sistemas",
        compute="_compute_client_system_count",
    )

    def _compute_client_system_count(self):
        ClientSystem = self.env["project.client.system"]
        if not ClientSystem.has_access("read"):
            self.client_system_count = 0
            return
        counts = {
            partner.id: count
            for partner, count in ClientSystem._read_group(
                [("partner_id", "in", self.commercial_partner_id.ids)],
                ["partner_id"],
                ["__count"],
            )
        }
        for partner in self:
            partner.client_system_count = counts.get(partner.commercial_partner_id.id, 0)

    def action_open_client_systems(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project_custom_extension.project_client_system_action"
        )
        partner = self.commercial_partner_id
        action["domain"] = [("partner_id", "=", partner.id)]
        action["context"] = {"default_partner_id": partner.id}
        return action
