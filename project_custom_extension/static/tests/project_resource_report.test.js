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

import { ProjectResourceReport } from "../src/resource_report/project_resource_report";

defineMailModels();


function makeRow(values) {
    return {
        project_id: 10,
        project_name: "Proyecto A",
        project_company_type: "tdp",
        customer_id: 1,
        customer_name: "Cliente A",
        stage_id: 1,
        stage_name: "En curso",
        stage_folded: false,
        progress: 40,
        date_start: "2026-01-01",
        date_end: "2026-12-31",
        warranty_start: false,
        warranty_end: false,
        warranty_status: false,
        pm_id: 2,
        pm_name: "PM Uno",
        collaborator_id: false,
        collaborator_name: "",
        identification: "",
        email: "",
        collaborator_company_type: false,
        ...values,
    };
}

function makePayload() {
    return {
        rows: [
            makeRow({
                collaborator_id: 100,
                collaborator_name: "Ana",
                identification: "111",
                email: "ana@example.com",
                collaborator_company_type: "tdp",
            }),
            makeRow({
                collaborator_id: 101,
                collaborator_name: "Beto",
                identification: "222",
                email: "beto@example.com",
                collaborator_company_type: "abi",
            }),
            makeRow({
                project_id: 20,
                project_name: "Proyecto B",
                project_company_type: "abi",
                progress: 80,
                warranty_status: "active",
                collaborator_id: 100,
                collaborator_name: "Ana",
                identification: "111",
                email: "ana@example.com",
                collaborator_company_type: "tdp",
            }),
            makeRow({
                project_id: 30,
                project_name: "Proyecto vacío",
                project_company_type: false,
                progress: false,
            }),
            makeRow({
                project_id: 40,
                project_name: "Proyecto cerrado",
                stage_id: 9,
                stage_name: "Cerrado",
                stage_folded: true,
                collaborator_id: 102,
                collaborator_name: "Carla",
            }),
        ],
        filters: {
            customers: [[1, "Cliente A"]],
            stages: [[1, "En curso"], [9, "Cerrado"]],
            pms: [[2, "PM Uno"]],
            company_types: [["tdp", "TDP"], ["abi", "ABI"]],
        },
        today: "2026-09-29",
    };
}

describe("informe de proyectos y recursos", () => {
    let executedActions;

    beforeEach(() => {
        executedActions = [];
        mockService("action", {
            doAction(action) {
                executedActions.push(action);
            },
        });
        mockService("orm", {
            call() {
                return makePayload();
            },
        });
        browser.localStorage.removeItem(
            `project_custom_extension.resource_report.filters.${session.db}.${session.uid}`
        );
    });

    test("groups collaborators by project and hides closed stages", async () => {
        const component = await mountWithCleanup(ProjectResourceReport, { noMainContainer: true });

        expect(".o_resource_report_group").toHaveCount(3);
        expect(".o_resource_report_project_cell").toHaveCount(3);
        expect(".o_resource_report_project_cell:first").toHaveAttribute("rowspan", "2");
        expect(".o_resource_report_no_people").toHaveCount(1);
        const kpis = component.kpis;
        expect(kpis.projects).toBe(3);
        expect(kpis.collaborators).toBe(2);
        expect(kpis.assignments).toBe(3);
        expect(kpis.averageProgress).toBe(60);
        expect(kpis.inWarranty).toBe(1);
        expect(kpis.withoutCollaborators).toBe(1);
        expect(kpis.companyCounts).toEqual({ tdp: 1, abi: 1, none: 0 });

        component.setFilter("includeClosed", true);
        await animationFrame();
        expect(".o_resource_report_group").toHaveCount(4);
    });

    test("filters update the table and the indicators", async () => {
        const component = await mountWithCleanup(ProjectResourceReport, { noMainContainer: true });

        component.setFilter("search", "beto");
        await animationFrame();
        expect(".o_resource_report_group").toHaveCount(1);
        expect(component.kpis.collaborators).toBe(1);

        component.setFilter("search", "");
        component.setFilter("projectCompany", "abi");
        await animationFrame();
        expect(".o_resource_report_group").toHaveCount(1);
        expect(".o_resource_report_project_link").toHaveText("Proyecto B");

        component.setFilter("projectCompany", "");
        component.setFilter("collaboratorCompany", "tdp");
        await animationFrame();
        expect(component.kpis.assignments).toBe(2);

        component.clearFilters();
        component.setFilter("onlyWithoutCollaborators", true);
        await animationFrame();
        expect(".o_resource_report_group").toHaveCount(1);
        expect(".o_resource_report_project_link").toHaveText("Proyecto vacío");
    });

    test("sorting by progress reorders project groups", async () => {
        const component = await mountWithCleanup(ProjectResourceReport, { noMainContainer: true });

        component.sortBy("progress");
        component.sortBy("progress");
        expect(component.groups.map((group) => group.project.project_name)).toEqual([
            "Proyecto B",
            "Proyecto A",
            "Proyecto vacío",
        ]);
    });

    test("opens the project form and the collaborator tasks", async () => {
        await mountWithCleanup(ProjectResourceReport, { noMainContainer: true });

        document.querySelector(".o_resource_report_project_link").click();
        expect(executedActions[0].res_model).toBe("project.project");
        expect(executedActions[0].res_id).toBe(10);
        expect(executedActions[0].views).toEqual([[false, "form"]]);

        document.querySelector(".o_resource_report_collaborator_link").click();
        expect(executedActions[1].res_model).toBe("project.task");
        expect(executedActions[1].domain).toEqual([
            ["project_id", "=", 10],
            ["user_ids", "in", [100]],
        ]);
    });

    test("persists filters per user", async () => {
        const component = await mountWithCleanup(ProjectResourceReport, { noMainContainer: true });
        component.setFilter("warranty", "active");
        const stored = JSON.parse(browser.localStorage.getItem(component.storageKey));
        expect(stored.warranty).toBe("active");
    });
});
