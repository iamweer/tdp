/** @odoo-module **/

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import {
    mockService,
    mountWithCleanup,
} from "@web/../tests/web_test_helpers";

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";

import { ProjectDashboard } from "../src/dashboard/project_dashboard";

defineMailModels();


function makePayload({ partner = false, activeCount = 2, projectName = "Proyecto A" } = {}) {
    const projectDomain = [["active", "=", true], ["last_update_status", "!=", "done"]];
    const taskDomain = [["active", "=", true], ["state", "=", "01_in_progress"]];
    return {
        customer_ids: [1, 2],
        selected_customer: partner
            ? { id: partner, display_name: partner === 1 ? "Cliente A" : "Cliente B" }
            : false,
        kpis: [
            {
                key: "active",
                title: "Proyectos activos",
                icon: "fa-folder-open",
                count: activeCount,
                model: "project.project",
                domain: projectDomain,
            },
            {
                key: "on_track",
                title: "En tiempo",
                icon: "fa-clock-o",
                count: 1,
                model: "project.project",
                domain: [...projectDomain, ["last_update_status", "=", "on_track"]],
            },
            {
                key: "at_risk",
                title: "En riesgo",
                icon: "fa-exclamation-triangle",
                count: 1,
                model: "project.project",
                domain: [...projectDomain, ["last_update_status", "=", "at_risk"]],
            },
            {
                key: "off_track",
                title: "Atrasados",
                icon: "fa-clock-o",
                count: 0,
                model: "project.project",
                domain: [...projectDomain, ["last_update_status", "=", "off_track"]],
            },
        ],
        projects: [{
            id: 10,
            name: projectName,
            customer_name: partner ? `Cliente ${partner === 1 ? "A" : "B"}` : "Cliente A",
            progress: 50,
            status: "on_track",
            status_label: "En tiempo",
            deadline: false,
        }],
        project_action: {
            title: "Proyectos activos",
            model: "project.project",
            domain: projectDomain,
        },
        alerts: [
            {
                key: "critical",
                title: "Actividades críticas",
                subtitle: "Requieren atención inmediata",
                icon: "fa-exclamation-triangle",
                count: 3,
                model: "project.task",
                domain: taskDomain,
            },
            {
                key: "upcoming",
                title: "Próximas a vencer",
                subtitle: "En los próximos 7 días",
                icon: "fa-calendar",
                count: 2,
                model: "project.task",
                domain: taskDomain,
            },
            {
                key: "blocked",
                title: "Bloqueos activos",
                subtitle: "Impedimentos que afectan el progreso",
                icon: "fa-lock",
                count: 1,
                model: "project.task",
                domain: taskDomain,
            },
        ],
        health: {
            score: 78,
            label: "Saludable",
            tone: "success",
            components: { progress: 50, status: 90, operations: 80 },
        },
    };
}

describe("dashboard de proyectos", () => {
    let executedActions;

    beforeEach(() => {
        executedActions = [];
        mockService("action", {
            doAction(action) {
                executedActions.push(action);
            },
        });
        browser.localStorage.removeItem(
            `project_custom_extension.dashboard.customer.${session.db}.${session.uid}`
        );
    });

test("renders the dashboard and opens KPI records in list view", async () => {
    mockService("orm", {
        call() {
            return makePayload();
        },
    });

    await mountWithCleanup(ProjectDashboard, { noMainContainer: true });

    expect(".o_project_dashboard_kpi").toHaveCount(4);
    expect(".o_project_dashboard_refresh").toHaveCount(0);
    expect(".o_project_dashboard_project_row").toHaveCount(1);
    expect(".o_project_dashboard_health_result strong").toHaveText("78%");
    expect(".o_project_dashboard_health_result span").toHaveText("Saludable");
    document.querySelector(".o_project_dashboard_kpi--active").click();
    const executedAction = executedActions[0];
    expect(executedAction.res_model).toBe("project.project");
    expect(executedAction.views).toEqual([[false, "list"], [false, "form"]]);
    expect(executedAction.domain).toEqual(makePayload().kpis[0].domain);
});

test("selecting a customer refreshes data and persists the valid selection", async () => {
    const requestedPartners = [];
    mockService("orm", {
        call(model, method, args, kwargs) {
            requestedPartners.push(kwargs.partner_id || false);
            return makePayload({
                partner: kwargs.partner_id || false,
                projectName: kwargs.partner_id === 2 ? "Proyecto B" : "Proyecto A",
            });
        },
    });

    const component = await mountWithCleanup(ProjectDashboard, {
        noMainContainer: true,
    });
    await component.loadDashboard(2);
    expect(requestedPartners).toEqual([false, 2]);
    expect(component.state.data.projects[0].name).toBe("Proyecto B");
    expect(component.state.selectedCustomer.id).toBe(2);
    expect(browser.localStorage.getItem(component.storageKey)).toBe("2");
});

test("drops an inaccessible persisted customer selection", async () => {
    const storageKey = `project_custom_extension.dashboard.customer.${session.db}.${session.uid}`;
    const requestedPartners = [];
    browser.localStorage.setItem(storageKey, "999");
    mockService("orm", {
        call(model, method, args, kwargs) {
            requestedPartners.push(kwargs.partner_id || false);
            return makePayload();
        },
    });

    const component = await mountWithCleanup(ProjectDashboard, {
        noMainContainer: true,
    });

    expect(requestedPartners).toEqual([999]);
    expect(component.state.selectedCustomer).toBe(false);
    expect(browser.localStorage.getItem(storageKey)).toBe(null);
});

test("a stale request cannot replace the latest customer data", async () => {
    const pending = new Map();
    let deferRequests = false;
    mockService("orm", {
        call(model, method, args, kwargs) {
            const partnerId = kwargs.partner_id || false;
            if (!deferRequests) {
                return makePayload();
            }
            return new Promise((resolve) => pending.set(partnerId, resolve));
        },
    });

    const component = await mountWithCleanup(ProjectDashboard, {
        noMainContainer: true,
    });
    deferRequests = true;
    const firstRequest = component.loadDashboard(1);
    const secondRequest = component.loadDashboard(2);
    pending.get(2)(makePayload({ partner: 2, projectName: "Proyecto reciente" }));
    await secondRequest;
    pending.get(1)(makePayload({ partner: 1, projectName: "Proyecto obsoleto" }));
    await firstRequest;

    expect(component.state.data.projects[0].name).toBe("Proyecto reciente");
    expect(component.state.selectedCustomer.id).toBe(2);
});

test("shows an error state and retries successfully", async () => {
    let shouldFail = true;
    mockService("orm", {
        call() {
            if (shouldFail) {
                throw new Error("Network error");
            }
            return makePayload();
        },
    });
    mockService("notification", {
        add(message, options) {
            expect.step(`${options.type}:${message}`);
        },
    });

    const component = await mountWithCleanup(ProjectDashboard, { noMainContainer: true });
    expect(".o_project_dashboard_feedback").toHaveCount(1);
    expect.verifySteps(["danger:No fue posible cargar el dashboard de proyectos."]);

    shouldFail = false;
    await component.refreshDashboard();
    expect(component.state.error).toBe(false);
    expect(component.state.data.kpis).toHaveLength(4);
});
});
