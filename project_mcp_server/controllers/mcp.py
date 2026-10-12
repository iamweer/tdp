import json

from odoo import http
from odoo.http import request

from ..models.mcp_server import PARSE_ERROR


class McpController(http.Controller):
    """MCP Streamable HTTP transport, stateless and without SSE.

    Clients authenticate with a personal Odoo API key:
    ``Authorization: Bearer <api_key>``.
    """

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False, default=str),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    @http.route("/mcp", type="http", auth="bearer", methods=["POST"], csrf=False, save_session=False)
    def mcp(self, **kwargs):
        server = request.env["project.mcp.server"]
        # Protection against DNS rebinding: browsers always send Origin.
        origin = request.httprequest.headers.get("Origin")
        if origin and origin.rstrip("/") not in server._mcp_allowed_origins():
            return request.make_response("Origin not allowed", status=403)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True))
        except ValueError:
            return self._json_response(
                server._mcp_error(None, PARSE_ERROR, "Parse error"), status=400
            )

        response = server.mcp_handle_payload(payload)
        if response is None:
            return request.make_response("", status=202)
        return self._json_response(response)

    @http.route("/mcp", type="http", auth="none", methods=["GET", "DELETE"], csrf=False, save_session=False)
    def mcp_unsupported(self, **kwargs):
        # No server-initiated stream and no sessions to close.
        return request.make_response("", headers=[("Allow", "POST")], status=405)
