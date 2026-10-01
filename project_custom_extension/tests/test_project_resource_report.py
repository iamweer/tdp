from datetime import date, datetime, timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProjectResourceReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.manager = new_test_user(
            cls.env,
            login="resource_report_manager",
            groups="project.group_project_manager",
        )
        cls.project_user = new_test_user(
            cls.env,
            login="resource_report_user",
            groups="project.group_project_user",
        )
        cls.alice = new_test_user(
            cls.env,
            login="resource_report_alice",
            name="Alice Recurso",
            email="alice.personal@example.com",
            groups="project.group_project_user",
        )
        cls.bob = new_test_user(
            cls.env,
            login="resource_report_bob",
            name="Bob Recurso",
            email="bob@example.com",
            groups="project.group_project_user",
        )
        cls.env["hr.employee"].create({
            "name": "Alice Recurso",
            "user_id": cls.alice.id,
            "identification_id": "1020304050",
            "work_email": "alice@tdp.example.com",
            "company_type": "abi",
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "Cliente informe recursos",
            "is_company": True,
        })
        today = fields.Date.context_today(cls.Project)
        cls.project = cls.Project.create({
            "name": "Proyecto informe recursos",
            "partner_id": cls.customer.id,
            "user_id": cls.manager.id,
            "company_type": "tdp",
            "date_start": today - timedelta(days=30),
            "date": today + timedelta(days=30),
            "warranty_start_date": today - timedelta(days=1),
            "warranty_end_date": today + timedelta(days=60),
        })
        cls.empty_project = cls.Project.create({
            "name": "Proyecto sin colaboradores",
        })
        phase = cls.Task.create({
            "name": "Fase",
            "project_id": cls.project.id,
            "user_ids": [Command.set(cls.alice.ids)],
            "planned_date_begin": datetime.combine(today - timedelta(days=10), datetime.min.time()),
            "date_deadline": datetime.combine(today + timedelta(days=10), datetime.min.time()),
        })
        cls.Task.create({
            "name": "Subtarea de Bob",
            "project_id": cls.project.id,
            "parent_id": phase.id,
            "user_ids": [Command.set((cls.alice | cls.bob).ids)],
        })

    def _rows(self, project):
        data = self.Project.with_user(self.manager).get_project_resource_report_data()
        return [row for row in data["rows"] if row["project_id"] == project.id]

    def test_one_row_per_collaborator_across_tasks_and_subtasks(self):
        rows = self._rows(self.project)
        self.assertEqual(
            [row["collaborator_id"] for row in rows],
            [self.alice.id, self.bob.id],
        )

    def test_project_values(self):
        row = self._rows(self.project)[0]
        self.assertEqual(row["customer_name"], self.customer.display_name)
        self.assertEqual(row["pm_id"], self.manager.id)
        self.assertEqual(row["project_company_type"], "tdp")
        self.assertEqual(row["warranty_status"], "active")
        self.assertEqual(
            row["progress"],
            self.Project._get_project_execution_progress(self.project)["percentage"],
        )

    def test_collaborator_data_comes_from_employee(self):
        alice_row, bob_row = self._rows(self.project)
        self.assertEqual(alice_row["identification"], "1020304050")
        self.assertEqual(alice_row["email"], "alice@tdp.example.com")
        self.assertEqual(alice_row["collaborator_company_type"], "abi")
        self.assertEqual(bob_row["identification"], "")
        self.assertEqual(bob_row["email"], "bob@example.com")
        self.assertFalse(bob_row["collaborator_company_type"])

    def test_project_without_tasks_has_single_empty_row(self):
        rows = self._rows(self.empty_project)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["collaborator_id"])
        self.assertFalse(rows[0]["warranty_status"])

    def test_archived_tasks_do_not_count(self):
        self.Task.search([
            ("project_id", "=", self.project.id),
            ("user_ids", "in", self.bob.id),
        ]).action_archive()
        rows = self._rows(self.project)
        self.assertEqual([row["collaborator_id"] for row in rows], [self.alice.id])

    def test_archived_users_are_flagged_inactive(self):
        self.bob.action_archive()
        rows = self._rows(self.project)
        self.assertEqual(
            [(row["collaborator_id"], row["collaborator_active"]) for row in rows],
            [(self.alice.id, True), (self.bob.id, False)],
        )

    def test_client_portal_and_odoobot_users_are_not_collaborators(self):
        client = new_test_user(
            self.env,
            login="resource_report_client",
            name="Cliente Recurso",
            groups="project_custom_extension.group_project_client",
        )
        portal = new_test_user(
            self.env,
            login="resource_report_portal",
            name="Portal Recurso",
            groups="base.group_portal",
        )
        self.Task.create({
            "name": "Tarea con clientes",
            "project_id": self.project.id,
            "user_ids": [Command.set(
                (client | portal | self.env.ref("base.user_root")).ids
            )],
        })
        rows = self._rows(self.project)
        self.assertEqual(
            [row["collaborator_id"] for row in rows],
            [self.alice.id, self.bob.id],
        )

    def test_warranty_status(self):
        today = date(2026, 6, 15)
        method = self.Project._get_resource_report_warranty_status
        self.project.write({
            "warranty_start_date": date(2026, 7, 1),
            "warranty_end_date": date(2026, 12, 31),
        })
        self.assertEqual(method(self.project, today), "upcoming")
        self.project.write({
            "warranty_start_date": date(2026, 1, 1),
            "warranty_end_date": date(2026, 6, 1),
        })
        self.assertEqual(method(self.project, today), "expired")

    def test_only_managers_can_read_report(self):
        with self.assertRaises(AccessError):
            self.Project.with_user(self.project_user).get_project_resource_report_data()
