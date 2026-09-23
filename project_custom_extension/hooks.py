def _copy_field_if_empty(model, source_field, target_field):
    if source_field not in model._fields:
        return

    records = model.with_context(active_test=False).search([
        (source_field, "!=", False),
        (target_field, "=", False),
    ])
    for record in records:
        record.with_context(tracking_disable=True).write({
            target_field: record[source_field],
        })


def _hide_existing_subtasks(env):
    subtasks = env["project.task"].with_context(active_test=False).search([
        ("parent_id", "!=", False),
        ("display_in_project", "=", True),
    ])
    subtasks.with_context(tracking_disable=True).write({
        "display_in_project": False,
    })


def _update_xml_record(env, xmlid, values):
    record = env.ref(xmlid, raise_if_not_found=False)
    if not record:
        return

    changed_values = {}
    for name, value in values.items():
        current_value = record[name]
        if record._fields[name].type == "many2one":
            current_value = current_value.id
        if current_value != value:
            changed_values[name] = value
    if changed_values:
        record.write(changed_values)


def configure_project_security(env):
    """Apply the project access policy, including native noupdate records."""
    restricted_native_rules = (
        "project.project_public_members_rule",
        "project.task_visibility_rule",
        "project.task_visibility_rule_project_user",
        "project.ir_rule_private_task",
    )
    for xmlid in restricted_native_rules:
        _update_xml_record(env, xmlid, {"active": False})

    user_project_report_domain = """[
        ('project_id.active', '=', True),
        '|',
            ('project_id.create_uid', '=', user.id),
            ('project_id.tasks', 'any', [
                ('active', '=', True),
                ('user_ids', 'in', user.id),
            ]),
    ]"""
    for xmlid in (
        "project.report_project_task_user_rule",
        "project.burndown_chart_project_user_rule",
    ):
        _update_xml_record(env, xmlid, {"domain_force": user_project_report_domain})

    todo_access_groups = (
        "project_todo.access_task_on_partner",
        "project_todo.access_project_task_type_user",
        "project_todo.access_project_tags_user",
        "project_todo.access_mail_activity_todo_create",
    )
    project_user_group = env.ref("project.group_project_user")
    for xmlid in todo_access_groups:
        _update_xml_record(env, xmlid, {"group_id": project_user_group.id})

    todo_rule = env.ref(
        "project_todo.task_edition_rule_internal",
        raise_if_not_found=False,
    )
    if todo_rule and todo_rule.groups != project_user_group:
        todo_rule.write({"groups": [(6, 0, project_user_group.ids)]})

    todo_menu = env.ref("project_todo.menu_todo_todos", raise_if_not_found=False)
    if todo_menu and todo_menu.groups_id != project_user_group:
        todo_menu.write({"groups_id": [(6, 0, project_user_group.ids)]})


def post_init_hook(env):
    _copy_field_if_empty(
        env["project.task"],
        "x_migration_planned_date_begin",
        "planned_date_begin",
    )
    _copy_field_if_empty(
        env["project.project"],
        "x_migration_inicio_garantia",
        "warranty_start_date",
    )
    _copy_field_if_empty(
        env["project.project"],
        "x_migration_fin_garantia",
        "warranty_end_date",
    )
    _hide_existing_subtasks(env)
    configure_project_security(env)
