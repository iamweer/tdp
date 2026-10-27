from datetime import datetime, time, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProjectUiTours(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.context_today(cls.env["project.project"])

        def moment(days):
            # Midday avoids moving to another day in the user's timezone.
            return datetime.combine(today + timedelta(days=days), time(12))

        partner = cls.env["res.partner"].create({"name": "Cliente Tour UI"})
        cls.project = cls.env["project.project"].create({
            "name": "Proyecto Tour UI",
            "partner_id": partner.id,
            "date_start": today - timedelta(days=30),
            "date": today + timedelta(days=70),
        })
        cls.project.write({"last_update_status": "at_risk"})
        Task = cls.env["project.task"]
        phase = Task.create({
            "name": "Fase Tour",
            "project_id": cls.project.id,
            "project_weight": 100,
            "planned_date_begin": moment(-30),
            "date_deadline": moment(60),
        })
        for name, start, end in (
            ("Tarea retrasada", -20, -5),
            ("Tarea en riesgo", -2, 2),
            ("Tarea a tiempo", 5, 20),
        ):
            Task.create({
                "name": name,
                "project_id": cls.project.id,
                "parent_id": phase.id,
                "planned_date_begin": moment(start),
                "date_deadline": moment(end),
            })

    def test_project_dashboard_tour(self):
        self.start_tour(
            "/odoo/action-project_custom_extension.action_project_dashboard",
            "project_custom_extension_dashboard_tour",
            login="admin",
        )

    def test_project_timesheet_grid_shows_today_tour(self):
        admin = self.env.ref("base.user_admin")
        employee = admin.employee_id or self.env["hr.employee"].create({
            "name": "Empleado Tour UI",
            "user_id": admin.id,
        })
        self.env["project.task.time.entry"].create({
            "task_id": self.env["project.task"].search(
                [("project_id", "=", self.project.id)], limit=1
            ).id,
            "employee_id": employee.id,
            "unit_amount": 3,
        })
        # Narrower than a whole month, like a laptop screen.
        self.browser_size = "1100x768"
        self.start_tour(
            "/odoo/action-project_custom_extension.action_project_timesheet_grid",
            "project_custom_extension_timesheet_grid_tour",
            login="admin",
        )

    def test_project_detail_dashboard_and_gantt_tour(self):
        self.start_tour(
            "/odoo/action-project_custom_extension.action_project_detail_dashboard",
            "project_custom_extension_detail_gantt_tour",
            login="admin",
        )
