{
    "name": "Servidor MCP de proyectos",
    "summary": "Expone proyectos, tareas y horas a asistentes de IA mediante el Model Context Protocol",
    "version": "18.0.1.0.0",
    "category": "Services/Project",
    "author": "TDP",
    "license": "LGPL-3",
    "depends": ["project_custom_extension"],
    "data": [
        "security/mcp_security.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
