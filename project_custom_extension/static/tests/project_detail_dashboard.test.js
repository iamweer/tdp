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
            end_date: "2026-12-10",
        },
        filters: {
            phases: [{ id: 51, name: "Diseño" }],
            phase_id: false,
            reference_date: "2026-10-08",
        },
        kpis: {
            progress: { percentage: 68, completed: 17, total: 25, domain: [["id", "=", 1]] },
            schedule: { key: "attention", label: "En atención", detail: "Esperado 78% · real 68%" },
            overdue: { count: 7, domain: [["id", "=", 2]] },
            milestones: { done: 8, total: 10, domain: [["id", "=", 3]] },
            blockers: { count: 2, domain: [["id", "=", 4]] },
        },
        phase_progress: [{
            id: 51,
            name: "Diseño",
            percentage: 90,
            weight: 30,
            completed: 9,
            total: 10,
            selected: false,
            domain: [["id", "child_of", 51]],
        }],
        milestone_chart: {
            done: 8,
            pending: 2,
            done_domain: [["id", "=", 5]],
            pending_domain: [["id", "=", 6]],
        },
        workload: [
            { key: "user_1", name: "Ana Torres", count: 8, domain: [["user_ids", "in", 1]] },
            { key: "unassigned", name: "Sin asignar", count: 2, domain: [["user_ids", "=", false]] },
        ],
        commitments: {
            count: 1,
            domain: [["id", "=", 7]],
            items: [{
                id: 70,
                name: "Entrega de diseño",
                responsible: "Ana Torres",
                deadline: "2026-10-15",
                status: "on_time",
                status_label: "En tiempo",
            }],
        },
        risks: {
            count: 1,
            domain: [["id", "=", 8]],
            items: [{
                id: 80,
                name: "Dependencia externa",
                priority: "high",
                priority_label: "Alta",
                responsible: "Carlos Méndez",
                next_action: "Cerrar «Insumos»",
                next_action_owner: "Lucía Rojas",
            }],
        },
    };
}

function filtersResult(projectId = 10, extra = {}) {
    return {
        customer_ids: [1, 2],
        manager_ids: [7],
        selected_customer: false,
        selected_manager: false,
        selected_project: projectId
            ? { id: projectId, display_name: `Proyecto ${projectId}` }
            : false,
        ...extra,
    };
}


