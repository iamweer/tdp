/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDate, serializeDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloatTime } from "@web/views/fields/formatters";
import { session } from "@web/session";

const { DateTime } = luxon;

const DEFAULT_PREFERENCES = {
    range: "month",
    groupBy: "employee",
    projectId: "",
    employeeId: "",
    companyType: "",
};

export const RANGE_OPTIONS = [
    ["week", _t("Semana")],
    ["month", _t("Mes")],
];

export const GROUP_BY_OPTIONS = [
    ["employee", _t("Empleado")],
    ["project", _t("Proyecto")],
    ["company", _t("Empresa")],
];

const SECOND_LEVEL_FIELD = {
    employee: "project_id",
    project: "employee_id",
    company: "employee_id",
};

export function periodBounds(anchor, range) {
    if (range === "week") {
        const start = anchor.startOf("week");
        return [start, start.plus({ days: 6 })];
    }
    return [anchor.startOf("month"), anchor.endOf("month").startOf("day")];
}

export function formatHours(value) {
    return formatFloatTime(value || 0, { noLeadingZeroHour: true });
}


export class ProjectTimesheetGrid extends Component {
    static template = "project_custom_extension.ProjectTimesheetGrid";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.rangeOptions = RANGE_OPTIONS;
        this.groupByOptions = GROUP_BY_OPTIONS;
        this.state = useState({
            data: false,
            loading: true,
            error: false,
            anchor: DateTime.local().startOf("day"),
            prefs: { ...DEFAULT_PREFERENCES, ...this.getStoredPreferences() },
            search: "",
            collapsed: {},
        });
        this.requestSequence = 0;
        onWillStart(() => this.loadData());
    }

    // ------------------------------------------------------------------
    // Preferences
    // ------------------------------------------------------------------

    get storageKey() {
        return `project_custom_extension.timesheet_grid.prefs.${session.db}.${session.uid}`;
    }

    getStoredPreferences() {
        try {
            const stored = JSON.parse(browser.localStorage.getItem(this.storageKey) || "{}");
            return Object.fromEntries(
                Object.entries(stored).filter(([key]) => key in DEFAULT_PREFERENCES)
            );
        } catch {
            return {};
        }
    }

    storePreferences() {
        try {
            browser.localStorage.setItem(this.storageKey, JSON.stringify(this.state.prefs));
        } catch {
            // Preferences are a convenience; the grid works without persistence.
        }
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    get period() {
        return periodBounds(this.state.anchor, this.state.prefs.range);
    }

    get periodLabel() {
        const [start, end] = this.period;
        if (this.state.prefs.range === "month") {
            const label = start.toFormat("LLLL yyyy");
            return label.charAt(0).toUpperCase() + label.slice(1);
        }
        return `${start.toFormat("dd/LL")} – ${end.toFormat("dd/LL/yyyy")}`;
    }

    async loadData() {
        const requestSequence = ++this.requestSequence;
        const [start, end] = this.period;
        const prefs = this.state.prefs;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.task.time.entry",
                "get_time_grid_data",
                [serializeDate(start), serializeDate(end)],
                {
                    group_by: prefs.groupBy,
                    filters: {
                        project_id: prefs.projectId ? Number(prefs.projectId) : false,
                        employee_id: prefs.employeeId ? Number(prefs.employeeId) : false,
                        company_type: prefs.companyType || false,
                    },
                }
            );
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.data = data;
        } catch {
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.error = true;
            this.notification.add(_t("No fue posible cargar el resumen de horas."), {
                type: "danger",
            });
        } finally {
            if (requestSequence === this.requestSequence) {
                this.state.loading = false;
            }
        }
    }

    // ------------------------------------------------------------------
    // Navigation and filters
    // ------------------------------------------------------------------

    goToday() {
        this.state.anchor = DateTime.local().startOf("day");
        return this.loadData();
    }

    move(step) {
        const unit = this.state.prefs.range === "week" ? "weeks" : "months";
        this.state.anchor = this.state.anchor.plus({ [unit]: step });
        return this.loadData();
    }

    setPreference(key, value) {
        this.state.prefs[key] = value;
        this.storePreferences();
        return this.loadData();
    }

    isSelected(key, value) {
        return this.state.prefs[key] === String(value);
    }

    onPreferenceChange(key, ev) {
        return this.setPreference(key, ev.target.value);
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    toggleGroup(group) {
        this.state.collapsed[group.key] = !this.state.collapsed[group.key];
    }

    isCollapsed(group) {
        return Boolean(this.state.collapsed[group.key]);
    }

    get hasActiveFilters() {
        const { projectId, employeeId, companyType } = this.state.prefs;
        return Boolean(projectId || employeeId || companyType || this.state.search);
    }

    clearFilters() {
        Object.assign(this.state.prefs, {
            projectId: "",
            employeeId: "",
            companyType: "",
        });
        this.state.search = "";
        this.storePreferences();
        return this.loadData();
    }

    // ------------------------------------------------------------------
    // Rendering helpers
    // ------------------------------------------------------------------

    get days() {
        return this.state.data?.days || [];
    }

    get groups() {
        const groups = this.state.data?.groups || [];
        const search = this.state.search.trim().toLowerCase();
        if (!search) {
            return groups;
        }
        return groups
            .map((group) => {
                if (group.name.toLowerCase().includes(search)) {
                    return group;
                }
                const lines = group.lines.filter((line) =>
                    line.name.toLowerCase().includes(search)
                );
                return lines.length ? { ...group, lines } : false;
            })
            .filter(Boolean);
    }

    get maxDailyTotal() {
        const totals = Object.values(this.state.data?.totals.daily || {});
        return Math.max(0, ...totals);
    }

    get isEmployeeGrouping() {
        return this.state.data?.group_by === "employee";
    }

    get secondLevelLabel() {
        return this.state.data?.group_by === "employee" ? _t("proyecto") : _t("empleado");
    }

    formatHours(value) {
        return formatHours(value);
    }

    dayParts(day) {
        const date = deserializeDate(day.date);
        return {
            weekday: date.toFormat("ccc"),
            label: date.toFormat("LLL d"),
        };
    }

    initial(name) {
        return (name || "?").trim().charAt(0).toUpperCase();
    }

    avatarColor(key) {
        const text = String(key);
        let hash = 0;
        for (const char of text) {
            hash = (hash * 31 + char.charCodeAt(0)) % 360;
        }
        return `hsl(${hash}, 45%, 46%)`;
    }

    groupCellClass(group, day) {
        const classes = [];
        if (day.is_weekend) {
            classes.push("o_ts_grid_weekend");
        }
        if (day.is_today) {
            classes.push("o_ts_grid_today");
        }
        if (group.missing_days.includes(day.date)) {
            classes.push("o_ts_grid_missing");
        } else if (!group.daily[day.date]) {
            classes.push("o_ts_grid_zero");
        }
        return classes.join(" ");
    }

    lineCellClass(line, day) {
        const classes = [];
        if (day.is_weekend) {
            classes.push("o_ts_grid_weekend");
        }
        if (day.is_today) {
            classes.push("o_ts_grid_today");
        }
        if (!line.daily[day.date]) {
            classes.push("o_ts_grid_zero");
        }
        return classes.join(" ");
    }

    barHeight(day) {
        const max = this.maxDailyTotal;
        const value = this.state.data?.totals.daily[day.date] || 0;
        return max ? Math.round((value / max) * 100) : 0;
    }

    companyLabel(value) {
        const option = (this.state.data?.filters.company_types || []).find(
            ([key]) => key === value
        );
        return option ? option[1] : "";
    }

    // ------------------------------------------------------------------
    // Drill-down
    // ------------------------------------------------------------------

    groupDomain(group) {
        const field = {
            employee: "employee_id",
            project: "project_id",
            company: "company_type",
        }[this.state.data.group_by];
        if (field === "company_type") {
            return [[field, "=", group.key === "none" ? false : group.key]];
        }
        return [[field, "=", group.key || false]];
    }

    lineDomain(line) {
        const field = SECOND_LEVEL_FIELD[this.state.data.group_by];
        return [[field, "=", line.key || false]];
    }

    baseDomain() {
        const prefs = this.state.prefs;
        const domain = [];
        if (prefs.projectId) {
            domain.push(["project_id", "=", Number(prefs.projectId)]);
        }
        if (prefs.employeeId) {
            domain.push(["employee_id", "=", Number(prefs.employeeId)]);
        }
        if (prefs.companyType) {
            domain.push(["company_type", "=", prefs.companyType]);
        }
        return domain;
    }

    openEntries({ group = false, line = false, day = false } = {}) {
        const data = this.state.data;
        const domain = [...this.baseDomain()];
        if (day) {
            domain.push(["date", "=", day.date]);
        } else {
            domain.push(["date", ">=", data.date_from], ["date", "<=", data.date_to]);
        }
        if (group) {
            domain.push(...this.groupDomain(group));
        }
        if (line) {
            domain.push(...this.lineDomain(line));
        }
        const title = [group?.name, line?.name].filter(Boolean).join(" · ");
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: title ? `${_t("Registros de horas")}: ${title}` : _t("Registros de horas"),
            res_model: "project.task.time.entry",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain,
            context: { create: false },
            target: "current",
        });
    }
}

registry.category("actions").add(
    "project_custom_extension.ProjectTimesheetGrid",
    ProjectTimesheetGrid
);
