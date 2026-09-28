const reportsPage = document.querySelector(".reports-main[data-api-url]");

if (reportsPage) {
    const apiUrl = reportsPage.dataset.apiUrl;
    const issueUrlTemplate = reportsPage.dataset.issueUrl;
    const loadingState = document.getElementById("reports-loading");
    const signedOutState = document.getElementById("reports-signed-out");
    const emptyState = document.getElementById("reports-empty");
    const noResultsState = document.getElementById("reports-no-results");
    const errorState = document.getElementById("reports-error");
    const errorMessage = document.getElementById("error-message");
    const reportList = document.getElementById("report-list");
    const filters = document.getElementById("report-filters");
    const resultsCount = document.getElementById("results-count");
    const searchInput = document.getElementById("report-search");
    const categoryFilter = document.getElementById("category-filter");
    const statusFilter = document.getElementById("status-filter");
    const clearFiltersButton = document.getElementById("clear-filters");
    const retryButton = document.getElementById("retry-reports");
    const trendCanvas = document.getElementById("student-trend-chart");
    const trendSummary = document.getElementById("student-trend-summary");
    const statusDonut = document.getElementById("student-status-donut");
    const statusLegend = document.getElementById("student-status-legend");
    let reports = [];
    let currentTrend = [];

    const statusDetails = {
        submitted: { label: "Pending", key: "pending", filter: "pending" },
        pending: { label: "Pending", key: "pending", filter: "pending" },
        under_review: { label: "Pending", key: "pending", filter: "pending" },
        in_progress: { label: "In Progress", key: "in_progress", filter: "in_progress" },
        resolved: { label: "Resolved", key: "resolved", filter: "resolved" },
        closed: { label: "Resolved", key: "resolved", filter: "resolved" },
    };

    function hideStates() {
        [loadingState, signedOutState, emptyState, noResultsState, errorState].forEach((state) => {
            state.hidden = true;
        });
    }

    function setStudentSummary(summary) {
        document.getElementById("student-total-reports").textContent = summary.total;
        document.getElementById("student-pending-reports").textContent = summary.pending;
        document.getElementById("student-progress-reports").textContent = summary.in_progress;
        document.getElementById("student-resolved-reports").textContent = summary.resolved;
        document.getElementById("student-pending-callout-count").textContent = summary.pending;
        document.getElementById("student-pending-callout").hidden = summary.pending === 0;
        document.getElementById("student-donut-total").textContent = summary.total;

        const colors = ["#dc9e18", "#348eb1", "#23a77c"];
        const values = [summary.pending, summary.in_progress, summary.resolved];
        const total = Math.max(summary.total, 1);
        let offset = 0;
        const stops = values.map((value, index) => {
            const start = offset;
            offset += (value / total) * 100;
            return `${colors[index]} ${start}% ${offset}%`;
        });
        statusDonut.style.background = summary.total
            ? `conic-gradient(${stops.join(", ")})`
            : "conic-gradient(#ded9cc 0% 100%)";
        statusLegend.replaceChildren();
        ["Pending", "In Progress", "Resolved"].forEach((label, index) => {
            const item = document.createElement("li");
            const swatch = document.createElement("span");
            swatch.className = "student-legend-swatch";
            swatch.style.backgroundColor = colors[index];
            const name = document.createElement("span");
            name.textContent = label;
            const count = document.createElement("strong");
            count.textContent = values[index];
            item.append(swatch, name, count);
            statusLegend.append(item);
        });
    }

    function drawStudentTrend(trend) {
        const context = trendCanvas.getContext("2d");
        const bounds = trendCanvas.getBoundingClientRect();
        if (!context || !bounds.width) return;

        const scale = window.devicePixelRatio || 1;
        trendCanvas.width = Math.floor(bounds.width * scale);
        trendCanvas.height = Math.floor(180 * scale);
        context.setTransform(scale, 0, 0, scale, 0, 0);

        const width = bounds.width;
        const height = 180;
        const inset = { top: 12, right: 10, bottom: 30, left: 26 };
        const chartWidth = width - inset.left - inset.right;
        const chartHeight = height - inset.top - inset.bottom;
        const maximum = Math.max(1, ...trend.map((point) => point.count));
        const x = (index) => inset.left + (index / Math.max(trend.length - 1, 1)) * chartWidth;
        const y = (value) => inset.top + chartHeight - (value / maximum) * chartHeight;

        context.clearRect(0, 0, width, height);
        for (let line = 0; line <= 2; line += 1) {
            const gridY = inset.top + (line / 2) * chartHeight;
            context.beginPath();
            context.moveTo(inset.left, gridY);
            context.lineTo(width - inset.right, gridY);
            context.strokeStyle = "#e8e4d9";
            context.lineWidth = 1;
            context.stroke();
        }

        const points = trend.map((point, index) => ({ x: x(index), y: y(point.count) }));
        if (points.length) {
            const gradient = context.createLinearGradient(0, inset.top, 0, inset.top + chartHeight);
            gradient.addColorStop(0, "rgba(204, 148, 17, 0.24)");
            gradient.addColorStop(1, "rgba(204, 148, 17, 0.015)");
            context.beginPath();
            context.moveTo(points[0].x, inset.top + chartHeight);
            points.forEach((point) => context.lineTo(point.x, point.y));
            context.lineTo(points[points.length - 1].x, inset.top + chartHeight);
            context.closePath();
            context.fillStyle = gradient;
            context.fill();

            context.beginPath();
            points.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
            context.strokeStyle = "#bc8610";
            context.lineWidth = 2.3;
            context.lineJoin = "round";
            context.lineCap = "round";
            context.stroke();
            points.forEach((point) => {
                context.beginPath();
                context.arc(point.x, point.y, 2.8, 0, Math.PI * 2);
                context.fillStyle = "#fffdf7";
                context.fill();
                context.strokeStyle = "#bc8610";
                context.lineWidth = 1.8;
                context.stroke();
            });
        }

        context.fillStyle = "#898478";
        context.font = "10px Trebuchet MS, sans-serif";
        context.textAlign = "center";
        trend.forEach((point, index) => {
            if (index % 3 !== 0 && index !== trend.length - 1) return;
            const label = new Date(`${point.day}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
            context.fillText(label, x(index), height - 11);
        });
        const total = trend.reduce((sum, point) => sum + point.count, 0);
        trendSummary.textContent = `${total} reports in the last 14 days; peak daily count ${maximum}.`;
    }

    document.getElementById("student-current-date").textContent = new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
    }).format(new Date());

    function formatDate(value) {
        const date = new Date(`${value.replace(" ", "T")}Z`);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        return new Intl.DateTimeFormat(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        }).format(date);
    }

    function addReportDetail(parent, label, value, extraClass = "") {
        const item = document.createElement("div");
        item.className = "report-detail-item";

        const detailLabel = document.createElement("span");
        detailLabel.className = "report-detail-label";
        detailLabel.textContent = label;

        const detailValue = document.createElement("span");
        detailValue.className = `report-detail-value ${extraClass}`.trim();
        detailValue.textContent = value;

        item.append(detailLabel, detailValue);
        parent.append(item);
    }

    function createReportCard(report) {
        const link = document.createElement("a");
        link.className = "report-card";
        link.href = issueUrlTemplate.replace(/\/0$/, `/${report.issue_id}`);
        link.setAttribute("aria-label", `Open issue ${report.issue_id}: ${report.title}`);

        const heading = document.createElement("div");
        heading.className = "report-card-heading";

        const issueId = document.createElement("span");
        issueId.className = "report-card-id";
        issueId.textContent = `#${report.issue_id}`;

        const title = document.createElement("h2");
        title.className = "report-card-title";
        title.textContent = report.title;
        heading.append(issueId, title);

        const summary = document.createElement("p");
        summary.className = "report-card-summary";
        summary.textContent = report.description;

        const status = statusDetails[report.status] || statusDetails.submitted;
        const badge = document.createElement("span");
        badge.className = `status-badge status-${status.key} report-card-status`;
        badge.textContent = status.label;

        const details = document.createElement("div");
        details.className = "report-card-details";
        const location = `${report.location.building_name}, ${report.location.area_name}`;
        addReportDetail(details, "Category", report.category);
        addReportDetail(details, "Location", location);
        addReportDetail(details, "Submitted", formatDate(report.created_at));

        const priority = document.createElement("span");
        priority.className = `priority-badge priority-${report.priority}`;
        priority.textContent = report.priority.charAt(0).toUpperCase() + report.priority.slice(1);
        addReportDetail(details, "Priority", "", "priority-value");
        details.querySelector(".priority-value").replaceWith(priority);

        link.append(heading, badge, summary, details);
        return link;
    }

    async function loadReports() {
        const params = new URLSearchParams();
        const search = searchInput.value.trim();
        const category = categoryFilter.value;
        const status = statusFilter.value;
        if (search) params.set("q", search);
        if (category) params.set("category", category);
        if (status) params.set("status", status);
        const hasFilters = Boolean(search || category || status);

        hideStates();
        loadingState.hidden = false;
        filters.hidden = !reports.length && !hasFilters;
        reportList.hidden = true;
        resultsCount.hidden = true;

        try {
            const response = await fetch(`${apiUrl}?${params.toString()}`, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            const payload = await response.json();
            loadingState.hidden = true;

            if (response.status === 401) {
                signedOutState.hidden = false;
                return;
            }
            if (!response.ok) {
                throw new Error(payload.error?.message || "The report service returned an error.");
            }

            reports = payload.data.reports;
            setStudentSummary(payload.meta.summary);
            currentTrend = payload.meta.trend;
            drawStudentTrend(currentTrend);
            if (reports.length === 0) {
                filters.hidden = !hasFilters;
                if (hasFilters) {
                    noResultsState.hidden = false;
                } else {
                    emptyState.hidden = false;
                }
                resultsCount.hidden = !hasFilters;
                resultsCount.textContent = `Showing 0 of ${payload.meta.total} reports`;
                reportList.replaceChildren();
                return;
            }

            filters.hidden = false;
            reportList.replaceChildren(...reports.map(createReportCard));
            reportList.hidden = false;
            noResultsState.hidden = true;
            resultsCount.hidden = false;
            const count = payload.meta.count;
            const total = payload.meta.total;
            resultsCount.textContent = hasFilters
                ? `Showing ${count} of ${total} reports`
                : `${total} ${total === 1 ? "report" : "reports"}`;
        } catch (error) {
            loadingState.hidden = true;
            errorMessage.textContent = error.message || "Check your connection and try again.";
            errorState.hidden = false;
        }
    }

    let searchTimer;
    searchInput.addEventListener("input", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(loadReports, 200);
    });
    categoryFilter.addEventListener("change", loadReports);
    statusFilter.addEventListener("change", loadReports);
    clearFiltersButton.addEventListener("click", () => {
        searchInput.value = "";
        categoryFilter.value = "";
        statusFilter.value = "";
        loadReports();
        searchInput.focus();
    });
    retryButton.addEventListener("click", loadReports);

    document.querySelectorAll("[data-student-filter]").forEach((shortcut) => {
        shortcut.addEventListener("click", () => {
            const controls = {
                status: statusFilter,
                category: categoryFilter,
            };
            const control = controls[shortcut.dataset.studentFilter];
            if (control) {
                control.value = shortcut.dataset.studentValue;
                loadReports();
            }
        });
    });

    const studentSidebar = document.getElementById("student-sidebar");
    const studentMenuToggle = document.querySelector("[data-student-menu-toggle]");
    const studentBackdrop = document.querySelector("[data-student-sidebar-close]");
    function setStudentSidebarOpen(isOpen) {
        document.body.classList.toggle("student-sidebar-open", isOpen);
        studentMenuToggle.setAttribute("aria-expanded", String(isOpen));
        studentBackdrop.hidden = !isOpen;
    }
    studentMenuToggle.addEventListener("click", () => setStudentSidebarOpen(!document.body.classList.contains("student-sidebar-open")));
    studentBackdrop.addEventListener("click", () => setStudentSidebarOpen(false));
    studentSidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setStudentSidebarOpen(false)));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setStudentSidebarOpen(false);
    });
    window.addEventListener("resize", () => drawStudentTrend(currentTrend));

    loadReports();
}