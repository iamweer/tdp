from datetime import date

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectGantt(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.project = cls.Project.create({
            "name": "Proyecto cronograma",
            "date_start": date(2026, 9, 1),
            "date": date(2026, 11, 30),
        })
        cls.root = cls.Task.create({
            "name": "1. Análisis",
            "project_id": cls.project.id,
            "sequence": 10,
            "date_deadline": date(2026, 9, 11),
            "planned_date_begin": "2026-09-01 08:00:00",
            "color": 3,
        })
        cls.child = cls.Task.create({
            "name": "Levantamiento",
            "project_id": cls.project.id,
            "parent_id": cls.root.id,
            "sequence": 1,
            "display_in_project": False,
            "planned_date_begin": "2026-09-01 08:00:00",
            "date_deadline": date(2026, 9, 3),
        })
        cls.grandchild = cls.Task.create({
            "name": "Entrevistas",
            "project_id": cls.project.id,
            "parent_id": cls.child.id,
            "sequence": 1,
            "planned_date_begin": "2026-09-05 00:00:00",
            "date_deadline": date(2026, 9, 5),
        })
        cls.partial_task = cls.Task.create({
            "name": "Actividad sin fecha completa",
            "project_id": cls.project.id,
            "parent_id": cls.root.id,
            "sequence": 2,
            "planned_date_begin": "2026-09-07 08:00:00",
        })
        cls.second_root = cls.Task.create({
            "name": "2. Desarrollo",
            "project_id": cls.project.id,
            "sequence": 20,
            "planned_date_begin": "2026-10-01 08:00:00",
            "date_deadline": date(2026, 10, 2),
        })
        cls.outside_task = cls.Task.create({
            "name": "Actividad fuera del filtro",
            "project_id": cls.project.id,
            "sequence": 30,
            "planned_date_begin": "2026-12-01 08:00:00",
            "date_deadline": date(2026, 12, 2),
        })
        cls.archived_task = cls.Task.create({
            "name": "Actividad archivada",
            "project_id": cls.project.id,
            "sequence": 40,
            "active": False,
            "planned_date_begin": "2026-09-01 08:00:00",
            "date_deadline": date(2026, 9, 2),
        })

    def test_action_uses_the_gantt_client_action_and_project_context(self):
        action = self.project.action_open_project_gantt()

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(
            action["tag"],
            "project_custom_extension.ProjectGantt",
        )
        self.assertEqual(action["target"], "current")
        self.assertEqual(action["context"], {"project_id": self.project.id})

    def test_gantt_action_and_menu_are_available(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "project_custom_extension.action_project_gantt"
        )
        menu = self.env.ref("project_custom_extension.menu_project_gantt")

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "project_custom_extension.ProjectGantt")
        self.assertEqual(menu.action.id, action["id"])

    def test_payload_includes_active_tasks_in_hierarchy_and_inclusive_duration(self):
        data = self.Project.get_project_gantt_data(self.project.id)
        rows = data["rows"]
        rows_by_name = {row["name"]: row for row in rows}

        self.assertEqual(
            [row["name"] for row in rows],
            [
                "1. Análisis",
                "Levantamiento",
                "Entrevistas",
                "Actividad sin fecha completa",
                "2. Desarrollo",
                "Actividad fuera del filtro",
            ],
        )
        self.assertEqual(rows_by_name["1. Análisis"]["depth"], 0)
        self.assertTrue(rows_by_name["1. Análisis"]["has_children"])
        self.assertEqual(rows_by_name["Levantamiento"]["parent_id"], self.root.id)
        self.assertEqual(rows_by_name["Entrevistas"]["depth"], 2)
        self.assertEqual(rows_by_name["Levantamiento"]["duration_days"], 3)
        self.assertEqual(rows_by_name["Levantamiento"]["color_index"], 3)
        self.assertEqual(rows_by_name["Entrevistas"]["color_index"], 3)
        self.assertEqual(rows_by_name["Actividad sin fecha completa"]["start_date"], "2026-09-07")
        self.assertFalse(rows_by_name["Actividad sin fecha completa"]["end_date"])
        self.assertFalse(rows_by_name["Actividad sin fecha completa"]["duration_days"])
        self.assertNotIn("Actividad archivada", rows_by_name)
        self.assertEqual(data["total"]["start_date"], "2026-09-01")
        self.assertEqual(data["total"]["end_date"], "2026-11-30")
        self.assertEqual(data["total"]["duration_days"], 91)

    def test_filter_uses_overlap_and_keeps_ancestors_and_incomplete_rows(self):
        data = self.Project.get_project_gantt_data(
            self.project.id,
            filter_start_date="2026-09-05",
            filter_end_date="2026-09-06",
        )
        names = [row["name"] for row in data["rows"]]

        self.assertIn("1. Análisis", names)
        self.assertIn("Levantamiento", names)
        self.assertIn("Entrevistas", names)
        self.assertIn("Actividad sin fecha completa", names)
        self.assertNotIn("2. Desarrollo", names)
        self.assertNotIn("Actividad fuera del filtro", names)
        self.assertEqual(data["timeline"]["start_date"], "2026-09-05")
        self.assertEqual(data["timeline"]["end_date"], "2026-09-06")

    def test_invalid_filter_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.Project.get_project_gantt_data(
                self.project.id,
                filter_start_date="2026-09-20",
                filter_end_date="2026-09-01",
            )

    def test_archived_project_is_not_available_to_the_gantt(self):
        self.project.write({"active": False})
        try:
            data = self.Project.get_project_gantt_data(self.project.id)
        finally:
            self.project.write({"active": True})

        self.assertFalse(data["project"])
        self.assertEqual(data["rows"], [])

    def test_project_form_and_kanban_expose_the_gantt_entry(self):
        form_arch = etree.fromstring(self.Project.get_view(
            view_id=self.env.ref("project.edit_project").id,
            view_type="form",
        )["arch"])
        kanban_arch = etree.fromstring(self.Project.get_view(
            view_id=self.env.ref("project.view_project_kanban").id,
            view_type="kanban",
        )["arch"])

        self.assertEqual(
            len(form_arch.xpath("//button[@name='action_open_project_gantt']")),
            1,
        )
        self.assertEqual(
            len(kanban_arch.xpath("//a[@name='action_open_project_gantt']")),
            1,
        )
