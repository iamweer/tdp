from datetime import date, datetime, timedelta

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression


DASHBOARD_HEALTH_DEFAULTS = {
    "progress_weight": 50,
    "status_weight": 30,
    "operations_weight": 20,
    "healthy_threshold": 75,
    "attention_threshold": 50,
}

DASHBOARD_HEALTH_PARAMETERS = {
    key: f"project_custom_extension.dashboard_health_{key}"
    for key in DASHBOARD_HEALTH_DEFAULTS
}

DASHBOARD_STATUS_SCORES = {
    "on_track": 100,
    "at_risk": 60,
    "off_track": 20,
    "on_hold": 40,
    "to_define": 50,
}

DASHBOARD_STATUS_ORDER = {
    "off_track": 0,
    "at_risk": 1,
    "on_hold": 2,
    "to_define": 3,
    "on_track": 4,
}

WARRANTY_ACTIVATION_PARAMETER = (
    "project_custom_extension.warranty_automation_activation_date"
)
WARRANTY_VICTOR_LOGIN = "victor.castano@tdpsolutions.co"
WARRANTY_TIMEZONE = "America/Bogota"


class ProjectProject(models.Model):
    _inherit = "project.project"

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
            arch.set("edit", "false")
            arch.set("delete", "false")
        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ) and (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ):
            raise AccessError(_("No tiene permiso para crear proyectos."))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.su or self.env.user.has_group("project.group_project_manager"):
            return super().write(vals)
        if (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ):
            raise AccessError(_("No tiene permiso para modificar proyectos."))

        self.check_access("write")
        if any(project.create_uid != self.env.user for project in self):
            raise AccessError(
                _("Solo puede modificar los proyectos que usted creó.")
            )
        return super().write(vals)

    def unlink(self):
        if (
            not self.env.su
            and not self.env.user.has_group("project.group_project_manager")
        ):
            raise AccessError(_("Solo un administrador puede eliminar proyectos."))
        return super().unlink()

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
    warranty_auto_closed_on = fields.Date(
        string="Cierre automático por garantía",
        readonly=True,
        copy=False,
        tracking=True,
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

    @api.model
    def _get_task_date_in_context(self, value):
        if not value:
            return False
        timestamp = fields.Datetime.to_datetime(value)
        return fields.Datetime.context_timestamp(self, timestamp).date()

    @api.model
    def _get_project_execution_progress(self, project, tasks=None):
        """Compute planned progress from dated top-level phases and leaf tasks."""
        if tasks is None:
            tasks = self.env["project.task"].search([
                ("project_id", "=", project.id),
                ("active", "=", True),
            ])
        tasks = tasks.filtered(
            lambda task: task.project_id == project and task.active
        )
        children_by_parent = {}
        for task in tasks:
            if task.parent_id:
                children_by_parent.setdefault(task.parent_id.id, []).append(task)
        phases = tasks.filtered(lambda task: not task.parent_id)
        if not phases:
            return {"percentage": False, "phases": []}

        phase_values = []
        for phase in phases:
            start_date = self._get_task_date_in_context(phase.planned_date_begin)
            end_date = self._get_task_date_in_context(phase.date_deadline)
            if not start_date or not end_date or start_date > end_date:
                return {"percentage": False, "phases": []}

            duration_days = (end_date - start_date).days + 1
            leaf_tasks = []
            pending = list(children_by_parent.get(phase.id, []))
            while pending:
                current = pending.pop()
                children = children_by_parent.get(current.id, [])
                if children:
                    pending.extend(children)
                else:
                    leaf_tasks.append(current)
            if not leaf_tasks:
                leaf_tasks = [phase]
            completed_count = sum(task.state == "1_done" for task in leaf_tasks)
            phase_percentage = completed_count / len(leaf_tasks)
            phase_values.append({
                "task": phase,
                "duration_days": duration_days,
                "completed_count": completed_count,
                "total_count": len(leaf_tasks),
                "percentage": phase_percentage,
            })

        total_days = sum(phase["duration_days"] for phase in phase_values)
        if not total_days:
            return {"percentage": False, "phases": []}
        percentage = sum(
            phase["duration_days"] * phase["percentage"]
            for phase in phase_values
        ) * 100 / total_days
        return {
            "percentage": round(percentage, 1),
            "phases": phase_values,
        }

    @api.model
    def _get_project_execution_progress_by_project(self, projects):
        if not projects:
            return {}
        tasks = self.env["project.task"].search([
            ("project_id", "in", projects.ids),
            ("active", "=", True),
        ])
        tasks_by_project = {}
        for task in tasks:
            tasks_by_project.setdefault(task.project_id.id, self.env["project.task"])
            tasks_by_project[task.project_id.id] |= task
        return {
            project.id: self._get_project_execution_progress(
                project,
                tasks_by_project.get(project.id, self.env["project.task"]),
            )
            for project in projects
        }

    @api.model
    def _ensure_warranty_automation_activation_date(self):
        parameters = self.env["ir.config_parameter"]
        if not parameters._get_param(WARRANTY_ACTIVATION_PARAMETER):
            parameters.set_param(
                WARRANTY_ACTIVATION_PARAMETER,
                fields.Date.to_string(fields.Date.context_today(
                    self.with_context(tz=WARRANTY_TIMEZONE)
                )),
            )

    @api.model
    def _cron_close_projects_after_warranty(self):
        """Close due projects and create one activity and email per recipient."""
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ):
            raise AccessError(_("Solo un gerente puede ejecutar el cierre por garantía."))

        self._ensure_warranty_automation_activation_date()
        activation_date = fields.Date.to_date(
            self.env["ir.config_parameter"]._get_param(
                WARRANTY_ACTIVATION_PARAMETER
            )
        )
        today = fields.Date.context_today(self.with_context(tz=WARRANTY_TIMEZONE))
        projects = self.search([
            ("active", "=", True),
            ("warranty_end_date", ">=", activation_date),
            ("warranty_end_date", "<=", today),
            ("warranty_auto_closed_on", "=", False),
        ])
        if not projects:
            return True

        victor = self.env["res.users"].search(
            [("login", "=", WARRANTY_VICTOR_LOGIN)],
            limit=1,
        )
        activity_type = self.env.ref("mail.mail_activity_data_todo")
        project_model_id = self.env["ir.model"]._get_id("project.project")
        template = self.env.ref(
            "project_custom_extension.mail_template_warranty_completion"
        )

        for project in projects:
            recipients = (project.user_id | victor) if victor else project.user_id
            missing = []
            queued_email_addresses = set()
            email_addresses = {}
            if not project.user_id:
                missing.append(_("gerente del proyecto sin asignar"))
            for user in recipients:
                email_address = user.email.strip() if user.email else False
                email_addresses[user.id] = email_address
                if not email_address:
                    missing.append(user.display_name)

            values = {"warranty_auto_closed_on": today}
            if project.last_update_status != "done":
                values["last_update_status"] = "done"
            project.write(values)
            for user in recipients:
                self.env["mail.activity"].create({
                    "activity_type_id": activity_type.id,
                    "res_model_id": project_model_id,
                    "res_id": project.id,
                    "user_id": user.id,
                    "date_deadline": today,
                    "summary": _("Garantía finalizada"),
                    "note": _(
                        "La garantía del proyecto %(project)s finalizó el %(date)s.",
                        project=project.display_name,
                        date=fields.Date.to_string(today),
                    ),
                })
                email_address = email_addresses.get(user.id)
                if email_address and email_address.casefold() not in queued_email_addresses:
                    template.send_mail(
                        project.id,
                        force_send=False,
                        email_values={"email_to": email_address},
                    )
                    queued_email_addresses.add(email_address.casefold())
            if not victor:
                missing.append(WARRANTY_VICTOR_LOGIN)
            if missing:
                project.message_post(body=_(
                    "Cierre automático ejecutado. No fue posible enviar el correo "
                    "a: %(recipients)s.",
                    recipients=", ".join(missing),
                ))
        return True

    @api.model
    def _get_dashboard_health_configuration(self):
        parameters = self.env["ir.config_parameter"]
        configuration = {}
        for key, default_value in DASHBOARD_HEALTH_DEFAULTS.items():
            # These fixed keys are non-sensitive dashboard settings. The public
            # getter is restricted to Settings users, while this dashboard is
            # intentionally available to every Project user. Reading only the
            # whitelisted keys through Odoo's cached internal getter avoids
            # privilege elevation and never exposes arbitrary parameters.
            raw_value = (
                parameters._get_param(DASHBOARD_HEALTH_PARAMETERS[key])
                or default_value
            )
            try:
                configuration[key] = int(raw_value)
            except (TypeError, ValueError):
                configuration[key] = default_value

        weights = (
            configuration["progress_weight"],
            configuration["status_weight"],
            configuration["operations_weight"],
        )
        if (
            any(weight < 0 or weight > 100 for weight in weights)
            or sum(weights) != 100
        ):
            for key in ("progress_weight", "status_weight", "operations_weight"):
                configuration[key] = DASHBOARD_HEALTH_DEFAULTS[key]

        healthy_threshold = configuration["healthy_threshold"]
        attention_threshold = configuration["attention_threshold"]
        if not (
            0 <= attention_threshold < healthy_threshold <= 100
        ):
            configuration["healthy_threshold"] = DASHBOARD_HEALTH_DEFAULTS[
                "healthy_threshold"
            ]
            configuration["attention_threshold"] = DASHBOARD_HEALTH_DEFAULTS[
                "attention_threshold"
            ]
        return configuration

    @api.model
    def _get_dashboard_health(
        self,
        projects,
        task_domain,
        current_datetime,
        progress_by_project=None,
    ):
        if not projects:
            return {
                "score": False,
                "label": _("Sin datos"),
                "tone": "empty",
                "components": {
                    "progress": False,
                    "status": False,
                    "operations": False,
                },
            }

        configuration = self._get_dashboard_health_configuration()
        project_count = len(projects)
        progress_by_project = progress_by_project or (
            self._get_project_execution_progress_by_project(projects)
        )
        planned_progress = [
            progress_by_project[project.id]["percentage"]
            for project in projects
            if progress_by_project[project.id]["percentage"] is not False
        ]
        progress_score = (
            round(sum(planned_progress) / len(planned_progress), 1)
            if planned_progress
            else False
        )
        status_score = round(
            sum(
                DASHBOARD_STATUS_SCORES.get(project.last_update_status, 50)
                for project in projects
            )
            / project_count,
            1,
        )

        Task = self.env["project.task"]
        open_task_count = Task.search_count(task_domain)
        problem_task_domain = expression.AND([
            task_domain,
            expression.OR([
                [("priority", "=", "1")],
                [("date_deadline", "<", current_datetime)],
                [("state", "=", "04_waiting_normal")],
            ]),
        ])
        problem_task_count = Task.search_count(problem_task_domain)
        operations_score = (
            round(
                100 * (open_task_count - problem_task_count) / open_task_count,
                1,
            )
            if open_task_count
            else 100.0
        )

        weighted_components = [
            (progress_score, configuration["progress_weight"]),
            (status_score, configuration["status_weight"]),
            (operations_score, configuration["operations_weight"]),
        ]
        weighted_components = [
            (value, weight)
            for value, weight in weighted_components
            if value is not False
        ]
        effective_weight = sum(weight for _value, weight in weighted_components)
        if not effective_weight:
            weighted_components = [
                (value, 1)
                for value, _weight in weighted_components
            ]
            effective_weight = len(weighted_components)
        score = round(
            sum(value * weight for value, weight in weighted_components)
            / effective_weight
        ) if effective_weight else False
        if score is False:
            label = _("Sin datos")
            tone = "empty"
        elif score >= configuration["healthy_threshold"]:
            label = _("Saludable")
            tone = "success"
        elif score >= configuration["attention_threshold"]:
            label = _("En atención")
            tone = "warning"
        else:
            label = _("Crítica")
            tone = "danger"

        return {
            "score": score,
            "label": label,
            "tone": tone,
            "components": {
                "progress": progress_score,
                "status": status_score,
                "operations": operations_score,
            },
        }

    @api.model
    def get_project_detail_dashboard_filters(self, partner_id=False, project_id=False):
        """Return filter options and any valid persisted selection."""
        Project = self.env["project.project"]
        partner_groups = Project._read_group(
            [
                ("active", "=", True),
                ("partner_id", "!=", False),
            ],
            ["partner_id"],
            ["__count"],
        )
        partner_ids = sorted(
            partner.id for partner, _count in partner_groups if partner
        )
        partner_id = self._dashboard_integer_id(partner_id)
        if partner_id not in partner_ids:
            partner_id = False

        selected_partner = self.env["res.partner"].browse(partner_id)
        selected_project = Project.browse()
        project_id = self._dashboard_integer_id(project_id)
        if project_id:
            project_domain = [
                ("id", "=", project_id),
                ("active", "=", True),
            ]
            if partner_id:
                project_domain.append(("partner_id", "=", partner_id))
            selected_project = Project.search(project_domain, limit=1)

        return {
            "customer_ids": partner_ids,
            "selected_customer": {
                "id": selected_partner.id,
                "display_name": selected_partner.display_name,
            } if selected_partner else False,
            "selected_project": {
                "id": selected_project.id,
                "display_name": selected_project.display_name,
            } if selected_project else False,
        }

    @api.model
    def _empty_project_detail_dashboard_data(self):
        return {
            "project": False,
            "progress": False,
            "activities_by_state": [],
            "activity_states_by_scope": {
                "all": [],
                "main": [],
                "subtasks": [],
            },
            "sprints": [],
            "critical_activities": {
                "count": 0,
                "items": [],
            },
        }

    @api.model
    def _dashboard_integer_id(self, value):
        if value in (False, None, ""):
            return False
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @api.model
    def _empty_project_gantt_data(self):
        return {
            "project": False,
            "rows": [],
            "total": {
                "start_date": False,
                "end_date": False,
                "duration_days": False,
            },
            "timeline": {
                "start_date": False,
                "end_date": False,
                "today": fields.Date.to_string(fields.Date.context_today(self)),
            },
        }

    @api.model
    def _project_gantt_date(self, value, label):
        if value in (False, None, ""):
            return False
        try:
            result = fields.Date.to_date(value)
        except (TypeError, ValueError):
            raise ValidationError(
                _("La fecha de %(label)s no es válida.", label=label)
            )
        if not result:
            raise ValidationError(
                _("La fecha de %(label)s no es válida.", label=label)
            )
        return result

    @api.model
    def _project_gantt_task_date(self, value):
        if not value:
            return False
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        timestamp = fields.Datetime.to_datetime(value)
        return fields.Datetime.context_timestamp(self, timestamp).date()

    @api.model
    def _project_gantt_duration(self, start_date, end_date):
        if not start_date or not end_date:
            return False
        return (end_date - start_date).days + 1

    @api.model
    def _project_gantt_next_month(self, value):
        month_start = value.replace(day=1)
        return (month_start + timedelta(days=32)).replace(day=1)

    def action_open_project_gantt(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.client",
            "name": _("Cronograma de proyecto"),
            "tag": "project_custom_extension.ProjectGantt",
            "target": "current",
            "context": {"project_id": self.id},
        }

    @api.model
    def get_project_gantt_data(
        self,
        project_id=False,
        filter_start_date=False,
        filter_end_date=False,
    ):
        """Return the accessible active tasks for the project Gantt."""
        project_id = self._dashboard_integer_id(project_id)
        if project_id is None or not project_id:
            return self._empty_project_gantt_data()

        filter_start_date = self._project_gantt_date(
            filter_start_date,
            _("inicio"),
        )
        filter_end_date = self._project_gantt_date(
            filter_end_date,
            _("fin"),
        )
        if (
            filter_start_date
            and filter_end_date
            and filter_start_date > filter_end_date
        ):
            raise ValidationError(
                _("La fecha de inicio no puede ser posterior a la fecha fin.")
            )

        Project = self.env["project.project"]
        Task = self.env["project.task"]
        project = Project.search([
            ("id", "=", project_id),
            ("active", "=", True),
        ], limit=1)
        if not project:
            return self._empty_project_gantt_data()

        tasks = Task.search([
            ("project_id", "=", project.id),
            ("active", "=", True),
        ], order="sequence, name, id")
        task_by_id = {task.id: task for task in tasks}
        parent_by_id = {}
        children_by_parent = {}
        task_dates = {}
        for task in tasks:
            parent_id = task.parent_id.id if task.parent_id.id in task_by_id else False
            parent_by_id[task.id] = parent_id
            children_by_parent.setdefault(parent_id, []).append(task)
            task_dates[task.id] = (
                self._project_gantt_task_date(task.planned_date_begin),
                self._project_gantt_task_date(task.date_deadline),
            )

        def is_in_requested_range(task_id):
            if not filter_start_date and not filter_end_date:
                return True
            start_date, end_date = task_dates[task_id]
            if not start_date or not end_date:
                return True
            if filter_start_date and end_date < filter_start_date:
                return False
            if filter_end_date and start_date > filter_end_date:
                return False
            return True

        visible_ids = {
            task_id for task_id in task_by_id if is_in_requested_range(task_id)
        }
        for task_id in tuple(visible_ids):
            parent_id = parent_by_id[task_id]
            while parent_id and parent_id not in visible_ids:
                visible_ids.add(parent_id)
                parent_id = parent_by_id[parent_id]

        task_start_dates = [
            dates[0] for dates in task_dates.values() if dates[0]
        ]
        task_end_dates = [
            dates[1] for dates in task_dates.values() if dates[1]
        ]
        if project.date_start and project.date:
            full_start_date = project.date_start
            full_end_date = project.date
        else:
            start_candidates = task_start_dates + (
                [project.date_start] if project.date_start else []
            )
            end_candidates = task_end_dates + (
                [project.date] if project.date else []
            )
            full_start_date = min(start_candidates) if start_candidates else False
            full_end_date = max(end_candidates) if end_candidates else False
        if full_start_date and not full_end_date:
            full_end_date = full_start_date
        elif full_end_date and not full_start_date:
            full_start_date = full_end_date

        today = fields.Date.context_today(self)
        fallback_start_date = today.replace(day=1)
        fallback_end_date = self._project_gantt_next_month(
            fallback_start_date
        ) - timedelta(days=1)
        timeline_start_date = (
            filter_start_date
            or full_start_date
            or filter_end_date
            or fallback_start_date
        )
        timeline_end_date = (
            filter_end_date
            or full_end_date
            or filter_start_date
            or fallback_end_date
        )
        if timeline_start_date > timeline_end_date:
            if filter_end_date and not filter_start_date:
                timeline_start_date = timeline_end_date
            else:
                timeline_end_date = timeline_start_date

        root_color_indexes = {}
        rows = []

        def append_rows(parent_id=False, depth=0, root_id=False):
            for task in children_by_parent.get(parent_id, []):
                if task.id not in visible_ids:
                    continue
                current_root_id = root_id or task.id
                if current_root_id not in root_color_indexes:
                    root_task = task_by_id[current_root_id]
                    root_color_indexes[current_root_id] = (
                        root_task.color
                        if root_task.color is not False
                        else len(root_color_indexes)
                    )
                start_date, end_date = task_dates[task.id]
                visible_children = [
                    child for child in children_by_parent.get(task.id, [])
                    if child.id in visible_ids
                ]
                rows.append({
                    "id": task.id,
                    "name": task.display_name,
                    "parent_id": task.parent_id.id if task.parent_id.id in task_by_id else False,
                    "depth": depth,
                    "has_children": bool(visible_children),
                    "sequence": task.sequence,
                    "start_date": fields.Date.to_string(start_date) if start_date else False,
                    "end_date": fields.Date.to_string(end_date) if end_date else False,
                    "duration_days": self._project_gantt_duration(start_date, end_date),
                    "root_id": current_root_id,
                    "color_index": root_color_indexes[current_root_id],
                })
                append_rows(task.id, depth + 1, current_root_id)

        append_rows()
        full_duration = self._project_gantt_duration(
            full_start_date,
            full_end_date,
        )
        return {
            "project": {
                "id": project.id,
                "name": project.display_name,
                "customer_name": project.partner_id.display_name or _(
                    "Sin cliente"
                ),
                "start_date": fields.Date.to_string(project.date_start)
                if project.date_start else False,
                "end_date": fields.Date.to_string(project.date)
                if project.date else False,
            },
            "rows": rows,
            "total": {
                "start_date": fields.Date.to_string(full_start_date)
                if full_start_date else False,
                "end_date": fields.Date.to_string(full_end_date)
                if full_end_date else False,
                "duration_days": full_duration,
            },
            "timeline": {
                "start_date": fields.Date.to_string(timeline_start_date),
                "end_date": fields.Date.to_string(timeline_end_date),
                "today": fields.Date.to_string(today),
            },
        }

    @api.model
    def get_project_detail_dashboard_data(self, project_id=False, partner_id=False):
        """Return data for one active project, scoped to the selected customer."""
        Project = self.env["project.project"]
        Task = self.env["project.task"]
        project_id = self._dashboard_integer_id(project_id)
        partner_id = self._dashboard_integer_id(partner_id)
        if project_id is None or partner_id is None:
            return self._empty_project_detail_dashboard_data()
        if not project_id:
            return self._empty_project_detail_dashboard_data()

        project_domain = [
            ("id", "=", project_id),
            ("active", "=", True),
        ]
        if partner_id:
            project_domain.append(("partner_id", "=", partner_id))
        project = Project.search(project_domain, limit=1)
        if not project:
            return self._empty_project_detail_dashboard_data()

        status_labels = dict(
            Project._fields["last_update_status"]._description_selection(self.env)
        )
        task_state_labels = dict(
            Task._fields["state"]._description_selection(self.env)
        )
        project_tasks = Task.search([
            ("project_id", "=", project.id),
            ("active", "=", True),
        ])
        progress_task_domain = [
            ("project_id", "=", project.id),
            ("active", "=", True),
            ("display_in_project", "=", True),
        ]
        closed_states = ["1_done", "1_canceled"]
        progress_metrics = []
        for key, title, extra_domain in (
            (
                "total",
                _("Total de actividades"),
                [],
            ),
            (
                "completed",
                _("Completadas"),
                [("state", "in", closed_states)],
            ),
            (
                "open",
                _("Pendientes"),
                [("state", "in", Task.OPEN_STATES)],
            ),
        ):
            domain = expression.AND([progress_task_domain, extra_domain])
            count = {
                "total": project.task_count,
                "completed": project.task_count - project.open_task_count,
                "open": project.open_task_count,
            }[key]
            progress_metrics.append({
                "key": key,
                "title": title,
                "count": count,
                "model": "project.task",
                "domain": domain,
            })

        main_tasks = Task.search(
            [("project_id", "=", project.id), ("active", "=", True), ("parent_id", "=", False)],
            order="sequence, name, id",
        )
        execution_progress = self._get_project_execution_progress(
            project,
            project_tasks,
        )
        phase_progress = execution_progress["phases"]
        parent_progress = [{
            "id": item["task"].id,
            "name": item["task"].display_name,
            "percentage": round(item["percentage"] * 100, 1),
            "completed_subtasks": item["completed_count"],
            "total_subtasks": item["total_count"],
            "duration_days": item["duration_days"],
            "weight_percentage": round(
                item["duration_days"] * 100
                / sum(value["duration_days"] for value in phase_progress),
                1,
            ) if phase_progress else 0,
            "model": "project.task",
            "domain": [
                ("project_id", "=", project.id),
                ("active", "=", True),
                ("id", "child_of", item["task"].id),
            ],
        } for item in phase_progress]
        progress_mode = (
            "parents"
            if parent_progress and len(main_tasks) <= 10
            else "general"
        )

        activity_states_by_scope = {}
        for scope, scope_domain in (
            ("all", []),
            ("main", [("parent_id", "=", False)]),
            ("subtasks", [("parent_id", "!=", False)]),
        ):
            scope_tasks = project_tasks.filtered(
                lambda task: scope == "all"
                or (scope == "main" and not task.parent_id)
                or (scope == "subtasks" and bool(task.parent_id))
            )
            scope_counts = {}
            for task in scope_tasks:
                scope_counts[task.state] = scope_counts.get(task.state, 0) + 1
            activity_states_by_scope[scope] = [
                {
                    "key": state,
                    "label": label,
                    "count": scope_counts.get(state, 0),
                    "model": "project.task",
                    "domain": [
                        ("project_id", "=", project.id),
                        ("active", "=", True),
                        ("state", "=", state),
                        *scope_domain,
                    ],
                }
                for state, label in task_state_labels.items()
                if scope_counts.get(state, 0)
            ]
        activities_by_state = activity_states_by_scope["all"]

        sprints = self.env["project.sprint"].search(
            [("project_id", "=", project.id)],
            order="sequence, name, id",
        )
        sprint_summary = {
            sprint.id: {"total": 0, "state_counts": {}}
            for sprint in sprints
        }
        sprint_summary[False] = {"total": 0, "state_counts": {}}
        for task in project_tasks:
            summary = sprint_summary.setdefault(
                task.sprint_id.id or False,
                {"total": 0, "state_counts": {}},
            )
            summary["total"] += 1
            summary["state_counts"][task.state] = (
                summary["state_counts"].get(task.state, 0) + 1
            )

        def serialize_sprint_summary(sprint_id):
            summary = sprint_summary[sprint_id]
            return {
                "total": summary["total"],
                "states": [{
                    "key": state,
                    "label": task_state_labels.get(state, state),
                    "count": summary["state_counts"][state],
                } for state in task_state_labels
                    if summary["state_counts"].get(state)],
            }

        sprint_data = [{
            "id": sprint.id,
            "name": sprint.display_name,
            "sequence": sprint.sequence,
            **serialize_sprint_summary(sprint.id),
        } for sprint in sprints]
        sprint_data.append({
            "id": False,
            "name": _("Sin Sprint"),
            "sequence": 2147483647,
            **serialize_sprint_summary(False),
        })

        current_datetime = fields.Datetime.to_string(fields.Datetime.now())
        critical_domain = [
            ("project_id", "=", project.id),
            ("active", "=", True),
            ("state", "in", Task.OPEN_STATES),
            ("date_deadline", "<", current_datetime),
        ]
        critical_tasks = Task.search(
            critical_domain,
            order="date_deadline asc, id asc",
            limit=3,
        )
        critical_items = [{
            "id": task.id,
            "name": task.display_name,
            "deadline": fields.Date.to_string(task.date_deadline.date()),
        } for task in critical_tasks]

        return {
            "project": {
                "id": project.id,
                "name": project.display_name,
                "customer_name": project.partner_id.display_name or _(
                    "Sin cliente"
                ),
                "responsible_name": project.user_id.display_name or _(
                    "Sin asignar"
                ),
                "start_date": fields.Date.to_string(project.date_start)
                if project.date_start else False,
                "end_date": fields.Date.to_string(project.date)
                if project.date else False,
                "status": project.last_update_status,
                "status_label": status_labels.get(
                    project.last_update_status,
                    project.last_update_status,
                ),
            },
            "progress": {
                "mode": progress_mode,
                "percentage": execution_progress["percentage"],
                "planned": execution_progress["percentage"] is not False,
                "total_tasks": project.task_count,
                "completed_tasks": project.task_count - project.open_task_count,
                "open_tasks": project.open_task_count,
                "metrics": progress_metrics,
                "parent_tasks": parent_progress,
            },
            "activities_by_state": activities_by_state,
            "activity_states_by_scope": activity_states_by_scope,
            "sprints": sprint_data,
            "critical_activities": {
                "count": Task.search_count(critical_domain),
                "items": critical_items,
            },
        }

    @api.model
    def get_project_sprint_dashboard_data(
        self,
        project_id=False,
        sprint_filter="all",
        limit=20,
    ):
        """Return a selected sprint's task preview and the full task domain."""
        Project = self.env["project.project"]
        Task = self.env["project.task"]
        project_id = self._dashboard_integer_id(project_id)
        if not project_id:
            return {"count": 0, "tasks": [], "domain": []}
        project = Project.search([
            ("id", "=", project_id),
            ("active", "=", True),
        ], limit=1)
        if not project:
            return {"count": 0, "tasks": [], "domain": []}

        domain = [
            ("project_id", "=", project.id),
            ("active", "=", True),
        ]
        if sprint_filter == "none":
            domain.append(("sprint_id", "=", False))
        elif sprint_filter != "all":
            sprint_id = self._dashboard_integer_id(sprint_filter)
            sprint = self.env["project.sprint"].search([
                ("id", "=", sprint_id or 0),
                ("project_id", "=", project.id),
            ], limit=1)
            if not sprint:
                return {"count": 0, "tasks": [], "domain": []}
            domain.append(("sprint_id", "=", sprint.id))

        try:
            limit = min(100, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 20
        count = Task.search_count(domain)
        tasks = Task.search(
            domain,
            order="sprint_sequence_order, hierarchical_priority_order, sequence, name, id",
            limit=limit,
        )
        state_labels = dict(
            Task._fields["state"]._description_selection(self.env)
        )
        return {
            "count": count,
            "domain": domain,
            "tasks": [{
                "id": task.id,
                "name": task.display_name,
                "state": task.state,
                "state_label": state_labels.get(task.state, task.state),
                "sprint_name": task.sprint_id.display_name or _("Sin Sprint"),
                "hierarchical_priority": task.hierarchical_priority,
            } for task in tasks],
        }

    @api.model
    def get_project_dashboard_data(self, partner_id=False):
        """Return the complete project dashboard payload for the current user."""
        Project = self.env["project.project"]
        Task = self.env["project.task"]
        base_project_domain = [
            ("active", "=", True),
            ("last_update_status", "!=", "done"),
        ]

        partner_groups = Project._read_group(
            base_project_domain + [("partner_id", "!=", False)],
            ["partner_id"],
            ["__count"],
        )
        available_partners = self.env["res.partner"].concat(
            *(partner for partner, _count in partner_groups)
        )
        available_partner_ids = set(available_partners.ids)
        try:
            partner_id = int(partner_id) if partner_id else False
        except (TypeError, ValueError):
            partner_id = False
        if partner_id not in available_partner_ids:
            partner_id = False

        project_domain = list(base_project_domain)
        if partner_id:
            project_domain.append(("partner_id", "=", partner_id))
        projects = Project.search(project_domain)

        status_labels = dict(
            Project._fields["last_update_status"]._description_selection(self.env)
        )
        progress_by_project = self._get_project_execution_progress_by_project(
            projects
        )
        project_rows = [{
            "id": project.id,
            "name": project.display_name,
            "customer_name": project.partner_id.display_name or "",
            "progress": progress_by_project[project.id]["percentage"],
            "status": project.last_update_status,
            "status_label": status_labels.get(project.last_update_status, ""),
            "deadline": fields.Date.to_string(project.date) if project.date else False,
        } for project in projects]
        project_rows.sort(key=lambda project: (
            DASHBOARD_STATUS_ORDER.get(project["status"], 99),
            project["progress"] is False,
            project["progress"] or 0,
            project["name"].lower(),
        ))

        kpi_definitions = (
            ("active", _("Proyectos Activos"), "fa-folder-open", []),
            (
                "on_track",
                _("En Tiempo"),
                "fa-clock-o",
                [("last_update_status", "=", "on_track")],
            ),
            (
                "at_risk",
                _("En Riesgo"),
                "fa-exclamation-triangle",
                [("last_update_status", "=", "at_risk")],
            ),
            (
                "off_track",
                _("Atrasados"),
                "fa-clock-o",
                [("last_update_status", "=", "off_track")],
            ),
        )
        kpis = []
        for key, title, icon, extra_domain in kpi_definitions:
            domain = expression.AND([project_domain, extra_domain])
            kpis.append({
                "key": key,
                "title": title,
                "icon": icon,
                "count": Project.search_count(domain),
                "model": "project.project",
                "domain": domain,
            })

        task_domain = [
            ("active", "=", True),
            ("project_id", "!=", False),
            ("project_id.active", "=", True),
            ("project_id.last_update_status", "!=", "done"),
            ("state", "in", Task.OPEN_STATES),
        ]
        if partner_id:
            task_domain.append(("project_id.partner_id", "=", partner_id))

        current_datetime = fields.Datetime.to_string(fields.Datetime.now())
        upcoming_datetime = fields.Datetime.to_string(
            fields.Datetime.now() + timedelta(days=7)
        )
        alert_definitions = (
            (
                "critical",
                _("Actividades Críticas"),
                _("Requieren atención inmediata"),
                "fa-exclamation-triangle",
                [("date_deadline", "<", current_datetime)],
            ),
            (
                "upcoming",
                _("Próximas a Vencer"),
                _("En los próximos 7 días"),
                "fa-calendar",
                [
                    ("date_deadline", ">=", current_datetime),
                    ("date_deadline", "<=", upcoming_datetime),
                ],
            ),
            (
                "blocked",
                _("Bloqueos Activos"),
                _("Impedimentos que afectan el progreso"),
                "fa-lock",
                [("state", "=", "04_waiting_normal")],
            ),
            (
                "no_deadline",
                _("Tareas sin fecha"),
                _("No tienen fecha límite"),
                "fa-calendar-o",
                [("date_deadline", "=", False)],
            ),
        )
        alerts = []
        for key, title, subtitle, icon, extra_domain in alert_definitions:
            domain = expression.AND([task_domain, extra_domain])
            alerts.append({
                "key": key,
                "title": title,
                "subtitle": subtitle,
                "icon": icon,
                "count": Task.search_count(domain),
                "model": "project.task",
                "domain": domain,
            })

        selected_partner = available_partners.filtered(
            lambda partner: partner.id == partner_id
        )
        return {
            "customer_ids": sorted(available_partner_ids),
            "selected_customer": {
                "id": selected_partner.id,
                "display_name": selected_partner.display_name,
            } if selected_partner else False,
            "kpis": kpis,
            "projects": project_rows,
            "project_action": {
                "title": _("Proyectos Activos"),
                "model": "project.project",
                "domain": project_domain,
            },
            "alerts": alerts,
            "health": self._get_dashboard_health(
                projects,
                task_domain,
                current_datetime,
                progress_by_project=progress_by_project,
            ),
        }
