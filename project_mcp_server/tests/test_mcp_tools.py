from odoo import Command, fields
from odoo.tests import new_test_user, tagged

from .common import McpCase


@tagged("post_install", "-at_install")
class TestMcpTools(McpCase):
    def test_list_and_get_projects_respect_visibility(self):
        error, data = self.call(self.user, "list_projects")
        self.assertFalse(error)
        ids = {project["id"] for project in data["projects"]}
        self.assertIn(self.project.id, ids)
        self.assertNotIn(self.other_project.id, ids)

        error, data = self.call(self.user, "get_project", project_id=self.project.id)
        self.assertFalse(error)
        self.assertEqual(data["customer"]["id"], self.customer.id)
        self.assertTrue(data["stages"])

        error, _message = self.call(self.user, "get_project", project_id=self.other_project.id)
        self.assertTrue(error)

    def test_dashboards(self):
        error, data = self.call(self.manager, "get_project_dashboard")
        self.assertFalse(error, data)
        error, data = self.call(
            self.manager, "get_project_dashboard", project_id=self.project.id
        )
        self.assertFalse(error, data)

    def test_search_and_get_task(self):
        error, data = self.call(self.user, "search_tasks", assigned_to_me=True)
        self.assertFalse(error)
        self.assertEqual([task["id"] for task in data["tasks"]], [self.task.id])

        error, data = self.call(self.user, "get_task", task_id=self.task.id)
        self.assertFalse(error)
        self.assertIn("time_spent_hours", data)

        error, data = self.call(self.client, "get_task", task_id=self.task.id)
        self.assertFalse(error)
        self.assertNotIn("time_spent_hours", data)

        error, _message = self.call(self.client, "get_task", task_id=self.other_task.id)
        self.assertTrue(error)

    def test_reference_lists(self):
        sprint = self.env["project.sprint"].create({
            "name": "Sprint MCP",
            "project_id": self.project.id,
        })
        error, data = self.call(self.user, "list_sprints", project_id=self.project.id)
        self.assertFalse(error)
        self.assertEqual(data["sprints"][0]["id"], sprint.id)

        error, data = self.call(self.user, "list_unified_stages")
        self.assertFalse(error)
        self.assertTrue(data["stages"])

    def test_create_and_update_task(self):
        error, data = self.call(
            self.user,
            "create_task",
            project_id=self.project.id,
            parent_id=self.task.id,
            name="Subtarea creada por IA",
            description="Detalle\nen dos líneas",
            date_deadline="2030-01-15T12:00:00Z",
            user_ids=[self.user.id],
        )
        self.assertFalse(error, data)
        task = self.env["project.task"].browse(data["id"])
        self.assertEqual(task.parent_id, self.task)
        self.assertEqual(task.date_deadline, fields.Datetime.to_datetime("2030-01-15 12:00:00"))
        self.assertIn("dos líneas", task.description)

        error, data = self.call(self.user, "update_task", task_id=task.id, priority="1")
        self.assertFalse(error, data)
        self.assertEqual(task.priority, "1")

    def test_failed_write_is_rolled_back(self):
        foreign_sprint = self.env["project.sprint"].create({
            "name": "Sprint ajeno",
            "project_id": self.other_project.id,
        })
        error, _message = self.call(
            self.manager,
            "update_task",
            task_id=self.task.id,
            name="No debe guardarse",
            sprint_id=foreign_sprint.id,
        )
        self.assertTrue(error)
        self.task.invalidate_recordset()
        self.assertEqual(self.task.name, "Tarea MCP")

    def test_client_restrictions(self):
        error, _message = self.call(
            self.client, "update_task", task_id=self.task.id, user_ids=[self.client.id]
        )
        self.assertTrue(error)
        error, _message = self.call(self.client, "log_time", task_id=self.task.id, hours=1)
        self.assertTrue(error)

    def test_move_task_stage(self):
        stage = self.project.type_ids.sorted("sequence")[-1]
        error, data = self.call(self.user, "move_task_stage", task_id=self.task.id, stage_id=stage.id)
        self.assertFalse(error, data)
        self.assertEqual(self.task.stage_id, stage)

        foreign_stage = self.env["project.task.type"].create({"name": "Etapa ajena"})
        error, _message = self.call(
            self.user, "move_task_stage", task_id=self.task.id, stage_id=foreign_stage.id
        )
        self.assertTrue(error)

    def _project_with_stages(self, *names):
        Stage = self.env["project.task.type"]
        project = self.env["project.project"].create({"name": "Proyecto cierre MCP"})
        stages = {
            name: Stage.create({"name": name, "sequence": sequence})
            for sequence, name in enumerate(names)
        }
        project.type_ids = [Command.set([stage.id for stage in stages.values()])]
        task = self.env["project.task"].create({
            "name": "Tarea cierre MCP",
            "project_id": project.id,
            "stage_id": stages[names[0]].id,
            "user_ids": [Command.link(self.user.id)],
        })
        return task, stages

    def test_close_task_moves_to_resolved_stage(self):
        task, stages = self._project_with_stages("EN CURSO", "RESUELTO")
        error, data = self.call(self.user, "close_task", task_id=task.id)
        self.assertFalse(error, data)
        self.assertTrue(data["closed"])
        self.assertEqual(task.stage_id, stages["RESUELTO"])
        self.assertEqual(task.state, "1_done")

        error, data = self.call(self.user, "close_task", task_id=task.id)
        self.assertFalse(error, data)
        self.assertTrue(data["closed"])

    def test_close_task_without_resolved_stage(self):
        task, stages = self._project_with_stages("EN CURSO", "Pendiente cliente")
        error, message = self.call(self.user, "close_task", task_id=task.id)
        self.assertTrue(error)
        self.assertIn("Pendiente cliente", message)
        self.assertEqual(task.stage_id, stages["EN CURSO"])

    def test_close_task_uses_resolved_synonym(self):
        task, stages = self._project_with_stages("En proceso", "Completado")
        error, data = self.call(self.user, "close_task", task_id=task.id)
        self.assertFalse(error, data)
        self.assertEqual(task.stage_id, stages["Completado"])
        self.assertEqual(task.state, "1_done")

    def test_close_task_asks_about_pending_validation_stages(self):
        task, stages = self._project_with_stages(
            "EN CURSO", "VALIDACION INTERNA", "VALIDACION CLIENTE", "RESUELTO"
        )
        error, data = self.call(self.user, "close_task", task_id=task.id)
        self.assertFalse(error, data)
        self.assertFalse(data["closed"])
        self.assertTrue(data["needs_confirmation"])
        self.assertEqual(
            [stage["id"] for stage in data["validation_stages"]],
            [stages["VALIDACION INTERNA"].id, stages["VALIDACION CLIENTE"].id],
        )
        self.assertEqual(task.stage_id, stages["EN CURSO"])

        # Once in the last validation stage, nothing is left to ask about.
        task.stage_id = stages["VALIDACION CLIENTE"]
        error, data = self.call(self.user, "close_task", task_id=task.id)
        self.assertFalse(error, data)
        self.assertTrue(data["closed"])
        self.assertEqual(task.stage_id, stages["RESUELTO"])

    def test_close_task_skip_validation(self):
        task, stages = self._project_with_stages("EN CURSO", "VALIDACION INTERNA", "RESUELTO")
        error, data = self.call(
            self.user, "close_task", task_id=task.id, skip_validation=True
        )
        self.assertFalse(error, data)
        self.assertTrue(data["closed"])
        self.assertEqual(task.stage_id, stages["RESUELTO"])
        self.assertEqual(task.state, "1_done")

    def test_log_time_and_my_entries(self):
        error, data = self.call(
            self.user, "log_time", task_id=self.task.id, hours=2.5, date="2026-01-05"
        )
        self.assertFalse(error, data)
        self.assertEqual(data["task_time_spent_hours"], 2.5)

        error, _message = self.call(self.user, "log_time", task_id=self.task.id, hours=30)
        self.assertTrue(error)

        error, data = self.call(
            self.user, "get_my_time_entries", date_from="2026-01-01", date_to="2026-01-31"
        )
        self.assertFalse(error)
        self.assertEqual(data["total_hours"], 2.5)
        self.assertEqual(len(data["entries"]), 1)

    def test_log_time_for_other_employee(self):
        employee = self.user.employee_id
        error, data = self.call(
            self.manager, "log_time", task_id=self.task.id, hours=1, employee_id=employee.id
        )
        self.assertFalse(error, data)
        self.assertEqual(data["employee"]["id"], employee.id)

        error, data = self.call(
            self.manager, "log_time", task_id=self.task.id, hours=2, user_id=self.user.id
        )
        self.assertFalse(error, data)
        self.assertEqual(data["employee"]["id"], employee.id)
        self.assertEqual(data["task_time_spent_hours"], 3)

        error, _message = self.call(
            self.manager, "log_time", task_id=self.task.id, hours=1,
            employee_id=employee.id, user_id=self.user.id,
        )
        self.assertTrue(error)

        error, _message = self.call(
            self.manager, "log_time", task_id=self.task.id, hours=1, user_id=self.client.id
        )
        self.assertTrue(error)

    def test_log_time_for_other_employee_requires_manager(self):
        other = new_test_user(self.env, login="mcp_other_user", groups="project.group_project_user")
        other_employee = self.env["hr.employee"].create({"name": "Otro", "user_id": other.id})
        error, _message = self.call(
            self.user, "log_time", task_id=self.task.id, hours=1, employee_id=other_employee.id
        )
        self.assertTrue(error)
        self.assertFalse(self.env["project.task.time.entry"].search([
            ("employee_id", "=", other_employee.id),
        ]))

    def test_post_task_message(self):
        error, data = self.call(
            self.user, "post_task_message", task_id=self.task.id, body="Avance desde IA"
        )
        self.assertFalse(error, data)
        message = self.env["mail.message"].browse(data["message_id"])
        self.assertIn("Avance desde IA", message.body)
