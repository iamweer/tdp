/** @odoo-module **/

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";

import { defineMailModels } from "@mail/../tests/mail_test_helpers";

import {
    buildProjectGanttCsv,
    ProjectGantt,
    STATUS_COLORS,
} from "../src/gantt/project_gantt";

defineMailModels();


function makeData(projectId = 10) {
    return {
        project: {
            id: projectId,
            name: `Proyecto ${projectId}`,
            customer_name: "Cliente de prueba",
            start_date: "2026-09-01",
            end_date: "2026-09-30",
        },
        rows: [
            {
                id: 1,
                status: "late",
                status_label: "Retrasada",
                name: "1. Análisis",
                parent_id: false,
                depth: 0,
                has_children: true,
                start_date: "2026-09-01",
                end_date: "2026-09-11",
                duration_days: 11,
                root_id: 1,
                color_index: 3,
            },
            {
                id: 2,
                status: "late",
                status_label: "Retrasada",
                name: "Levantamiento",
                parent_id: 1,
                depth: 1,
                has_children: false,
                start_date: "2026-09-01",
                end_date: "2026-09-03",
                duration_days: 3,
                root_id: 1,
                color_index: 3,
            },
            {
                id: 3,
                status: "no_dates",
                status_label: "Sin fechas",
                name: "Actividad sin fecha",
                parent_id: 1,
                depth: 1,
                has_children: false,
                start_date: "2026-09-07",
                end_date: false,
                duration_days: false,
                root_id: 1,
                color_index: 3,
            },
            {
                id: 4,
                status: "on_time",
                status_label: "A tiempo",
                name: "2. Diseño",
                parent_id: false,
                depth: 0,
                has_children: false,
                start_date: "2026-09-14",
                end_date: "2026-09-20",
                duration_days: 7,
                root_id: 4,
                color_index: 1,
            },
        ],
        status_summary: [
            { key: "late", label: "Retrasada", count: 2 },
            { key: "at_risk", label: "En riesgo de atraso", count: 0 },
            { key: "on_time", label: "A tiempo", count: 1 },
            { key: "no_dates", label: "Sin fechas", count: 1 },
            { key: "done", label: "Completada", count: 0 },
            { key: "canceled", label: "Cancelada", count: 0 },
        ],
        total: {
            start_date: "2026-09-01",
            end_date: "2026-09-30",
            duration_days: 30,
        },
        timeline: {
            start_date: "2026-09-01",
            end_date: "2026-09-30",
            today: "2026-09-23",
        },
    };
}


