/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";


export class ProjectDashboard extends Component {
    static template = "project_custom_extension.ProjectDashboard";
    static components = { Many2XAutocomplete };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            data: false,
            customerIds: [],
            selectedCustomer: false,
            loading: true,
            error: false,
        });
        this.customerActiveActions = {
            create: false,
            createEdit: false,
            write: false,
        };
        this.requestSequence = 0;
        onWillStart(() => this.loadDashboard(this.getStoredCustomerId()));
    }

    get storageKey() {
        return `project_custom_extension.dashboard.customer.${session.db}.${session.uid}`;
    }

    get customerValue() {
        return this.state.selectedCustomer?.display_name || "";
    }

    get hasSelectedCustomer() {
        return Boolean(this.state.selectedCustomer);
    }

    get gaugeNeedleTransform() {
        const score = this.state.data?.health?.score;
        const angle = score === false || score === undefined ? 180 : 180 + score * 1.8;
        return `rotate(${angle} 100 100)`;
    }

    getStoredCustomerId() {
        const storedValue = browser.localStorage.getItem(this.storageKey);
        const partnerId = Number.parseInt(storedValue, 10);
        return Number.isInteger(partnerId) && partnerId > 0 ? partnerId : false;
    }

    storeCustomerId(partnerId) {
        if (partnerId) {
            browser.localStorage.setItem(this.storageKey, String(partnerId));
        } else {
            browser.localStorage.removeItem(this.storageKey);
        }
    }

    getCustomerDomain() {
        return [["id", "in", this.state.customerIds]];
    }

    formatPercentage(value) {
        return Math.round(value);
    }

    async loadDashboard(partnerId = false) {
        const requestSequence = ++this.requestSequence;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_dashboard_data",
                [],
                { partner_id: partnerId || false }
            );
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.data = data;
            this.state.customerIds = data.customer_ids;
            this.state.selectedCustomer = data.selected_customer || false;
            this.storeCustomerId(data.selected_customer?.id || false);
        } catch (error) {
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.error = true;
            this.notification.add(
                _t("No fue posible cargar el dashboard de proyectos."),
                { type: "danger" }
            );
        } finally {
            if (requestSequence === this.requestSequence) {
                this.state.loading = false;
            }
        }
    }

    async onCustomerUpdate(records) {
        const selectedCustomer = records?.[0] || false;
        this.state.selectedCustomer = selectedCustomer || false;
        await this.loadDashboard(selectedCustomer?.id || false);
    }

    async showAllCustomers() {
        this.state.selectedCustomer = false;
        await this.loadDashboard(false);
    }

    async refreshDashboard() {
        await this.loadDashboard(this.state.selectedCustomer?.id || false);
    }

    openMetric(metric) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: metric.title,
            res_model: metric.model,
            views: [[false, "list"], [false, "form"]],
            domain: metric.domain,
            context: { active_test: true },
        });
    }

    openProject(project) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: project.name,
            res_model: "project.project",
            res_id: project.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add(
    "project_custom_extension.ProjectDashboard",
    ProjectDashboard
);
