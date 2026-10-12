from odoo import Command, _, api, fields, models
from odoo.addons.project.models.project_task import CLOSED_STATES
from odoo.tools import html2plaintext, plaintext2html

from .mcp_server import McpToolInputError


MAX_LIMIT = 100
DEFAULT_LIMIT = 20

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

ID = {"type": "integer", "minimum": 1}
LIMIT = {
    "type": "integer",
    "minimum": 1,
    "maximum": MAX_LIMIT,
    "description": f"Máximo de resultados (por defecto {DEFAULT_LIMIT}).",
}
DATE = {"type": "string", "description": "Fecha AAAA-MM-DD."}
DATETIME = {
    "type": "string",
    "description": "Fecha AAAA-MM-DD o fecha y hora AAAA-MM-DD HH:MM:SS en UTC.",
}
TASK_FIELDS_SCHEMA = {
    "name": {"type": "string", "description": "Título de la tarea."},
    "description": {"type": "string", "description": "Descripción en texto plano."},
    "user_ids": {
        "type": "array",
        "items": ID,
        "description": "IDs de los usuarios asignados (reemplaza la asignación).",
    },
    "date_deadline": DATETIME,
    "planned_date_begin": DATETIME,
    "allocated_hours": {"type": "number", "minimum": 0},
    "priority": {
        "type": "string",
        "enum": ["0", "1"],
        "description": "0 = normal, 1 = alta.",
    },
    "sprint_id": {**ID, "description": "Sprint del mismo proyecto."},
    "tag_ids": {
        "type": "array",
        "items": ID,
        "description": "IDs de etiquetas (reemplaza las actuales).",
    },
}


def _ref(record):
    return {"id": record.id, "name": record.display_name} if record else None


def _refs(records):
    return [_ref(record) for record in records]


def _limit(limit):
    return min(max(int(limit or DEFAULT_LIMIT), 1), MAX_LIMIT)


def _datetime(value, label):
    if value in (None, False, ""):
        return False
    normalized = str(value).replace("T", " ").removesuffix("Z")[:19]
    try:
        return fields.Datetime.to_datetime(normalized)
    except ValueError as error:
        raise McpToolInputError(_("Fecha no válida en %s: %s", label, value)) from error


def _date(value, label):
    if value in (None, False, ""):
        return False
    try:
        return fields.Date.to_date(str(value)[:10])
    except ValueError as error:
        raise McpToolInputError(_("Fecha no válida en %s: %s", label, value)) from error


