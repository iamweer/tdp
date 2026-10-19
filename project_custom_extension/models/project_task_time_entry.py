from collections import defaultdict
from datetime import datetime, time, timedelta

import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .project_project import COMPANY_TYPE_SELECTION, WARRANTY_TIMEZONE

_logger = logging.getLogger(__name__)

MAX_GRID_DAYS = 62

# Las alertas semanales de horas se calculan con el calendario de Colombia.
TIME_ALERT_TIMEZONE = WARRANTY_TIMEZONE
WEEKDAY_LABELS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

# group_by -> (first level field, second level field)
TIME_GRID_GROUPINGS = {
    "employee": ("employee_id", "project_id"),
    "project": ("project_id", "employee_id"),
    "company": ("company_type", "employee_id"),
    "customer": ("partner_id", "project_id"),
}


class ProjectTaskTimeEntry(models.Model):
    _name = "project.task.time.entry"
    _description = "Registro de horas en tareas"
    _order = "date desc, id desc"

    task_id = fields.Many2one(
        "project.task",
        string="Tarea",
        required=True,
        ondelete="cascade",
        index=True,
    )
    project_id = fields.Many2one(
        related="task_id.project_id",
        string="Proyecto",
        store=True,
        index=True,
    )
    partner_id = fields.Many2one(
        related="project_id.partner_id",
        string="Cliente",
        store=True,
    )
    company_id = fields.Many2one(
        related="task_id.company_id",
        string="Compañía",
        store=True,
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Empleado",
        compute="_compute_employee_id",
        store=True,
        precompute=True,
        readonly=False,
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        related="employee_id.user_id",
        string="Usuario",
        store=True,
        index=True,
    )
    company_type = fields.Selection(
        string="Empresa (TDP/ABI)",
        related="employee_id.company_type",
        store=True,
        # The source field is HR-only; TDP/ABI is not sensitive here.
        groups="base.group_user",
    )
    name = fields.Char(string="Descripción")
    unit_amount = fields.Float(string="Horas", required=True, default=0.0)
    # The default is needed for new records: onchange fills every field
    # without a default with False and never recomputes dependency-less fields.
    can_choose_employee = fields.Boolean(
        compute="_compute_can_choose_employee",
        default=lambda self: self._is_project_manager(),
    )

    @api.model
    def _is_project_manager(self):
        return self.env.user.has_group("project.group_project_manager")

    @api.model
    def _is_client_only(self):
        return (
            self.env.user.has_group("project_custom_extension.group_project_client")
            and not self._is_project_manager()
        )

    @api.depends_context("uid")
    def _compute_can_choose_employee(self):
        self.can_choose_employee = self._is_project_manager()

    @api.depends("task_id")
    def _compute_employee_id(self):
        is_manager = self._is_project_manager()
        own_employee = self.env.user.employee_id
        for entry in self:
            if entry.employee_id:
                entry.employee_id = entry.employee_id
                continue
            assignees = entry.task_id.user_ids
            if is_manager and self.env.user not in assignees:
                assignee_employee = assignees.employee_id[:1]
                entry.employee_id = assignee_employee or own_employee
            else:
                entry.employee_id = own_employee

    @api.constrains("unit_amount")
    def _check_unit_amount(self):
        for entry in self:
            if not 0 < entry.unit_amount <= 24:
                raise ValidationError(
                    _("Las horas registradas deben ser mayores a 0 y no superar 24.")
                )

    @api.constrains("employee_id")
    def _check_employee_user(self):
        for entry in self.sudo():
            if not entry.employee_id.user_id:
                raise ValidationError(_(
                    "El empleado %(employee)s no tiene un usuario asociado.",
                    employee=entry.employee_id.name,
                ))

    def _check_time_entry_access(self):
        if self.env.su or self._is_project_manager():
            return
        if self.env.user.has_group(
            "project_custom_extension.group_project_client"
        ) or not self.env.user.has_group("project.group_project_user"):
            raise AccessError(_("No tiene permiso para registrar horas."))

    def _check_own_employee(self, employee_ids):
        if self.env.su or self._is_project_manager():
            return
        employees = self.env["hr.employee"].sudo().browse(employee_ids)
        if any(employee.user_id != self.env.user for employee in employees):
            raise AccessError(_("Solo puede registrar horas a su nombre."))

    def _check_task_readable(self, task_ids):
        if self.env.su or not task_ids:
            return
        self.env["project.task"].browse(task_ids).check_access("read")

    @api.model_create_multi
    def create(self, vals_list):
        self._check_time_entry_access()
        self._check_task_readable({
            values["task_id"] for values in vals_list if values.get("task_id")
        })
        entries = super().create(vals_list)
        self._check_own_employee(entries.employee_id.ids)
        return entries

    def write(self, vals):
        self._check_time_entry_access()
        if vals.get("task_id"):
            self._check_task_readable({vals["task_id"]})
        if "employee_id" in vals:
            self._check_own_employee([vals["employee_id"]])
        return super().write(vals)

    def unlink(self):
        self._check_time_entry_access()
        return super().unlink()

    # ------------------------------------------------------------------
    # Resumen de horas (cuadrícula OWL)
    # ------------------------------------------------------------------

    @api.model
    def _time_grid_group_value(self, group_by_field, value):
        """(key, name) de un valor de agrupación de `_read_group`."""
        if group_by_field == "company_type":
            labels = dict(COMPANY_TYPE_SELECTION)
            return (value or "none", labels.get(value) or _("Sin empresa"))
        if group_by_field == "project_id":
            # The entry is readable, its project may not be (archived).
            return (value.id or 0, value.sudo().display_name or _("Sin proyecto"))
        if group_by_field == "partner_id":
            return (value.id or 0, value.sudo().display_name or _("Sin cliente"))
        return (value.id or 0, value.sudo().name or _("Sin empleado"))

    @api.model
    def _time_grid_expected_hours(self, employees, date_from, date_to):
        """Horas laborables por empleado y día según su calendario."""
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        start = tz.localize(datetime.combine(date_from, time.min))
        end = tz.localize(datetime.combine(date_to, time.max))
        employees = employees.sudo().filtered(
            lambda employee: employee.resource_calendar_id
            or employee.company_id.resource_calendar_id
        )
        if not employees:
            return {}
        work_time = employees._list_work_time_per_day(start, end)
        return {
            employee_id: {day: hours for day, hours in days}
            for employee_id, days in work_time.items()
        }

    @api.model
    def _time_grid_roster(self, filters):
        """Empleados que el gerente debe ver aunque no tengan horas."""
        user_group = self.env.ref("project.group_project_user")
        client_group = self.env.ref("project_custom_extension.group_project_client")
        domain = [
            ("user_id", "!=", False),
            ("user_id.share", "=", False),
            ("user_id.groups_id", "in", user_group.ids),
            ("user_id.groups_id", "not in", client_group.ids),
        ]
        if filters.get("employee_id"):
            domain.append(("id", "=", int(filters["employee_id"])))
        if filters.get("company_type"):
            domain.append(("company_type", "=", filters["company_type"]))
        return self.env["hr.employee"].sudo().search(domain)

    @api.model
    def get_time_grid_data(self, date_from, date_to, group_by="employee", filters=None):
        if self._is_client_only() or not self.env.user.has_group(
            "project.group_project_user"
        ):
            raise AccessError(_("No tiene permiso para consultar el registro de horas."))
        if group_by not in TIME_GRID_GROUPINGS:
            raise UserError(_("Agrupación no válida: %s", group_by))
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if not date_from or not date_to or date_from > date_to:
            raise UserError(_("El rango de fechas no es válido."))
        if (date_to - date_from).days >= MAX_GRID_DAYS:
            raise UserError(_("El rango no puede superar %s días.", MAX_GRID_DAYS))

        filters = filters or {}
        is_manager = self._is_project_manager()
        today = fields.Date.context_today(self)
        first_field, second_field = TIME_GRID_GROUPINGS[group_by]

        period_domain = [("date", ">=", date_from), ("date", "<=", date_to)]
        domain = list(period_domain)
        if filters.get("project_id"):
            domain.append(("project_id", "=", int(filters["project_id"])))
        if filters.get("employee_id"):
            domain.append(("employee_id", "=", int(filters["employee_id"])))
        if filters.get("company_type"):
            domain.append(("company_type", "=", filters["company_type"]))

        days = []
        day = date_from
        while day <= date_to:
            days.append({
                "date": fields.Date.to_string(day),
                "is_weekend": day.weekday() >= 5,
                "is_today": day == today,
            })
            day += timedelta(days=1)

        groups = {}

        def get_group(key, name, employee=False):
            if key not in groups:
                groups[key] = {
                    "key": key,
                    "name": name,
                    "employee_id": employee.id if employee else False,
                    "company_type": False,
                    "daily": defaultdict(float),
                    "total": 0.0,
                    "lines": {},
                    "expected": False,
                    "balance": False,
                    "missing_days": [],
                }
            return groups[key]

        rows = self._read_group(
            domain,
            groupby=[first_field, second_field, "date:day"],
            aggregates=["unit_amount:sum"],
        )
        totals_daily = defaultdict(float)
        for first_value, second_value, row_day, hours in rows:
            first_key, first_name = self._time_grid_group_value(first_field, first_value)
            second_key, second_name = self._time_grid_group_value(
                second_field, second_value
            )
            day_key = fields.Date.to_string(row_day)
            group = get_group(
                first_key,
                first_name,
                first_value if first_field == "employee_id" else False,
            )
            line = group["lines"].setdefault(second_key, {
                "key": second_key,
                "name": second_name,
                "employee_id": second_value.id if second_field == "employee_id" else False,
                "project_id": second_value.id if second_field == "project_id" else False,
                "daily": defaultdict(float),
                "total": 0.0,
            })
            group["daily"][day_key] += hours
            group["total"] += hours
            line["daily"][day_key] += hours
            line["total"] += hours
            totals_daily[day_key] += hours

        if group_by == "employee":
            employees = self.env["hr.employee"].browse([
                group["employee_id"] for group in groups.values() if group["employee_id"]
            ])
            if is_manager and not filters.get("project_id"):
                employees |= self._time_grid_roster(filters)
            elif not is_manager and self.env.user.employee_id:
                employees |= self.env.user.employee_id
            for employee in employees.sudo():
                get_group(employee.id, employee.name, employee)
            expected = self._time_grid_expected_hours(employees, date_from, date_to)
            for group in groups.values():
                employee = employees.sudo().browse(group["employee_id"])
                group["company_type"] = employee.company_type or False
                expected_by_day = expected.get(employee.id)
                if expected_by_day is None:
                    continue
                expected_to_date = sum(
                    hours for day, hours in expected_by_day.items() if day <= today
                )
                logged_to_date = sum(
                    hours for day_key, hours in group["daily"].items()
                    if fields.Date.to_date(day_key) <= today
                )
                group["expected"] = sum(expected_by_day.values())
                group["balance"] = logged_to_date - expected_to_date
                group["missing_days"] = sorted(
                    fields.Date.to_string(day)
                    for day, hours in expected_by_day.items()
                    if hours and day <= today
                    and not group["daily"].get(fields.Date.to_string(day))
                )

        def serialize_lines(lines):
            return sorted(
                (dict(line, daily=dict(line["daily"])) for line in lines.values()),
                key=lambda line: line["name"].lower(),
            )

        serialized_groups = sorted(
            (
                dict(group, daily=dict(group["daily"]), lines=serialize_lines(group["lines"]))
                for group in groups.values()
            ),
            key=lambda group: group["name"].lower(),
        )

        option_rows = self._read_group(period_domain, groupby=["project_id", "employee_id"])
        project_options = {}
        employee_options = {}
        for project, employee in option_rows:
            if project:
                project_options[project.id] = project.sudo().display_name
            if employee:
                employee_options[employee.id] = employee.sudo().name
        if filters.get("project_id") and int(filters["project_id"]) not in project_options:
            project = self.env["project.project"].browse(int(filters["project_id"])).exists()
            if project:
                project_options[project.id] = project.display_name
        if is_manager:
            for employee in self._time_grid_roster({}):
                employee_options.setdefault(employee.id, employee.name)

        def sorted_options(options):
            return sorted(
                ([key, name] for key, name in options.items()),
                key=lambda item: (item[1] or "").lower(),
            )

        return {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "group_by": group_by,
            "days": days,
            "groups": serialized_groups,
            "totals": {
                "daily": dict(totals_daily),
                "total": sum(totals_daily.values()),
            },
            "filters": {
                "projects": sorted_options(project_options),
                "employees": sorted_options(employee_options),
                "company_types": [list(item) for item in COMPANY_TYPE_SELECTION],
            },
            "is_manager": is_manager,
            "today": fields.Date.to_string(today),
        }

    # ------------------------------------------------------------------
    # Alertas semanales de horas
    # ------------------------------------------------------------------

    @api.model
    def _time_entry_missing_hours(self, employees, date_from, date_to):
        """Empleados con días laborables sin horas entre las dos fechas.

        Solo cuenta hasta hoy, con el calendario de cada empleado y la misma
        regla que los días faltantes del reporte de horas. Devuelve
        ``{employee: {"missing_days", "expected", "logged"}}``.
        """
        date_to = min(date_to, fields.Date.context_today(self))
        if not employees or date_from > date_to:
            return {}
        expected = self._time_grid_expected_hours(employees, date_from, date_to)
        logged = defaultdict(lambda: defaultdict(float))
        for employee, day, hours in self.sudo()._read_group(
            [
                ("employee_id", "in", employees.ids),
                ("date", ">=", date_from),
                ("date", "<=", date_to),
            ],
            groupby=["employee_id", "date:day"],
            aggregates=["unit_amount:sum"],
        ):
            logged[employee.id][fields.Date.to_date(day)] += hours

        result = {}
        for employee in employees:
            expected_by_day = expected.get(employee.id)
            if not expected_by_day:
                continue
            missing_days = sorted(
                day for day, hours in expected_by_day.items()
                if hours and not logged[employee.id].get(day)
            )
            if missing_days:
                result[employee] = {
                    "missing_days": missing_days,
                    "expected": sum(expected_by_day.values()),
                    "logged": sum(logged[employee.id].values()),
                }
        return result

    @api.model
    def _time_alert_row(self, employee, info):
        def format_hours(value):
            minutes = round(value * 60)
            return f"{minutes // 60}:{minutes % 60:02d}"

        return {
            "name": employee.name,
            "days": ", ".join(
                f"{WEEKDAY_LABELS[day.weekday()]} {day.strftime('%d/%m')}"
                for day in info["missing_days"]
            ),
            "logged": format_hours(info["logged"]),
            "expected": format_hours(info["expected"]),
        }

    @api.model
    def _time_alert_rows(self, missing):
        return sorted(
            (self._time_alert_row(employee, info) for employee, info in missing.items()),
            key=lambda row: row["name"].lower(),
        )

    @api.model
    def _time_alert_send(self, template, user, values):
        """Encola el correo de la plantilla para un usuario; False si no tiene correo."""
        email = user.email.strip() if user.email else False
        if not email:
            _logger.info("Alerta de horas sin enviar: %s no tiene correo.", user.login)
            return False
        template.with_context(**values).send_mail(
            user.id,
            force_send=False,
            email_values={"email_to": email},
        )
        return True

    @api.model
    def _time_alert_grid_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{base_url}/odoo/action-project_custom_extension.action_project_timesheet_grid"

    @api.model
    def _cron_remind_missing_hours(self):
        """Viernes: recuerda a cada persona los días de la semana sin horas."""
        self = self.sudo().with_context(tz=TIME_ALERT_TIMEZONE)
        today = fields.Date.context_today(self)
        week_start = today - timedelta(days=today.weekday())
        missing = self._time_entry_missing_hours(
            self._time_grid_roster({}), week_start, today
        )
        template = self.env.ref(
            "project_custom_extension.mail_template_missing_hours_reminder"
        )
        week_label = self._time_alert_week_label(week_start, today)
        grid_url = self._time_alert_grid_url()
        for employee, info in missing.items():
            self._time_alert_send(template, employee.user_id, {
                "missing_row": self._time_alert_row(employee, info),
                "week_label": week_label,
                "grid_url": grid_url,
            })
        return True

    @api.model
    def _time_alert_week_label(self, date_from, date_to):
        return f"{date_from.strftime('%d/%m')} – {date_to.strftime('%d/%m/%Y')}"

    @api.model
    def _cron_notify_missing_hours_summary(self):
        """Lunes: resumen de la semana anterior de quién no registró horas.

        Los gerentes de proyecto reciben a todos; cada PM, solo a las
        personas de sus proyectos (asignadas a tareas abiertas o con horas
        en ellos esa semana).
        """
        self = self.sudo().with_context(tz=TIME_ALERT_TIMEZONE)
        today = fields.Date.context_today(self)
        week_start = today - timedelta(days=today.weekday() + 7)
        week_end = week_start + timedelta(days=6)
        missing = self._time_entry_missing_hours(
            self._time_grid_roster({}), week_start, week_end
        )
        if not missing:
            return True

        template = self.env.ref(
            "project_custom_extension.mail_template_missing_hours_summary"
        )
        week_label = self._time_alert_week_label(week_start, week_end)
        grid_url = self._time_alert_grid_url()
        manager_group = self.env.ref("project.group_project_manager")
        managers = self.env["res.users"].search([
            ("groups_id", "in", manager_group.ids),
            ("share", "=", False),
        ])
        all_rows = self._time_alert_rows(missing)
        for manager in managers:
            self._time_alert_send(template, manager, {
                "missing_rows": all_rows,
                "week_label": week_label,
                "grid_url": grid_url,
                "scope_label": _("todo el equipo"),
            })

        Task = self.env["project.task"]
        projects = self.env["project.project"].search([
            ("active", "=", True),
            ("last_update_status", "!=", "done"),
            ("user_id", "!=", False),
            ("user_id", "not in", managers.ids),
        ])
        for pm in projects.user_id:
            pm_projects = projects.filtered(lambda project: project.user_id == pm)
            assigned_users = Task.search([
                ("project_id", "in", pm_projects.ids),
                ("state", "in", Task.OPEN_STATES),
            ]).user_ids
            logged_employees = self.search([
                ("project_id", "in", pm_projects.ids),
                ("date", ">=", week_start),
                ("date", "<=", week_end),
            ]).employee_id
            team = {
                employee: info for employee, info in missing.items()
                if employee.user_id in assigned_users or employee in logged_employees
            }
            if team:
                self._time_alert_send(template, pm, {
                    "missing_rows": self._time_alert_rows(team),
                    "week_label": week_label,
                    "grid_url": grid_url,
                    "scope_label": _("las personas de tus proyectos"),
                })
        return True
