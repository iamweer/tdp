from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectUnifiedStage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Task = cls.env["project.task"]
        cls.Stage = cls.env["project.task.type"]
        cls.project = cls.env["project.project"].create({
            "name": "Proyecto con etapas unificadas",
        })
        cls.stages = {stage.name: stage for stage in cls.project.type_ids}
        cls.unified = {
            key: cls.env.ref(f"project_custom_extension.unified_stage_{key}")
            for key in (
                "new",
                "in_progress",
                "internal_validation",
                "client_validation",
                "resolved",
            )
        }

    def test_project_stages_get_unified_stage_by_name(self):
        self.assertEqual(
            {name: stage.unified_stage_id for name, stage in self.stages.items()},
            {
                "NUEVO": self.unified["new"],
                "EN CURSO": self.unified["in_progress"],
                "VALIDACION CLIENTE": self.unified["client_validation"],
                "VALIDACION INTERNA": self.unified["internal_validation"],
                "RESUELTO": self.unified["resolved"],
            },
        )
        project_link = [Command.link(self.project.id)]
        variants = self.Stage.create([
            {"name": "Validación Cliente ", "project_ids": project_link},
            {"name": "  en   curso", "project_ids": project_link},
            {"name": "Nuevas", "project_ids": project_link},
            {"name": "Resueltas.", "project_ids": project_link},
            {"name": "NO CUMPLE", "project_ids": project_link},
            # Personal stages ("Mis tareas" native columns) are not unified.
            {"name": "Nuevo", "user_id": self.env.user.id},
        ])
        self.assertEqual(
            [stage.unified_stage_id for stage in variants],
            [
                self.unified["client_validation"],
                self.unified["in_progress"],
                self.unified["new"],
                self.unified["resolved"],
                self.env["project.task.unified.stage"],
                self.env["project.task.unified.stage"],
            ],
        )

    def test_manual_unified_stage_is_kept(self):
        stage = self.Stage.create({
            "name": "NO CUMPLE",
            "project_ids": [Command.link(self.project.id)],
            "unified_stage_id": self.unified["in_progress"].id,
        })
        self.assertEqual(stage.unified_stage_id, self.unified["in_progress"])
        stage.unified_stage_id = self.unified["internal_validation"]
        stage.sequence = 99
        self.assertEqual(stage.unified_stage_id, self.unified["internal_validation"])

    def test_task_follows_and_moves_with_unified_stage(self):
        task = self.Task.create({"name": "Tarea", "project_id": self.project.id})
        self.assertEqual(task.unified_stage_id, self.unified["new"])

        task.unified_stage_id = self.unified["internal_validation"]
        self.assertEqual(task.stage_id, self.stages["VALIDACION INTERNA"])

        task.unified_stage_id = self.unified["resolved"]
        self.assertEqual(task.stage_id, self.stages["RESUELTO"])
        self.assertEqual(task.state, "1_done")

        # Reassigning a project stage reclassifies its tasks.
        self.stages["VALIDACION INTERNA"].unified_stage_id = self.unified["in_progress"]
        moved = self.Task.create({
            "name": "Otra",
            "project_id": self.project.id,
            "stage_id": self.stages["VALIDACION INTERNA"].id,
        })
        self.assertEqual(moved.unified_stage_id, self.unified["in_progress"])

    def test_unified_stage_move_errors(self):
        task = self.Task.create({"name": "Tarea", "project_id": self.project.id})
        self.stages["EN CURSO"].unified_stage_id = False
        with self.assertRaisesRegex(UserError, "no tiene una etapa equivalente"):
            task.unified_stage_id = self.unified["in_progress"]
        with self.assertRaisesRegex(UserError, "sin etapa unificada"):
            task.unified_stage_id = False
        private_task = self.Task.create({"name": "Privada", "project_id": False})
        with self.assertRaisesRegex(UserError, "no tiene proyecto"):
            private_task.unified_stage_id = self.unified["new"]

    def test_my_tasks_kanban_groups_by_unified_stage(self):
        arch = etree.fromstring(self.Task.get_view(
            view_id=self.env.ref("project.view_task_kanban_inherit_my_task").id,
            view_type="kanban",
        )["arch"])
        self.assertEqual(arch.get("default_group_by"), "unified_stage_id")

        groups = self.Task.read_group(
            [("project_id", "=", self.project.id)],
            ["unified_stage_id"],
            ["unified_stage_id"],
        )
        group_ids = [group["unified_stage_id"][0] for group in groups if group["unified_stage_id"]]
        self.assertEqual(
            group_ids[:5],
            [stage.id for stage in self.unified.values()],
        )


