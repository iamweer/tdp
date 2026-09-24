from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sprint_action = env.ref(
        "project_custom_extension.project_sprint_action",
        raise_if_not_found=False,
    )
    if sprint_action and sprint_action.context != "{}":
        sprint_action.write({"context": "{}"})
