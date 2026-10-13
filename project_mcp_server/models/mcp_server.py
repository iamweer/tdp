import json
import logging
import time

from odoo import _, api, models, release
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError


_logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
MCP_ENABLED_PARAMETER = "project_mcp_server.enabled"
MCP_ALLOWED_ORIGINS_PARAMETER = "project_mcp_server.allowed_origins"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Implementation defined: the user may not use the MCP server.
ACCESS_DENIED = -32001

# Business errors the model can read and recover from.
TOOL_ERRORS = (AccessError, MissingError, UserError, ValidationError)


class McpToolInputError(Exception):
    """Raised by a tool when its arguments are invalid."""


class ProjectMcpServer(models.AbstractModel):
    _name = "project.mcp.server"
    _description = "Servidor MCP de proyectos"

    @api.model
    def _mcp_is_enabled(self):
        return (
            self.env["ir.config_parameter"].sudo().get_param(MCP_ENABLED_PARAMETER)
            == "True"
        )

    @api.model
    def _mcp_check_access(self):
        if not self._mcp_is_enabled():
            raise AccessError(_("El servidor MCP está desactivado."))
        if not self.env.user.has_group("project_mcp_server.group_mcp_access"):
            raise AccessError(_("Su usuario no tiene acceso MCP."))

    @api.model
    def _mcp_allowed_origins(self):
        Param = self.env["ir.config_parameter"].sudo()
        origins = {Param.get_param("web.base.url", "").rstrip("/")}
        extra = Param.get_param(MCP_ALLOWED_ORIGINS_PARAMETER, "")
        origins.update(
            origin.strip().rstrip("/") for origin in extra.split(",") if origin.strip()
        )
        origins.discard("")
        return origins

    @api.model
    def _mcp_tools(self):
        """Return the tool definitions as ``{name: definition}``.

        Each definition holds ``description``, ``inputSchema``,
        ``annotations`` and ``method``, the name of the handler on this model.
        Extend it with ``super()`` to add tools.
        """
        return {}

    @api.model
    def _mcp_error(self, request_id, code, message):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    @api.model
    def _mcp_result(self, request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @api.model
    def mcp_handle_payload(self, payload):
        """Handle a decoded JSON-RPC payload (message or batch).

        Returns the response payload, or ``None`` when the payload only held
        notifications.
        """
        if isinstance(payload, list):
            if not payload:
                return self._mcp_error(None, INVALID_REQUEST, "Empty batch")
            responses = [self.mcp_handle_message(message) for message in payload]
            return [response for response in responses if response] or None
        return self.mcp_handle_message(payload)

    @api.model
    def mcp_handle_message(self, message):
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            if isinstance(message, dict) and "method" not in message:
                # A response sent by the client; nothing to answer.
                return None
            return self._mcp_error(None, INVALID_REQUEST, "Invalid JSON-RPC request")

        method = message["method"]
        request_id = message.get("id")
        is_notification = "id" not in message
        params = message.get("params") or {}
        if is_notification:
            return None
        if not isinstance(params, dict):
            return self._mcp_error(request_id, INVALID_PARAMS, "params must be an object")

        try:
            self._mcp_check_access()
        except AccessError as error:
            return self._mcp_error(request_id, ACCESS_DENIED, str(error.args[0]))

        handler = {
            "initialize": self._mcp_initialize,
            "ping": lambda params: {},
            "tools/list": self._mcp_tools_list,
            "tools/call": self._mcp_tools_call,
        }.get(method)
        if not handler:
            return self._mcp_error(
                request_id, METHOD_NOT_FOUND, f"Method not found: {method}"
            )
        try:
            return self._mcp_result(request_id, handler(params))
        except McpToolInputError as error:
            return self._mcp_error(request_id, INVALID_PARAMS, str(error))
        except Exception:
            _logger.exception("MCP: error inesperado en %s", method)
            return self._mcp_error(request_id, INTERNAL_ERROR, "Internal error")

    @api.model
    def _mcp_initialize(self, params):
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "odoo-projects",
                "title": "Proyectos Odoo",
                "version": release.version,
            },
            "instructions": _(
                "Herramientas para consultar y operar proyectos, tareas, sprints "
                "y registro de horas de Odoo. Las fechas con hora se expresan en "
                "UTC. Todas las operaciones respetan los permisos del usuario. "
                "Cuando el usuario pida cerrar, terminar, finalizar (o un sinónimo) "
                "una tarea, use close_task."
            ),
        }

    @api.model
    def _mcp_tools_list(self, params):
        return {
            "tools": [
                {
                    "name": name,
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                    "annotations": tool.get("annotations", {}),
                }
                for name, tool in self._mcp_tools().items()
            ]
        }

    @api.model
    def _mcp_tools_call(self, params):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = self._mcp_tools().get(name)
        if not tool:
            raise McpToolInputError(f"Unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise McpToolInputError("arguments must be an object")
        schema = tool["inputSchema"]
        unknown = set(arguments) - set(schema.get("properties", {}))
        missing = set(schema.get("required", [])) - set(arguments)
        if unknown or missing:
            raise McpToolInputError(
                "Invalid arguments: unknown %s, missing %s"
                % (sorted(unknown), sorted(missing))
            )

        started = time.monotonic()
        try:
            # A failed write must not leave partial changes behind.
            with self.env.cr.savepoint():
                result = getattr(self, tool["method"])(**arguments)
        except (McpToolInputError, *TOOL_ERRORS) as error:
            message = error.args[0] if error.args else str(error)
            return {"content": [{"type": "text", "text": str(message)}], "isError": True}
        finally:
            _logger.info(
                "MCP: uid=%s tool=%s %.0fms",
                self.env.uid,
                name,
                (time.monotonic() - started) * 1000,
            )
        response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, default=str),
            }],
        }
        if isinstance(result, dict):
            response["structuredContent"] = json.loads(
                json.dumps(result, default=str)
            )
        return response
