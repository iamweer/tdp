/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { downloadFile } from "@web/core/network/download";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";


const DEFAULT_FILTERS = {
    search: "",
    customerId: "",
    stageId: "",
    pmId: "",
    collaboratorId: "",
    year: "",
    dateFrom: "",
    dateTo: "",
    projectCompany: "",
    collaboratorCompany: "",
    warranty: "",
    includeClosed: false,
    includeInactiveUsers: false,
    onlyWithoutCollaborators: false,
};

const WARRANTY_LABELS = {
    active: _t("Vigente"),
    upcoming: _t("Próxima"),
    expired: _t("Vencida"),
};

const PROJECT_SORT_KEYS = {
    project: (row) => row.project_name.toLowerCase(),
    customer: (row) => row.customer_name.toLowerCase(),
    stage: (row) => row.stage_name.toLowerCase(),
    progress: (row) => (row.progress === false ? -1 : row.progress),
    date_start: (row) => row.date_start || "",
    date_end: (row) => row.date_end || "",
    warranty_end: (row) => row.warranty_end || "",
    pm: (row) => row.pm_name.toLowerCase(),
};

const SORTABLE_COLUMNS = [
    ["project", _t("Proyecto")],
    ["customer", _t("Cliente")],
    ["stage", _t("Etapa actual")],
    ["progress", _t("% Ejecución")],
    ["date_start", _t("Inicio estimado")],
    ["date_end", _t("Fin estimado")],
    ["warranty_end", _t("Garantía")],
    ["pm", _t("PM (responsable)")],
    ["collaborator", _t("Colaborador")],
];


