import re
import unicodedata

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_repr

RESOLVED_STAGE_NAME_PATTERN = re.compile(r"^resuelt[oa]s?$")


def normalize_stage_name(name):
    """Normaliza un nombre de etapa para compararlo.

    Ignora mayúsculas, tildes, espacios repetidos y signos de puntuación en
    los extremos: "  Validación Cliente." -> "validacion cliente".
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    normalized = re.sub(r"\s+", " ", normalized.casefold())
    return re.sub(r"^\W+|\W+$", "", normalized)


def is_resolved_stage_name(name):
    """Indica si el nombre de etapa es una variante de "Resuelto".

    Acepta género y número (Resuelto, RESUELTA, resueltos...).
    """
    return bool(RESOLVED_STAGE_NAME_PATTERN.match(normalize_stage_name(name)))


class ProjectTask(models.Model):
    _inherit = "project.task"

    CLIENT_WRITABLE_FIELDS = frozenset({
        "name",
        "description",
        "priority",
        "stage_id",
        "unified_stage_id",
        "state",
        "planned_date_begin",
        "date_deadline",
        "allocated_hours",
        "tag_ids",
    })
    # Written by Odoo itself after a client change (e.g. a state change
    # updates the last stage date); never shown as editable to clients.
    CLIENT_SYSTEM_FIELDS = frozenset({
        "date_last_stage_update",
    })
    CLIENT_HIDDEN_VIEW_ELEMENTS = (
        ".//page[@name='sub_tasks_page']",
        ".//page[@name='task_dependencies']",
        ".//div[@name='button_box']",
        ".//page[@name='time_entries_page']",
    )

    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        result = super().get_view(view_id, view_type, **options)
        if (
            not self.env.user.has_group(
                "project_custom_extension.group_project_client"
            )
            or self.env.user.has_group("project.group_project_manager")
        ):
            return result

        arch = etree.fromstring(result["arch"])
        if arch.tag in {"form", "list", "kanban"}:
            arch.set("create", "false")
            arch.set("delete", "false")

        for element_xpath in self.CLIENT_HIDDEN_VIEW_ELEMENTS:
            for element in arch.xpath(element_xpath):
                element.set("invisible", "True")

        for field_node in arch.xpath(".//field[@name]"):
            field_name = field_node.get("name")
            if field_name == "user_ids":
                if arch.tag == "list":
                    field_node.set("column_invisible", "True")
                else:
                    field_node.set("invisible", "True")
            if field_name in self.CLIENT_WRITABLE_FIELDS:
                if field_name == "allocated_hours":
                    field_node.set("invisible", "0")
                existing_readonly = field_node.get("readonly")
                readonly = "uid not in user_ids"
                if existing_readonly and existing_readonly not in {
                    "0", "False", "false",
                }:
                    readonly = f"({existing_readonly}) or ({readonly})"
                field_node.set("readonly", readonly)
            else:
                field_node.set("readonly", "True")

        if arch.tag == "list" and not arch.xpath(".//field[@name='user_ids']"):
            etree.SubElement(
                arch,
                "field",
                name="user_ids",
                column_invisible="True",
            )
        elif arch.tag == "form" and not arch.xpath(".//field[@name='user_ids']"):
            container = arch.find(".//sheet")
            if container is None:
                container = arch
            etree.SubElement(
                container,
                "field",
                name="user_ids",
                invisible="True",
            )

        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    def _check_project_user_task_links(self, values, default_project_id=False):
        project_ids = {
            values.get("project_id") or default_project_id,
        } - {False, None}
        parent_ids = {
            values.get("parent_id") or self.env.context.get("default_parent_id"),
        } - {False, None}

        if project_ids:
            readable_project_ids = set(self.env["project.project"].search([
                ("id", "in", list(project_ids)),
            ]).ids)
            if project_ids - readable_project_ids:
                raise AccessError(
                    _("No puede crear o mover tareas a proyectos que no puede consultar.")
                )
        if parent_ids:
            readable_parent_ids = set(self.search([
                ("id", "in", list(parent_ids)),
            ]).ids)
            if parent_ids - readable_parent_ids:
                raise AccessError(
                    _("No puede crear subtareas bajo tareas que no puede consultar.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ) and (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ):
            raise AccessError(_("No tiene permiso para crear tareas."))
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ):
            default_project_id = self.env.context.get("default_project_id")
            for values in vals_list:
                self._check_project_user_task_links(values, default_project_id)
        for values in vals_list:
            if values.get("parent_id"):
                # Dates sent explicitly, even empty, are kept as they are.
                parent = self.browse(values["parent_id"])
                for name, value in self._get_subtask_default_dates(
                    parent, values.get("date_deadline"),
                ).items():
                    values.setdefault(name, value)
        tasks = super().create(vals_list)
        resolved_tasks = tasks.filtered(
            lambda task: is_resolved_stage_name(task.stage_id.name)
            and task.state != "1_done"
        )
        if resolved_tasks:
            resolved_tasks.with_context(
                _skip_resolved_stage_state_sync=True
            ).write({"state": "1_done"})
        return tasks

    def _write_with_resolved_stage_sync(self, vals):
        previous_stage_ids = {task.id: task.stage_id.id for task in self}
        result = super().write(vals)
        if not self.env.context.get("_skip_resolved_stage_state_sync"):
            resolved_tasks = self.filtered(
                lambda task: previous_stage_ids.get(task.id) != task.stage_id.id
                and is_resolved_stage_name(task.stage_id.name)
                and task.state != "1_done"
            )
            if resolved_tasks:
                resolved_tasks.with_context(
                    _skip_resolved_stage_state_sync=True
                ).write({"state": "1_done"})
        return result

    def write(self, vals):
        if self.env.su or self.env.user.has_group("project.group_project_manager"):
            return self._write_with_resolved_stage_sync(vals)
        if "is_internal_task" in vals:
            raise AccessError(
                _("Solo un administrador de proyectos puede marcar tareas como internas.")
            )

        is_client = self.env.user.has_group(
            "project_custom_extension.group_project_client"
        )
        if not is_client and not self.env.user.has_group("project.group_project_user"):
            raise AccessError(_("No tiene permiso para modificar tareas."))

        if is_client:
            forbidden_fields = (
                set(vals) - self.CLIENT_WRITABLE_FIELDS - self.CLIENT_SYSTEM_FIELDS
            )
            if forbidden_fields:
                raise AccessError(
                    _("No tiene permiso para modificar la asignación o estructura de la tarea.")
                )
            self.check_access("write")
            if any(
                not task.active
                or not task.project_id.active
                or self.env.user not in task.user_ids
                for task in self
            ):
                raise AccessError(
                    _("Solo puede modificar tareas activas asignadas a usted.")
                )
        elif "project_id" in vals or "parent_id" in vals:
            self._check_project_user_task_links(vals)
        return self._write_with_resolved_stage_sync(vals)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        parent_id = values.get("parent_id") or self.env.context.get(
            "default_parent_id"
        )
        if parent_id:
            parent = self.browse(parent_id).exists()
            for name, value in self._get_subtask_default_dates(
                parent, values.get("date_deadline"),
            ).items():
                if name in fields_list and not values.get(name):
                    values[name] = value
        return values

    @api.model
    def _get_subtask_default_dates(self, parent, deadline=False):
        """Start a subtask now and end it with its parent, if still ahead.

        ``deadline`` is the end date already chosen for the subtask: the start
        is not proposed when it would fall after it.
        """
        now = fields.Datetime.now()
        values = {}
        if not deadline and parent and parent.date_deadline and parent.date_deadline > now:
            values["date_deadline"] = parent.date_deadline
        end = fields.Datetime.to_datetime(deadline) or values.get("date_deadline")
        if not end or end >= now:
            values["planned_date_begin"] = now
        return values

    def unlink(self):
        if not self.env.su and (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ) and not self.env.user.has_group("project.group_project_manager"):
            raise AccessError(_("No tiene permiso para eliminar tareas."))
        return super().unlink()

    planned_date_begin = fields.Datetime(
        string="Fecha inicial",
        tracking=True,
    )
    unified_stage_id = fields.Many2one(
        "project.task.unified.stage",
        string="Etapa unificada",
        compute="_compute_unified_stage_id",
        inverse="_inverse_unified_stage_id",
        store=True,
        index=True,
        group_expand="_read_group_unified_stage_ids",
        help="Etapa común a todos los proyectos. Al cambiarla, la tarea pasa "
        "a la etapa equivalente de su proyecto.",
    )
    hierarchical_priority = fields.Integer(
        string="Prioridad jerárquica",
        default=0,
        tracking=True,
        index=True,
    )
    hierarchical_priority_order = fields.Integer(
        string="Orden de prioridad jerárquica",
        compute="_compute_hierarchical_priority_order",
        store=True,
        index=True,
    )

    project_weight = fields.Float(
        string="Peso en el proyecto (%)",
        digits=(5, 2),
        default=0.0,
        tracking=True,
        help="Porcentaje del avance del proyecto que representa esta tarea "
        "principal. Se reparte en partes iguales entre sus subtareas.",
    )
    time_entry_ids = fields.One2many(
        "project.task.time.entry",
        "task_id",
        string="Registro de horas",
        groups="project.group_project_user",
    )
    time_spent_hours = fields.Float(
        string="Horas registradas",
        compute="_compute_time_spent_hours",
        groups="project.group_project_user",
    )
    project_progress_percentage = fields.Float(
        string="Avance de la tarea (%)",
        digits=(5, 1),
        compute="_compute_project_progress_percentage",
    )
    # Not restricted with ``groups``: dashboards and record rules search on
    # it for every user. The views only show it to project managers.
    is_internal_task = fields.Boolean(
        string="Tarea interna",
        compute="_compute_is_internal_task",
        store=True,
        readonly=False,
        recursive=True,
        index=True,
        tracking=True,
        help="Tarea de manejo interno: no la ven los clientes y no cuenta "
        "para el avance ni los reportes del proyecto. Las subtareas heredan "
        "esta marca.",
    )

    @api.depends("stage_id.unified_stage_id")
    def _compute_unified_stage_id(self):
        for task in self:
            task.unified_stage_id = task.stage_id.unified_stage_id

    def _inverse_unified_stage_id(self):
        for task in self:
            unified_stage = task.unified_stage_id
            if task.stage_id.unified_stage_id == unified_stage:
                continue
            if not unified_stage:
                raise UserError(_(
                    "Las tareas no se pueden mover a la columna sin etapa "
                    "unificada: elija una etapa unificada."
                ))
            if not task.project_id:
                raise UserError(_(
                    "La tarea %(task)s no tiene proyecto, así que no tiene "
                    "etapas a las que moverla.",
                    task=task.display_name,
                ))
            stage = task.project_id.type_ids.filtered(
                lambda project_stage: project_stage.unified_stage_id == unified_stage
            )[:1]
            if not stage:
                raise UserError(_(
                    "El proyecto %(project)s no tiene una etapa equivalente a "
                    "\"%(stage)s\". Asígnela en la configuración de etapas.",
                    project=task.project_id.display_name,
                    stage=unified_stage.name,
                ))
            task.stage_id = stage

    @api.model
    def _read_group_unified_stage_ids(self, stages, domain):
        return stages.search([])

    @api.depends("parent_id.is_internal_task")
    def _compute_is_internal_task(self):
        for task in self:
            if task.parent_id:
                task.is_internal_task = task.parent_id.is_internal_task

    @api.constrains("is_internal_task", "parent_id")
    def _check_internal_task_parent(self):
        for task in self:
            if task.parent_id.is_internal_task and not task.is_internal_task:
                raise ValidationError(
                    _("Una subtarea de una tarea interna también debe ser interna.")
                )

    @api.depends("time_entry_ids.unit_amount")
    def _compute_time_spent_hours(self):
        for task in self:
            task.time_spent_hours = sum(task.time_entry_ids.mapped("unit_amount"))

    @api.depends("state", "child_ids.state", "project_id", "is_internal_task")
    def _compute_project_progress_percentage(self):
        self.project_progress_percentage = 0.0
        tasks = self.filtered(
            lambda task: task._origin and task.project_id and not task.parent_id
        )
        Project = self.env["project.project"]
        for project in tasks.project_id:
            progress = Project._get_project_execution_progress(project._origin)
            fraction_by_task = {
                phase["task"].id: phase["percentage"]
                for phase in progress["phases"]
            }
            for task in tasks.filtered(lambda task: task.project_id == project):
                task.project_progress_percentage = round(
                    fraction_by_task.get(task._origin.id, 0.0) * 100, 1
                )

    @api.constrains(
        "project_weight", "parent_id", "project_id", "active", "is_internal_task"
    )
    def _check_project_weight(self):
        for task in self:
            if not 0 <= task.project_weight <= 100:
                raise ValidationError(
                    _("El peso de una tarea debe estar entre 0% y 100%.")
                )
        if self.env.context.get("skip_project_weight_total_check"):
            return
        projects = self.filtered(
            lambda task: not task.parent_id and task.project_weight
        ).project_id
        for project in projects:
            # The limit applies to every main task, including those hidden
            # from the current user by record rules.
            main_tasks = self.sudo().search([
                ("project_id", "=", project.id),
                ("parent_id", "=", False),
                ("is_internal_task", "=", False),
            ])
            total = sum(main_tasks.mapped("project_weight"))
            if float_compare(total, 100, precision_digits=2) > 0:
                raise ValidationError(_(
                    "La suma de los pesos de las tareas principales del "
                    "proyecto %(project)s es %(total)s%% y no puede superar "
                    "el 100%%.",
                    project=project.display_name,
                    total=float_repr(total, 2),
                ))

    @api.depends("hierarchical_priority")
    def _compute_hierarchical_priority_order(self):
        for task in self:
            task.hierarchical_priority_order = (
                task.hierarchical_priority or 2147483647
            )

    @api.constrains("hierarchical_priority")
    def _check_hierarchical_priority(self):
        for task in self:
            if task.hierarchical_priority < 0:
                raise ValidationError(
                    _("La prioridad jerárquica no puede ser negativa.")
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
