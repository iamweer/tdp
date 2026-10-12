from odoo import api, fields, models

from .mcp_server import MCP_ALLOWED_ORIGINS_PARAMETER, MCP_ENABLED_PARAMETER


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    project_mcp_enabled = fields.Boolean(
        string="Servidor MCP",
        config_parameter=MCP_ENABLED_PARAMETER,
    )
    project_mcp_allowed_origins = fields.Char(
        string="Orígenes permitidos",
        config_parameter=MCP_ALLOWED_ORIGINS_PARAMETER,
        help="Orígenes web adicionales autorizados a llamar al endpoint, separados por comas.",
    )
    project_mcp_url = fields.Char(string="URL del endpoint MCP", compute="_compute_project_mcp_url")

    @api.depends("project_mcp_enabled")
    def _compute_project_mcp_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for settings in self:
            settings.project_mcp_url = f"{base_url.rstrip('/')}/mcp"
