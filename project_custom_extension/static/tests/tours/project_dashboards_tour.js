/** @odoo-module **/

import { registry } from "@web/core/registry";

const PROJECT = "Proyecto Tour UI";
const PROJECT_ROW = `.o_project_dashboard_project_row:contains("${PROJECT}")`;

registry.category("web_tour.tours").add("project_custom_extension_dashboard_tour", {
    steps: () => [
        {
            content: "El proyecto muestra sus fechas de inicio y fin",
            trigger: `${PROJECT_ROW} .o_project_dashboard_project_dates:contains("→")`,
        },
        {
            content: "La barra marca el avance esperado",
            trigger: `${PROJECT_ROW} .o_project_dashboard_progress_expected`,
        },
        {
            content: "Se muestra el porcentaje esperado",
            trigger: `${PROJECT_ROW} .o_project_dashboard_progress_expected_value:contains("Esp. 30%")`,
        },
        {
            content: "El KPI usa la nueva etiqueta",
            trigger: `.o_project_dashboard_kpi--at_risk:contains("En Riesgo de Atraso")`,
        },
        {
            content: "El estado del proyecto es el cronograma automático (tarea vencida)",
            trigger: `${PROJECT_ROW} .o_project_dashboard_project_status--late`,
        },
        {
            content: "Hay una tarjeta para los proyectos sin planificación",
            trigger: `.o_project_dashboard_kpi--unplanned:contains("Sin Planificación")`,
        },
        {
            content: "Las tarjetas de estado suman los proyectos activos",
            trigger: ".o_project_dashboard_kpis",
            run() {
                const count = (key) => Number(
                    document.querySelector(
                        `.o_project_dashboard_kpi--${key} .o_project_dashboard_kpi_value`
                    ).textContent
                );
                const statuses = ["on_time", "at_risk", "late", "unplanned"];
                const sum = statuses.reduce((total, key) => total + count(key), 0);
                if (sum !== count("active")) {
                    throw new Error(`Las tarjetas suman ${sum} y hay ${count("active")} activos`);
                }
            },
        },
    ],
});

registry.category("web_tour.tours").add("project_custom_extension_detail_gantt_tour", {
    steps: () => [
        {
            content: "Selecciona el proyecto del tour",
            trigger: "#project_detail_project",
            run: `edit ${PROJECT}`,
        },
        {
            trigger: `.o-autocomplete--dropdown-item a:contains("${PROJECT}")`,
            run: "click",
        },
        {
            content: "Cada fase muestra sus fechas",
            trigger: `.o_project_detail_dashboard_bar_row:contains("Fase Tour") .o_project_detail_dashboard_phase_dates:contains("→")`,
        },
        {
            content: "Los compromisos usan la nueva etiqueta",
            trigger: `.o_project_detail_dashboard_pill--at_risk:contains("En riesgo de atraso")`,
        },
        {
            content: "Abre el cronograma",
            trigger: `.o_project_detail_dashboard_header_actions button:contains("Cronograma")`,
            run: "click",
        },
        {
            content: "La tarea vencida aparece retrasada",
            trigger: `.o_project_gantt_row:contains("Tarea retrasada") .o_project_gantt_status--late`,
        },
        {
            trigger: `.o_project_gantt_row:contains("Tarea retrasada") .o_project_gantt_bar--late`,
        },
        {
            content: "Se dibuja el tiempo vencido",
            trigger: `.o_project_gantt_row:contains("Tarea retrasada") .o_project_gantt_overdue_tail`,
        },
        {
            content: "La tarea próxima a vencer aparece en riesgo",
            trigger: `.o_project_gantt_row:contains("Tarea en riesgo") .o_project_gantt_status--at_risk:contains("En riesgo de atraso")`,
        },
        {
            trigger: `.o_project_gantt_row:contains("Tarea a tiempo") .o_project_gantt_status--on_time`,
        },
        {
            content: "La fase hereda el peor estado",
            trigger: `.o_project_gantt_row:contains("Fase Tour") .o_project_gantt_status--late`,
        },
        {
            content: "La leyenda resume los estados",
            trigger: `.o_project_gantt_legend_item--late:contains("Retrasada")`,
        },
    ],
});