describe("cronograma Gantt de proyectos", () => {
    let actions;
    let calls;

    beforeEach(() => {
        actions = [];
        calls = [];
        mockService("action", {
            doAction(action) {
                actions.push(action);
            },
        });
        mockService("notification", {
            add() {},
        });
    });

    test("loads the project supplied in the client action context", async () => {
        mockService("orm", {
            call(model, method, args, kwargs) {
                calls.push({ model, method, args, kwargs });
                return makeData(kwargs.project_id);
            },
        });

        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });

        expect(component.state.data.project.id).toBe(10);
        expect(calls[0].method).toBe("get_project_gantt_data");
        expect(calls[0].kwargs).toEqual({
            project_id: 10,
            filter_start_date: false,
            filter_end_date: false,
        });
        expect(".o_project_gantt_content").toHaveCount(1);
        expect(".o_project_gantt_row").toHaveCount(4);
    });

    test("changes scale without changing the visible range and controls zoom", async () => {
        mockService("orm", { call: () => makeData() });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });
        const originalStart = component.state.viewportStart;
        const originalEnd = component.state.viewportEnd;

        component.onScaleChange({ target: { value: "year_month" } });
        component.onZoomInput({ target: { value: "120" } });

        expect(component.state.scale).toBe("year_month");
        expect(component.state.viewportStart).toBe(originalStart);
        expect(component.state.viewportEnd).toBe(originalEnd);
        expect(component.state.cellWidth).toBe(120);
        expect(component.columns).toHaveLength(1);
    });

    test("expands and collapses the hierarchy and calculates bar geometry", async () => {
        mockService("orm", { call: () => makeData() });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });
        const parent = component.allRows[0];

        component.toggleRow(parent.id);
        expect(component.visibleRows.map((row) => row.id)).toEqual([1, 4]);
        component.expandAll();
        expect(component.visibleRows).toHaveLength(4);
        component.collapseAll();
        expect(component.visibleRows.map((row) => row.id)).toEqual([1, 4]);

        const geometry = component.barGeometry(component.allRows[1]);
        expect(geometry.left).toBeGreaterThan(-1);
        expect(geometry.width).toBeGreaterThan(0);
    });

    test("shows the status of each task with colors, a legend and the overdue time", async () => {
        mockService("orm", { call: () => makeData() });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });
        await animationFrame();

        expect(".o_project_gantt_status--late").toHaveCount(2);
        expect(".o_project_gantt_status--on_time").toHaveCount(1);
        expect(".o_project_gantt_bar--late").toHaveCount(2);
        expect(".o_project_gantt_legend_item--late strong").toHaveText("2");
        expect(".o_project_gantt_legend_item--at_risk").toHaveCount(0);
        expect(component.barStyle(component.allRows[1])).toInclude(
            `background-color: ${STATUS_COLORS.late}`
        );
        // Levantamiento ended on 03/09 and today is 23/09: overdue tail.
        expect(component.overdueTailStyle(component.allRows[1])).toInclude("width:");
        expect(component.overdueTailStyle(component.allRows[3])).toBe(false);
    });

    test("validates filters and sends only the applied range", async () => {
        mockService("orm", {
            call(model, method, args, kwargs) {
                calls.push(kwargs);
                return makeData();
            },
        });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });

        component.onFilterStartInput({ target: { value: "2026-09-20" } });
        component.onFilterEndInput({ target: { value: "2026-09-01" } });
        await component.applyFilters();
        expect(Boolean(component.state.filterError)).toBe(true);
        expect(calls).toHaveLength(1);

        component.onFilterStartInput({ target: { value: "2026-09-05" } });
        component.onFilterEndInput({ target: { value: "2026-09-15" } });
        await component.applyFilters();
        expect(calls[calls.length - 1]).toEqual({
            project_id: 10,
            filter_start_date: "2026-09-05",
            filter_end_date: "2026-09-15",
        });
    });

    test("navigates the visible range, returns to today and supports fullscreen", async () => {
        mockService("orm", { call: () => makeData() });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });
        const originalStart = component.state.viewportStart;
        const originalEnd = component.state.viewportEnd;

        component.goNext();
        expect(component.state.viewportStart).not.toBe(originalStart);
        component.goPrevious();
        expect(component.state.viewportStart).toBe(originalStart);
        expect(component.state.viewportEnd).toBe(originalEnd);
        component.goToday();
        expect(Boolean(component.state.viewportStart)).toBe(true);
        expect(Boolean(component.state.viewportEnd)).toBe(true);

        Object.defineProperty(component.rootRef.el, "requestFullscreen", {
            configurable: true,
            value: undefined,
        });
        await component.toggleFullscreen();
        expect(component.state.fullscreen).toBe(true);
    });

    test("opens a task form in the main action and exports visible rows", async () => {
        mockService("orm", { call: () => makeData() });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
            props: { action: { context: { project_id: 10 } } },
        });

        component.openTask(component.allRows[1]);
        expect(actions[0]).toEqual({
            type: "ir.actions.act_window",
            name: "Levantamiento",
            res_model: "project.task",
            res_id: 2,
            views: [[false, "form"]],
            target: "current",
        });

        const csv = buildProjectGanttCsv(component.visibleRows, component.total);
        expect(csv).toInclude('"Actividad";"Inicio";"Fin";"Duración";"Estado"');
        expect(csv).toInclude('"Levantamiento";"01/09/2026";"03/09/2026";"3 días";"Retrasada"');
        expect(csv).toInclude("Levantamiento");
        expect(csv).toInclude("Total del proyecto");
        expect(csv).toInclude("01/09/2026");
    });

    test("ignores an obsolete RPC response", async () => {
        const pending = new Map();
        mockService("orm", {
            call(model, method, args, kwargs) {
                return new Promise((resolve) => pending.set(kwargs.project_id, resolve));
            },
        });
        const component = await mountWithCleanup(ProjectGantt, {
            noMainContainer: true,
        });

        const first = component.onProjectUpdate([{ id: 10, display_name: "Proyecto 10" }]);
        const second = component.onProjectUpdate([{ id: 11, display_name: "Proyecto 11" }]);
        pending.get(11)(makeData(11));
        await second;
        pending.get(10)(makeData(10));
        await first;

        expect(component.state.data.project.id).toBe(11);
        expect(component.state.selectedProject.id).toBe(11);
    });
});
