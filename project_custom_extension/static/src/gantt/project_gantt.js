/** @odoo-module **/

import { Component, onWillStart, useExternalListener, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { downloadFile } from "@web/core/network/download";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";


const { DateTime } = luxon;

export const GANTT_SCALES = {
    month_day: {
        label: _t("Mes · días"),
        unit: "day",
    },
    year_month: {
        label: _t("Año · meses"),
        unit: "month",
    },
    month_week: {
        label: _t("Mes · semanas"),
        unit: "week",
    },
};

const MONTH_NAMES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
];

const MONTH_SHORT_NAMES = [
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
];

const BAR_COLORS = [
    "#7c3fb2",
    "#10a5a2",
    "#3568c8",
    "#5b9f43",
    "#d17a23",
    "#c34872",
    "#5968b7",
    "#198f65",
];

function parseDate(value) {
    if (!value) {
        return false;
    }
    const date = DateTime.fromISO(value).startOf("day");
    return date.isValid ? date : false;
}

function dateToString(date) {
    return date?.toISODate() || false;
}

function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
}

function dateDifferenceInDays(start, end) {
    return Math.round(end.diff(start, "days").days);
}

function formatCsvDate(value) {
    if (!value) {
        return "Sin fecha";
    }
    const [year, month, day] = value.split("-");
    return `${day}/${month}/${year}`;
}

function formatCsvDuration(value) {
    if (!value) {
        return "Sin fecha";
    }
    return `${value} ${value === 1 ? "día" : "días"}`;
}

