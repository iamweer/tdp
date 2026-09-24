from datetime import date, datetime, timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..hooks import _copy_field_if_empty, _hide_existing_subtasks
from ..models.project_project import (
    DASHBOARD_HEALTH_DEFAULTS,
    DASHBOARD_HEALTH_PARAMETERS,
    WARRANTY_ACTIVATION_PARAMETER,
    WARRANTY_VICTOR_LOGIN,
)


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

    def test_hierarchical_priority_rejects_negative_values(self):
        with self.assertRaises(ValidationError):
            self.env["project.task"].create({
                "name": "Prioridad negativa",
                "project_id": self.project.id,
                "hierarchical_priority": -1,
            })

    def test_resolved_stage_marks_tasks_done_on_create_and_batch_write(self):
        stage = self.env["project.task.type"].create({
            "name": "Resuelto",
            "project_ids": [Command.link(self.project.id)],
        })
        task_model = self.env["project.task"]
        task = task_model.create({
            "name": "Creada como resuelta",
            "project_id": self.project.id,
            "stage_id": stage.id,
        })
        self.assertEqual(task.state, "1_done")

        tasks = task_model.create([
            {"name": "Resuelta A", "project_id": self.project.id},
            {"name": "Resuelta B", "project_id": self.project.id},
        ])
        tasks.write({"stage_id": stage.id})
        self.assertEqual(set(tasks.mapped("state")), {"1_done"})

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
        task_kanban = etree.fromstring(self.env["project.task"].get_view(
            view_id=self.env.ref("project.view_task_kanban").id,
            view_type="kanban",
        )["arch"])
        sprint_list = etree.fromstring(self.env["project.sprint"].get_view(
            view_id=self.env.ref(
                "project_custom_extension.project_sprint_view_list"
            ).id,
            view_type="list",
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
            len(task_form.xpath("//field[@name='hierarchical_priority']")),
            1,
        )
        self.assertEqual(
            [field.get("name") for field in task_form.xpath(
                "//div[@id='date_deadline_and_recurring_task']/"
                "following-sibling::*[position() <= 2]"
            )],
            ["sprint_id", "hierarchical_priority"],
        )
        self.assertTrue(task_list.xpath("//field[@name='hierarchical_priority']"))
        self.assertTrue(task_kanban.xpath("//field[@name='hierarchical_priority']"))
        self.assertTrue(task_form.xpath("//field[@name='sprint_id']"))
        self.assertTrue(task_list.xpath("//field[@name='sprint_id']"))
        self.assertTrue(task_kanban.xpath("//field[@name='sprint_id']"))
        self.assertIn(
            "sprint_sequence_order, hierarchical_priority_order",
            task_list.get("default_order"),
        )
        self.assertIn(
            "sprint_sequence_order, hierarchical_priority_order",
            task_kanban.get("default_order"),
        )
        self.assertTrue(task_list.xpath(
            "//field[@name='sprint_sequence_order' and @column_invisible='True']"
        ))
        self.assertTrue(sprint_list.xpath("//field[@name='sequence']"))
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

    def test_task_actions_use_the_expected_flow_domains(self):
        project_action = self.env["ir.actions.actions"]._for_xml_id(
            "project.act_project_project_2_project_task_all"
        )
        all_tasks_action = self.env["ir.actions.actions"]._for_xml_id(
            "project.action_view_all_task"
        )

        self.assertIn(
            "('display_in_project', '=', True)",
            project_action["domain"],
        )
        self.assertEqual(all_tasks_action["domain"], "[]")

    def test_dashboard_views_and_action_are_available(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "project_custom_extension.action_project_dashboard"
        )
        detail_action = self.env["ir.actions.actions"]._for_xml_id(
            "project_custom_extension.action_project_detail_dashboard"
        )
        settings_view = etree.fromstring(self.env["res.config.settings"].get_view(
            view_id=self.env.ref(
                "project_custom_extension.res_config_settings_view_form_project_dashboard"
            ).id,
            view_type="form",
        )["arch"])

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(
            action["tag"],
            "project_custom_extension.ProjectDashboard",
        )
        self.assertEqual(detail_action["type"], "ir.actions.client")
        self.assertEqual(
            detail_action["tag"],
            "project_custom_extension.ProjectDetailDashboard",
        )
        sprint_action = self.env["ir.actions.actions"]._for_xml_id(
            "project_custom_extension.project_sprint_action"
        )
        sprint_action_record = self.env.ref(
            "project_custom_extension.project_sprint_action"
        )
        self.assertEqual(sprint_action_record.context, "{}")
        self.assertNotIn("active_id", str(sprint_action.get("context", {})))
        self.assertEqual(
            len(settings_view.xpath(
                "//field[@name='project_dashboard_progress_weight']"
            )),
            1,
        )
        self.assertEqual(
            len(settings_view.xpath(
                "//field[@name='project_dashboard_healthy_threshold']"
            )),
            1,
        )
        self.assertEqual(sprint_action["res_model"], "project.sprint")


@tagged("post_install", "-at_install")
class TestProjectDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_a = cls.env["res.partner"].create({"name": "Cliente A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "Cliente B"})
        cls.partner_private = cls.env["res.partner"].create({
            "name": "Cliente privado",
        })

        cls.on_track_project = cls._create_project(
            "Proyecto en tiempo",
            cls.partner_a,
            "on_track",
            allow_task_dependencies=True,
        )
        cls.at_risk_project = cls._create_project(
            "Proyecto en riesgo",
            cls.partner_a,
            "at_risk",
        )
        cls.off_track_project = cls._create_project(
            "Proyecto atrasado",
            cls.partner_b,
            "off_track",
        )
        cls.on_hold_project = cls._create_project(
            "Proyecto en pausa",
            cls.partner_a,
            "on_hold",
        )
        cls.to_define_project = cls._create_project(
            "Proyecto sin definir",
            cls.partner_a,
            "to_define",
        )
        cls.done_project = cls._create_project(
            "Proyecto terminado",
            cls.partner_a,
            "done",
        )
        cls.archived_project = cls._create_project(
            "Proyecto archivado",
            cls.partner_a,
            "on_track",
            active=False,
        )
        cls.private_project = cls._create_project(
            "Proyecto privado",
            cls.partner_private,
            "off_track",
            privacy_visibility="followers",
        )

        cls.completed_task = cls.env["project.task"].create({
            "name": "Tarea completada",
            "project_id": cls.on_track_project.id,
            "state": "1_done",
        })
        cls.safe_task = cls.env["project.task"].create({
            "name": "Tarea segura",
            "project_id": cls.on_track_project.id,
            "date_deadline": fields.Datetime.now() + timedelta(days=10),
        })
        cls.critical_subtask = cls.env["project.task"].create({
            "name": "Subtarea crítica",
            "project_id": cls.on_track_project.id,
            "parent_id": cls.safe_task.id,
            "priority": "1",
            "date_deadline": fields.Datetime.now() - timedelta(days=1),
        })
        cls.upcoming_subtask = cls.env["project.task"].create({
            "name": "Subtarea próxima",
            "project_id": cls.on_track_project.id,
            "parent_id": cls.safe_task.id,
            "date_deadline": fields.Datetime.now() + timedelta(days=2),
        })
        cls.blocker_task = cls.env["project.task"].create({
            "name": "Tarea bloqueadora",
            "project_id": cls.on_track_project.id,
        })
        cls.blocked_subtask = cls.env["project.task"].create({
            "name": "Subtarea bloqueada",
            "project_id": cls.on_track_project.id,
            "parent_id": cls.safe_task.id,
            "depend_on_ids": [Command.link(cls.blocker_task.id)],
        })
        cls.blocked_subtask.write({"state": "04_waiting_normal"})
        cls.overdue_task = cls.env["project.task"].create({
            "name": "Tarea vencida",
            "project_id": cls.on_track_project.id,
            "date_deadline": fields.Datetime.now() - timedelta(days=2),
        })
        cls.env["project.task"].create({
            "name": "Tarea de proyecto terminado",
            "project_id": cls.done_project.id,
            "priority": "1",
            "date_deadline": fields.Datetime.now() + timedelta(days=1),
        })

        cls.project_user = new_test_user(
            cls.env,
            login="project_dashboard_user",
            groups="project.group_project_user",
        )

    @classmethod
    def _create_project(cls, name, partner, status, **extra_values):
        project = cls.env["project.project"].create({
            "name": name,
            "partner_id": partner.id,
            **extra_values,
        })
        if status != "to_define":
            project.write({"last_update_status": status})
        return project

    def setUp(self):
        super().setUp()
        parameters = self.env["ir.config_parameter"]
        for key, default_value in DASHBOARD_HEALTH_DEFAULTS.items():
            parameters.set_param(DASHBOARD_HEALTH_PARAMETERS[key], default_value)

    def _item_by_key(self, items, key):
        return next(item for item in items if item["key"] == key)

    def test_project_detail_dashboard_filters_use_active_projects(self):
        archived_partner = self.env["res.partner"].create({
            "name": "Cliente archivado",
        })
        self._create_project(
            "Proyecto archivado del cliente",
            archived_partner,
            "on_track",
            active=False,
        )

        filters = self.env["project.project"].get_project_detail_dashboard_filters()

        self.assertIn(self.partner_a.id, filters["customer_ids"])
        self.assertIn(self.partner_b.id, filters["customer_ids"])
        self.assertIn(self.partner_private.id, filters["customer_ids"])
        self.assertNotIn(archived_partner.id, filters["customer_ids"])

        selected_filters = (
            self.env["project.project"].get_project_detail_dashboard_filters(
                self.partner_a.id,
                self.on_track_project.id,
            )
        )
        self.assertEqual(
            selected_filters["selected_customer"]["id"],
            self.partner_a.id,
        )
        self.assertEqual(
            selected_filters["selected_project"]["id"],
            self.on_track_project.id,
        )

    def test_project_detail_dashboard_returns_project_data_and_activity_metrics(self):
        data = self.env["project.project"].get_project_detail_dashboard_data(
            self.on_track_project.id,
            self.partner_a.id,
        )

        self.assertEqual(data["project"]["id"], self.on_track_project.id)
        self.assertEqual(data["project"]["customer_name"], "Cliente A")
        self.assertEqual(
            data["project"]["responsible_name"],
            self.on_track_project.user_id.display_name or "Sin asignar",
        )
        self.assertFalse(data["progress"]["percentage"])
        self.assertEqual(
            data["progress"]["total_tasks"],
            self.on_track_project.task_count,
        )
        self.assertEqual(
            data["progress"]["open_tasks"],
            self.on_track_project.open_task_count,
        )
        self.assertEqual(data["progress"]["mode"], "general")
        self.assertFalse(data["progress"]["planned"])
        completed_domain = self._item_by_key(
            data["progress"]["metrics"], "completed"
        )["domain"]
        self.assertIn(("project_id", "=", self.on_track_project.id), completed_domain)
        self.assertIn(("active", "=", True), completed_domain)
        self.assertIn(("display_in_project", "=", True), completed_domain)
        self.assertIn(("state", "in", ["1_done", "1_canceled"]), completed_domain)
        state_counts = {
            state["key"]: state["count"]
            for state in data["activities_by_state"]
        }
        self.assertGreaterEqual(state_counts["01_in_progress"], 1)
        self.assertGreaterEqual(state_counts["1_done"], 1)
        self.assertEqual(data["critical_activities"]["count"], 2)
        self.assertEqual(
            data["critical_activities"]["items"][0]["name"],
            "Tarea vencida",
        )

    def test_project_detail_dashboard_state_scopes_return_matching_domains(self):
        main_task = self.env["project.task"].create({
            "name": "Principal hecha",
            "project_id": self.on_track_project.id,
            "state": "1_done",
        })
        subtask = self.env["project.task"].create({
            "name": "Subtarea en progreso",
            "project_id": self.on_track_project.id,
            "parent_id": main_task.id,
        })

        data = self.env["project.project"].get_project_detail_dashboard_data(
            self.on_track_project.id,
            self.partner_a.id,
        )
        main_slice = next(
            state for state in data["activity_states_by_scope"]["main"]
            if state["key"] == "1_done"
        )
        subtask_slice = next(
            state for state in data["activity_states_by_scope"]["subtasks"]
            if state["key"] == "01_in_progress"
        )

        self.assertIn(("parent_id", "=", False), main_slice["domain"])
        self.assertIn(("parent_id", "!=", False), subtask_slice["domain"])
        self.assertEqual(
            self.env["project.task"].search_count(main_slice["domain"]),
            main_slice["count"],
        )
        self.assertEqual(
            self.env["project.task"].search_count(subtask_slice["domain"]),
            subtask_slice["count"],
        )
        self.assertIn(main_task, self.env["project.task"].search(main_slice["domain"]))
        self.assertIn(subtask, self.env["project.task"].search(subtask_slice["domain"]))

    def test_project_detail_dashboard_uses_oldest_overdue_activities(self):
        now = fields.Datetime.now()
        earliest = self.env["project.task"].create({
            "name": "Vencida más antigua",
            "project_id": self.on_track_project.id,
            "date_deadline": now - timedelta(days=5),
        })
        middle = self.env["project.task"].create({
            "name": "Vencida intermedia",
            "project_id": self.on_track_project.id,
            "date_deadline": now - timedelta(days=3),
        })

        data = self.env["project.project"].get_project_detail_dashboard_data(
            self.on_track_project.id,
            self.partner_a.id,
        )

        self.assertEqual(data["critical_activities"]["count"], 4)
        self.assertEqual(
            [item["id"] for item in data["critical_activities"]["items"]],
            [earliest.id, middle.id, self.overdue_task.id],
        )

    def test_project_detail_dashboard_falls_back_to_general_progress_after_ten_parents(self):
        project = self._create_project(
            "Proyecto con muchas tareas padre",
            self.partner_a,
            "on_track",
        )
        for index in range(11):
            parent = self.env["project.task"].create({
                "name": f"Tarea padre {index}",
                "project_id": project.id,
                "planned_date_begin": datetime(2026, 1, 1, 12),
                "date_deadline": datetime(2026, 1, 7, 12),
            })
            self.env["project.task"].create({
                "name": f"Subtarea {index}",
                "project_id": project.id,
                "parent_id": parent.id,
            })

        data = self.env["project.project"].get_project_detail_dashboard_data(
            project.id,
            self.partner_a.id,
        )

        self.assertEqual(data["progress"]["mode"], "general")
        self.assertEqual(len(data["progress"]["parent_tasks"]), 11)

    def test_project_detail_dashboard_validates_customer_and_active_project(self):
        self.assertFalse(
            self.env["project.project"].get_project_detail_dashboard_data(
                self.on_track_project.id,
                self.partner_b.id,
            )["project"]
        )
        self.assertFalse(
            self.env["project.project"].get_project_detail_dashboard_data(
                self.archived_project.id,
                self.partner_a.id,
            )["project"]
        )
        self.assertFalse(
            self.env["project.project"].get_project_detail_dashboard_data(
                "invalid",
                self.partner_a.id,
            )["project"]
        )

        unassigned_project = self.env["project.project"].create({
            "name": "Proyecto sin cliente",
        })
        unassigned_data = (
            self.env["project.project"].get_project_detail_dashboard_data(
                unassigned_project.id,
            )
        )
        self.assertEqual(
            unassigned_data["project"]["customer_name"],
            "Sin cliente",
        )

    def test_project_detail_dashboard_respects_project_record_rules(self):
        filters = self.env["project.project"].with_user(
            self.project_user
        ).get_project_detail_dashboard_filters()
        data = self.env["project.project"].with_user(
            self.project_user
        ).get_project_detail_dashboard_data(
            self.private_project.id,
            self.partner_private.id,
        )

        self.assertNotIn(self.partner_private.id, filters["customer_ids"])
        self.assertFalse(data["project"])

    def test_dashboard_metrics_customer_filter_and_click_domains(self):
        data = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )

        self.assertEqual(data["selected_customer"]["id"], self.partner_a.id)
        self.assertEqual(self._item_by_key(data["kpis"], "active")["count"], 4)
        self.assertEqual(self._item_by_key(data["kpis"], "on_track")["count"], 1)
        self.assertEqual(self._item_by_key(data["kpis"], "at_risk")["count"], 1)
        self.assertEqual(self._item_by_key(data["kpis"], "off_track")["count"], 0)
        self.assertNotIn(self.done_project.id, [row["id"] for row in data["projects"]])
        self.assertNotIn(
            self.archived_project.id,
            [row["id"] for row in data["projects"]],
        )

        for metric in (*data["kpis"], *data["alerts"]):
            count = self.env[metric["model"]].search_count(metric["domain"])
            self.assertEqual(count, metric["count"])

    def test_dashboard_includes_subtasks_in_alerts(self):
        data = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )
        critical = self._item_by_key(data["alerts"], "critical")
        upcoming = self._item_by_key(data["alerts"], "upcoming")
        blocked = self._item_by_key(data["alerts"], "blocked")
        no_deadline = self._item_by_key(data["alerts"], "no_deadline")

        self.assertIn(
            self.critical_subtask,
            self.env["project.task"].search(critical["domain"]),
        )
        self.assertNotIn(
            self.safe_task,
            self.env["project.task"].search(critical["domain"]),
        )
        self.assertIn(
            self.upcoming_subtask,
            self.env["project.task"].search(upcoming["domain"]),
        )
        self.assertIn(
            self.blocked_subtask,
            self.env["project.task"].search(blocked["domain"]),
        )
        self.assertIn(
            self.blocker_task,
            self.env["project.task"].search(no_deadline["domain"]),
        )
        self.assertIn(
            self.blocked_subtask,
            self.env["project.task"].search(no_deadline["domain"]),
        )
        self.assertEqual(no_deadline["count"], 2)
        self.assertNotIn(
            self.done_project,
            self.env["project.task"].search(critical["domain"]).project_id,
        )

    def test_project_progress_weights_phase_duration_and_nested_leaf_tasks(self):
        project = self._create_project(
            "Proyecto con fases planificadas",
            self.partner_a,
            "on_track",
        )
        short_phase = self.env["project.task"].create({
            "name": "Fase corta",
            "project_id": project.id,
            "planned_date_begin": datetime(2026, 1, 1, 12),
            "date_deadline": datetime(2026, 1, 7, 12),
        })
        self.env["project.task"].create({
            "name": "Historia hecha",
            "project_id": project.id,
            "parent_id": short_phase.id,
            "state": "1_done",
        })
        self.env["project.task"].create({
            "name": "Historia cancelada",
            "project_id": project.id,
            "parent_id": short_phase.id,
            "state": "1_canceled",
        })
        long_phase = self.env["project.task"].create({
            "name": "Fase larga",
            "project_id": project.id,
            "planned_date_begin": datetime(2026, 1, 1, 12),
            "date_deadline": datetime(2026, 1, 14, 12),
        })
        container = self.env["project.task"].create({
            "name": "Contenedor de historias",
            "project_id": project.id,
            "parent_id": long_phase.id,
        })
        self.env["project.task"].create({
            "name": "Historia anidada hecha",
            "project_id": project.id,
            "parent_id": container.id,
            "state": "1_done",
        })
        self.env["project.task"].create({
            "name": "Historia anidada pendiente",
            "project_id": project.id,
            "parent_id": container.id,
        })

        detail = self.env["project.project"].get_project_detail_dashboard_data(
            project.id,
            self.partner_a.id,
        )
        dashboard = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id,
        )
        project_row = next(row for row in dashboard["projects"] if row["id"] == project.id)

        self.assertEqual(detail["progress"]["percentage"], 50.0)
        self.assertEqual(project_row["progress"], detail["progress"]["percentage"])
        phases = {item["id"]: item for item in detail["progress"]["parent_tasks"]}
        self.assertEqual(phases[short_phase.id]["duration_days"], 7)
        self.assertEqual(phases[long_phase.id]["duration_days"], 14)
        self.assertEqual(phases[short_phase.id]["percentage"], 50.0)
        self.assertEqual(phases[long_phase.id]["percentage"], 50.0)

    def test_project_progress_is_unavailable_when_a_phase_date_is_missing(self):
        project = self._create_project(
            "Proyecto sin planificación completa",
            self.partner_a,
            "on_track",
        )
        self.env["project.task"].create({
            "name": "Fase sin fecha final",
            "project_id": project.id,
            "planned_date_begin": datetime(2026, 1, 1, 12),
        })
        progress = self.env["project.project"]._get_project_execution_progress(
            project
        )
        self.assertFalse(progress["percentage"])

    def test_dashboard_progress_uses_planned_phase_completion(self):
        project = self._create_project(
            "Proyecto de avance general",
            self.partner_a,
            "on_track",
        )
        self.env["project.task"].create({
            "name": "Fase completada",
            "project_id": project.id,
            "planned_date_begin": datetime(2026, 1, 1, 12),
            "date_deadline": datetime(2026, 1, 7, 12),
            "state": "1_done",
        })
        self.env["project.task"].create({
            "name": "Fase pendiente",
            "project_id": project.id,
            "planned_date_begin": datetime(2026, 1, 1, 12),
            "date_deadline": datetime(2026, 1, 14, 12),
        })
        data = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )
        project_row = next(
            row for row in data["projects"]
            if row["id"] == project.id
        )

        self.assertEqual(project_row["progress"], 33.3)
        self.assertEqual(data["health"]["components"]["progress"], 33.3)
        self.assertEqual(data["projects"][0]["id"], self.at_risk_project.id)

    def test_dashboard_health_formula_and_problem_deduplication(self):
        data = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )
        health = data["health"]

        self.assertIsNot(health["score"], False)
        self.assertGreaterEqual(health["components"]["operations"], 0)
        self.assertLessEqual(health["components"]["operations"], 100)
        self.assertFalse(health["components"]["progress"])
        self.assertEqual(
            health["score"],
            round(
                (health["components"]["status"] * 0.3
                 + health["components"]["operations"] * 0.2) / 0.5
            ),
        )

        previous_critical_count = self._item_by_key(
            data["alerts"],
            "critical",
        )["count"]
        new_overdue_task = self.env["project.task"].create({
            "name": "Otra tarea retrasada",
            "project_id": self.on_track_project.id,
            "date_deadline": fields.Datetime.now() - timedelta(days=1),
        })
        refreshed = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )
        self.assertEqual(
            previous_critical_count + 1,
            self._item_by_key(refreshed["alerts"], "critical")["count"],
        )
        self.assertIn(
            new_overdue_task,
            self.env["project.task"].search(
                self._item_by_key(refreshed["alerts"], "critical")["domain"]
            ),
        )
        self.assertGreaterEqual(refreshed["health"]["components"]["operations"], 0)

    def test_dashboard_no_data_and_invalid_saved_customer(self):
        empty_partner = self.env["res.partner"].create({"name": "Sin proyectos"})
        data = self.env["project.project"].get_project_dashboard_data(
            empty_partner.id
        )

        self.assertFalse(data["selected_customer"])
        self.assertGreater(self._item_by_key(data["kpis"], "active")["count"], 0)

        self.env["project.project"].search([
            ("active", "=", True),
            ("last_update_status", "!=", "done"),
        ]).write({"active": False})
        empty_data = self.env["project.project"].get_project_dashboard_data()
        self.assertFalse(empty_data["projects"])
        self.assertFalse(empty_data["health"]["score"])
        self.assertEqual(empty_data["health"]["label"], "Sin datos")

    def test_dashboard_health_configuration_falls_back_safely(self):
        parameters = self.env["ir.config_parameter"]
        parameters.set_param(
            DASHBOARD_HEALTH_PARAMETERS["progress_weight"],
            "invalid",
        )
        parameters.set_param(
            DASHBOARD_HEALTH_PARAMETERS["status_weight"],
            99,
        )
        configuration = (
            self.env["project.project"]._get_dashboard_health_configuration()
        )

        self.assertEqual(
            configuration["progress_weight"],
            DASHBOARD_HEALTH_DEFAULTS["progress_weight"],
        )
        self.assertEqual(
            configuration["status_weight"],
            DASHBOARD_HEALTH_DEFAULTS["status_weight"],
        )

    def test_dashboard_health_uses_custom_configuration(self):
        parameters = self.env["ir.config_parameter"]
        parameters.set_param(DASHBOARD_HEALTH_PARAMETERS["progress_weight"], 0)
        parameters.set_param(DASHBOARD_HEALTH_PARAMETERS["status_weight"], 0)
        parameters.set_param(DASHBOARD_HEALTH_PARAMETERS["operations_weight"], 100)
        parameters.set_param(DASHBOARD_HEALTH_PARAMETERS["healthy_threshold"], 90)
        parameters.set_param(DASHBOARD_HEALTH_PARAMETERS["attention_threshold"], 70)

        health = self.env["project.project"].get_project_dashboard_data(
            self.partner_a.id
        )["health"]

        self.assertEqual(
            health["score"],
            round(health["components"]["operations"]),
        )
        self.assertEqual(health["label"], "Crítica")

    def test_dashboard_health_settings_validation(self):
        Settings = self.env["res.config.settings"]
        with self.assertRaises(ValidationError):
            Settings.create({
                "project_dashboard_progress_weight": 80,
                "project_dashboard_status_weight": 30,
                "project_dashboard_operations_weight": 20,
            })
        with self.assertRaises(ValidationError):
            Settings.create({
                "project_dashboard_progress_weight": 50,
                "project_dashboard_status_weight": 30,
                "project_dashboard_operations_weight": 20,
                "project_dashboard_healthy_threshold": 50,
                "project_dashboard_attention_threshold": 75,
            })

    def test_dashboard_respects_project_record_rules(self):
        data = self.env["project.project"].with_user(
            self.project_user
        ).get_project_dashboard_data()

        self.assertNotIn(
            self.private_project.id,
            [row["id"] for row in data["projects"]],
        )
        self.assertNotIn(self.partner_private.id, data["customer_ids"])

    def test_sprint_dashboard_orders_tasks_and_filters_by_sprint(self):
        project = self._create_project(
            "Proyecto con Sprints",
            self.partner_a,
            "on_track",
        )
        first_sprint = self.env["project.sprint"].create({
            "name": "Sprint primero",
            "project_id": project.id,
            "sequence": 10,
        })
        second_sprint = self.env["project.sprint"].create({
            "name": "Sprint segundo",
            "project_id": project.id,
            "sequence": 20,
        })
        task_unprioritized = self.env["project.task"].create({
            "name": "Sin prioridad",
            "project_id": project.id,
            "sprint_id": first_sprint.id,
            "state": "1_canceled",
        })
        task_first = self.env["project.task"].create({
            "name": "Prioridad uno",
            "project_id": project.id,
            "sprint_id": first_sprint.id,
            "hierarchical_priority": 1,
            "state": "1_done",
        })
        task_later_sprint = self.env["project.task"].create({
            "name": "Sprint posterior",
            "project_id": project.id,
            "sprint_id": second_sprint.id,
            "hierarchical_priority": 1,
        })
        task_without_sprint = self.env["project.task"].create({
            "name": "Sin Sprint",
            "project_id": project.id,
        })

        all_data = self.env["project.project"].get_project_sprint_dashboard_data(
            project.id,
        )
        first_data = self.env["project.project"].get_project_sprint_dashboard_data(
            project.id,
            str(first_sprint.id),
        )
        none_data = self.env["project.project"].get_project_sprint_dashboard_data(
            project.id,
            "none",
        )
        detail = self.env["project.project"].get_project_detail_dashboard_data(
            project.id,
            self.partner_a.id,
        )
        sprint_summaries = {item["id"]: item for item in detail["sprints"]}

        self.assertEqual(all_data["count"], 4)
        self.assertEqual(
            [task["id"] for task in all_data["tasks"]],
            [task_first.id, task_unprioritized.id, task_later_sprint.id, task_without_sprint.id],
        )
        self.assertEqual(first_data["count"], 2)
        self.assertEqual(first_data["tasks"][0]["id"], task_first.id)
        self.assertEqual(none_data["count"], 1)
        self.assertEqual(none_data["tasks"][0]["id"], task_without_sprint.id)
        self.assertEqual(sprint_summaries[first_sprint.id]["total"], 2)
        self.assertEqual(sprint_summaries[False]["total"], 1)
        first_sprint_states = {
            state["key"]: state["count"]
            for state in sprint_summaries[first_sprint.id]["states"]
        }
        self.assertEqual(first_sprint_states["1_done"], 1)
        self.assertEqual(first_sprint_states["1_canceled"], 1)
        self.assertEqual(
            self.env["project.task"].search_count(first_data["domain"]),
            first_data["count"],
        )

    def test_sprint_permissions_follow_project_visibility_and_clients_read_only(self):
        project = self._create_project(
            "Proyecto con permisos de Sprint",
            self.partner_a,
            "on_track",
        )
        assigned_task = self.env["project.task"].create({
            "name": "Tarea del usuario interno",
            "project_id": project.id,
            "user_ids": [Command.link(self.project_user.id)],
        })
        sprint_model = self.env["project.sprint"]
        sprint = sprint_model.with_user(self.project_user).create({
            "name": "Sprint interno",
            "project_id": project.id,
        })
        self.assertTrue(sprint_model.with_user(self.project_user).search([
            ("id", "=", sprint.id),
        ]))

        client = new_test_user(
            self.env,
            login="project_sprint_client",
            groups="project_custom_extension.group_project_client",
        )
        assigned_task.write({"user_ids": [Command.link(client.id)]})
        self.assertTrue(sprint_model.with_user(client).search([
            ("id", "=", sprint.id),
        ]))
        with self.assertRaises(AccessError):
            sprint_model.with_user(client).browse(sprint.id).write({
                "name": "Cambio no permitido",
            })

    def test_task_cannot_use_a_sprint_from_another_project(self):
        other_project = self.env["project.project"].create({
            "name": "Otro proyecto",
        })
        sprint = self.env["project.sprint"].create({
            "name": "Sprint ajeno",
            "project_id": other_project.id,
        })
        task = self.env["project.task"].create({
            "name": "Tarea de prueba",
            "project_id": self.on_track_project.id,
        })
        with self.assertRaises(ValidationError):
            task.write({"sprint_id": sprint.id})

    def test_warranty_cron_closes_due_projects_and_notifies_once(self):
        today = fields.Date.context_today(self.env["project.project"])
        parameters = self.env["ir.config_parameter"]
        parameters.set_param(
            WARRANTY_ACTIVATION_PARAMETER,
            fields.Date.to_string(today),
        )
        manager = new_test_user(
            self.env,
            login="warranty_project_manager",
            groups="project.group_project_manager",
        )
        victor = self.env["res.users"].search(
            [("login", "=", WARRANTY_VICTOR_LOGIN)],
            limit=1,
        ) or new_test_user(
            self.env,
            login=WARRANTY_VICTOR_LOGIN,
            groups="project.group_project_user",
        )
        manager.partner_id.email = "manager@example.com"
        victor.partner_id.email = "victor@example.com"
        self.assertEqual(manager.email, "manager@example.com")
        self.assertEqual(victor.email, "victor@example.com")
        due_project = self._create_project(
            "Garantía vence hoy",
            self.partner_a,
            "on_track",
            user_id=manager.id,
            warranty_end_date=today,
        )
        self.assertEqual(due_project.user_id, manager)
        past_project = self._create_project(
            "Garantía histórica",
            self.partner_a,
            "on_track",
            warranty_end_date=today - timedelta(days=1),
        )
        root_user = self.env.ref("base.user_root")
        project_model = self.env["project.project"].with_user(root_user)

        project_model._cron_close_projects_after_warranty()

        self.assertEqual(due_project.last_update_status, "done")
        self.assertEqual(due_project.warranty_auto_closed_on, today)
        self.assertEqual(past_project.last_update_status, "on_track")
        activities = self.env["mail.activity"].search([
            ("res_model", "=", "project.project"),
            ("res_id", "=", due_project.id),
            ("summary", "=", "Garantía finalizada"),
        ])
        self.assertEqual(set(activities.mapped("user_id").ids), {manager.id, victor.id})
        mail_model = self.env["mail.mail"]
        queued_addresses = mail_model.search([]).mapped("email_to")
        self.assertIn("manager@example.com", queued_addresses)
        self.assertIn("victor@example.com", queued_addresses)

        activity_count = len(activities)
        mail_count = mail_model.search_count([
            ("email_to", "ilike", "manager@example.com"),
        ]) + mail_model.search_count([
            ("email_to", "ilike", "victor@example.com"),
        ])
        project_model._cron_close_projects_after_warranty()
        self.assertEqual(
            self.env["mail.activity"].search_count([
                ("res_model", "=", "project.project"),
                ("res_id", "=", due_project.id),
                ("summary", "=", "Garantía finalizada"),
            ]),
            activity_count,
        )
        self.assertEqual(
            mail_model.search_count([
                ("email_to", "ilike", "manager@example.com"),
            ]) + mail_model.search_count([
                ("email_to", "ilike", "victor@example.com"),
            ]),
            mail_count,
        )

    def test_warranty_cron_closes_when_recipients_are_missing_and_logs_them(self):
        today = fields.Date.context_today(self.env["project.project"])
        self.env["ir.config_parameter"].set_param(
            WARRANTY_ACTIVATION_PARAMETER,
            fields.Date.to_string(today),
        )
        victor = self.env["res.users"].search(
            [("login", "=", WARRANTY_VICTOR_LOGIN)],
            limit=1,
        ) or new_test_user(
            self.env,
            login=WARRANTY_VICTOR_LOGIN,
            groups="project.group_project_user",
        )
        victor.partner_id.email = False
        project = self._create_project(
            "Proyecto sin destinatario completo",
            self.partner_a,
            "on_track",
            user_id=False,
            warranty_end_date=today,
        )

        self.env["project.project"].with_user(
            self.env.ref("base.user_root")
        )._cron_close_projects_after_warranty()

        self.assertEqual(project.last_update_status, "done")
        activities = self.env["mail.activity"].search([
            ("res_model", "=", "project.project"),
            ("res_id", "=", project.id),
            ("summary", "=", "Garantía finalizada"),
        ])
        self.assertEqual(activities.mapped("user_id").ids, [victor.id])
        self.assertFalse(self.env["mail.mail"].search([
            ("email_to", "ilike", WARRANTY_VICTOR_LOGIN),
        ]))
        self.assertIn(
            "gerente del proyecto sin asignar",
            " ".join(project.message_ids.mapped("body")),
        )

    def test_warranty_cron_deduplicates_recipients_with_the_same_email(self):
        today = fields.Date.context_today(self.env["project.project"])
        self.env["ir.config_parameter"].set_param(
            WARRANTY_ACTIVATION_PARAMETER,
            fields.Date.to_string(today),
        )
        manager = new_test_user(
            self.env,
            login="warranty_shared_email_manager",
            groups="project.group_project_manager",
        )
        victor = self.env["res.users"].search(
            [("login", "=", WARRANTY_VICTOR_LOGIN)],
            limit=1,
        ) or new_test_user(
            self.env,
            login=WARRANTY_VICTOR_LOGIN,
            groups="project.group_project_user",
        )
        shared_email = "shared-warranty@example.com"
        manager.partner_id.email = shared_email
        victor.partner_id.email = shared_email
        project = self._create_project(
            "Garantía con correo compartido",
            self.partner_a,
            "on_track",
            user_id=manager.id,
            warranty_end_date=today,
        )

        self.env["project.project"].with_user(
            self.env.ref("base.user_root")
        )._cron_close_projects_after_warranty()

        activities = self.env["mail.activity"].search([
            ("res_model", "=", "project.project"),
            ("res_id", "=", project.id),
            ("summary", "=", "Garantía finalizada"),
        ])
        self.assertEqual(set(activities.mapped("user_id").ids), {manager.id, victor.id})
        self.assertEqual(
            self.env["mail.mail"].search_count([
                ("email_to", "=", shared_email),
            ]),
            1,
        )
