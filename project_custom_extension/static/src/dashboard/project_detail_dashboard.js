/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";


const STATE_COLORS = {
    "1_done": "#269b3b",
    "01_in_progress": "#0756bb",
    "02_changes_requested": "#f0a400",
    "03_approved": "#43a047",
    "04_waiting_normal": "#e63138",
    "1_canceled": "#98a1b2",
};


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
            selectedCustomer: false,
            selectedProject: false,
            data: false,
            loading: false,
            error: false,
        });
        this.activeActions = {
            create: false,
            createEdit: false,
            write: false,
        };
        this.requestSequence = 0;
        onWillStart(() => this.loadFilters());
    }

    get customerValue() {
        return this.state.selectedCustomer?.display_name || "";
    }

    get storageKey() {
        return `project_custom_extension.project_detail_dashboard.filters.${session.db}.${session.uid}`;
    }

    get projectValue() {
        return this.state.selectedProject?.display_name || "";
    }

    get hasSelectedCustomer() {
        return Boolean(this.state.selectedCustomer);
    }

    get hasSelectedProject() {
        return Boolean(this.state.selectedProject);
    }

    get project() {
        return this.state.data?.project || false;
    }

    get progressMetrics() {
        return this.state.data?.progress?.metrics || [];
    }

    get parentProgress() {
        return this.state.data?.progress?.parent_tasks || [];
    }

    get activityStates() {
        const states = this.state.data?.activities_by_state || [];
        const total = states.reduce((sum, state) => sum + state.count, 0);
        return states.map((state, index) => ({
            ...state,
            color: STATE_COLORS[state.key] || this.getFallbackColor(index),
            percentage: total ? Math.round((state.count * 100) / total) : 0,
        }));
    }

    get activityStateTotal() {
        return this.activityStates.reduce((sum, state) => sum + state.count, 0);
    }

    get activityTotalMetric() {
        const projectId = this.project?.id;
        if (!projectId) {
            return false;
        }
        return {
            title: _t("Actividades del proyecto"),
            model: "project.task",
            domain: [
                ["project_id", "=", projectId],
                ["active", "=", true],
            ],
        };
    }

    get activityChartStyle() {
        if (!this.activityStates.length) {
            return "background: #e8ecf2;";
        }
        let start = 0;
        const segments = this.activityStates.map((state) => {
            const end = start + (state.count * 100) / this.activityStateTotal;
            const segment = `${state.color} ${start}% ${end}%`;
            start = end;
            return segment;
        });
        return `background: conic-gradient(${segments.join(", ")});`;
    }

    get progressRingStyle() {
        const percentage = Math.max(
            0,
            Math.min(100, this.state.data?.progress?.percentage || 0)
        );
        return `background: conic-gradient(var(--project-detail-blue) ${percentage}%, #e8ecf2 0);`;
    }

    getCustomerDomain() {
        return [["id", "in", this.state.customerIds]];
    }

    getProjectDomain() {
        const domain = [["active", "=", true]];
        if (this.state.selectedCustomer) {
            domain.push(["partner_id", "=", this.state.selectedCustomer.id]);
        }
        return domain;
    }

    getFallbackColor(index) {
        return ["#126bd0", "#7e57c2", "#78909c"][index % 3];
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
        const storedValue = browser.localStorage.getItem(this.storageKey);
        if (!storedValue) {
            return { customerId: false, projectId: false };
        }
        try {
            const filters = JSON.parse(storedValue);
            const customerId = Number.parseInt(filters.customer_id, 10);
            const projectId = Number.parseInt(filters.project_id, 10);
            return {
                customerId: Number.isInteger(customerId) && customerId > 0
                    ? customerId
                    : false,
                projectId: Number.isInteger(projectId) && projectId > 0
                    ? projectId
                    : false,
            };
        } catch {
            return { customerId: false, projectId: false };
        }
    }

    storeFilters(customerId = false, projectId = false) {
        if (customerId || projectId) {
            browser.localStorage.setItem(
                this.storageKey,
                JSON.stringify({
                    customer_id: customerId || false,
                    project_id: projectId || false,
                })
            );
        } else {
            browser.localStorage.removeItem(this.storageKey);
        }
    }

    async loadFilters() {
        this.state.loading = true;
        this.state.error = false;
        const storedFilters = this.getStoredFilters();
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_detail_dashboard_filters",
                [],
                {
                    partner_id: storedFilters.customerId || false,
                    project_id: storedFilters.projectId || false,
                }
            );
            this.state.customerIds = data.customer_ids || [];
            this.state.selectedCustomer = data.selected_customer || false;
            this.state.selectedProject = data.selected_project || false;
            this.storeFilters(
                this.state.selectedCustomer?.id || false,
                this.state.selectedProject?.id || false
            );
            if (this.state.selectedProject) {
                await this.loadProjectData(
                    this.state.selectedProject.id,
                    this.state.selectedCustomer?.id || false
                );
            }
        } catch (error) {
            this.state.error = true;
            this.notification.add(
                _t("No fue posible cargar los filtros del dashboard."),
                { type: "danger" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    async retryDashboard() {
        if (this.state.selectedProject) {
            await this.loadProjectData(
                this.state.selectedProject.id,
                this.state.selectedCustomer?.id || false
            );
            return;
        }
        await this.loadFilters();
    }

    clearProject() {
        this.requestSequence += 1;
        this.state.selectedProject = false;
        this.state.data = false;
        this.state.error = false;
        this.state.loading = false;
        this.storeFilters(this.state.selectedCustomer?.id || false, false);
    }

    onCustomerUpdate(records) {
        this.state.selectedCustomer = records?.[0] || false;
        this.storeFilters(this.state.selectedCustomer?.id || false, false);
        this.clearProject();
    }

    async onProjectUpdate(records) {
        this.state.selectedProject = records?.[0] || false;
        this.storeFilters(
            this.state.selectedCustomer?.id || false,
            this.state.selectedProject?.id || false
        );
        this.state.data = false;
        this.state.error = false;
        if (!this.state.selectedProject) {
            this.requestSequence += 1;
            this.state.loading = false;
            return;
        }
        await this.loadProjectData(
            this.state.selectedProject.id,
            this.state.selectedCustomer?.id || false
        );
    }

    async loadProjectData(projectId, partnerId = false) {
        const requestSequence = ++this.requestSequence;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_detail_dashboard_data",
                [],
                {
                    project_id: projectId,
                    partner_id: partnerId || false,
                }
            );
            if (requestSequence !== this.requestSequence) {
                return;
            }
            if (data.project) {
                this.state.data = data;
            } else {
                this.state.selectedProject = false;
                this.state.data = false;
                this.storeFilters(this.state.selectedCustomer?.id || false, false);
            }
        } catch (error) {
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

    openMetric(metric) {
        if (!metric?.model || !metric?.domain) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: metric.title,
            res_model: metric.model,
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: metric.domain,
            context: { active_test: true },
        });
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
