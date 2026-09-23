from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProjectRoleAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.customer_company = cls.env["res.partner"].create({
            "name": "Empresa cliente de seguridad",
            "is_company": True,
        })
        cls.customer_contact = cls.env["res.partner"].create({
            "name": "Contacto relacionado",
            "parent_id": cls.customer_company.id,
        })
        cls.other_customer = cls.env["res.partner"].create({
            "name": "Empresa ajena a seguridad",
            "is_company": True,
        })

        cls.project_user = new_test_user(
            cls.env,
            login="project_role_user",
            groups="project.group_project_user",
        )
        cls.client_user = new_test_user(
            cls.env,
            login="project_role_client",
            groups="project_custom_extension.group_project_client",
        )
        cls.client_user.partner_id.write({
            "parent_id": cls.customer_company.id,
        })
        cls.generic_user = new_test_user(
            cls.env,
            login="project_role_generic_internal",
            groups="base.group_user",
        )
        cls.manager = new_test_user(
            cls.env,
            login="project_role_manager",
            groups="project.group_project_manager",
        )

        cls.user_project = cls._create_project(
            "Proyecto por tarea asignada al Usuario",
            cls.other_customer,
        )
        cls.user_assigned_task = cls._create_task(
            "Tarea asignada al Usuario",
            cls.user_project,
            cls.project_user,
        )
        cls.user_context_task = cls._create_task(
            "Tarea de contexto del Usuario",
            cls.user_project,
        )
        cls.client_project = cls._create_project(
            "Proyecto por tarea asignada al Cliente",
            cls.other_customer,
        )
        cls.client_assigned_task = cls._create_task(
            "Tarea asignada al Cliente",
            cls.client_project,
            cls.client_user,
        )
        cls.client_context_task = cls._create_task(
            "Tarea de contexto del Cliente",
            cls.client_project,
        )
        cls.customer_project = cls._create_project(
            "Proyecto de la empresa del Cliente",
            cls.customer_contact,
        )
        cls.customer_project_task = cls._create_task(
            "Tarea de la empresa del Cliente",
            cls.customer_project,
        )
        cls.foreign_project = cls._create_project(
            "Proyecto sin relación",
            cls.other_customer,
        )
        cls.foreign_task = cls._create_task(
            "Tarea sin relación",
            cls.foreign_project,
        )
        cls.archived_task_project = cls._create_project(
            "Proyecto con tarea archivada",
            cls.other_customer,
        )
        cls.archived_assigned_task = cls._create_task(
            "Tarea archivada asignada al Usuario",
            cls.archived_task_project,
            cls.project_user,
            active=False,
        )
        cls.archived_project = cls._create_project(
            "Proyecto archivado asignado al Cliente",
            cls.other_customer,
            active=False,
        )
        cls.archived_project_task = cls._create_task(
            "Tarea activa en proyecto archivado",
            cls.archived_project,
            cls.client_user,
        )

    @classmethod
    def _create_project(cls, name, partner, **values):
        return cls.Project.create({
            "name": name,
            "partner_id": partner.id,
            **values,
        })

    @classmethod
    def _create_task(cls, name, project, assignee=None, **values):
        task_values = {
            "name": name,
            "project_id": project.id,
            **values,
        }
        if assignee:
            task_values["user_ids"] = [Command.link(assignee.id)]
        return cls.Task.create(task_values)

    def test_project_user_sees_only_owned_or_assigned_projects(self):
        own_project = self.Project.with_user(self.project_user).create({
            "name": "Proyecto creado por Usuario",
            "partner_id": self.other_customer.id,
        })
        visible_ids = set(
            self.Project.with_user(self.project_user).search([]).ids
        )

        self.assertIn(own_project.id, visible_ids)
        self.assertIn(self.user_project.id, visible_ids)
        self.assertNotIn(self.client_project.id, visible_ids)
        self.assertNotIn(self.foreign_project.id, visible_ids)
        self.assertNotIn(self.archived_task_project.id, visible_ids)
        self.assertNotIn(self.archived_project.id, visible_ids)

    def test_project_user_can_edit_only_projects_created_by_them(self):
        own_project = self.Project.with_user(self.project_user).create({
            "name": "Proyecto propio editable",
        })
        own_project.with_user(self.project_user).write({"name": "Proyecto editado"})
        self.assertEqual(own_project.name, "Proyecto editado")

        with self.assertRaises(AccessError):
            self.user_project.with_user(self.project_user).write({
                "name": "Cambio no autorizado",
            })
        with self.assertRaises(AccessError):
            own_project.with_user(self.project_user).unlink()

        with self.assertRaises(AccessError):
            self.user_project.with_user(self.project_user).check_access("write")

    def test_project_user_sees_all_active_tasks_in_visible_projects(self):
        visible_tasks = set(
            self.Task.with_user(self.project_user).search([
                ("project_id", "=", self.user_project.id),
            ]).ids
        )

        self.assertIn(self.user_assigned_task.id, visible_tasks)
        self.assertIn(self.user_context_task.id, visible_tasks)
        self.assertNotIn(self.archived_assigned_task.id, visible_tasks)
        self.assertNotIn(self.foreign_task.id, set(
            self.Task.with_user(self.project_user).search([]).ids
        ))

    def test_project_user_cannot_expand_visibility_through_task_links(self):
        with self.assertRaises(AccessError):
            self.Task.with_user(self.project_user).create({
                "name": "Intento de entrar a proyecto ajeno",
                "project_id": self.foreign_project.id,
            })
        with self.assertRaises(AccessError):
            self.user_assigned_task.with_user(self.project_user).write({
                "project_id": self.foreign_project.id,
            })

        own_project = self.Project.with_user(self.project_user).create({
            "name": "Proyecto para tareas nuevas",
        })
        new_task = self.Task.with_user(self.project_user).create({
            "name": "Tarea en proyecto propio",
            "project_id": own_project.id,
        })
        self.assertEqual(new_task.project_id, own_project)

    def test_client_sees_assigned_and_commercial_customer_projects(self):
        visible_ids = set(self.Project.with_user(self.client_user).search([]).ids)

        self.assertIn(self.client_project.id, visible_ids)
        self.assertIn(self.customer_project.id, visible_ids)
        self.assertNotIn(self.user_project.id, visible_ids)
        self.assertNotIn(self.foreign_project.id, visible_ids)
        self.assertNotIn(self.archived_project.id, visible_ids)

    def test_client_reads_all_tasks_in_visible_projects_but_not_archived_tasks(self):
        visible_ids = set(self.Task.with_user(self.client_user).search([
            ("project_id", "=", self.client_project.id),
        ]).ids)
        archived_ids = set(self.Task.with_user(self.client_user).with_context(
            active_test=False,
        ).search([]).ids)

        self.assertIn(self.client_assigned_task.id, visible_ids)
        self.assertIn(self.client_context_task.id, visible_ids)
        self.assertIn(self.customer_project_task.id, archived_ids)
        self.assertNotIn(self.archived_project_task.id, archived_ids)

    def test_client_can_edit_only_assigned_task_content_and_progress(self):
        task = self.client_assigned_task.with_user(self.client_user)
        task.check_access("write")
        with self.assertRaises(AccessError):
            self.client_context_task.with_user(self.client_user).check_access(
                "write"
            )
        task.write({
            "name": "Título actualizado por Cliente",
            "description": "Avance actualizado",
            "priority": "1",
            "planned_date_begin": "2026-09-01 09:00:00",
            "date_deadline": "2026-09-30 17:00:00",
            "allocated_hours": 4.0,
        })
        self.assertEqual(task.name, "Título actualizado por Cliente")
        self.assertEqual(task.allocated_hours, 4.0)

        with self.assertRaises(AccessError):
            self.client_context_task.with_user(self.client_user).write({
                "name": "No asignada",
            })

        protected_writes = (
            {"project_id": self.foreign_project.id},
            {"partner_id": self.other_customer.id},
            {"user_ids": [Command.clear()]},
            {"parent_id": False},
            {"company_id": False},
            {"active": False},
            {"depend_on_ids": [Command.clear()]},
        )
        for values in protected_writes:
            with self.subTest(values=values):
                with self.assertRaises(AccessError):
                    task.write(values)

    def test_client_cannot_create_delete_projects_or_tasks(self):
        with self.assertRaises(AccessError):
            self.Project.with_user(self.client_user).create({
                "name": "Proyecto creado por Cliente",
            })
        with self.assertRaises(AccessError):
            self.client_project.with_user(self.client_user).write({
                "name": "Proyecto modificado por Cliente",
            })
        with self.assertRaises(AccessError):
            self.Task.with_user(self.client_user).create({
                "name": "Tarea creada por Cliente",
                "project_id": self.client_project.id,
            })
        with self.assertRaises(AccessError):
            self.client_assigned_task.with_user(self.client_user).unlink()

    def test_internal_user_without_project_role_has_no_access(self):
        projects = self.Project.with_user(self.generic_user).search([])
        tasks = self.Task.with_user(self.generic_user).search([])

        self.assertFalse(projects)
        self.assertFalse(tasks)
        with self.assertRaises(AccessError):
            self.Project.with_user(self.generic_user).create({
                "name": "Proyecto interno sin rol",
            })
        with self.assertRaises(AccessError):
            self.Task.with_user(self.generic_user).create({
                "name": "Tarea interna sin rol",
            })

    def test_manager_retains_access_to_all_project_records(self):
        company_b = self.env["res.company"].create({
            "name": "Compañía B para seguridad",
        })
        self.manager.write({
            "company_ids": [Command.link(company_b.id)],
        })
        other_company_project = self._create_project(
            "Proyecto de otra compañía",
            self.other_customer,
            company_id=company_b.id,
        )

        manager_projects = self.Project.with_user(self.manager).search([])
        self.assertIn(self.foreign_project, manager_projects)
        self.assertIn(other_company_project, manager_projects)
        self.assertIn(self.foreign_task, self.Task.with_user(self.manager).search([]))

    def test_company_rule_still_limits_project_user(self):
        company_b = self.env["res.company"].create({
            "name": "Compañía B aislada",
        })
        self.assertNotIn(company_b, self.project_user.company_ids)
        other_company_project = self._create_project(
            "Proyecto fuera de compañías permitidas",
            self.other_customer,
            company_id=company_b.id,
        )
        other_company_task = self._create_task(
            "Tarea en otra compañía",
            other_company_project,
            self.project_user,
        )

        self.assertNotIn(
            other_company_project,
            self.Project.with_user(self.project_user).search([]),
        )
        self.assertNotIn(
            other_company_task,
            self.Task.with_user(self.project_user).search([]),
        )

    def test_project_menus_and_client_views_match_permissions(self):
        client_group = self.env.ref(
            "project_custom_extension.group_project_client"
        )
        project_menu = self.env.ref("project.menu_main_pm")
        dashboard_menu = self.env.ref(
            "project_custom_extension.menu_project_dashboard"
        )
        detail_menu = self.env.ref(
            "project_custom_extension.menu_project_detail_dashboard"
        )
        analysis_menu = self.env.ref("project.menu_project_report_task_analysis")

        self.assertIn(client_group, project_menu.groups_id)
        self.assertIn(client_group, dashboard_menu.groups_id)
        self.assertIn(client_group, detail_menu.groups_id)
        self.assertNotIn(client_group, analysis_menu.groups_id)

        dashboard_data = self.Project.with_user(
            self.client_user,
        ).get_project_dashboard_data()
        self.assertIn(
            self.client_project.id,
            [project["id"] for project in dashboard_data["projects"]],
        )
        self.assertNotIn(
            self.foreign_project.id,
            [project["id"] for project in dashboard_data["projects"]],
        )
        detail_filters = self.Project.with_user(
            self.client_user,
        ).get_project_detail_dashboard_filters()
        self.assertIn(self.other_customer.id, detail_filters["customer_ids"])

        project_form = etree.fromstring(self.Project.with_user(
            self.client_user,
        ).get_view(
            view_id=self.env.ref("project.edit_project").id,
            view_type="form",
        )["arch"])
        task_form = etree.fromstring(self.Task.with_user(
            self.client_user,
        ).get_view(
            view_id=self.env.ref("project.view_task_form2").id,
            view_type="form",
        )["arch"])
        task_list = etree.fromstring(self.Task.with_user(
            self.client_user,
        ).get_view(
            view_id=self.env.ref("project.view_task_tree2").id,
            view_type="list",
        )["arch"])
        self.assertEqual(project_form.get("edit"), "false")
        self.assertEqual(project_form.get("create"), "false")
        self.assertEqual(task_form.get("create"), "false")
        self.assertEqual(task_form.get("delete"), "false")
        self.assertEqual(task_list.get("create"), "false")
        self.assertEqual(task_list.get("delete"), "false")
        self.assertEqual(
            task_form.xpath("//field[@name='name']")[0].get("readonly"),
            "uid not in user_ids",
        )
        self.assertEqual(
            task_form.xpath("//field[@name='project_id']")[0].get("readonly"),
            "True",
        )
        self.assertEqual(
            len(task_form.xpath(
                "//field[@name='allocated_hours' and @invisible='0']"
            )),
            1,
        )

    def test_project_todo_access_is_limited_to_project_users(self):
        todo_module = self.env["ir.module.module"].search([
            ("name", "=", "project_todo"),
            ("state", "=", "installed"),
        ], limit=1)
        if not todo_module:
            self.skipTest("project_todo no está instalado en esta base de pruebas")

        project_user_group = self.env.ref("project.group_project_user")
        task_acl = self.env.ref("project_todo.access_task_on_partner")
        task_rule = self.env.ref("project_todo.task_edition_rule_internal")
        todo_menu = self.env.ref("project_todo.menu_todo_todos")

        self.assertEqual(task_acl.group_id, project_user_group)
        self.assertEqual(task_rule.groups, project_user_group)
        self.assertEqual(todo_menu.groups_id, project_user_group)
