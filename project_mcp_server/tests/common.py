import json

from odoo import Command
from odoo.tests import TransactionCase, new_test_user

from ..models.mcp_server import MCP_ENABLED_PARAMETER


class McpCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(MCP_ENABLED_PARAMETER, "True")
        cls.Server = cls.env["project.mcp.server"]
        cls.customer = cls.env["res.partner"].create({
            "name": "Cliente MCP",
            "is_company": True,
        })
        cls.other_customer = cls.env["res.partner"].create({
            "name": "Cliente ajeno MCP",
            "is_company": True,
        })
        cls.user = new_test_user(
            cls.env,
            login="mcp_project_user",
            groups="project.group_project_user,project_mcp_server.group_mcp_access",
        )
        cls.client = new_test_user(
            cls.env,
            login="mcp_project_client",
            groups="project_custom_extension.group_project_client,"
            "project_mcp_server.group_mcp_access",
        )
        cls.client.partner_id.parent_id = cls.customer
        cls.manager = new_test_user(
            cls.env,
            login="mcp_project_manager",
            groups="project.group_project_manager,project_mcp_server.group_mcp_access",
        )
        cls.no_mcp_user = new_test_user(
            cls.env,
            login="mcp_project_no_access",
            groups="project.group_project_user",
        )
        cls.env["hr.employee"].create({"name": "Empleado MCP", "user_id": cls.user.id})

        cls.project = cls.env["project.project"].create({
            "name": "Proyecto MCP",
            "partner_id": cls.customer.id,
        })
        cls.task = cls.env["project.task"].create({
            "name": "Tarea MCP",
            "project_id": cls.project.id,
            "user_ids": [Command.link(cls.user.id), Command.link(cls.client.id)],
        })
        cls.other_project = cls.env["project.project"].create({
            "name": "Proyecto ajeno MCP",
            "partner_id": cls.other_customer.id,
        })
        cls.other_task = cls.env["project.task"].create({
            "name": "Tarea ajena MCP",
            "project_id": cls.other_project.id,
        })

    def rpc(self, user, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.Server.with_user(user).mcp_handle_message(message)

    def call(self, user, tool, **arguments):
        """Call a tool and return ``(is_error, payload)``."""
        response = self.rpc(user, "tools/call", {"name": tool, "arguments": arguments})
        self.assertNotIn("error", response, response.get("error"))
        result = response["result"]
        text = result["content"][0]["text"]
        if result.get("isError"):
            return True, text
        return False, json.loads(text)
