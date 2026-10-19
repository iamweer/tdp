from datetime import date

from freezegun import freeze_time

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

    def test_task_form_manager_can_choose_employee(self):
        with Form(self.task.with_user(self.manager)) as task_form:
            with task_form.time_entry_ids.new() as line:
                self.assertTrue(line.can_choose_employee)
                line.employee_id = self.bob_employee
                line.unit_amount = 2
        self.assertEqual(self.task.time_entry_ids.employee_id, self.bob_employee)

        with Form(self.task.with_user(self.alice)) as task_form:
            with task_form.time_entry_ids.new() as line:
                self.assertFalse(line.can_choose_employee)
                with self.assertRaises(AssertionError):
                    line.employee_id = self.bob_employee
                line.unit_amount = 1

    def test_list_view_manager_can_choose_employee(self):
        values = self.Entry.with_user(self.manager).onchange(
            {}, [], {"can_choose_employee": {}, "employee_id": {}}
        )["value"]
        self.assertTrue(values["can_choose_employee"])

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

    def test_grid_by_customer(self):
        self._grid_entries()
        data = self.Entry.with_user(self.manager).get_time_grid_data(
            "2026-01-05", "2026-01-11", "customer"
        )
        groups = {group["name"]: group for group in data["groups"]}
        self.assertEqual(set(groups), {"Cliente registro horas", "Sin cliente"})
        self.assertEqual(groups["Cliente registro horas"]["key"], self.customer.id)
        self.assertEqual(
            {line["name"]: line["total"] for line in groups["Cliente registro horas"]["lines"]},
            {"Proyecto horas": 13},
        )
        self.assertEqual(
            {line["name"]: line["total"] for line in groups["Sin cliente"]["lines"]},
            {"Proyecto horas B": 1.5},
        )

    def _alert_mails(self, user):
        return self.env["mail.mail"].search([("email_to", "=", user.email)])

    def _setup_alert_users(self):
        for user in (self.manager, self.alice, self.bob):
            user.email = f"{user.login}@alertas.example.com"

    def test_missing_hours_by_employee(self):
        self._grid_entries()
        with freeze_time("2026-01-09 21:00:00"):
            missing = self.Entry.with_context(tz="America/Bogota")._time_entry_missing_hours(
                self.alice_employee | self.bob_employee,
                date(2026, 1, 5),
                date(2026, 1, 11),
            )
        self.assertEqual(
            missing[self.alice_employee]["missing_days"],
            [date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)],
        )
        self.assertEqual(missing[self.alice_employee]["logged"], 11)
        self.assertEqual(
            missing[self.bob_employee]["missing_days"],
            [date(2026, 1, 6), date(2026, 1, 8), date(2026, 1, 9)],
        )

        # Future days are not missing yet.
        with freeze_time("2026-01-06 21:00:00"):
            missing = self.Entry.with_context(tz="America/Bogota")._time_entry_missing_hours(
                self.alice_employee, date(2026, 1, 5), date(2026, 1, 11)
            )
        self.assertFalse(missing)

    def test_friday_reminder_goes_to_people_missing_hours(self):
        self._setup_alert_users()
        self._grid_entries()
        for day in (7, 8, 9):
            self._entry(self.alice, date=date(2026, 1, day), unit_amount=8)
        with freeze_time("2026-01-09 20:00:00"):
            self.Entry._cron_remind_missing_hours()

        self.assertFalse(self._alert_mails(self.alice))
        bob_mail = self._alert_mails(self.bob)
        self.assertEqual(len(bob_mail), 1)
        self.assertIn("05/01 – 09/01/2026", bob_mail.subject)
        self.assertIn("mar 06/01, jue 08/01, vie 09/01", bob_mail.body_html)
        self.assertTrue(self._alert_mails(self.manager))

    def test_monday_summary_for_managers_and_project_pms(self):
        self._setup_alert_users()
        pm = new_test_user(
            self.env,
            login="time_entry_pm",
            name="PM Horas",
            email="time_entry_pm@alertas.example.com",
            groups="project.group_project_user",
        )
        pm_project = self.env["project.project"].create({
            "name": "Proyecto del PM",
            "user_id": pm.id,
        })
        self.env["project.task"].create({
            "name": "Tarea del PM",
            "project_id": pm_project.id,
            "user_ids": [Command.set([self.alice.id])],
        })
        self._grid_entries()
        with freeze_time("2026-01-12 13:00:00"):
            self.Entry._cron_notify_missing_hours_summary()

        manager_mail = self._alert_mails(self.manager)
        self.assertEqual(len(manager_mail), 1)
        self.assertIn("05/01 – 11/01/2026", manager_mail.subject)
        for name in ("Alice Horas", "Bob Horas", "Gerente Horas"):
            self.assertIn(name, manager_mail.body_html)

        pm_mail = self._alert_mails(pm)
        self.assertEqual(len(pm_mail), 1)
        self.assertIn("Alice Horas", pm_mail.body_html)
        self.assertNotIn("Bob Horas", pm_mail.body_html)
        # People without hours do not receive the summary.
        self.assertFalse(self._alert_mails(self.alice))
