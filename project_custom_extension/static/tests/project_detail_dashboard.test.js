/** @odoo-module **/

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";

import { ProjectDetailDashboard } from "../src/dashboard/project_detail_dashboard";

defineMailModels();


function makeData(projectId = 10) {
    return {
        project: {
            id: projectId,
            name: `Proyecto ${projectId}`,
            customer_name: "Cliente A",
            responsible_name: "Responsable",
            start_date: "2026-01-10",
            end_date: "2026-03-10",
            status: "on_track",
            status_label: "En tiempo",
        },
        progress: {
            mode: "general",
            percentage: 72,
            total_tasks: 10,
            completed_tasks: 7,
            open_tasks: 3,
            metrics: [
                {
                    key: "total",
                    title: "Total de actividades",
                    count: 10,
                    model: "project.task",
                    domain: [["project_id", "=", projectId], ["active", "=", true]],
                },
                {
                    key: "completed",
                    title: "Completadas",
                    count: 7,
                    model: "project.task",
                    domain: [["project_id", "=", projectId], ["state", "in", ["1_done"]]],
                },
                {
                    key: "open",
                    title: "Pendientes",
                    count: 3,
                    model: "project.task",
                    domain: [["project_id", "=", projectId], ["state", "in", ["01_in_progress"]]],
                },
            ],
            parent_tasks: [],
        },
        activities_by_state: [
            {
                key: "1_done",
                label: "Hecho",
                count: 7,
                model: "project.task",
                domain: [["project_id", "=", projectId], ["state", "=", "1_done"]],
            },
            {
                key: "01_in_progress",
                label: "En progreso",
                count: 3,
                model: "project.task",
                domain: [["project_id", "=", projectId], ["state", "=", "01_in_progress"]],
            },
        ],
        critical_activities: {
            count: 1,
            items: [{ id: 99, name: "Actividad vencida", deadline: "2026-01-05" }],
        },
    };
}


describe("detalle de proyecto", () => {
    const storageKey = `project_custom_extension.project_detail_dashboard.filters.${session.db}.${session.uid}`;
    let executedActions;

    beforeEach(() => {
        executedActions = [];
        browser.localStorage.removeItem(storageKey);
        mockService("action", {
            doAction(action) {
                executedActions.push(action);
            },
        });
        mockService("notification", {
            add() {},
        });
    });

    test("starts without project details and exposes all active projects", async () => {
        const calls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                calls.push({ model, method, args, kwargs });
                return { customer_ids: [1, 2] };
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });

        expect(".o_project_detail_dashboard_empty").toHaveCount(1);
        expect(calls).toHaveLength(1);
        expect(calls[0].method).toBe("get_project_detail_dashboard_filters");
        expect(component.getProjectDomain()).toEqual([["active", "=", true]]);
    });

    test("restricts project domain and clears selected project when customer changes", async () => {
        mockService("orm", {
            call(model, method) {
                return method === "get_project_detail_dashboard_filters"
                    ? { customer_ids: [1, 2] }
                    : makeData();
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        await component.onProjectUpdate([{ id: 10, display_name: "Proyecto 10" }]);
        expect(component.state.data.project.id).toBe(10);

        component.onCustomerUpdate([{ id: 2, display_name: "Cliente B" }]);

        expect(component.state.selectedProject).toBe(false);
        expect(component.state.data).toBe(false);
        expect(component.getProjectDomain()).toEqual([
            ["active", "=", true],
            ["partner_id", "=", 2],
        ]);
        expect(".o_project_detail_dashboard_empty").toHaveCount(1);
    });

    test("loads detail only after project selection", async () => {
        const detailCalls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    return { customer_ids: [1] };
                }
                detailCalls.push(kwargs);
                return makeData(12);
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        expect(detailCalls).toHaveLength(0);

        await component.onProjectUpdate([{ id: 12, display_name: "Proyecto 12" }]);
        await animationFrame();

        expect(detailCalls).toEqual([{ project_id: 12, partner_id: false }]);
        expect(".o_project_detail_dashboard_content").toHaveCount(1);
        expect(".o_project_detail_dashboard_project_identity h3").toHaveText(
            "Proyecto 12"
        );
    });

    test("persists valid customer and project filters", async () => {
        const filterCalls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    filterCalls.push(kwargs);
                    return {
                        customer_ids: [2],
                        selected_customer: { id: 2, display_name: "Cliente B" },
                        selected_project: { id: 12, display_name: "Proyecto 12" },
                    };
                }
                return makeData(12);
            },
        });
        browser.localStorage.setItem(
            storageKey,
            JSON.stringify({ customer_id: 2, project_id: 12 })
        );

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });

        expect(filterCalls).toEqual([{ partner_id: 2, project_id: 12 }]);
        expect(component.state.selectedCustomer.id).toBe(2);
        expect(component.state.selectedProject.id).toBe(12);
        expect(component.state.data.project.id).toBe(12);
    });

    test("opens the project task kanban and clickable metric domains", async () => {
        mockService("orm", {
            call(model, method) {
                return method === "get_project_detail_dashboard_filters"
                    ? { customer_ids: [1] }
                    : makeData(12);
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        await component.onProjectUpdate([{ id: 12, display_name: "Proyecto 12" }]);

        component.openProjectTasks();
        expect(executedActions[0].res_model).toBe("project.task");
        expect(executedActions[0].views[0]).toEqual([false, "kanban"]);
        expect(executedActions[0].domain).toEqual([["project_id", "=", 12]]);

        component.openMetric(component.progressMetrics[1]);
        expect(executedActions[1].domain).toEqual(
            component.progressMetrics[1].domain
        );

        component.openMetric(component.activityStates[0]);
        expect(executedActions[2].domain).toEqual(
            component.activityStates[0].domain
        );
    });

    test("opens the shared project gantt action from project detail", async () => {
        mockService("orm", {
            call(model, method) {
                return method === "get_project_detail_dashboard_filters"
                    ? { customer_ids: [1] }
                    : makeData(12);
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        await component.onProjectUpdate([{ id: 12, display_name: "Proyecto 12" }]);

        component.openProjectGantt();

        expect(executedActions[0]).toEqual({
            type: "ir.actions.client",
            name: "Cronograma de proyecto",
            tag: "project_custom_extension.ProjectGantt",
            target: "current",
            context: { project_id: 12 },
        });
    });

    test("does not let a stale project request replace the latest selection", async () => {
        const pending = new Map();
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    return { customer_ids: [1] };
                }
                return new Promise((resolve) => pending.set(kwargs.project_id, resolve));
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        const firstRequest = component.onProjectUpdate([
            { id: 10, display_name: "Proyecto 10" },
        ]);
        const secondRequest = component.onProjectUpdate([
            { id: 11, display_name: "Proyecto 11" },
        ]);

        pending.get(11)(makeData(11));
        await secondRequest;
        pending.get(10)(makeData(10));
        await firstRequest;

        expect(component.state.data.project.id).toBe(11);
        expect(component.state.selectedProject.id).toBe(11);
    });
});