@tagged("post_install", "-at_install")
class TestSubtaskDefaultDates(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Task = cls.env["project.task"]
        cls.project = cls.env["project.project"].create({"name": "Proyecto con subtareas"})
        cls.now = fields.Datetime.now().replace(microsecond=0)
        cls.parent = cls.Task.create({
            "name": "Padre",
            "project_id": cls.project.id,
            "date_deadline": cls.now + timedelta(days=10),
        })

    def _defaults(self, parent):
        with patch.object(fields.Datetime, "now", return_value=self.now):
            return self.Task.with_context(default_parent_id=parent.id).default_get(
                ["planned_date_begin", "date_deadline"]
            )

    def test_default_get_proposes_start_now_and_parent_deadline(self):
        defaults = self._defaults(self.parent)
        self.assertEqual(defaults["planned_date_begin"], self.now)
        self.assertEqual(defaults["date_deadline"], self.parent.date_deadline)

    def test_default_get_with_overdue_or_undated_parent_only_sets_start(self):
        for deadline in (self.now - timedelta(days=1), False):
            with self.subTest(deadline=deadline):
                self.parent.date_deadline = deadline
                defaults = self._defaults(self.parent)
                self.assertEqual(defaults["planned_date_begin"], self.now)
                self.assertFalse(defaults.get("date_deadline"))

    def test_default_get_without_parent_proposes_nothing(self):
        defaults = self.Task.default_get(["planned_date_begin", "date_deadline"])
        self.assertFalse(defaults.get("planned_date_begin"))
        self.assertFalse(defaults.get("date_deadline"))

    def test_create_subtask_fills_missing_dates_and_keeps_explicit_ones(self):
        with patch.object(fields.Datetime, "now", return_value=self.now):
            subtask = self.Task.create({
                "name": "Subtarea",
                "project_id": self.project.id,
                "parent_id": self.parent.id,
            })
            explicit = self.Task.create({
                "name": "Sin fechas",
                "project_id": self.project.id,
                "parent_id": self.parent.id,
                "planned_date_begin": False,
                "date_deadline": False,
            })
            past_deadline = self.Task.create({
                "name": "Fin ya pasado",
                "project_id": self.project.id,
                "parent_id": self.parent.id,
                "date_deadline": self.now - timedelta(days=2),
            })
        self.assertEqual(subtask.planned_date_begin, self.now)
        self.assertEqual(subtask.date_deadline, self.parent.date_deadline)
        self.assertFalse(explicit.planned_date_begin)
        self.assertFalse(explicit.date_deadline)
        # A start after the chosen deadline would be invalid: it is not set.
        self.assertFalse(past_deadline.planned_date_begin)

    def test_subtasks_created_from_the_parent_form_get_dates(self):
        with patch.object(fields.Datetime, "now", return_value=self.now):
            parent = self.Task.create({
                "name": "Padre nuevo",
                "project_id": self.project.id,
                "date_deadline": self.now + timedelta(days=5),
                "child_ids": [Command.create({
                    "name": "Hija",
                    "project_id": self.project.id,
                })],
            })
        self.assertEqual(parent.child_ids.planned_date_begin, self.now)
        self.assertEqual(parent.child_ids.date_deadline, parent.date_deadline)

    def test_copied_subtasks_keep_their_dates(self):
        subtask = self.Task.create({
            "name": "Subtarea fechada",
            "project_id": self.project.id,
            "parent_id": self.parent.id,
            "planned_date_begin": self.now - timedelta(days=30),
            "date_deadline": self.now - timedelta(days=20),
        })
        copy = subtask.copy()
        self.assertEqual(copy.planned_date_begin, subtask.planned_date_begin)
        self.assertEqual(copy.date_deadline, subtask.date_deadline)
