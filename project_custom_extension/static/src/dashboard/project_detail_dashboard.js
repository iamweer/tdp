/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";


const WORKLOAD_COLORS = ["teal", "indigo", "amber", "navy", "lilac"];

const SCHEDULE_TONES = {
    on_time: "green",
    attention: "amber",
    late: "red",
    unplanned: "muted",
};

function emptyFilters() {
    return {
        customer: false,
        manager: false,
        project: false,
        phaseId: "",
        cutoff: "",
    };
}


export class ProjectDetailDashboard extends Component {
    static template = "project_custom_extension.ProjectDetailDashboard";
    static components = { Many2XAutocomplete };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            customerIds: [],
            managerIds: [],
            draft: emptyFilters(),
            applied: emptyFilters(),
            data: false,
            noProject: false,
            loading: false,
            error: false,
        });
        this.activeActions = {
            create: false,
            createEdit: false,
            write: false,
        };
        this.requestSequence = 0;
        onWillStart(() => this.loadFilters(this.getStoredFilters()));
    }

    get storageKey() {
        return `project_custom_extension.project_detail_dashboard.v2.filters.${session.db}.${session.uid}`;
    }

    get project() {
        return this.state.data?.project || false;
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }

    get draftPhases() {
        // Phases are only known for the loaded project.
        return this.state.draft.project?.id === this.project?.id
            ? this.state.data?.filters?.phases || []
            : [];
    }

    get scheduleTone() {
        return SCHEDULE_TONES[this.kpis.schedule?.key] || "muted";
    }

    get milestonePercentage() {
        const milestones = this.kpis.milestones;
        return milestones?.total
            ? Math.round((milestones.done * 100) / milestones.total)
            : 0;
    }

    get milestoneChartStyle() {
        const chart = this.state.data?.milestone_chart;
        const total = (chart?.done || 0) + (chart?.pending || 0);
        if (!total) {
            return "background: var(--project-detail-track);";
        }
        const done = (chart.done * 100) / total;
        return `background: conic-gradient(var(--project-detail-teal) 0 ${done}%, var(--project-detail-track) ${done}% 100%);`;
    }

    get workload() {
        const items = this.state.data?.workload || [];
        const max = Math.max(1, ...items.map((item) => item.count));
        return items.map((item, index) => ({
            ...item,
            color: item.key === "unassigned"
                ? "muted"
                : WORKLOAD_COLORS[index % WORKLOAD_COLORS.length],
            width: Math.round((item.count * 100) / max),
        }));
    }

    getPhaseTone(percentage) {
        if (percentage >= 100) {
            return "teal";
        }
        if (percentage >= 70) {
            return "indigo";
        }
        return percentage >= 40 ? "amber" : "red";
    }

    getBarStyle(percentage) {
        return `width: ${Math.min(100, Math.max(0, percentage || 0))}%;`;
    }

    getCustomerDomain() {
        return [["id", "in", this.state.customerIds]];
    }

    getManagerDomain() {
        return [["id", "in", this.state.managerIds]];
    }

    getProjectDomain() {
        const domain = [["active", "=", true]];
        if (this.state.draft.customer) {
            domain.push(["partner_id", "=", this.state.draft.customer.id]);
        }
        if (this.state.draft.manager) {
            domain.push(["user_id", "=", this.state.draft.manager.id]);
        }
        return domain;
    }

    formatDate(value) {
        if (!value) {
            return _t("Sin fecha");
        }
        const [year, month, day] = value.split("-");
        return `${day}/${month}/${year}`;
    }

    formatPercentage(value) {
        return Math.round(value || 0);
    }

    getStoredFilters() {
        try {
            const filters = JSON.parse(
                browser.localStorage.getItem(this.storageKey) || "{}"
            );
            const toId = (value) => {
                const id = Number.parseInt(value, 10);
                return Number.isInteger(id) && id > 0 ? id : false;
            };
            return {
                customerId: toId(filters.customer_id),
                managerId: toId(filters.manager_id),
                projectId: toId(filters.project_id),
                phaseId: toId(filters.phase_id) ? String(toId(filters.phase_id)) : "",
                cutoff: /^\d{4}-\d{2}$/.test(filters.cutoff || "") ? filters.cutoff : "",
            };
        } catch {
            return {
                customerId: false,
                managerId: false,
                projectId: false,
                phaseId: "",
                cutoff: "",
            };
        }
    }

    storeFilters(filters) {
        try {
            browser.localStorage.setItem(
                this.storageKey,
                JSON.stringify({
                    customer_id: filters.customer?.id || false,
                    manager_id: filters.manager?.id || false,
                    project_id: filters.project?.id || false,
                    phase_id: filters.phaseId || false,
                    cutoff: filters.cutoff || "",
                })
            );
        } catch {
            // Storage is only a convenience.
        }
    }

    /**
     * Validate the filters on the server, which always returns a project
     * when one matches, and load its dashboard.
     */
    async loadFilters({ customerId, managerId, projectId, phaseId, cutoff }) {
        const requestSequence = ++this.requestSequence;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_detail_dashboard_filters",
                [],
                {
                    partner_id: customerId || false,
                    project_id: projectId || false,
                    manager_id: managerId || false,
                }
            );
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.customerIds = data.customer_ids || [];
            this.state.managerIds = data.manager_ids || [];
            const project = data.selected_project || false;
            const applied = {
                customer: data.selected_customer || false,
                manager: data.selected_manager || false,
                project,
                phaseId: project && project.id === projectId ? phaseId || "" : "",
                cutoff: cutoff || "",
            };
            this.state.applied = applied;
            this.state.draft = { ...applied };
            this.storeFilters(applied);
            if (!project) {
                this.state.data = false;
                this.state.noProject = true;
                return;
            }
            await this.loadProjectData(applied, requestSequence);
        } catch {
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.error = true;
            this.notification.add(
                _t("No fue posible cargar el detalle del proyecto."),
                { type: "danger" }
            );
        } finally {
            if (requestSequence === this.requestSequence) {
                this.state.loading = false;
            }
        }
    }

    async loadProjectData(filters, requestSequence) {
        const data = await this.orm.call(
            "project.project",
            "get_project_detail_dashboard_data",
            [],
            {
                project_id: filters.project.id,
                partner_id: filters.customer?.id || false,
                manager_id: filters.manager?.id || false,
                phase_id: filters.phaseId ? Number(filters.phaseId) : false,
                cutoff: filters.cutoff || false,
            }
        );
        if (requestSequence !== this.requestSequence) {
            return;
        }
        if (!data.project && filters.phaseId) {
            // The stored phase no longer exists: show the whole project.
            filters.phaseId = "";
            this.state.draft.phaseId = "";
            this.storeFilters(filters);
            return this.loadProjectData(filters, requestSequence);
        }
        this.state.data = data.project ? data : false;
        this.state.noProject = !data.project;
    }

    filtersFrom(filters) {
        return {
            customerId: filters.customer?.id || false,
            managerId: filters.manager?.id || false,
            projectId: filters.project?.id || false,
            phaseId: filters.phaseId,
            cutoff: filters.cutoff,
        };
    }

    applyFilters() {
        return this.loadFilters(this.filtersFrom(this.state.draft));
    }

    clearFilters() {
        // The project is kept: the dashboard always has one.
        return this.loadFilters({
            ...this.filtersFrom(emptyFilters()),
            projectId: this.state.applied.project?.id || false,
        });
    }

    retryDashboard() {
        return this.loadFilters(this.filtersFrom(this.state.applied));
    }

    // Every filter reloads the dashboard as soon as it changes.
    onCustomerUpdate(records) {
        this.state.draft.customer = records?.[0] || false;
        this.state.draft.project = false;
        this.state.draft.phaseId = "";
        return this.applyFilters();
    }

    onManagerUpdate(records) {
        this.state.draft.manager = records?.[0] || false;
        this.state.draft.project = false;
        this.state.draft.phaseId = "";
        return this.applyFilters();
    }

    onProjectUpdate(records) {
        // Clearing the field keeps the current project: there is always one.
        this.state.draft.project = records?.[0] || this.state.applied.project;
        this.state.draft.phaseId = "";
        return this.applyFilters();
    }

    onPhaseChange(event) {
        this.state.draft.phaseId = event.target.value;
        return this.applyFilters();
    }

    onCutoffChange(event) {
        this.state.draft.cutoff = event.target.value;
        return this.applyFilters();
    }

    openMetric(metric, title) {
        if (!metric?.domain) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: title || metric.name || this.project.name,
            res_model: "project.task",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: metric.domain,
            context: { active_test: true },
        });
    }

    openDomain(domain, title) {
        return this.openMetric({ domain }, title);
    }

    openProjectTasks() {
        if (!this.project) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: this.project.name,
            res_model: "project.task",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: [["project_id", "=", this.project.id]],
            context: {
                active_test: true,
                default_project_id: this.project.id,
            },
        });
    }

    openProjectGantt() {
        if (!this.project) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.client",
            name: _t("Cronograma de proyecto"),
            tag: "project_custom_extension.ProjectGantt",
            target: "current",
            context: { project_id: this.project.id },
        });
    }

    openTask(task) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: task.name,
            res_model: "project.task",
            res_id: task.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add(
    "project_custom_extension.ProjectDetailDashboard",
    ProjectDetailDashboard
);
