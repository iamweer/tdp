from datetime import date

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProjectTaskTimeEntry(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Entry = cls.env["project.task.time.entry"]
        cls.manager = new_test_user(
            cls.env,
            login="time_entry_manager",
            name="Gerente Horas",
            groups="project.group_project_manager",
        )
        cls.alice = new_test_user(
            cls.env,
            login="time_entry_alice",
            name="Alice Horas",
            groups="project.group_project_user",
        )
        cls.bob = new_test_user(
            cls.env,
            login="time_entry_bob",
            name="Bob Horas",
            groups="project.group_project_user",
        )
        cls.client = new_test_user(
            cls.env,
            login="time_entry_client",
            name="Cliente Horas",
            groups="project_custom_extension.group_project_client",
        )
        Employee = cls.env["hr.employee"]
        cls.manager_employee = Employee.create({
            "name": "Gerente Horas",
            "user_id": cls.manager.id,
            "company_type": "tdp",
        })
        cls.alice_employee = Employee.create({
            "name": "Alice Horas",
            "user_id": cls.alice.id,
            "company_type": "tdp",
        })
        cls.bob_employee = Employee.create({
            "name": "Bob Horas",
            "user_id": cls.bob.id,
            "company_type": "abi",
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "Cliente registro horas",
            "is_company": True,
        })
        cls.client.partner_id.parent_id = cls.customer
        cls.project = cls.env["project.project"].create({
            "name": "Proyecto horas",
            "partner_id": cls.customer.id,
            "user_id": cls.manager.id,
        })
        cls.other_project = cls.env["project.project"].create({
            "name": "Proyecto horas B",
            "user_id": cls.manager.id,
        })
        cls.task = cls.env["project.task"].create({
            "name": "Tarea con horas",
            "project_id": cls.project.id,
            "user_ids": [Command.set([cls.alice.id, cls.bob.id])],
        })
        cls.other_task = cls.env["project.task"].create({
            "name": "Tarea con horas B",
            "project_id": cls.other_project.id,
            "user_ids": [Command.set([cls.bob.id])],
        })

    def _entry(self, user, **values):
        return self.Entry.with_user(user).create({
            "task_id": self.task.id,
            "unit_amount": 2.0,
            **values,
        })

    def test_defaults_for_project_user(self):
        entry = self._entry(self.alice, name="Análisis")
        self.assertEqual(entry.employee_id, self.alice_employee)
        self.assertEqual(entry.date, fields.Date.context_today(entry))
        self.assertEqual(entry.project_id, self.project)
        self.assertEqual(entry.partner_id, self.customer)
        self.assertEqual(entry.company_type, "tdp")
        self.assertFalse(entry.with_user(self.alice).can_choose_employee)

    def test_manager_defaults_to_task_assignee(self):
        entry = self._entry(self.manager)
        self.assertEqual(entry.employee_id, self.alice_employee)
        self.assertTrue(entry.with_user(self.manager).can_choose_employee)

    def test_task_form_line_defaults(self):
        with Form(self.task.with_user(self.alice)) as task_form:
            with task_form.time_entry_ids.new() as line:
                self.assertEqual(line.employee_id, self.alice_employee)
                self.assertEqual(line.date, fields.Date.context_today(self.task))
                line.name = "Desarrollo"
                line.unit_amount = 1.5
        self.assertEqual(self.task.time_entry_ids.employee_id, self.alice_employee)
        self.assertEqual(self.task.with_user(self.alice).time_spent_hours, 1.5)

    def test_user_cannot_log_hours_for_others(self):
        with self.assertRaises(AccessError):
            self._entry(self.alice, employee_id=self.bob_employee.id)
        entry = self._entry(self.alice)
        with self.assertRaises(AccessError):
            entry.with_user(self.alice).write({"employee_id": self.bob_employee.id})

    def test_manager_can_log_hours_for_anyone(self):
        entry = self._entry(self.manager, employee_id=self.bob_employee.id)
        self.assertEqual(entry.employee_id, self.bob_employee)
        entry.with_user(self.manager).write({"employee_id": self.alice_employee.id})
        self.assertEqual(entry.user_id, self.alice)

    def test_user_only_sees_own_entries(self):
        alice_entry = self._entry(self.alice)
        bob_entry = self._entry(self.bob)
        visible = self.Entry.with_user(self.alice).search([])
        self.assertEqual(visible, alice_entry)
        with self.assertRaises(AccessError):
            bob_entry.with_user(self.alice).unit_amount = 4
        self.assertEqual(self.Entry.with_user(self.manager).search([]), alice_entry | bob_entry)

    def test_user_cannot_log_hours_on_hidden_task(self):
        with self.assertRaises(AccessError):
            self.Entry.with_user(self.alice).create({
                "task_id": self.other_task.id,
                "unit_amount": 1,
            })

    def test_client_has_no_access(self):
        self._entry(self.alice)
        with self.assertRaises(AccessError):
            self.Entry.with_user(self.client).search([])
        with self.assertRaises(AccessError):
            self._entry(self.client, employee_id=self.alice_employee.id)
        with self.assertRaises(AccessError):
            self.Entry.with_user(self.client).get_time_grid_data(
                "2026-01-05", "2026-01-11"
            )
        view = self.env["project.task"].with_user(self.client).get_view(
            self.env.ref("project.view_task_form2").id, "form"
        )
        self.assertNotIn("time_entry_ids", view["arch"])

    def test_hours_validation(self):
        with self.assertRaises(ValidationError):
            self._entry(self.alice, unit_amount=0)
        with self.assertRaises(ValidationError):
            self._entry(self.alice, unit_amount=25)

    def _grid_entries(self):
        self._entry(self.alice, date=date(2026, 1, 5), unit_amount=8)
        self._entry(self.alice, date=date(2026, 1, 6), unit_amount=3)
        self._entry(self.bob, date=date(2026, 1, 5), unit_amount=2)
        self.Entry.with_user(self.bob).create({
            "task_id": self.other_task.id,
            "date": date(2026, 1, 7),
            "unit_amount": 1.5,
        })

    def test_grid_by_employee(self):
        self._grid_entries()
        data = self.Entry.with_user(self.manager).get_time_grid_data(
            "2026-01-05", "2026-01-11", "employee"
        )
        self.assertEqual(len(data["days"]), 7)
        self.assertTrue(data["days"][5]["is_weekend"])
        self.assertTrue(data["is_manager"])
        self.assertEqual(data["totals"]["total"], 14.5)
        self.assertEqual(data["totals"]["daily"]["2026-01-05"], 10)

        groups = {group["name"]: group for group in data["groups"]}
        self.assertIn("Gerente Horas", groups)
        alice = groups["Alice Horas"]
        self.assertEqual(alice["total"], 11)
        self.assertEqual(alice["company_type"], "tdp")
        self.assertEqual(
            [line["name"] for line in alice["lines"]], ["Proyecto horas"]
        )
        self.assertEqual(alice["expected"], 40)
        self.assertEqual(alice["balance"], -29)
        self.assertEqual(
            alice["missing_days"], ["2026-01-07", "2026-01-08", "2026-01-09"]
        )
        bob = groups["Bob Horas"]
        self.assertEqual(
            {line["name"]: line["total"] for line in bob["lines"]},
            {"Proyecto horas": 2, "Proyecto horas B": 1.5},
        )

    def test_grid_by_project_and_company(self):
        self._grid_entries()
        data = self.Entry.with_user(self.manager).get_time_grid_data(
            "2026-01-05", "2026-01-11", "project"
        )
        groups = {group["name"]: group for group in data["groups"]}
        self.assertEqual(set(groups), {"Proyecto horas", "Proyecto horas B"})
        self.assertEqual(
            {line["name"]: line["total"] for line in groups["Proyecto horas"]["lines"]},
            {"Alice Horas": 11, "Bob Horas": 2},
        )
        self.assertFalse(groups["Proyecto horas"]["balance"])

        data = self.Entry.with_user(self.manager).get_time_grid_data(
            "2026-01-05", "2026-01-11", "company",
            {"company_type": "abi"},
        )
        self.assertEqual([group["name"] for group in data["groups"]], ["ABI"])
        self.assertEqual(data["groups"][0]["total"], 3.5)

    def test_grid_for_user_only_shows_own_hours(self):
        self._grid_entries()
        data = self.Entry.with_user(self.alice).get_time_grid_data(
            "2026-01-05", "2026-01-11", "employee"
        )
        self.assertFalse(data["is_manager"])
        self.assertEqual([group["name"] for group in data["groups"]], ["Alice Horas"])
        self.assertEqual(data["totals"]["total"], 11)
        self.assertEqual(
            [name for _id, name in data["filters"]["employees"]], ["Alice Horas"]
        )
