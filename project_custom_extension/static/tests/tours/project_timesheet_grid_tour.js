/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("project_custom_extension_timesheet_grid_tour", {
    steps: () => [
        {
            content: "Ver el mes completo",
            trigger: ".o_ts_grid_range",
            run: "select month",
        },
        {
            content: "La columna de hoy queda visible sin desplazar la grilla",
            trigger: ".o_ts_grid_table thead .o_ts_grid_today",
            run() {
                const today = document
                    .querySelector(".o_ts_grid_table thead .o_ts_grid_today")
                    .getBoundingClientRect();
                const name = document.querySelector("thead .o_ts_grid_name_col").getBoundingClientRect();
                const total = document.querySelector("thead .o_ts_grid_total_col").getBoundingClientRect();
                if (today.left < name.right - 1 || today.right > total.left + 1) {
                    throw new Error("La columna de hoy está oculta detrás de las columnas fijas");
                }
            },
        },
        {
            content: "Las esquinas fijas tapan los días que se desplazan debajo",
            trigger: ".o_ts_grid_scroll",
            run() {
                // Scroll to the end so there are days under the left corners
                // whatever today's date is.
                const container = document.querySelector(".o_ts_grid_scroll");
                container.scrollLeft = container.scrollWidth;
                for (const selector of ["thead .o_ts_grid_name_col", "tfoot .o_ts_grid_totals_row .o_ts_grid_name_col"]) {
                    const corner = document.querySelector(selector);
                    const rect = corner.getBoundingClientRect();
                    const topElement = document.elementFromPoint(rect.right - 4, rect.top + rect.height / 2);
                    if (!corner.contains(topElement)) {
                        throw new Error(`Una columna de día tapa ${selector}`);
                    }
                }
            },
        },
        {
            content: "Hoy muestra las horas registradas",
            trigger: ".o_ts_grid_totals_row .o_ts_grid_today:contains(3:00)",
        },
    ],
});
