from datetime import date, datetime

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..hooks import _copy_field_if_empty, _hide_existing_subtasks


@tagged("post_install", "-at_install")
class TestProjectCustomExtension(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({
            "name": "Proyecto de prueba",
        })

    def test_task_planned_dates_allow_partial_values(self):
        start_only = self.env["project.task"].create({
            "name": "Solo inicio",
            "project_id": self.project.id,
            "planned_date_begin": datetime(2026, 1, 1, 8, 0),
        })
        end_only = self.env["project.task"].create({
            "name": "Solo fin",
            "project_id": self.project.id,
            "date_deadline": datetime(2026, 1, 31, 17, 0),
        })

        self.assertTrue(start_only.planned_date_begin)
        self.assertTrue(end_only.date_deadline)

    def test_task_planned_dates_reject_inverted_range(self):
        with self.assertRaises(ValidationError):
            self.env["project.task"].create({
                "name": "Rango invertido",
                "project_id": self.project.id,
                "planned_date_begin": datetime(2026, 2, 1, 8, 0),
                "date_deadline": datetime(2026, 1, 31, 17, 0),
            })

    def test_warranty_display_formats(self):
        self.project.write({
            "warranty_start_date": date(2026, 1, 1),
            "warranty_end_date": date(2026, 1, 31),
        })
        self.assertEqual(
            self.project.warranty_period_display,
            "Garantía: 01-01-2026 > 31-01-2026",
        )

        self.project.warranty_end_date = False
        self.assertEqual(
            self.project.warranty_period_display,
            "Garantía: 01-01-2026 >",
        )

        self.project.write({
            "warranty_start_date": False,
            "warranty_end_date": date(2026, 1, 31),
        })
        self.assertEqual(
            self.project.warranty_period_display,
            "Garantía: > 31-01-2026",
        )

    def test_warranty_dates_reject_inverted_range(self):
        with self.assertRaises(ValidationError):
            self.project.write({
                "warranty_start_date": date(2026, 2, 1),
                "warranty_end_date": date(2026, 1, 31),
            })

    def test_existing_subtasks_are_hidden_from_project_flow(self):
        root_task = self.env["project.task"].create({
            "name": "Tarea principal",
            "project_id": self.project.id,
        })
        subtask = self.env["project.task"].create({
            "name": "Subtarea",
            "project_id": self.project.id,
            "parent_id": root_task.id,
            "display_in_project": True,
        })

        _hide_existing_subtasks(self.env)

        self.assertTrue(root_task.display_in_project)
        self.assertFalse(subtask.display_in_project)

    def test_copy_field_preserves_existing_target(self):
        source_date = datetime(2026, 1, 1, 8, 0)
        preserved_date = datetime(2025, 12, 31, 8, 0)
        copied_task = self.env["project.task"].create({
            "name": "Valor por copiar",
            "project_id": self.project.id,
            "date_deadline": source_date,
        })
        preserved_task = self.env["project.task"].create({
            "name": "Valor existente",
            "project_id": self.project.id,
            "date_deadline": source_date,
            "planned_date_begin": preserved_date,
        })

        _copy_field_if_empty(
            self.env["project.task"],
            "date_deadline",
            "planned_date_begin",
        )

        self.assertEqual(copied_task.planned_date_begin, source_date)
        self.assertEqual(preserved_task.planned_date_begin, preserved_date)

    def test_custom_views_are_applied(self):
        task_form = etree.fromstring(self.env["project.task"].get_view(
            view_id=self.env.ref("project.view_task_form2").id,
            view_type="form",
        )["arch"])
        task_list = etree.fromstring(self.env["project.task"].get_view(
            view_id=self.env.ref("project.project_task_view_tree_main_base").id,
            view_type="list",
        )["arch"])
        project_form = etree.fromstring(self.env["project.project"].get_view(
            view_id=self.env.ref("project.edit_project").id,
            view_type="form",
        )["arch"])
        project_kanban = etree.fromstring(self.env["project.project"].get_view(
            view_id=self.env.ref("project.view_project_kanban").id,
            view_type="kanban",
        )["arch"])

        self.assertEqual(
            len(task_form.xpath(
                "//field[@name='planned_date_begin' and @widget='daterange']"
            )),
            1,
        )
        self.assertEqual(
            len(task_list.xpath("//field[@name='planned_date_begin']")),
            1,
        )
        self.assertEqual(
            len(project_form.xpath("//field[@name='warranty_start_date']")),
            1,
        )
        self.assertEqual(
            len(project_form.xpath("//field[@name='warranty_end_date']")),
            1,
        )
        self.assertEqual(
            len(project_kanban.xpath("//field[@name='warranty_period_display']")),
            1,
        )

    def test_project_task_action_keeps_native_flow_domain(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "project.act_project_project_2_project_task_all"
        )

        self.assertIn("('display_in_project', '=', True)", action["domain"])
        self.assertNotIn("parent_id", action["domain"])