export class ProjectResourceReport extends Component {
    static template = "project_custom_extension.ProjectResourceReport";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            data: false,
            loading: true,
            error: false,
            filters: { ...DEFAULT_FILTERS, ...this.getStoredFilters() },
            sort: { key: "project", asc: true },
            showKpis: this.getStoredShowKpis(),
        });
        this.requestSequence = 0;
        onWillStart(() => this.loadReport());
    }

    get storageKey() {
        return `project_custom_extension.resource_report.filters.${session.db}.${session.uid}`;
    }

    getStoredFilters() {
        try {
            const stored = JSON.parse(browser.localStorage.getItem(this.storageKey) || "{}");
            return Object.fromEntries(
                Object.entries(stored).filter(([key]) => key in DEFAULT_FILTERS)
            );
        } catch {
            return {};
        }
    }

    get kpisStorageKey() {
        return `project_custom_extension.resource_report.show_kpis.${session.db}.${session.uid}`;
    }

    getStoredShowKpis() {
        try {
            return browser.localStorage.getItem(this.kpisStorageKey) !== "false";
        } catch {
            return true;
        }
    }

    toggleKpis() {
        this.state.showKpis = !this.state.showKpis;
        try {
            browser.localStorage.setItem(this.kpisStorageKey, String(this.state.showKpis));
        } catch {
            // A UI preference; the report works without persistence.
        }
    }

    storeFilters() {
        try {
            browser.localStorage.setItem(this.storageKey, JSON.stringify(this.state.filters));
        } catch {
            // Filters are a convenience; the report works without persistence.
        }
    }

    async loadReport() {
        const requestSequence = ++this.requestSequence;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_resource_report_data",
                []
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
            this.notification.add(
                _t("No fue posible cargar el informe de proyectos y recursos."),
                { type: "danger" }
            );
        } finally {
            if (requestSequence === this.requestSequence) {
                this.state.loading = false;
            }
        }
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------

    get hasActiveFilters() {
        return Object.entries(DEFAULT_FILTERS).some(
            ([key, value]) => this.state.filters[key] !== value
        );
    }

    get collaboratorOptions() {
        const collaborators = new Map();
        for (const row of this.collaboratorRows) {
            if (row.collaborator_id) {
                collaborators.set(row.collaborator_id, row.collaborator_name);
            }
        }
        return [...collaborators].sort((a, b) => a[1].localeCompare(b[1]));
    }

    get yearOptions() {
        const years = new Set();
        for (const row of this.state.data?.rows || []) {
            const [start, end] = this.projectPeriod(row);
            if (!start) {
                continue;
            }
            for (let year = Number(start.slice(0, 4)); year <= Number(end.slice(0, 4)); year++) {
                years.add(String(year));
            }
        }
        return [...years].sort().reverse();
    }

    get invalidDateRange() {
        const { dateFrom, dateTo } = this.state.filters;
        return Boolean(dateFrom && dateTo && dateFrom > dateTo);
    }

    /**
     * Estimated project period as ISO strings; a missing bound takes the
     * other one, and a project without dates has no period.
     */
    projectPeriod(row) {
        const start = row.date_start || row.date_end;
        const end = row.date_end || row.date_start;
        return start ? [start, end] : [false, false];
    }

    periodOverlaps(row, from, to) {
        const [start, end] = this.projectPeriod(row);
        if (!start) {
            return false;
        }
        return (!from || end >= from) && (!to || start <= to);
    }

    get companyOptions() {
        return this.state.data?.filters.company_types || [];
    }

    isSelected(key, value) {
        return this.state.filters[key] === String(value);
    }

    setFilter(key, value) {
        this.state.filters[key] = value;
        this.storeFilters();
    }

    onInputFilter(key, ev) {
        this.setFilter(key, ev.target.value);
    }

    onToggleFilter(key, ev) {
        this.setFilter(key, ev.target.checked);
    }

    clearFilters() {
        Object.assign(this.state.filters, DEFAULT_FILTERS);
        this.storeFilters();
    }

    rowMatches(row) {
        const filters = this.state.filters;
        if (!filters.includeClosed && row.stage_folded) {
            return false;
        }
        if (filters.customerId && String(row.customer_id) !== filters.customerId) {
            return false;
        }
        if (filters.stageId && String(row.stage_id) !== filters.stageId) {
            return false;
        }
        if (filters.pmId && String(row.pm_id) !== filters.pmId) {
            return false;
        }
        if (filters.collaboratorId && String(row.collaborator_id) !== filters.collaboratorId) {
            return false;
        }
        if (
            filters.year
            && !this.periodOverlaps(row, `${filters.year}-01-01`, `${filters.year}-12-31`)
        ) {
            return false;
        }
        if (
            (filters.dateFrom || filters.dateTo)
            && !this.invalidDateRange
            && !this.periodOverlaps(row, filters.dateFrom, filters.dateTo)
        ) {
            return false;
        }
        if (filters.projectCompany && row.project_company_type !== filters.projectCompany) {
            return false;
        }
        if (
            filters.collaboratorCompany
            && row.collaborator_company_type !== filters.collaboratorCompany
        ) {
            return false;
        }
        if (filters.warranty) {
            const status = row.warranty_status || "none";
            if (status !== filters.warranty) {
                return false;
            }
        }
        if (filters.onlyWithoutCollaborators && row.collaborator_id) {
            return false;
        }
        const search = filters.search.trim().toLowerCase();
        if (search) {
            const haystack = [
                row.project_name,
                row.customer_name,
                row.stage_name,
                row.pm_name,
                row.collaborator_name,
                row.identification,
                row.email,
            ].join(" ").toLowerCase();
            if (!haystack.includes(search)) {
                return false;
            }
        }
        return true;
    }

    get collaboratorRows() {
        const rows = this.state.data?.rows || [];
        if (this.state.filters.includeInactiveUsers) {
            return rows;
        }
        const result = [];
        const placeholders = new Map();
        const projectsWithRows = new Set();
        for (const row of rows) {
            if (row.collaborator_active === false) {
                // Keep the project visible, as without collaborators, when
                // all of its collaborators are inactive.
                if (!placeholders.has(row.project_id)) {
                    placeholders.set(row.project_id, {
                        ...row,
                        collaborator_id: false,
                        collaborator_active: true,
                        collaborator_name: "",
                        identification: "",
                        email: "",
                        collaborator_company_type: false,
                    });
                }
                continue;
            }
            projectsWithRows.add(row.project_id);
            result.push(row);
        }
        for (const [projectId, placeholder] of placeholders) {
            if (!projectsWithRows.has(projectId)) {
                result.push(placeholder);
            }
        }
        return result;
    }

    get filteredRows() {
        return this.collaboratorRows.filter((row) => this.rowMatches(row));
    }

    // ------------------------------------------------------------------
    // Table
    // ------------------------------------------------------------------

    get groups() {
        const groupsById = new Map();
        for (const row of this.filteredRows) {
            if (!groupsById.has(row.project_id)) {
                groupsById.set(row.project_id, { project: row, rows: [] });
            }
            groupsById.get(row.project_id).rows.push(row);
        }
        const { key, asc } = this.state.sort;
        const direction = asc ? 1 : -1;
        const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
        const projectKey = PROJECT_SORT_KEYS[key] || PROJECT_SORT_KEYS.project;
        const groups = [...groupsById.values()];
        groups.sort((a, b) => (
            direction * compare(projectKey(a.project), projectKey(b.project))
            || compare(a.project.project_name.toLowerCase(), b.project.project_name.toLowerCase())
        ));
        const collaboratorDirection = key === "collaborator" ? direction : 1;
        for (const group of groups) {
            group.rows.sort((a, b) => collaboratorDirection * compare(
                a.collaborator_name.toLowerCase(),
                b.collaborator_name.toLowerCase()
            ));
        }
        return groups;
    }

    get sortableColumns() {
        return SORTABLE_COLUMNS;
    }

    sortBy(key) {
        if (this.state.sort.key === key) {
            this.state.sort.asc = !this.state.sort.asc;
        } else {
            this.state.sort.key = key;
            this.state.sort.asc = true;
        }
    }

    sortIcon(key) {
        if (this.state.sort.key !== key) {
            return "fa-sort o_resource_report_sort--idle";
        }
        return this.state.sort.asc ? "fa-sort-asc" : "fa-sort-desc";
    }

    ariaSort(key) {
        if (this.state.sort.key !== key) {
            return "none";
        }
        return this.state.sort.asc ? "ascending" : "descending";
    }

    // ------------------------------------------------------------------
    // Indicators
    // ------------------------------------------------------------------

    get kpis() {
        const rows = this.filteredRows;
        const projects = new Map();
        const collaborators = new Map();
        let assignments = 0;
        for (const row of rows) {
            projects.set(row.project_id, row);
            if (row.collaborator_id) {
                assignments++;
                collaborators.set(row.collaborator_id, row.collaborator_company_type);
            }
        }
        const projectRows = [...projects.values()];
        const progressValues = projectRows
            .map((row) => row.progress)
            .filter((progress) => progress !== false);
        const averageProgress = progressValues.length
            ? Math.round(progressValues.reduce((total, value) => total + value, 0) / progressValues.length)
            : false;
        const projectsWithPeople = new Set(
            rows.filter((row) => row.collaborator_id).map((row) => row.project_id)
        );
        const companyCounts = { tdp: 0, abi: 0, none: 0 };
        for (const companyType of collaborators.values()) {
            companyCounts[companyType || "none"]++;
        }
        return {
            projects: projects.size,
            collaborators: collaborators.size,
            assignments,
            averageProgress,
            inWarranty: projectRows.filter((row) => row.warranty_status === "active").length,
            withoutCollaborators: projectRows.filter(
                (row) => !projectsWithPeople.has(row.project_id)
            ).length,
            companyCounts,
        };
    }

    companyShare(count, total) {
        return total ? (count * 100) / total : 0;
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------

    formatDate(value) {
        return value ? formatDate(deserializeDate(value)) : "—";
    }

    formatProgress(value) {
        return value === false ? "—" : `${Math.round(value)}%`;
    }

    progressWidth(value) {
        return value === false ? 0 : Math.max(0, Math.min(100, value));
    }

    companyLabel(value) {
        return this.companyOptions.find(([key]) => key === value)?.[1] || "";
    }

    warrantyLabel(status) {
        return WARRANTY_LABELS[status] || "";
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------

    openProject(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: row.project_name,
            res_model: "project.project",
            res_id: row.project_id,
            views: [[false, "form"]],
        });
    }

    openCollaboratorTasks(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Tareas de %(collaborator)s en %(project)s", {
                collaborator: row.collaborator_name,
                project: row.project_name,
            }),
            res_model: "project.task",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: [
                ["project_id", "=", row.project_id],
                ["user_ids", "in", [row.collaborator_id]],
            ],
            context: { active_test: true },
        });
    }

    exportCsv() {
        const headers = [
            _t("Proyecto"),
            _t("Empresa proyecto"),
            _t("Cliente"),
            _t("Etapa actual"),
            _t("% Ejecución"),
            _t("Fecha inicio estimada"),
            _t("Fecha fin estimada"),
            _t("Fecha inicio garantía"),
            _t("Fecha fin garantía"),
            _t("PM (responsable)"),
            _t("Colaborador"),
            _t("Cédula"),
            _t("Correo"),
            _t("Empresa (TDP / ABI)"),
        ];
        const lines = this.groups.flatMap((group) => group.rows).map((row) => [
            row.project_name,
            this.companyLabel(row.project_company_type),
            row.customer_name,
            row.stage_name,
            row.progress === false ? "" : row.progress,
            row.date_start || "",
            row.date_end || "",
            row.warranty_start || "",
            row.warranty_end || "",
            row.pm_name,
            row.collaborator_name,
            row.identification,
            row.email,
            this.companyLabel(row.collaborator_company_type),
        ]);
        const escape = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
        const csv = [headers, ...lines]
            .map((line) => line.map(escape).join(";"))
            .join("\r\n");
        const today = this.state.data?.today || "";
        return downloadFile(
            `﻿${csv}`,
            `proyectos_y_recursos_${today}.csv`,
            "text/csv;charset=utf-8"
        );
    }
}

registry.category("actions").add(
    "project_custom_extension.ProjectResourceReport",
    ProjectResourceReport
);
