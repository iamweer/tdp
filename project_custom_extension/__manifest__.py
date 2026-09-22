{
    "name": "Extensión personalizada de proyectos",
    "summary": "Fechas planeadas, garantías y migración del flujo de subtareas",
    "version": "18.0.1.0.0",
    "category": "Services/Project",
    "author": "TDP",
    "license": "LGPL-3",
    "depends": ["project"],
    "data": [
        "views/project_project_views.xml",
        "views/project_task_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
