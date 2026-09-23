from datetime import timedelta

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
    def _get_dashboard_health(self, projects, task_domain, current_datetime):
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
        progress_score = round(
            sum(projects.mapped("task_completion_percentage"))
            * 100
            / project_count,
            1,
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

        score = round(
            (
                progress_score * configuration["progress_weight"]
                + status_score * configuration["status_weight"]
                + operations_score * configuration["operations_weight"]
            )
            / 100
        )
        if score >= configuration["healthy_threshold"]:
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
            progress_task_domain + [("parent_id", "=", False)],
            order="sequence, name, id",
        )
        parent_tasks = main_tasks.filtered(lambda task: task.subtask_count > 0)
        parent_progress = [{
            "id": task.id,
            "name": task.display_name,
            "percentage": round(task.subtask_completion_percentage * 100, 1),
            "completed_subtasks": task.closed_subtask_count,
            "total_subtasks": task.subtask_count,
            "model": "project.task",
            "domain": [
                ("project_id", "=", project.id),
                ("active", "=", True),
                ("parent_id", "=", task.id),
            ],
        } for task in parent_tasks]
        progress_mode = (
            "parents"
            if parent_progress and len(main_tasks) <= 10
            else "general"
        )

        state_counts = {state: 0 for state in task_state_labels}
        for task in project_tasks:
            state_counts[task.state] = state_counts.get(task.state, 0) + 1

        activities_by_state = [
            {
                "key": state,
                "label": label,
                "count": state_counts.get(state, 0),
                "model": "project.task",
                "domain": [
                    ("project_id", "=", project.id),
                    ("active", "=", True),
                    ("state", "=", state),
                ],
            }
            for state, label in task_state_labels.items()
            if state_counts.get(state, 0)
        ]

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
                "percentage": round(project.task_completion_percentage * 100, 1),
                "total_tasks": project.task_count,
                "completed_tasks": project.task_count - project.open_task_count,
                "open_tasks": project.open_task_count,
                "metrics": progress_metrics,
                "parent_tasks": parent_progress,
            },
            "activities_by_state": activities_by_state,
            "critical_activities": {
                "count": Task.search_count(critical_domain),
                "items": critical_items,
            },
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
        project_rows = [{
            "id": project.id,
            "name": project.display_name,
            "customer_name": project.partner_id.display_name or "",
            "progress": round(project.task_completion_percentage * 100, 1),
            "status": project.last_update_status,
            "status_label": status_labels.get(project.last_update_status, ""),
            "deadline": fields.Date.to_string(project.date) if project.date else False,
        } for project in projects]
        project_rows.sort(key=lambda project: (
            DASHBOARD_STATUS_ORDER.get(project["status"], 99),
            project["progress"],
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
            ),
        }