class ProjectMcpServerTools(models.AbstractModel):
    _inherit = "project.mcp.server"

    @api.model
    def _mcp_tools(self):
        tools = super()._mcp_tools()
        tools.update({
            "list_projects": {
                "description": "Lista los proyectos visibles con cliente, responsable, avance ponderado y garantía.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string", "description": "Texto a buscar en el nombre."},
                        "partner_id": {**ID, "description": "Filtra por cliente."},
                        "include_closed": {"type": "boolean", "description": "Incluye proyectos cerrados."},
                        "limit": LIMIT,
                    },
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_list_projects",
            },
            "get_project": {
                "description": "Detalle de un proyecto: etapas, sprints, fases principales y avance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"project_id": ID},
                    "required": ["project_id"],
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_get_project",
            },
            "get_project_dashboard": {
                "description": (
                    "Dashboard de proyectos. Sin project_id devuelve el resumen general "
                    "(salud, alertas, vencimientos). Con project_id devuelve el dashboard "
                    "ejecutivo del proyecto (fases, bloqueos, próximas acciones)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": ID,
                        "partner_id": {**ID, "description": "Filtra el resumen general por cliente."},
                        "cutoff": {
                            "type": "string",
                            "pattern": "^[0-9]{4}-[0-9]{2}$",
                            "description": "Mes de corte AAAA-MM del dashboard de proyecto (por defecto hoy).",
                        },
                    },
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_get_project_dashboard",
            },
            "search_tasks": {
                "description": "Busca tareas visibles. Por defecto excluye las tareas cerradas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string", "description": "Texto a buscar en el título."},
                        "project_id": ID,
                        "sprint_id": ID,
                        "unified_stage_id": ID,
                        "user_id": {**ID, "description": "Tareas asignadas a este usuario."},
                        "assigned_to_me": {"type": "boolean"},
                        "overdue": {"type": "boolean", "description": "Solo tareas con fecha límite vencida."},
                        "include_closed": {"type": "boolean"},
                        "limit": LIMIT,
                    },
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_search_tasks",
            },
            "get_task": {
                "description": "Detalle de una tarea: descripción, subtareas, dependencias y horas registradas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": ID},
                    "required": ["task_id"],
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_get_task",
            },
            "list_sprints": {
                "description": "Lista los sprints de un proyecto con su cantidad de tareas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"project_id": ID},
                    "required": ["project_id"],
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_list_sprints",
            },
            "list_unified_stages": {
                "description": "Lista las etapas unificadas, comunes a todos los proyectos.",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": READ_ONLY,
                "method": "_mcp_tool_list_unified_stages",
            },
            "get_my_time_entries": {
                "description": "Horas registradas por el usuario actual en un rango de fechas, con totales.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_from": DATE,
                        "date_to": DATE,
                        "project_id": ID,
                        "limit": LIMIT,
                    },
                    "required": ["date_from", "date_to"],
                },
                "annotations": READ_ONLY,
                "method": "_mcp_tool_get_my_time_entries",
            },
            "create_task": {
                "description": "Crea una tarea en un proyecto. Con parent_id se crea como subtarea.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": ID,
                        "parent_id": {**ID, "description": "Tarea padre (fase)."},
                        **TASK_FIELDS_SCHEMA,
                    },
                    "required": ["project_id", "name"],
                },
                "annotations": WRITE,
                "method": "_mcp_tool_create_task",
            },
            "update_task": {
                "description": "Actualiza campos de una tarea. Solo se modifican los campos enviados.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": ID, **TASK_FIELDS_SCHEMA},
                    "required": ["task_id"],
                },
                "annotations": {**WRITE, "idempotentHint": True},
                "method": "_mcp_tool_update_task",
            },
            "move_task_stage": {
                "description": (
                    "Mueve una tarea de etapa. Use stage_id (etapa del proyecto, ver get_project) "
                    "o unified_stage_id (ver list_unified_stages)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": ID, "stage_id": ID, "unified_stage_id": ID},
                    "required": ["task_id"],
                },
                "annotations": {**WRITE, "idempotentHint": True},
                "method": "_mcp_tool_move_task_stage",
            },
            "log_time": {
                "description": (
                    "Registra horas en una tarea (más de 0 y hasta 24 por registro). Por defecto "
                    "a nombre del usuario actual; los administradores de proyectos pueden indicar "
                    "employee_id o user_id para registrarlas a nombre de otra persona."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": ID,
                        "hours": {"type": "number", "exclusiveMinimum": 0, "maximum": 24},
                        "employee_id": {**ID, "description": "Empleado al que se imputan las horas."},
                        "user_id": {
                            **ID,
                            "description": "Usuario (p. ej. un asignado de la tarea) al que se imputan las horas.",
                        },
                        "date": {**DATE, "description": "Fecha del trabajo (por defecto hoy)."},
                        "description": {"type": "string"},
                    },
                    "required": ["task_id", "hours"],
                },
                "annotations": WRITE,
                "method": "_mcp_tool_log_time",
            },
            "post_task_message": {
                "description": "Publica un comentario en el chatter de una tarea.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": ID, "body": {"type": "string"}},
                    "required": ["task_id", "body"],
                },
                "annotations": WRITE,
                "method": "_mcp_tool_post_task_message",
            },
        })
        return tools

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _mcp_browse(self, model, record_id, label):
        record = self.env[model].browse(int(record_id)).exists()
        if not record:
            raise McpToolInputError(_("No existe %s con id %s.", label, record_id))
        record.check_access("read")
        return record

    @api.model
    def _mcp_time_entry_employee(self, employee_id=None, user_id=None):
        """Employee to log time for; permissions are enforced by the time entry model."""
        if employee_id and user_id:
            raise McpToolInputError(_("Indique employee_id o user_id, no ambos."))
        # hr.employee is HR-restricted; project managers may still pick any employee.
        if employee_id:
            employee = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
            if not employee:
                raise McpToolInputError(_("No existe empleado con id %s.", employee_id))
            return employee
        if user_id:
            user = self.env["res.users"].sudo().browse(int(user_id)).exists()
            if not user:
                raise McpToolInputError(_("No existe usuario con id %s.", user_id))
            if not user.employee_id:
                raise McpToolInputError(
                    _("El usuario %s no tiene un empleado asociado.", user.name)
                )
            return user.employee_id
        if not self.env.user.employee_id:
            raise McpToolInputError(_("Su usuario no tiene un empleado asociado."))
        return self.env.user.employee_id

    @api.model
    def _mcp_project_summary(self, project):
        return {
            "id": project.id,
            "name": project.name,
            "customer": _ref(project.partner_id),
            "manager": _ref(project.user_id),
            "company_type": project.company_type or None,
            "status": project.last_update_status,
            "weighted_progress": round(project.weighted_progress, 2),
            "date_start": project.date_start,
            "date_end": project.date,
            "warranty": project.warranty_period_display or None,
            "warranty_end_date": project.warranty_end_date,
        }

    @api.model
    def _mcp_task_summary(self, task):
        return {
            "id": task.id,
            "name": task.name,
            "project": _ref(task.project_id),
            "parent": _ref(task.parent_id),
            "stage": _ref(task.stage_id),
            "unified_stage": _ref(task.unified_stage_id),
            "state": task.state,
            "sprint": _ref(task.sprint_id),
            "assignees": _refs(task.user_ids),
            "priority": task.priority,
            "planned_date_begin": task.planned_date_begin,
            "date_deadline": task.date_deadline,
            "allocated_hours": task.allocated_hours,
            "progress": round(task.project_progress_percentage, 1),
        }

    @api.model
    def _mcp_task_values(self, arguments):
        values = {}
        for key in ("name", "allocated_hours", "priority"):
            if key in arguments:
                values[key] = arguments[key]
        if "description" in arguments:
            values["description"] = plaintext2html(arguments["description"] or "")
        for key in ("date_deadline", "planned_date_begin"):
            if key in arguments:
                values[key] = _datetime(arguments[key], key)
        if "sprint_id" in arguments:
            values["sprint_id"] = arguments["sprint_id"] or False
        for key in ("user_ids", "tag_ids"):
            if key in arguments:
                values[key] = [Command.set([int(i) for i in arguments[key] or []])]
        return values

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    @api.model
    def _mcp_tool_list_projects(
        self, search=None, partner_id=None, include_closed=False, limit=None
    ):
        domain = [("active", "=", True)]
        if not include_closed:
            domain.append(("last_update_status", "!=", "done"))
        if search:
            domain.append(("name", "ilike", search))
        if partner_id:
            domain.append(("partner_id", "child_of", int(partner_id)))
        projects = self.env["project.project"].search(
            domain, limit=_limit(limit), order="name, id"
        )
        return {"projects": [self._mcp_project_summary(p) for p in projects]}

    @api.model
    def _mcp_tool_get_project(self, project_id):
        project = self._mcp_browse("project.project", project_id, _("proyecto"))
        return {
            **self._mcp_project_summary(project),
            "description": html2plaintext(project.description or "") or None,
            "stages": _refs(project.type_ids.sorted("sequence")),
            "sprints": _refs(
                self.env["project.sprint"].search([("project_id", "=", project.id)])
            ),
            "main_tasks": [
                {
                    **_ref(task),
                    "weight": task.project_weight,
                    "progress": round(task.project_progress_percentage, 1),
                    "state": task.state,
                }
                for task in project.main_task_ids
            ],
        }

    @api.model
    def _mcp_tool_get_project_dashboard(self, project_id=None, partner_id=None, cutoff=None):
        Project = self.env["project.project"]
        if project_id:
            self._mcp_browse("project.project", project_id, _("proyecto"))
            return Project.get_project_detail_dashboard_data(
                project_id=int(project_id),
                cutoff=cutoff or False,
            )
        return Project.get_project_dashboard_data(partner_id=partner_id or False)

    @api.model
    def _mcp_tool_search_tasks(
        self,
        search=None,
        project_id=None,
        sprint_id=None,
        unified_stage_id=None,
        user_id=None,
        assigned_to_me=False,
        overdue=False,
        include_closed=False,
        limit=None,
    ):
        domain = [("active", "=", True)]
        if not include_closed:
            domain.append(("state", "not in", list(CLOSED_STATES)))
        if search:
            domain.append(("name", "ilike", search))
        for field_name, value in (
            ("project_id", project_id),
            ("sprint_id", sprint_id),
            ("unified_stage_id", unified_stage_id),
            ("user_ids", user_id),
        ):
            if value:
                domain.append((field_name, "=", int(value)))
        if assigned_to_me:
            domain.append(("user_ids", "in", self.env.uid))
        if overdue:
            domain.append(("date_deadline", "<", fields.Datetime.now()))
        tasks = self.env["project.task"].search(domain, limit=_limit(limit))
        return {"tasks": [self._mcp_task_summary(task) for task in tasks]}

    @api.model
    def _mcp_tool_get_task(self, task_id):
        task = self._mcp_browse("project.task", task_id, _("tarea"))
        result = {
            **self._mcp_task_summary(task),
            "description": html2plaintext(task.description or "") or None,
            "tags": _refs(task.tag_ids),
            "subtasks": [
                {**_ref(child), "state": child.state, "assignees": _refs(child.user_ids)}
                for child in task.child_ids
            ],
            "blocked_by": _refs(task.depend_on_ids),
        }
        if self.env.user.has_group("project.group_project_user"):
            result["time_spent_hours"] = task.time_spent_hours
        return result

    @api.model
    def _mcp_tool_list_sprints(self, project_id):
        project = self._mcp_browse("project.project", project_id, _("proyecto"))
        sprints = self.env["project.sprint"].search([("project_id", "=", project.id)])
        return {
            "sprints": [
                {**_ref(sprint), "sequence": sprint.sequence, "task_count": sprint.task_count}
                for sprint in sprints
            ]
        }

    @api.model
    def _mcp_tool_list_unified_stages(self):
        stages = self.env["project.task.unified.stage"].search([])
        return {
            "stages": [
                {**_ref(stage), "sequence": stage.sequence, "folded": stage.fold}
                for stage in stages
            ]
        }

    @api.model
    def _mcp_tool_get_my_time_entries(self, date_from, date_to, project_id=None, limit=None):
        domain = [
            ("user_id", "=", self.env.uid),
            ("date", ">=", _date(date_from, "date_from")),
            ("date", "<=", _date(date_to, "date_to")),
        ]
        if project_id:
            domain.append(("project_id", "=", int(project_id)))
        Entry = self.env["project.task.time.entry"]
        entries = Entry.search(domain, limit=_limit(limit))
        total = sum(Entry.search(domain).mapped("unit_amount"))
        return {
            "total_hours": total,
            "entries": [
                {
                    "id": entry.id,
                    "date": entry.date,
                    "hours": entry.unit_amount,
                    "description": entry.name or None,
                    "task": _ref(entry.task_id),
                    "project": _ref(entry.project_id),
                }
                for entry in entries
            ],
        }

    # ------------------------------------------------------------------
    # Write tools (no tool ever deletes records)
    # ------------------------------------------------------------------

    @api.model
    def _mcp_tool_create_task(self, project_id, name, parent_id=None, **arguments):
        project = self._mcp_browse("project.project", project_id, _("proyecto"))
        values = {
            "project_id": project.id,
            "name": name,
            **self._mcp_task_values(arguments),
        }
        if parent_id:
            values["parent_id"] = self._mcp_browse("project.task", parent_id, _("tarea")).id
        task = self.env["project.task"].create(values)
        return self._mcp_task_summary(task)

    @api.model
    def _mcp_tool_update_task(self, task_id, **arguments):
        task = self._mcp_browse("project.task", task_id, _("tarea"))
        values = self._mcp_task_values(arguments)
        if not values:
            raise McpToolInputError(_("No se indicó ningún campo para actualizar."))
        task.write(values)
        return self._mcp_task_summary(task)

    @api.model
    def _mcp_tool_move_task_stage(self, task_id, stage_id=None, unified_stage_id=None):
        task = self._mcp_browse("project.task", task_id, _("tarea"))
        if bool(stage_id) == bool(unified_stage_id):
            raise McpToolInputError(_("Indique stage_id o unified_stage_id, no ambos."))
        if stage_id:
            if int(stage_id) not in task.project_id.type_ids.ids:
                raise McpToolInputError(
                    _("La etapa %s no pertenece al proyecto de la tarea.", stage_id)
                )
            task.write({"stage_id": int(stage_id)})
        else:
            self._mcp_browse("project.task.unified.stage", unified_stage_id, _("etapa unificada"))
            task.write({"unified_stage_id": int(unified_stage_id)})
        return self._mcp_task_summary(task)

    @api.model
    def _mcp_tool_log_time(
        self, task_id, hours, date=None, description=None, employee_id=None, user_id=None
    ):
        task = self._mcp_browse("project.task", task_id, _("tarea"))
        employee = self._mcp_time_entry_employee(employee_id, user_id)
        values = {
            "task_id": task.id,
            "employee_id": employee.id,
            "unit_amount": hours,
            "name": description or False,
        }
        if date:
            values["date"] = _date(date, "date")
        entry = self.env["project.task.time.entry"].create(values)
        return {
            "id": entry.id,
            "date": entry.date,
            "hours": entry.unit_amount,
            "employee": _ref(entry.employee_id.sudo()),
            "task": _ref(entry.task_id),
            "task_time_spent_hours": task.time_spent_hours,
        }

    @api.model
    def _mcp_tool_post_task_message(self, task_id, body):
        task = self._mcp_browse("project.task", task_id, _("tarea"))
        if not (body or "").strip():
            raise McpToolInputError(_("El comentario está vacío."))
        message = task.message_post(
            body=plaintext2html(body),
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        return {"message_id": message.id, "task": _ref(task)}
