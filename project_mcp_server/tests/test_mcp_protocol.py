import json

from odoo.tests import HttpCase, tagged

from ..models.mcp_server import ACCESS_DENIED, INVALID_PARAMS, METHOD_NOT_FOUND
from .common import McpCase


@tagged("post_install", "-at_install")
class TestMcpProtocol(McpCase):
    def test_initialize_negotiates_version(self):
        result = self.rpc(self.user, "initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "odoo-projects")

        result = self.rpc(self.user, "initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")

    def test_ping_and_notifications(self):
        self.assertEqual(self.rpc(self.user, "ping")["result"], {})
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.assertIsNone(self.Server.with_user(self.user).mcp_handle_message(notification))
        self.assertIsNone(self.Server.with_user(self.user).mcp_handle_payload([notification]))

    def test_batch(self):
        responses = self.Server.with_user(self.user).mcp_handle_payload([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ])
        self.assertEqual([response["id"] for response in responses], [1, 2])

    def test_tools_list(self):
        tools = self.rpc(self.user, "tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertTrue({"search_tasks", "create_task", "log_time"} <= names)
        self.assertFalse(any("delete" in name for name in names))
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("readOnlyHint", tool["annotations"])

    def test_errors(self):
        self.assertEqual(
            self.rpc(self.user, "resources/list")["error"]["code"], METHOD_NOT_FOUND
        )
        response = self.rpc(self.user, "tools/call", {"name": "nope"})
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)
        response = self.rpc(
            self.user, "tools/call", {"name": "get_task", "arguments": {"bad": 1}}
        )
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_access_requires_group_and_setting(self):
        response = self.rpc(self.no_mcp_user, "tools/list")
        self.assertEqual(response["error"]["code"], ACCESS_DENIED)

        self.env["ir.config_parameter"].sudo().set_param("project_mcp_server.enabled", "False")
        response = self.rpc(self.user, "tools/list")
        self.assertEqual(response["error"]["code"], ACCESS_DENIED)


@tagged("post_install", "-at_install")
class TestMcpEndpoint(HttpCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("project_mcp_server.enabled", "True")
        user = self.env["res.users"].create({
            "name": "Usuario MCP HTTP",
            "login": "mcp_http_user",
            "groups_id": [
                (4, self.env.ref("project.group_project_user").id),
                (4, self.env.ref("project_mcp_server.group_mcp_access").id),
            ],
        })
        self.api_key = self.env["res.users.apikeys"].with_user(user).sudo()._generate(
            None, "MCP test", None
        )

    def post(self, payload, key=None, headers=None):
        return self.url_open(
            "/mcp",
            data=payload if isinstance(payload, str) else json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {key or self.api_key}",
                **(headers or {}),
            },
        )

    def test_endpoint(self):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"]["tools"])

        response = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(response.status_code, 202)

        response = self.post("{not json")
        self.assertEqual(response.status_code, 400)

    def test_endpoint_rejects_bad_key_and_origin(self):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, key="invalid")
        self.assertEqual(response.status_code, 401)

        response = self.post(
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_get_not_allowed(self):
        self.assertEqual(self.url_open("/mcp").status_code, 405)
