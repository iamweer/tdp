from odoo import fields, models

from .project_project import COMPANY_TYPE_SELECTION


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    company_type = fields.Selection(
        COMPANY_TYPE_SELECTION,
        string="Empresa (TDP/ABI)",
        groups="hr.group_hr_user",
        tracking=True,
    )