function csvCell(value) {
    return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export function buildProjectGanttCsv(rows, total = false) {
    const lines = [
        ["Actividad", "Inicio", "Fin", "Duración"],
        ...rows.map((row) => [
            row.name,
            formatCsvDate(row.start_date),
            formatCsvDate(row.end_date),
            formatCsvDuration(row.duration_days),
        ]),
    ];
    if (total) {
        lines.push([
            "Total del proyecto",
            formatCsvDate(total.start_date),
            formatCsvDate(total.end_date),
            formatCsvDuration(total.duration_days),
        ]);
    }
    return `\uFEFF${lines.map((line) => line.map(csvCell).join(";")).join("\r\n")}\r\n`;
}

export class ProjectGantt extends Component {
    static template = "project_custom_extension.ProjectGantt";
    static components = { Many2XAutocomplete };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.rootRef = useRef("root");
        this.state = useState({
            selectedProject: false,
            data: false,
            loading: false,
            error: false,
            filterStart: "",
            filterEnd: "",
            appliedFilterStart: false,
            appliedFilterEnd: false,
            filterOpen: false,
            filterError: false,
            scale: "month_week",
            viewportStart: false,
            viewportEnd: false,
            cellWidth: 76,
            collapsed: {},
            fullscreen: false,
        });
        this.activeActions = {
            create: false,
            createEdit: false,
            write: false,
        };
        this.requestSequence = 0;
        useExternalListener(document, "fullscreenchange", this.onFullscreenChange);
        onWillStart(() => this.loadInitialProject());
    }

    get initialProjectId() {
        const value = this.props.action?.context?.project_id;
        const projectId = Number.parseInt(value, 10);
        return Number.isInteger(projectId) && projectId > 0 ? projectId : false;
    }

    get project() {
        return this.state.data?.project || false;
    }

    get projectValue() {
        return this.state.selectedProject?.display_name || this.project?.name || "";
    }

    get hasProject() {
        return Boolean(this.project);
    }

    get scaleOptions() {
        return Object.entries(GANTT_SCALES).map(([value, scale]) => ({
            value,
            label: scale.label,
        }));
    }

    get currentScale() {
        return GANTT_SCALES[this.state.scale] || GANTT_SCALES.month_week;
    }

    get viewportStartDate() {
        return parseDate(this.state.viewportStart);
    }

    get viewportEndDate() {
        return parseDate(this.state.viewportEnd);
    }

    get columns() {
        const cacheKey = [
            this.state.scale,
            this.state.viewportStart,
            this.state.viewportEnd,
        ].join("|");
        if (this._columnsCache?.key === cacheKey) {
            return this._columnsCache.columns;
        }
        const start = this.viewportStartDate;
        const end = this.viewportEndDate;
        if (!start || !end || start > end) {
            this._columnsCache = { key: cacheKey, columns: [] };
            return this._columnsCache.columns;
        }
        let columns;
        switch (this.currentScale.unit) {
            case "day":
                columns = this.makeDayColumns(start, end);
                break;
            case "month":
                columns = this.makeMonthColumns(start, end);
                break;
            case "week":
            default:
                columns = this.makeWeekColumns(start, end);
                break;
        }
        this._columnsCache = { key: cacheKey, columns };
        return columns;
    }

    get timelineWidth() {
        return this.columns.length * this.state.cellWidth;
    }

    get gridTemplateStyle() {
        return `grid-template-columns: repeat(${this.columns.length}, ${this.state.cellWidth}px);`;
    }

    get timelineStyle() {
        return `width: ${this.timelineWidth}px;`;
    }

    get rootStyle() {
        return [
            `--project-gantt-cell-width: ${this.state.cellWidth}px`,
            `--project-gantt-timeline-width: ${this.timelineWidth}px`,
        ].join(";");
    }

    get todayPosition() {
        const today = parseDate(this.state.data?.timeline?.today);
        if (!today || !this.viewportStartDate || !this.viewportEndDate) {
            return false;
        }
        if (today < this.viewportStartDate || today > this.viewportEndDate) {
            return false;
        }
        return this.datePosition(today);
    }

    get allRows() {
        return this.state.data?.rows || [];
    }

    get visibleRows() {
        const rows = this.allRows;
        const rowById = new Map(rows.map((row) => [row.id, row]));
        return rows.filter((row) => {
            let parentId = row.parent_id;
            while (parentId) {
                if (this.state.collapsed[parentId]) {
                    return false;
                }
                parentId = rowById.get(parentId)?.parent_id || false;
            }
            return true;
        });
    }

    get total() {
        return this.state.data?.total || false;
    }

    get totalRow() {
        if (!this.total?.start_date || !this.total?.end_date) {
            return false;
        }
        return {
            start_date: this.total.start_date,
            end_date: this.total.end_date,
            color_index: 0,
        };
    }

    get hasVisibleRows() {
        return this.visibleRows.length > 0;
    }

    get filterApplied() {
        return Boolean(this.state.appliedFilterStart || this.state.appliedFilterEnd);
    }

    get filterSummary() {
        if (!this.filterApplied) {
            return "";
        }
        const start = this.state.appliedFilterStart
            ? this.formatDate(this.state.appliedFilterStart)
            : "…";
        const end = this.state.appliedFilterEnd
            ? this.formatDate(this.state.appliedFilterEnd)
            : "…";
        return `${start} → ${end}`;
    }

    get isFullscreen() {
        return this.state.fullscreen;
    }

    getProjectDomain() {
        return [["active", "=", true]];
    }

    async loadInitialProject() {
        if (this.initialProjectId) {
            await this.loadProject(this.initialProjectId);
        }
    }

    async loadProject(projectId) {
        const requestSequence = ++this.requestSequence;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "project.project",
                "get_project_gantt_data",
                [],
                {
                    project_id: projectId || false,
                    filter_start_date: this.state.appliedFilterStart || false,
                    filter_end_date: this.state.appliedFilterEnd || false,
                }
            );
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.data = data;
            this.state.selectedProject = data.project
                ? {
                      id: data.project.id,
                      display_name: data.project.name,
                  }
                : false;
            this.state.viewportStart = data.timeline?.start_date || false;
            this.state.viewportEnd = data.timeline?.end_date || false;
            if (!data.project) {
                this.state.error = _t("El proyecto no existe, está archivado o no es accesible.");
            }
        } catch (error) {
            if (requestSequence !== this.requestSequence) {
                return;
            }
            this.state.error = true;
            this.notification.add(
                error?.data?.message || _t("No fue posible cargar el cronograma del proyecto."),
                { type: "danger" }
            );
        } finally {
            if (requestSequence === this.requestSequence) {
                this.state.loading = false;
            }
        }
    }

    clearProject() {
        this.requestSequence += 1;
        this.state.selectedProject = false;
        this.state.data = false;
        this.state.error = false;
        this.state.loading = false;
        this.state.collapsed = {};
        this.state.viewportStart = false;
        this.state.viewportEnd = false;
    }

    async onProjectUpdate(records) {
        const project = records?.[0] || false;
        if (!project) {
            this.clearProject();
            return;
        }
        this.state.selectedProject = project;
        this.state.collapsed = {};
        await this.loadProject(project.id);
    }

    onFilterStartInput(ev) {
        this.state.filterStart = ev.target.value;
        this.state.filterError = false;
    }

    onFilterEndInput(ev) {
        this.state.filterEnd = ev.target.value;
        this.state.filterError = false;
    }

    async applyFilters() {
        if (
            this.state.filterStart &&
            this.state.filterEnd &&
            this.state.filterStart > this.state.filterEnd
        ) {
            this.state.filterError = _t(
                "La fecha de inicio no puede ser posterior a la fecha fin."
            );
            return;
        }
        this.state.filterError = false;
        this.state.appliedFilterStart = this.state.filterStart || false;
        this.state.appliedFilterEnd = this.state.filterEnd || false;
        if (this.state.selectedProject) {
            await this.loadProject(this.state.selectedProject.id);
        }
    }

    async clearFilters() {
        this.state.filterStart = "";
        this.state.filterEnd = "";
        this.state.appliedFilterStart = false;
        this.state.appliedFilterEnd = false;
        this.state.filterError = false;
        if (this.state.selectedProject) {
            await this.loadProject(this.state.selectedProject.id);
        }
    }

    onScaleChange(ev) {
        if (GANTT_SCALES[ev.target.value]) {
            this.state.scale = ev.target.value;
        }
    }

    onZoomInput(ev) {
        const value = Number(ev.target.value);
        this.state.cellWidth = Number.isFinite(value)
            ? clamp(value, 48, 180)
            : 76;
    }

    toggleFilters() {
        this.state.filterOpen = !this.state.filterOpen;
    }

    toggleRow(rowId) {
        const collapsed = { ...this.state.collapsed };
        if (collapsed[rowId]) {
            delete collapsed[rowId];
        } else {
            collapsed[rowId] = true;
        }
        this.state.collapsed = collapsed;
    }

    expandAll() {
        this.state.collapsed = {};
    }

    collapseAll() {
        this.state.collapsed = Object.fromEntries(
            this.allRows.filter((row) => row.has_children).map((row) => [row.id, true])
        );
    }

    shiftViewport(amount) {
        const start = this.viewportStartDate;
        const end = this.viewportEndDate;
        if (!start || !end) {
            return;
        }
        const count = Math.max(1, this.columns.length);
        const unit = this.currentScale.unit === "day" ? "days" : `${this.currentScale.unit}s`;
        this.state.viewportStart = dateToString(start.plus({ [unit]: amount * count }));
        this.state.viewportEnd = dateToString(end.plus({ [unit]: amount * count }));
    }

    goPrevious() {
        this.shiftViewport(-1);
    }

    goNext() {
        this.shiftViewport(1);
    }

    goToday() {
        const today = parseDate(this.state.data?.timeline?.today)
            || DateTime.local().startOf("day");
        const count = Math.max(1, this.columns.length);
        let start;
        let end;
        if (this.currentScale.unit === "day") {
            start = today.minus({ days: Math.floor((count - 1) / 2) });
            end = start.plus({ days: count - 1 });
        } else if (this.currentScale.unit === "month") {
            start = today.startOf("month").minus({ months: Math.floor((count - 1) / 2) });
            end = start.plus({ months: count }).minus({ days: 1 });
        } else {
            const weekStart = today.minus({ days: today.weekday - 1 });
            start = weekStart.minus({ weeks: Math.floor((count - 1) / 2) });
            end = start.plus({ weeks: count }).minus({ days: 1 });
        }
        this.state.viewportStart = dateToString(start);
        this.state.viewportEnd = dateToString(end);
    }

    async toggleFullscreen() {
        const element = this.rootRef.el;
        if (!element) {
            return;
        }
        try {
            if (document.fullscreenElement === element) {
                await document.exitFullscreen?.();
            } else if (element.requestFullscreen) {
                await element.requestFullscreen();
            } else {
                this.state.fullscreen = !this.state.fullscreen;
            }
        } catch {
            this.state.fullscreen = !this.state.fullscreen;
        }
    }

    onFullscreenChange() {
        this.state.fullscreen = document.fullscreenElement === this.rootRef.el;
    }

    openTask(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: row.name,
            res_model: "project.task",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    exportCsv() {
        const csv = buildProjectGanttCsv(this.visibleRows, this.total);
        const projectName = (this.project?.name || "proyecto")
            .toLowerCase()
            .replace(/[^a-z0-9áéíóúüñ]+/gi, "-")
            .replace(/^-|-$/g, "") || "proyecto";
        downloadFile(csv, `cronograma-${projectName}.csv`, "text/csv;charset=utf-8");
    }

    formatDate(value) {
        return formatCsvDate(value);
    }

    formatDuration(value) {
        return formatCsvDuration(value);
    }

    formatRange() {
        if (!this.state.viewportStart || !this.state.viewportEnd) {
            return "Sin rango";
        }
        return `${this.formatDate(this.state.viewportStart)} → ${this.formatDate(this.state.viewportEnd)}`;
    }

    formatMonth(date, short = false) {
        const names = short ? MONTH_SHORT_NAMES : MONTH_NAMES;
        return `${names[date.month - 1]} ${date.year}`;
    }

    makeDayColumns(start, end) {
        const columns = [];
        for (let date = start; date <= end; date = date.plus({ days: 1 })) {
            columns.push({
                key: dateToString(date),
                start: date,
                end: date,
                label: String(date.day).padStart(2, "0"),
                groupKey: `${date.year}-${date.month}`,
                groupLabel: this.formatMonth(date),
            });
        }
        return columns;
    }

    makeMonthColumns(start, end) {
        const columns = [];
        for (
            let date = start.startOf("month");
            date <= end;
            date = date.plus({ months: 1 })
        ) {
            const columnStart = date < start ? start : date;
            const columnEnd = date.endOf("month") < end ? date.endOf("month") : end;
            columns.push({
                key: dateToString(date.startOf("month")),
                start: columnStart,
                end: columnEnd,
                label: MONTH_SHORT_NAMES[date.month - 1],
                groupKey: String(date.year),
                groupLabel: String(date.year),
            });
        }
        return columns;
    }

    makeWeekColumns(start, end) {
        const firstWeek = start.minus({ days: start.weekday - 1 });
        const columns = [];
        for (let date = firstWeek; date <= end; date = date.plus({ weeks: 1 })) {
            const weekEnd = date.plus({ days: 6 });
            const columnStart = date < start ? start : date;
            const columnEnd = weekEnd > end ? end : weekEnd;
            columns.push({
                key: dateToString(date),
                start: columnStart,
                end: columnEnd,
                label: String(date.day).padStart(2, "0"),
                groupKey: `${date.year}-${date.month}`,
                groupLabel: this.formatMonth(date),
            });
        }
        return columns;
    }

    get columnGroups() {
        const groups = [];
        for (const column of this.columns) {
            const previous = groups[groups.length - 1];
            if (previous?.key === column.groupKey) {
                previous.span += 1;
            } else {
                groups.push({
                    key: column.groupKey,
                    label: column.groupLabel,
                    span: 1,
                });
            }
        }
        return groups;
    }

    datePosition(date) {
        const columns = this.columns;
        let offset = 0;
        for (const column of columns) {
            const columnEndExclusive = column.end.plus({ days: 1 });
            if (date <= column.start) {
                return offset;
            }
            if (date < columnEndExclusive) {
                const totalDays = Math.max(1, dateDifferenceInDays(column.start, columnEndExclusive));
                return offset + (dateDifferenceInDays(column.start, date) / totalDays) * this.state.cellWidth;
            }
            offset += this.state.cellWidth;
        }
        return offset;
    }

    barGeometry(row) {
        const start = parseDate(row.start_date);
        const end = parseDate(row.end_date);
        const viewportStart = this.viewportStartDate;
        const viewportEnd = this.viewportEndDate;
        if (!start || !end || !viewportStart || !viewportEnd || start > end) {
            return false;
        }
        const clippedStart = start < viewportStart ? viewportStart : start;
        const clippedEnd = end > viewportEnd ? viewportEnd : end;
        if (clippedStart > clippedEnd) {
            return false;
        }
        const left = this.datePosition(clippedStart);
        const right = this.datePosition(clippedEnd.plus({ days: 1 }));
        return {
            left,
            width: Math.max(6, right - left),
        };
    }

    barStyle(row) {
        const geometry = this.barGeometry(row);
        if (!geometry) {
            return "display: none;";
        }
        return `left: ${geometry.left}px; width: ${geometry.width}px; background-color: ${this.colorForRow(row)};`;
    }

    colorForRow(row) {
        const index = Number.isFinite(Number(row.color_index)) ? Number(row.color_index) : 0;
        return BAR_COLORS[Math.abs(index) % BAR_COLORS.length];
    }

    rowClass(row) {
        return [
            "o_project_gantt_row",
            row.has_children ? "is-parent" : "is-leaf",
            row.depth ? "is-child" : "is-root",
        ].join(" ");
    }

    dateCellClass(value) {
        return value ? "" : "is-empty";
    }
}

registry.category("actions").add(
    "project_custom_extension.ProjectGantt",
    ProjectGantt
);
