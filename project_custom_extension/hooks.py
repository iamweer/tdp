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
