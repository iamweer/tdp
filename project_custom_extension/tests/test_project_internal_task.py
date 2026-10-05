from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProjectInternalTask(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.customer = cls.env["res.partner"].create({
            "name": "Empresa cliente de tareas internas",
            "is_company": True,
        })
        cls.manager = new_test_user(
            cls.env,
            login="internal_task_manager",
            groups="project.group_project_manager",
        )
        cls.project_user = new_test_user(
            cls.env,
            login="internal_task_user",
            groups="project.group_project_user",
        )
        cls.client_user = new_test_user(
            cls.env,
            login="internal_task_client",
            groups="project_custom_extension.group_project_client",
        )
        cls.client_user.partner_id.write({"parent_id": cls.customer.id})
        cls.portal_user = new_test_user(
            cls.env,
            login="internal_task_portal",
            groups="base.group_portal",
        )

        cls.project = cls.Project.create({
            "name": "Proyecto con tareas internas",
            "partner_id": cls.customer.id,
            "privacy_visibility": "portal",
        })
        cls.visible_task = cls.Task.create({
            "name": "Tarea visible",
            "project_id": cls.project.id,
            "project_weight": 40,
            "user_ids": [Command.link(cls.project_user.id)],
        })
        cls.internal_task = cls.Task.create({
            "name": "Tarea interna",
            "project_id": cls.project.id,
            "project_weight": 60,
            "is_internal_task": True,
            "user_ids": [Command.link(cls.project_user.id)],
        })
        cls.internal_subtask = cls.Task.create({
            "name": "Subtarea interna",
            "project_id": cls.project.id,
            "parent_id": cls.internal_task.id,
        })
        (cls.visible_task | cls.internal_task | cls.internal_subtask).message_subscribe(
            partner_ids=cls.portal_user.partner_id.ids,
        )

    def test_clients_and_portal_do_not_see_internal_tasks(self):
        internal_ids = (self.internal_task | self.internal_subtask).ids
        for user in (self.client_user, self.portal_user):
            visible_ids = self.Task.with_user(user).search([
                ("project_id", "=", self.project.id),
            ]).ids
            self.assertIn(self.visible_task.id, visible_ids, user.login)
            self.assertFalse(set(internal_ids) & set(visible_ids), user.login)
            with self.assertRaises(AccessError):
                self.internal_task.with_user(user).read(["name"])

    def test_project_user_and_manager_see_internal_tasks(self):
        for user in (self.project_user, self.manager):
            visible_ids = self.Task.with_user(user).search([
                ("project_id", "=", self.project.id),
            ]).ids
            self.assertIn(self.internal_task.id, visible_ids, user.login)
            self.assertIn(self.internal_subtask.id, visible_ids, user.login)

    def test_client_assigned_only_to_internal_task_does_not_see_project(self):
        foreign_project = self.Project.create({"name": "Proyecto ajeno"})
        self.Task.create({
            "name": "Tarea interna asignada al cliente",
            "project_id": foreign_project.id,
            "is_internal_task": True,
            "user_ids": [Command.link(self.client_user.id)],
        })
        visible_ids = self.Project.with_user(self.client_user).search([]).ids
        self.assertNotIn(foreign_project.id, visible_ids)

    def test_subtasks_inherit_internal_flag(self):
        self.assertTrue(self.internal_subtask.is_internal_task)
        self.visible_task.is_internal_task = True
        subtask = self.Task.create({
            "name": "Subtarea nueva",
            "project_id": self.project.id,
            "parent_id": self.visible_task.id,
        })
        self.assertTrue(subtask.is_internal_task)
        self.visible_task.is_internal_task = False
        self.assertFalse(subtask.is_internal_task)
        with self.assertRaises(ValidationError):
            self.internal_subtask.is_internal_task = False

    def test_only_managers_can_change_internal_flag(self):
        with self.assertRaises(AccessError):
            self.visible_task.with_user(self.project_user).write({
                "is_internal_task": True,
            })
        self.visible_task.with_user(self.manager).write({"is_internal_task": True})
        self.assertTrue(self.visible_task.is_internal_task)

    def test_internal_tasks_do_not_count_for_progress_or_weights(self):
        progress = self.Project._get_project_execution_progress(self.project)
        self.assertEqual(
            [phase["task"] for phase in progress["phases"]],
            [self.visible_task],
        )
        self.assertEqual(self.project.progress_weight_total, 40)
        self.assertEqual(self.project.weighted_progress, 0)
        self.assertNotIn(self.internal_task, self.project.main_task_ids)

        self.visible_task.state = "1_done"
        self.project.invalidate_recordset(["weighted_progress"])
        self.assertEqual(self.project.weighted_progress, 40)

        # The internal task's 60% does not block the visible tasks from 100%.
        self.visible_task.project_weight = 100
        with self.assertRaises(ValidationError):
            self.internal_task.is_internal_task = False

    def test_native_counters_exclude_internal_tasks(self):
        self.assertEqual(self.project.task_count, 1)
        self.assertEqual(self.project.open_task_count, 1)
        self.assertEqual(self.project.closed_task_count, 0)

    def test_dashboards_exclude_internal_tasks(self):
        Project = self.Project.with_user(self.project_user)
        detail = Project.get_project_detail_dashboard_data(self.project.id)
        self.assertEqual(detail["progress"]["total_tasks"], 1)
        self.assertEqual(
            [item["id"] for item in detail["progress"]["parent_tasks"]],
            [self.visible_task.id],
        )
        self.assertEqual(
            sum(item["count"] for item in detail["activities_by_state"]),
            1,
        )
        sprint_data = Project.get_project_sprint_dashboard_data(self.project.id)
        self.assertEqual(
            [task["id"] for task in sprint_data["tasks"]],
            [self.visible_task.id],
        )

        general = self.Project.with_user(self.manager).get_project_dashboard_data()
        no_deadline = next(
            alert for alert in general["alerts"] if alert["key"] == "no_deadline"
        )
        no_deadline_tasks = self.Task.search(no_deadline["domain"])
        self.assertIn(self.visible_task, no_deadline_tasks)
        self.assertNotIn(self.internal_task, no_deadline_tasks)

    def test_gantt_excludes_internal_tasks(self):
        data = self.Project.with_user(self.manager).get_project_gantt_data(
            self.project.id
        )
        self.assertEqual(
            [row["id"] for row in data["rows"]],
            [self.visible_task.id],
        )

    def test_internal_field_only_in_manager_views(self):
        for user, expected in (
            (self.manager, True),
            (self.project_user, False),
            (self.client_user, False),
        ):
            arch = etree.fromstring(
                self.Task.with_user(user).get_view(view_type="form")["arch"]
            )
            self.assertEqual(
                bool(arch.xpath("//field[@name='is_internal_task']")),
                expected,
                user.login,
            )
