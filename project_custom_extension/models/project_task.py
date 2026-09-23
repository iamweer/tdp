from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ProjectTask(models.Model):
    _inherit = "project.task"

    CLIENT_WRITABLE_FIELDS = frozenset({
        "name",
        "description",
        "priority",
        "stage_id",
        "state",
        "planned_date_begin",
        "date_deadline",
        "allocated_hours",
        "tag_ids",
    })
    CLIENT_HIDDEN_VIEW_ELEMENTS = (
        ".//page[@name='sub_tasks_page']",
        ".//page[@name='task_dependencies']",
        ".//div[@name='button_box']",
    )

    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        result = super().get_view(view_id, view_type, **options)
        if (
            not self.env.user.has_group(
                "project_custom_extension.group_project_client"
            )
            or self.env.user.has_group("project.group_project_manager")
        ):
            return result

        arch = etree.fromstring(result["arch"])
        if arch.tag in {"form", "list", "kanban"}:
            arch.set("create", "false")
            arch.set("delete", "false")

        for element_xpath in self.CLIENT_HIDDEN_VIEW_ELEMENTS:
            for element in arch.xpath(element_xpath):
                element.set("invisible", "True")

        for field_node in arch.xpath(".//field[@name]"):
            field_name = field_node.get("name")
            if field_name == "user_ids":
                if arch.tag == "list":
                    field_node.set("column_invisible", "True")
                else:
                    field_node.set("invisible", "True")
            if field_name in self.CLIENT_WRITABLE_FIELDS:
                if field_name == "allocated_hours":
                    field_node.set("invisible", "0")
                existing_readonly = field_node.get("readonly")
                readonly = "uid not in user_ids"
                if existing_readonly and existing_readonly not in {
                    "0", "False", "false",
                }:
                    readonly = f"({existing_readonly}) or ({readonly})"
                field_node.set("readonly", readonly)
            else:
                field_node.set("readonly", "True")

        if arch.tag == "list" and not arch.xpath(".//field[@name='user_ids']"):
            etree.SubElement(
                arch,
                "field",
                name="user_ids",
                column_invisible="True",
            )
        elif arch.tag == "form" and not arch.xpath(".//field[@name='user_ids']"):
            container = arch.find(".//sheet")
            if container is None:
                container = arch
            etree.SubElement(
                container,
                "field",
                name="user_ids",
                invisible="True",
            )

        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    def _check_project_user_task_links(self, values, default_project_id=False):
        project_ids = {
            values.get("project_id") or default_project_id,
        } - {False, None}
        parent_ids = {
            values.get("parent_id") or self.env.context.get("default_parent_id"),
        } - {False, None}

        if project_ids:
            readable_project_ids = set(self.env["project.project"].search([
                ("id", "in", list(project_ids)),
            ]).ids)
            if project_ids - readable_project_ids:
                raise AccessError(
                    _("No puede crear o mover tareas a proyectos que no puede consultar.")
                )
        if parent_ids:
            readable_parent_ids = set(self.search([
                ("id", "in", list(parent_ids)),
            ]).ids)
            if parent_ids - readable_parent_ids:
                raise AccessError(
                    _("No puede crear subtareas bajo tareas que no puede consultar.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ) and (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ):
            raise AccessError(_("No tiene permiso para crear tareas."))
        if not self.env.su and not self.env.user.has_group(
            "project.group_project_manager"
        ):
            default_project_id = self.env.context.get("default_project_id")
            for values in vals_list:
                self._check_project_user_task_links(values, default_project_id)
        return super().create(vals_list)

    def write(self, vals):
        if self.env.su or self.env.user.has_group("project.group_project_manager"):
            return super().write(vals)

        is_client = self.env.user.has_group(
            "project_custom_extension.group_project_client"
        )
        if not is_client and not self.env.user.has_group("project.group_project_user"):
            raise AccessError(_("No tiene permiso para modificar tareas."))

        if is_client:
            forbidden_fields = set(vals) - self.CLIENT_WRITABLE_FIELDS
            if forbidden_fields:
                raise AccessError(
                    _("No tiene permiso para modificar la asignación o estructura de la tarea.")
                )
            self.check_access("write")
            if any(
                not task.active
                or not task.project_id.active
                or self.env.user not in task.user_ids
                for task in self
            ):
                raise AccessError(
                    _("Solo puede modificar tareas activas asignadas a usted.")
                )
        elif "project_id" in vals or "parent_id" in vals:
            self._check_project_user_task_links(vals)
        return super().write(vals)

    def unlink(self):
        if not self.env.su and (
            self.env.user.has_group("project_custom_extension.group_project_client")
            or not self.env.user.has_group("project.group_project_user")
        ) and not self.env.user.has_group("project.group_project_manager"):
            raise AccessError(_("No tiene permiso para eliminar tareas."))
        return super().unlink()

    planned_date_begin = fields.Datetime(
        string="Fecha inicial",
        tracking=True,
    )

    @api.constrains("planned_date_begin", "date_deadline")
    def _check_planned_dates(self):
        for task in self:
            if (
                task.planned_date_begin
                and task.date_deadline
                and task.planned_date_begin > task.date_deadline
            ):
                raise ValidationError(
                    _("La fecha inicial no puede ser posterior a la fecha límite.")
                )
