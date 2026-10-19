from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectDeliverable(models.Model):
    """Delivery committed in the offer for a phase (top-level task).

    Deliverables are not subtasks: they measure the phase compliance shown
    in the project dashboard, not its execution progress.
    """

    _name = "project.deliverable"
    _description = "Entregable de fase"
    _order = "phase_id, sequence, id"

    name = fields.Char(string="Entregable", required=True)
    sequence = fields.Integer(default=10)
    phase_id = fields.Many2one(
        "project.task",
        string="Fase",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('parent_id', '=', False)]",
    )
    project_id = fields.Many2one(
        related="phase_id.project_id",
        string="Proyecto",
        store=True,
        index=True,
    )
    date_commitment = fields.Date(string="Fecha comprometida")
    state = fields.Selection(
        [("pending", "Pendiente"), ("delivered", "Entregado")],
        string="Estado",
        required=True,
        default="pending",
    )
    date_delivered = fields.Date(string="Fecha de entrega")
    user_id = fields.Many2one("res.users", string="Responsable")
    notes = fields.Text(string="Notas")

    @api.constrains("phase_id")
    def _check_phase_is_top_level(self):
        for deliverable in self:
            if deliverable.phase_id.parent_id:
                raise ValidationError(_(
                    "Los entregables solo se registran en fases (tareas de "
                    "primer nivel), no en subtareas."
                ))

    @api.onchange("state")
    def _onchange_state(self):
        if self.state == "delivered" and not self.date_delivered:
            self.date_delivered = fields.Date.context_today(self)
        elif self.state == "pending":
            self.date_delivered = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._fill_date_delivered(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._fill_date_delivered(vals)
        return super().write(vals)

    def _fill_date_delivered(self, vals):
        if vals.get("state") == "delivered" and not vals.get("date_delivered"):
            vals["date_delivered"] = fields.Date.context_today(self)
        elif vals.get("state") == "pending":
            vals["date_delivered"] = False


class ProjectTask(models.Model):
    _inherit = "project.task"

    deliverable_ids = fields.One2many(
        "project.deliverable",
        "phase_id",
        string="Entregables",
    )
