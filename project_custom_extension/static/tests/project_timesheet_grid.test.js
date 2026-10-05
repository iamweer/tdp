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

import {
    ProjectTimesheetGrid,
    formatHours,
    periodBounds,
} from "../src/timesheet_grid/project_timesheet_grid";

defineMailModels();

const { DateTime } = luxon;


function makePayload(groupBy = "employee") {
    const days = ["2026-01-05", "2026-01-06", "2026-01-07"].map((date) => ({
        date,
        is_weekend: false,
        is_today: date === "2026-01-06",
    }));
    return {
        date_from: "2026-01-05",
        date_to: "2026-01-07",
        group_by: groupBy,
        days,
        groups: [
            {
                key: 1,
                name: "Ana",
                employee_id: 1,
                company_type: "tdp",
                daily: { "2026-01-05": 8, "2026-01-06": 1.5 },
                total: 9.5,
                expected: 24,
                balance: -6.5,
                missing_days: ["2026-01-07"],
                lines: [
                    {
                        key: 10,
                        name: "Proyecto A",
                        employee_id: false,
                        project_id: 10,
                        daily: { "2026-01-05": 8, "2026-01-06": 1.5 },
                        total: 9.5,
                    },
                ],
            },
            {
                key: 2,
                name: "Beto",
                employee_id: 2,
                company_type: "abi",
                daily: { "2026-01-05": 2 },
                total: 2,
                expected: false,
                balance: false,
                missing_days: [],
                lines: [
                    {
                        key: 20,
                        name: "Proyecto B",
                        employee_id: false,
                        project_id: 20,
                        daily: { "2026-01-05": 2 },
                        total: 2,
                    },
                ],
            },
        ],
        totals: { daily: { "2026-01-05": 10, "2026-01-06": 1.5 }, total: 11.5 },
        filters: {
            projects: [[10, "Proyecto A"], [20, "Proyecto B"]],
            employees: [[1, "Ana"], [2, "Beto"]],
            company_types: [["tdp", "TDP"], ["abi", "ABI"]],
        },
        is_manager: true,
        today: "2026-01-06",
    };
}

describe("resumen de horas", () => {
    let calls;
    let executedActions;

    beforeEach(() => {
        calls = [];
        executedActions = [];
        mockService("action", {
            doAction(action) {
                executedActions.push(action);
            },
        });
        mockService("orm", {
            call(model, method, args, kwargs) {
                calls.push({ model, method, args, kwargs });
                return makePayload(kwargs.group_by);
            },
        });
        browser.localStorage.removeItem(
            `project_custom_extension.timesheet_grid.prefs.${session.db}.${session.uid}`
        );
    });

    test("period helpers and hour formatting", () => {
        const anchor = DateTime.fromISO("2026-01-08");
        const [weekStart, weekEnd] = periodBounds(anchor, "week");
        expect(weekStart.toISODate()).toBe("2026-01-05");
        expect(weekEnd.toISODate()).toBe("2026-01-11");
        const [monthStart, monthEnd] = periodBounds(anchor, "month");
        expect(monthStart.toISODate()).toBe("2026-01-01");
        expect(monthEnd.toISODate()).toBe("2026-01-31");
        expect(formatHours(8.5)).toBe("8:30");
        expect(formatHours(-6.5)).toBe("-6:30");
        expect(formatHours(false)).toBe("0:00");
    });

    test("renders groups, lines, missing days and totals", async () => {
        await mountWithCleanup(ProjectTimesheetGrid, { noMainContainer: true });

        expect(calls[0].method).toBe("get_time_grid_data");
        expect(calls[0].kwargs.group_by).toBe("employee");
        expect(".o_ts_grid_group_row").toHaveCount(2);
        expect(".o_ts_grid_line_row").toHaveCount(2);
        expect(".o_ts_grid_missing").toHaveCount(1);
        expect(".o_ts_grid_missing").toHaveText("0:00");
        expect(".o_ts_grid_balance--negative").toHaveText("-6:30");
        expect(".o_ts_grid_grand_total").toHaveText("11:30");
        expect(".o_ts_grid_group_row:first .o_ts_grid_total_col").toHaveClass(
            "o_ts_grid_total--warning"
        );
        expect(".o_ts_grid_filter_employee").toHaveCount(1);
    });

    test("changing grouping and period reloads the data", async () => {
        const component = await mountWithCleanup(ProjectTimesheetGrid, {
            noMainContainer: true,
        });

        await component.setPreference("groupBy", "company");
        await animationFrame();
        expect(calls.at(-1).kwargs.group_by).toBe("company");

        await component.setPreference("range", "week");
        const [weekFrom, weekTo] = calls.at(-1).args;
        expect(DateTime.fromISO(weekFrom).weekday).toBe(1);
        expect(DateTime.fromISO(weekTo).diff(DateTime.fromISO(weekFrom), "days").days).toBe(6);

        await component.move(-1);
        expect(calls.at(-1).args[1] < weekTo).toBe(true);

        await component.setPreference("projectId", "20");
        expect(calls.at(-1).kwargs.filters.project_id).toBe(20);
    });

    test("search filters lines and cells open the matching entries", async () => {
        const component = await mountWithCleanup(ProjectTimesheetGrid, {
            noMainContainer: true,
        });
        component.state.search = "proyecto b";
        await animationFrame();
        expect(".o_ts_grid_group_row").toHaveCount(1);
        expect(".o_ts_grid_group_name").toHaveText("Beto");

        const [group] = component.groups;
        component.openEntries({ group, line: group.lines[0], day: component.days[0] });
        expect(executedActions[0].res_model).toBe("project.task.time.entry");
        expect(executedActions[0].domain).toEqual([
            ["date", "=", "2026-01-05"],
            ["employee_id", "=", 2],
            ["project_id", "=", 20],
        ]);
    });
});
