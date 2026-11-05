"""Mejoras del proyecto "Mejoras Gestión de proyectos Odoo" (noviembre 2026)."""

from datetime import date, datetime, timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.project_project import (
    AT_RISK_LABEL,
    WARRANTY_ACTIVATION_PARAMETER,
    WARRANTY_TIMEZONE,
    natural_sort_key,
)
from ..models.resource_calendar import colombia_public_holidays


@tagged("post_install", "-at_install")
class TestProjectImprovements(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.Entry = cls.env["project.task.time.entry"]
        cls.manager = new_test_user(
            cls.env,
            login="improvements_manager",
            name="Gerente Mejoras",
            groups="project.group_project_manager",
        )
        cls.worker = new_test_user(
            cls.env,
            login="improvements_worker",
            name="Analista Mejoras",
            groups="project.group_project_user",
        )
        cls.worker_employee = cls.env["hr.employee"].create({
            "name": "Analista Mejoras",
            "user_id": cls.worker.id,
            "company_type": "tdp",
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "Empresa Mejoras",
            "is_company": True,
            "email": "empresa@mejoras.example.com",
        })
        cls.customer_contact = cls.env["res.partner"].create({
            "name": "Contacto Mejoras",
            "parent_id": cls.customer.id,
            "email": "contacto@mejoras.example.com",
        })
        cls.project = cls.Project.create({
            "name": "Proyecto mejoras",
            "partner_id": cls.customer.id,
            "user_id": cls.manager.id,
        })

    # ------------------------------------------------------------------
    # 2368: orden de fases
    # ------------------------------------------------------------------

    def test_natural_sort_key_orders_numbers_by_value(self):
        names = ["Fase 10", "Fase 2", "fase 1", "Garantía"]
        self.assertEqual(
            sorted(names, key=natural_sort_key),
            ["fase 1", "Fase 2", "Fase 10", "Garantía"],
        )

    def test_phases_follow_start_date_then_natural_name(self):
        start = datetime(2026, 9, 14, 13, 0)
        # Sequences as left by kanban drag and drop: they must be ignored.
        values = [
            ("Fase 4 Pruebas", start + timedelta(days=17), 0),
            ("Fase 3 Construcción II", start + timedelta(days=3), 1),
            ("Fase 1 Levantamiento", start, 0),
            ("Fase 2 Construcción I", start + timedelta(days=3), 0),
            ("Garantía", False, 0),
        ]
        for name, begin, sequence in values:
            self.Task.create({
                "name": name,
                "project_id": self.project.id,
                "planned_date_begin": begin,
                "date_deadline": begin + timedelta(days=2) if begin else False,
                "sequence": sequence,
                "project_weight": 20 if begin else 0,
            })
        expected = [
            "Fase 1 Levantamiento",
            "Fase 2 Construcción I",
            "Fase 3 Construcción II",
            "Fase 4 Pruebas",
            "Garantía",
        ]
        progress = self.Project._get_project_execution_progress(self.project)
        self.assertEqual([phase["task"].name for phase in progress["phases"]], expected)

        gantt = self.Project.get_project_gantt_data(self.project.id)
        self.assertEqual(
            [row["name"] for row in gantt["rows"] if not row["parent_id"]],
            expected,
        )

        dashboard = self.Project.get_project_detail_dashboard_data(self.project.id)
        self.assertEqual(
            [phase["name"] for phase in dashboard["filters"]["phases"]], expected
        )

    # ------------------------------------------------------------------
    # 2656: etapa en el gantt
    # ------------------------------------------------------------------

    def test_gantt_rows_include_the_task_stage(self):
        stage = self.project.type_ids.sorted("sequence")[1]
        task = self.Task.create({
            "name": "Tarea con etapa",
            "project_id": self.project.id,
            "stage_id": stage.id,
        })
        rows = self.Project.get_project_gantt_data(self.project.id)["rows"]
        row = next(row for row in rows if row["id"] == task.id)
        self.assertEqual(row["stage_name"], task.unified_stage_id.name or stage.name)
        self.assertTrue(row["stage_name"])

    # ------------------------------------------------------------------
    # 2654: "En riesgo de atraso" también en el estado nativo
    # ------------------------------------------------------------------

    def test_native_at_risk_status_uses_the_new_label(self):
        for model, field_name in (
            ("project.project", "last_update_status"),
            ("project.update", "status"),
        ):
            selection = dict(
                self.env[model].fields_get([field_name])[field_name]["selection"]
            )
            self.assertEqual(selection["at_risk"], AT_RISK_LABEL)

    # ------------------------------------------------------------------
    # 2408 / 2447 / 2653: dashboard general
    # ------------------------------------------------------------------

    def test_users_without_timezone_use_bogota_day_start(self):
        self.manager.tz = False
        start = self.Project.with_user(self.manager).with_context(tz=False)._dashboard_local_day_start(
            date(2026, 10, 6)
        )
        # 00:00 in Bogotá is 05:00 UTC.
        self.assertEqual(start, datetime(2026, 10, 6, 5, 0))

    def test_future_cutoff_month_is_measured_today(self):
        today = fields.Date.context_today(self.Project)
        next_month = (today.replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
        self.assertEqual(self.Project._project_detail_reference_date(next_month), today)

    def test_general_dashboard_date_filter_keeps_open_ended_projects(self):
        today = fields.Date.context_today(self.Project)
        open_ended = self.Project.create({
            "name": "Proyecto sin fecha fin",
            "date_start": today - timedelta(days=30),
        })
        undated = self.Project.create({"name": "Proyecto sin fechas"})
        finished_before = self.Project.create({
            "name": "Proyecto de otro año",
            "date_start": today - timedelta(days=800),
            "date": today - timedelta(days=700),
        })
        data = self.Project.get_project_dashboard_data(
            date_from=fields.Date.to_string(today - timedelta(days=10)),
        )
        ids = {row["id"] for row in data["projects"]}
        self.assertIn(open_ended.id, ids)
        self.assertNotIn(undated.id, ids)
        self.assertNotIn(finished_before.id, ids)

    def test_general_dashboard_rows_include_the_deviation(self):
        today = fields.Date.context_today(self.Project)
        self.project.write({
            "date_start": today - timedelta(days=50),
            "date": today + timedelta(days=50),
        })
        self.Task.create({
            "name": "Fase única",
            "project_id": self.project.id,
            "project_weight": 100,
        })
        data = self.Project.get_project_dashboard_data()
        row = next(row for row in data["projects"] if row["id"] == self.project.id)
        self.assertEqual(row["expected_progress"], 50.0)
        self.assertEqual(row["deviation"], -50.0)

    # ------------------------------------------------------------------
    # 2500: entregables
    # ------------------------------------------------------------------

    def test_delivered_date_is_kept_when_written_again(self):
        phase = self.Task.create({"name": "Fase", "project_id": self.project.id})
        deliverable = self.env["project.deliverable"].create({
            "name": "Documento",
            "phase_id": phase.id,
            "state": "delivered",
            "date_delivered": date(2026, 10, 1),
        })
        deliverable.write({"state": "delivered"})
        self.assertEqual(deliverable.date_delivered, date(2026, 10, 1))
        deliverable.write({"state": "pending"})
        self.assertFalse(deliverable.date_delivered)
        deliverable.write({"state": "delivered"})
        self.assertEqual(
            deliverable.date_delivered, fields.Date.context_today(deliverable)
        )

    def test_deliverables_delivered_after_a_past_cutoff_count_as_pending(self):
        phase = self.Task.create({"name": "Fase", "project_id": self.project.id})
        Deliverable = self.env["project.deliverable"]
        Deliverable.create([{
            "name": "Entregado a tiempo",
            "phase_id": phase.id,
            "state": "delivered",
            "date_delivered": date(2026, 8, 20),
        }, {
            "name": "Entregado después",
            "phase_id": phase.id,
            "state": "delivered",
            "date_delivered": date(2026, 9, 10),
        }])
        result = self.Project._project_detail_deliverables(
            self.project, [phase], date(2026, 8, 31)
        )
        self.assertEqual((result["done"], result["total"]), (1, 2))

    # ------------------------------------------------------------------
    # 2595: festivos
    # ------------------------------------------------------------------

    def test_colombia_holidays_2026(self):
        holidays = dict(colombia_public_holidays(2026))
        self.assertEqual(len(holidays), 18)
        for day, name in (
            (date(2026, 1, 1), "Año Nuevo"),
            (date(2026, 1, 12), "Reyes Magos"),
            (date(2026, 3, 23), "San José"),
            (date(2026, 4, 2), "Jueves Santo"),
            (date(2026, 4, 3), "Viernes Santo"),
            (date(2026, 5, 18), "Ascensión del Señor"),
            (date(2026, 6, 8), "Corpus Christi"),
            (date(2026, 6, 15), "Sagrado Corazón"),
            (date(2026, 8, 17), "Asunción de la Virgen"),
            (date(2026, 10, 12), "Día de la Raza"),
            (date(2026, 11, 2), "Todos los Santos"),
            (date(2026, 11, 16), "Independencia de Cartagena"),
            (date(2026, 12, 25), "Navidad"),
        ):
            self.assertEqual(holidays.get(day), name)

    def test_holiday_sync_is_idempotent_and_respects_loaded_years(self):
        Calendar = self.env["resource.calendar"]
        calendar = self.env.company.resource_calendar_id
        Calendar._tdp_sync_colombia_holidays([2030])
        holidays = calendar._tdp_holidays(date(2030, 1, 1), date(2030, 12, 31))
        # Two holidays may fall on the same Monday (2030: San Pedro and
        # Sagrado Corazón, both on July 1).
        self.assertEqual(
            len(holidays), len({day for day, _name in colombia_public_holidays(2030)})
        )
        self.assertEqual(Calendar._tdp_sync_colombia_holidays([2030]), 0)

    def test_grid_credits_holiday_hours(self):
        self.env["resource.calendar"]._tdp_sync_colombia_holidays([2026])
        task = self.Task.create({
            "name": "Tarea semana festiva",
            "project_id": self.project.id,
            "user_ids": [Command.set([self.worker.id])],
        })
        for day in (13, 14, 15, 16):
            self.Entry.with_user(self.worker).create({
                "task_id": task.id,
                "date": date(2026, 10, day),
                "unit_amount": 8,
            })
        with freeze_time("2026-10-19 15:00:00"):
            data = self.Entry.with_user(self.manager).with_context(
                tz="America/Bogota"
            ).get_time_grid_data(
                "2026-10-12", "2026-10-18", "employee",
                {"employee_id": self.worker_employee.id},
            )
        group = next(g for g in data["groups"] if g["employee_id"] == self.worker_employee.id)
        holiday_line = next(line for line in group["lines"] if line["is_holiday"])
        self.assertEqual(holiday_line["daily"], {"2026-10-12": 8.0})
        self.assertEqual(group["daily"]["2026-10-12"], 8.0)
        self.assertEqual(group["total"], 40.0)
        self.assertEqual(group["expected"], 40.0)
        self.assertEqual(group["balance"], 0.0)
        self.assertNotIn("2026-10-12", group["missing_days"])
        monday = next(day for day in data["days"] if day["date"] == "2026-10-12")
        self.assertEqual(monday["holiday"], "Día de la Raza")
        # The holiday line is listed after the projects.
        self.assertTrue(group["lines"][-1]["is_holiday"])

    def test_missing_hours_alerts_skip_holidays(self):
        self.env["resource.calendar"]._tdp_sync_colombia_holidays([2026])
        with freeze_time("2026-10-13 21:00:00"):
            missing = self.Entry.with_context(tz="America/Bogota")._time_entry_missing_hours(
                self.worker_employee, date(2026, 10, 12), date(2026, 10, 13)
            )
        self.assertEqual(missing[self.worker_employee]["missing_days"], [date(2026, 10, 13)])

    # ------------------------------------------------------------------
    # 2491: agrupación por empresa cliente
    # ------------------------------------------------------------------

    def test_grid_by_customer_groups_contacts_of_the_same_company(self):
        contact_project = self.Project.create({
            "name": "Proyecto de un contacto",
            "partner_id": self.customer_contact.id,
        })
        for project in (self.project, contact_project):
            task = self.Task.create({
                "name": f"Tarea {project.name}",
                "project_id": project.id,
                "user_ids": [Command.set([self.worker.id])],
            })
            self.Entry.with_user(self.worker).create({
                "task_id": task.id,
                "date": date(2026, 10, 14),
                "unit_amount": 2,
            })
        data = self.Entry.with_user(self.manager).get_time_grid_data(
            "2026-10-12", "2026-10-18", "customer"
        )
        group = next(g for g in data["groups"] if g["key"] == self.customer.id)
        self.assertEqual(group["total"], 4)
        self.assertEqual(len(group["lines"]), 2)

    # ------------------------------------------------------------------
    # 2372: interruptores de las alertas
    # ------------------------------------------------------------------

    def test_settings_switch_the_time_alert_crons(self):
        reminder = self.env.ref("project_custom_extension.ir_cron_remind_missing_hours")
        summary = self.env.ref(
            "project_custom_extension.ir_cron_notify_missing_hours_summary"
        )
        reminder.active = summary.active = True
        settings = self.env["res.config.settings"].create({})
        self.assertTrue(settings.project_time_alert_reminder)
        settings.project_time_alert_reminder = False
        settings.execute()
        self.assertFalse(reminder.active)
        self.assertTrue(summary.active)

    # ------------------------------------------------------------------
    # 2403: fechas de subtareas (ver también test_project_unified_stage)
    # ------------------------------------------------------------------

    def test_subtask_of_an_overdue_parent_takes_its_end_date(self):
        parent = self.Task.create({
            "name": "Padre vencido",
            "project_id": self.project.id,
            "date_deadline": fields.Datetime.now() - timedelta(days=3),
        })
        child = self.Task.create({
            "name": "Hija",
            "project_id": self.project.id,
            "parent_id": parent.id,
        })
        self.assertEqual(child.date_deadline, parent.date_deadline)
        self.assertLessEqual(child.planned_date_begin, child.date_deadline)

    # ------------------------------------------------------------------
    # 2366: aviso de fin de garantía al cliente
    # ------------------------------------------------------------------

    def test_warranty_end_notifies_the_configured_customer_contacts(self):
        today = fields.Date.context_today(self.Project.with_context(tz=WARRANTY_TIMEZONE))
        self.env["ir.config_parameter"].set_param(
            WARRANTY_ACTIVATION_PARAMETER, fields.Date.to_string(today)
        )
        no_email = self.env["res.partner"].create({
            "name": "Contacto sin correo",
            "parent_id": self.customer.id,
        })
        self.manager.email = "gerente@mejoras.example.com"
        self.project.write({
            "warranty_end_date": today,
            "warranty_notify_partner_ids": [
                Command.set([self.customer_contact.id, no_email.id])
            ],
        })
        self.Project.with_user(self.env.ref("base.user_root"))._cron_close_projects_after_warranty()

        customer_mails = self.env["mail.mail"].search([
            ("email_to", "=", "contacto@mejoras.example.com"),
        ])
        self.assertEqual(len(customer_mails), 1)
        self.assertIn("Finalización del periodo de garantía", customer_mails.subject)
        self.assertNotIn("Terminado", customer_mails.body_html)
        # The internal notice to the PM is still sent.
        self.assertTrue(self.env["mail.mail"].search([
            ("email_to", "=", "gerente@mejoras.example.com"),
        ]))
        self.assertIn(
            "Contacto sin correo",
            " ".join(self.project.message_ids.mapped("body")),
        )

    def test_warranty_contacts_must_belong_to_the_customer_in_the_view_domain(self):
        field = self.Project._fields["warranty_notify_partner_ids"]
        self.assertIn("child_of", field.domain)

    # ------------------------------------------------------------------
    # 2657: staffing
    # ------------------------------------------------------------------

    def test_service_observations_history(self):
        staffing = self.Project.create({
            "name": "Staffing desarrollador",
            "partner_id": self.customer.id,
            "project_type": "staffing",
        })
        Observation = self.env["project.service.observation"]
        older = Observation.create({
            "name": "Inicio del servicio",
            "project_id": staffing.id,
            "date": date(2026, 9, 1),
            "resource_user_id": self.worker.id,
        })
        newer = Observation.create({
            "name": "Novedad de vacaciones",
            "project_id": staffing.id,
            "date": date(2026, 10, 1),
            "observation_type": "novelty",
        })
        staffing.invalidate_recordset(["service_observation_ids"])
        self.assertEqual(staffing.service_observation_ids, newer | older)
        self.assertEqual(staffing.service_observation_ids[0], newer)
        self.assertEqual(staffing.service_observation_count, 2)
        self.assertEqual(newer.partner_id, self.customer)
        self.assertEqual(newer.author_id, self.env.user)
        self.assertEqual(self.project.project_type, "project")

    def test_clients_only_read_observations_of_their_company(self):
        client = new_test_user(
            self.env,
            login="improvements_client",
            groups="project_custom_extension.group_project_client",
        )
        client.partner_id.parent_id = self.customer
        other = self.Project.create({"name": "Servicio ajeno", "project_type": "support"})
        Observation = self.env["project.service.observation"]
        own = Observation.create({"name": "Propia", "project_id": self.project.id})
        Observation.create({"name": "Ajena", "project_id": other.id})
        self.assertEqual(Observation.with_user(client).search([]), own)

    # ------------------------------------------------------------------
    # 2658: sistemas por cliente
    # ------------------------------------------------------------------

    def test_client_system_traceability(self):
        odoo = self.env["project.system"].create({
            "name": "Odoo",
            "module_ids": [
                Command.create({"name": "Ventas"}),
                Command.create({"name": "Contabilidad"}),
            ],
        })
        other_system = self.env["project.system"].create({
            "name": "Sofía",
            "module_ids": [Command.create({"name": "Agenda"})],
        })
        sales, accounting = odoo.module_ids
        client_system = self.env["project.client.system"].create({
            "partner_id": self.customer.id,
            "system_id": odoo.id,
            "module_line_ids": [
                Command.create({"module_id": sales.id}),
                Command.create({"module_id": accounting.id, "state": "inactive"}),
            ],
        })
        self.assertEqual(client_system.display_name, "Empresa Mejoras · Odoo")
        self.assertEqual(client_system.active_module_count, 1)
        with self.assertRaises(ValidationError):
            self.env["project.client.system.module"].create({
                "client_system_id": client_system.id,
                "module_id": other_system.module_ids.id,
            })

        customization = self.env["project.system.customization"].create({
            "name": "Reporte de cartera",
            "client_system_id": client_system.id,
            "module_id": accounting.id,
        })
        self.assertEqual(client_system.open_customization_count, 1)
        self.assertEqual(customization.partner_id, self.customer)
        customization.state = "delivered"
        self.assertEqual(
            customization.delivery_date, fields.Date.context_today(customization)
        )
        self.assertEqual(client_system.open_customization_count, 0)
        self.assertEqual(self.customer_contact.client_system_count, 1)
        action = self.customer_contact.action_open_client_systems()
        self.assertEqual(action["domain"], [("partner_id", "=", self.customer.id)])