describe("detalle de proyecto", () => {
    const storageKey = `project_custom_extension.project_detail_dashboard.v2.filters.${session.db}.${session.uid}`;
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

    test("selects a project on start and renders the executive dashboard", async () => {
        const calls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                calls.push({ method, kwargs });
                return method === "get_project_detail_dashboard_filters"
                    ? filtersResult(10)
                    : makeData(10);
            },
        });

        await mountWithCleanup(ProjectDetailDashboard, { noMainContainer: true });

        expect(calls.map((call) => call.method)).toEqual([
            "get_project_detail_dashboard_filters",
            "get_project_detail_dashboard_data",
        ]);
        expect(calls[1].kwargs).toEqual({
            project_id: 10,
            partner_id: false,
            manager_id: false,
            phase_id: false,
            cutoff: false,
        });
        expect(".o_project_detail_dashboard_kpi").toHaveCount(5);
        expect(".o_project_detail_dashboard_kpi--tone-amber").toHaveCount(1);
        expect(".o_project_detail_dashboard_table tbody tr").toHaveCount(2);
        expect(".o_project_detail_dashboard_pill--high").toHaveCount(1);
        expect(".o_project_detail_dashboard_bar_row").toHaveCount(3);
    });

    test("shows a message when no project matches the filters", async () => {
        mockService("orm", {
            call() {
                return filtersResult(false);
            },
        });

        await mountWithCleanup(ProjectDetailDashboard, { noMainContainer: true });

        expect(".o_project_detail_dashboard_empty").toHaveCount(1);
        expect(".o_project_detail_dashboard_content").toHaveCount(0);
    });

    test("reloads on every filter change and clearing keeps the project", async () => {
        const filterCalls = [];
        const dataCalls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    filterCalls.push(kwargs);
                    return filtersResult(kwargs.project_id || (kwargs.partner_id ? 20 : 10), {
                        selected_customer: kwargs.partner_id
                            ? { id: kwargs.partner_id, display_name: "Cliente B" }
                            : false,
                    });
                }
                dataCalls.push(kwargs);
                return makeData(kwargs.project_id);
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        expect(".o_project_detail_dashboard_apply").toHaveCount(0);

        await component.onPhaseChange({ target: { value: "51" } });
        expect(dataCalls.at(-1)).toMatchObject({ project_id: 10, phase_id: 51 });

        await component.onCutoffChange({ target: { value: "2026-08" } });
        expect(dataCalls.at(-1)).toEqual({
            project_id: 10,
            partner_id: false,
            manager_id: false,
            phase_id: 51,
            cutoff: "2026-08",
        });
        expect(JSON.parse(browser.localStorage.getItem(storageKey))).toEqual({
            customer_id: false,
            manager_id: false,
            project_id: 10,
            phase_id: "51",
            cutoff: "2026-08",
        });

        // Clearing the project field keeps the current project.
        await component.onProjectUpdate([]);
        expect(filterCalls.at(-1)).toMatchObject({ project_id: 10 });
        expect(component.state.applied.project.id).toBe(10);

        // A new customer drops the project and the server picks one.
        await component.onCustomerUpdate([{ id: 2, display_name: "Cliente B" }]);
        expect(filterCalls.at(-1)).toEqual({
            partner_id: 2,
            project_id: false,
            manager_id: false,
        });
        expect(component.state.applied.project.id).toBe(20);
        expect(component.state.applied.cutoff).toBe("2026-08");
        expect(component.getProjectDomain()).toEqual([
            ["active", "=", true],
            ["partner_id", "=", 2],
        ]);

        await component.clearFilters();
        expect(filterCalls.at(-1)).toEqual({
            partner_id: false,
            project_id: 20,
            manager_id: false,
        });
        expect(component.state.applied.project.id).toBe(20);
        expect(component.state.applied.phaseId).toBe("");
        expect(component.state.applied.cutoff).toBe("");
    });

    test("restores stored filters", async () => {
        const filterCalls = [];
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    filterCalls.push(kwargs);
                    return filtersResult(12, {
                        selected_manager: { id: 7, display_name: "Gerente" },
                    });
                }
                return makeData(12);
            },
        });
        browser.localStorage.setItem(
            storageKey,
            JSON.stringify({ manager_id: 7, project_id: 12, phase_id: 51, cutoff: "2026-05" })
        );

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });

        expect(filterCalls).toEqual([{ partner_id: false, project_id: 12, manager_id: 7 }]);
        expect(component.state.applied.manager.id).toBe(7);
        expect(component.state.applied.phaseId).toBe("51");
        expect(component.state.applied.cutoff).toBe("2026-05");
        expect(component.state.data.project.id).toBe(12);
    });

    test("opens task lists from metrics and rows", async () => {
        mockService("orm", {
            call(model, method) {
                return method === "get_project_detail_dashboard_filters"
                    ? filtersResult(10)
                    : makeData(10);
            },
        });

        await mountWithCleanup(ProjectDetailDashboard, { noMainContainer: true });

        document.querySelector(".o_project_detail_dashboard_kpi--accent").click();
        document.querySelector(".o_project_detail_dashboard_table tbody tr").click();
        await animationFrame();

        expect(executedActions[0].res_model).toBe("project.task");
        expect(executedActions[0].domain).toEqual([["id", "=", 2]]);
        expect(executedActions[1].res_id).toBe(70);
    });

    test("does not let a stale request replace the latest selection", async () => {
        let resolveFirst;
        let dataCall = 0;
        mockService("orm", {
            call(model, method, args, kwargs) {
                if (method === "get_project_detail_dashboard_filters") {
                    return filtersResult(kwargs.project_id || 10);
                }
                dataCall += 1;
                if (dataCall === 2) {
                    return new Promise((resolve) => {
                        resolveFirst = () => resolve(makeData(kwargs.project_id));
                    });
                }
                return makeData(kwargs.project_id);
            },
        });

        const component = await mountWithCleanup(ProjectDetailDashboard, {
            noMainContainer: true,
        });
        const staleRequest = component.onProjectUpdate([
            { id: 11, display_name: "Proyecto 11" },
        ]);
        await animationFrame();
        await component.onProjectUpdate([{ id: 12, display_name: "Proyecto 12" }]);
        resolveFirst();
        await staleRequest;

        expect(component.state.data.project.id).toBe(12);
    });
});
