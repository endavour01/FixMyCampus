const adminPage = document.querySelector(".admin-main[data-api-url]");

if (adminPage) {
    const apiUrl = adminPage.dataset.apiUrl;
    const detailUrl = adminPage.dataset.detailUrl;
    const searchInput = document.getElementById("issue-search");
    const statusFilter = document.getElementById("filter-status");
    const categoryFilter = document.getElementById("filter-category");
    const locationFilter = document.getElementById("filter-location");
    const priorityFilter = document.getElementById("filter-priority");
    const filters = [searchInput, statusFilter, categoryFilter, locationFilter, priorityFilter];
    const loadingState = document.getElementById("admin-loading");
    const emptyState = document.getElementById("admin-empty");
    const emptyDescription = document.getElementById("empty-description");
    const emptyReset = document.getElementById("empty-reset");
    const errorState = document.getElementById("admin-error");
    const errorDescription = document.getElementById("error-description");
    const tableWrap = document.getElementById("table-wrap");
    const tableBody = document.getElementById("issues-body");
    const tableCount = document.getElementById("table-count");
    const pagination = document.getElementById("pagination");
    const pageDescription = document.getElementById("page-description");
    const previousPage = document.getElementById("previous-page");
    const nextPage = document.getElementById("next-page");
    const trendCanvas = document.getElementById("trend-chart");
    const trendSummary = document.getElementById("trend-summary");
    const statusDonut = document.getElementById("status-donut");
    const statusLegend = document.getElementById("status-legend");
    const pageSize = 20;
    let currentPage = 1;
    let totalPages = 0;
    let searchTimer;
    let currentTrend = [];

    function setSummary(summary) {
        document.getElementById("total-issues").textContent = summary.total;
        document.getElementById("pending-issues").textContent = summary.pending;
        document.getElementById("in-progress-issues").textContent = summary.in_progress;
        document.getElementById("resolved-issues").textContent = summary.resolved;
        document.getElementById("pending-callout-count").textContent = summary.pending;
        document.getElementById("pending-callout").hidden = summary.pending === 0;
        document.getElementById("donut-total").textContent = summary.total;

        const colors = ["#dc9e18", "#348eb1", "#23a77c"];
        const values = [summary.pending, summary.in_progress, summary.resolved];
        const total = Math.max(summary.total, 1);
        let offset = 0;
        const stops = values.map((value, index) => {
            const start = offset;
            offset += (value / total) * 100;
            return `${colors[index]} ${start}% ${offset}%`;
        });
        statusDonut.style.background = `conic-gradient(${stops.join(", ")})`;
        statusLegend.replaceChildren();
        ["Pending", "In Progress", "Resolved"].forEach((label, index) => {
            const item = document.createElement("li");
            const swatch = document.createElement("span");
            swatch.className = "legend-swatch";
            swatch.style.backgroundColor = colors[index];
            const name = document.createElement("span");
            name.textContent = label;
            const count = document.createElement("strong");
            count.textContent = values[index];
            item.append(swatch, name, count);
            statusLegend.append(item);
        });
    }

    function drawTrend(trend) {
        const context = trendCanvas.getContext("2d");
        const bounds = trendCanvas.getBoundingClientRect();
        if (!context || !bounds.width) return;

        const scale = window.devicePixelRatio || 1;
        trendCanvas.width = Math.floor(bounds.width * scale);
        trendCanvas.height = Math.floor(190 * scale);
        context.setTransform(scale, 0, 0, scale, 0, 0);

        const width = bounds.width;
        const height = 190;
        const inset = { top: 14, right: 12, bottom: 32, left: 30 };
        const chartWidth = width - inset.left - inset.right;
        const chartHeight = height - inset.top - inset.bottom;
        const maximum = Math.max(1, ...trend.map((point) => point.count));
        const values = trend.map((point) => point.count);
        const x = (index) => inset.left + (index / Math.max(trend.length - 1, 1)) * chartWidth;
        const y = (value) => inset.top + chartHeight - (value / maximum) * chartHeight;

        context.clearRect(0, 0, width, height);
        context.font = "11px Trebuchet MS, sans-serif";
        context.textBaseline = "middle";
        for (let step = 0; step <= 3; step += 1) {
            const gridY = inset.top + (step / 3) * chartHeight;
            const labelValue = Math.round(maximum * (1 - step / 3));
            context.strokeStyle = "#e8e4d9";
            context.lineWidth = 1;
            context.beginPath();
            context.moveTo(inset.left, gridY);
            context.lineTo(width - inset.right, gridY);
            context.stroke();
            context.fillStyle = "#898478";
            context.textAlign = "right";
            context.fillText(String(labelValue), inset.left - 8, gridY);
        }

        const points = trend.map((point, index) => ({ x: x(index), y: y(point.count) }));
        if (points.length) {
            const gradient = context.createLinearGradient(0, inset.top, 0, inset.top + chartHeight);
            gradient.addColorStop(0, "rgba(204, 148, 17, 0.25)");
            gradient.addColorStop(1, "rgba(204, 148, 17, 0.015)");
            context.beginPath();
            context.moveTo(points[0].x, inset.top + chartHeight);
            points.forEach((point) => context.lineTo(point.x, point.y));
            context.lineTo(points[points.length - 1].x, inset.top + chartHeight);
            context.closePath();
            context.fillStyle = gradient;
            context.fill();

            context.beginPath();
            points.forEach((point, index) => {
                if (index === 0) context.moveTo(point.x, point.y);
                else context.lineTo(point.x, point.y);
            });
            context.strokeStyle = "#bc8610";
            context.lineWidth = 2.5;
            context.lineJoin = "round";
            context.lineCap = "round";
            context.stroke();

            points.forEach((point) => {
                context.beginPath();
                context.arc(point.x, point.y, 3, 0, Math.PI * 2);
                context.fillStyle = "#fffdf7";
                context.fill();
                context.strokeStyle = "#bc8610";
                context.lineWidth = 2;
                context.stroke();
            });
        }

        context.fillStyle = "#898478";
        context.textAlign = "center";
        trend.forEach((point, index) => {
            if (index % 3 !== 0 && index !== trend.length - 1) return;
            const label = new Date(`${point.day}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
            context.fillText(label, x(index), height - 12);
        });
        const total = values.reduce((sum, value) => sum + value, 0);
        trendSummary.textContent = `${total} reports in the last 14 days; peak daily count ${maximum}.`;
    }

    function setDashboardDate() {
        document.getElementById("admin-current-date").textContent = new Intl.DateTimeFormat(undefined, {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
        }).format(new Date());
    }

    function formatDate(value) {
        const date = new Date(`${value.replace(" ", "T")}Z`);
        if (Number.isNaN(date.getTime())) return value;
        return new Intl.DateTimeFormat(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        }).format(date);
    }

    function statusBadge(status) {
        const statusMap = {
            submitted: ["Pending", "pending"],
            under_review: ["Pending", "pending"],
            in_progress: ["In Progress", "in_progress"],
            resolved: ["Resolved", "resolved"],
            closed: ["Resolved", "resolved"],
        };
        const [label, key] = statusMap[status] || statusMap.submitted;
        const badge = document.createElement("span");
        badge.className = `status-badge status-${key}`;
        badge.textContent = label;
        return badge;
    }

    function priorityBadge(priority) {
        const badge = document.createElement("span");
        badge.className = `priority-badge priority-${priority}`;
        badge.textContent = `${priority.charAt(0).toUpperCase()}${priority.slice(1)}`;
        return badge;
    }

    function makeCell(content, className = "", label = "") {
        const cell = document.createElement("td");
        if (className) cell.className = className;
        cell.dataset.label = label;
        if (content instanceof Node) {
            cell.append(content);
        } else {
            cell.textContent = content;
        }
        return cell;
    }

    function renderIssue(issue) {
        const row = document.createElement("tr");
        row.append(makeCell(`#${issue.issue_id}`, "issue-id-cell", "ID"));

        const issueTitle = document.createElement("div");
        issueTitle.className = "issue-title-cell";
        issueTitle.textContent = issue.title;
        const issueDescription = document.createElement("span");
        issueDescription.className = "table-secondary";
        issueDescription.textContent = issue.description || "";
        issueTitle.append(issueDescription);
        row.append(makeCell(issueTitle, "", "Issue"));
        row.append(makeCell(issue.category, "", "Category"));

        const location = document.createElement("span");
        location.className = "table-location";
        location.textContent = `${issue.building_name}, ${issue.area_name}`;
        row.append(makeCell(location, "", "Location"));
        row.append(makeCell(issue.student_name || "Guest report", "", "Student"));
        row.append(makeCell(priorityBadge(issue.priority), "", "Priority"));
        row.append(makeCell(formatDate(issue.created_at), "", "Submitted"));
        row.append(makeCell(statusBadge(issue.status), "", "Status"));

        const action = document.createElement("a");
        action.className = "manage-link";
        action.href = detailUrl.replace(/\/0$/, `/${issue.issue_id}`);
        action.textContent = "Manage";
        action.setAttribute("aria-label", `Manage issue ${issue.issue_id}: ${issue.title}`);
        row.append(makeCell(action, "", "Manage"));
        return row;
    }

    function populateLocations(locations) {
        const currentValue = locationFilter.value;
        const options = [new Option("All locations", "")];
        locations.forEach((location) => {
            options.push(new Option(
                `${location.building_name} · ${location.area_name}`,
                String(location.location_id),
            ));
        });
        locationFilter.replaceChildren(...options);
        if (locations.some((location) => String(location.location_id) === currentValue)) {
            locationFilter.value = currentValue;
        }
    }

    function updateViewState() {
        loadingState.hidden = true;
        errorState.hidden = true;
    }

    async function loadIssues() {
        const params = new URLSearchParams({ page: String(currentPage), per_page: String(pageSize) });
        const [search, status, category, location, priority] = filters.map((filter) => filter.value.trim());
        if (search) params.set("q", search);
        if (status) params.set("status", status);
        if (category) params.set("category", category);
        if (location) params.set("location", location);
        if (priority) params.set("priority", priority);

        loadingState.hidden = false;
        errorState.hidden = true;
        emptyState.hidden = true;
        tableWrap.hidden = true;
        pagination.hidden = true;

        try {
            const response = await fetch(`${apiUrl}?${params.toString()}`, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error?.message || "The issue service returned an error.");
            }

            updateViewState();
            const { issues } = payload.data;
            const { summary, filters: availableFilters } = payload.meta;
            setSummary(summary);
            currentTrend = payload.meta.trend;
            drawTrend(currentTrend);
            populateLocations(availableFilters.locations);
            totalPages = payload.meta.pages;
            tableCount.textContent = `${payload.meta.total} ${payload.meta.total === 1 ? "issue" : "issues"}`;

            if (issues.length === 0) {
                emptyState.hidden = false;
                const hasFilters = Boolean(search || status || category || location || priority);
                emptyDescription.textContent = hasFilters
                    ? "No reports match these filters. Try broadening your search."
                    : "There are no reports to display yet.";
                emptyReset.hidden = !hasFilters;
                return;
            }

            tableBody.replaceChildren(...issues.map(renderIssue));
            tableWrap.hidden = false;
            pagination.hidden = totalPages <= 1;
            pageDescription.textContent = `Page ${payload.meta.page} of ${totalPages}`;
            previousPage.disabled = payload.meta.page <= 1;
            nextPage.disabled = payload.meta.page >= totalPages;
        } catch (error) {
            loadingState.hidden = true;
            errorDescription.textContent = error.message || "Check your connection and try again.";
            errorState.hidden = false;
        }
    }

    function applyFilters() {
        currentPage = 1;
        loadIssues();
    }

    searchInput.addEventListener("input", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(applyFilters, 250);
    });
    [statusFilter, categoryFilter, locationFilter, priorityFilter].forEach((filter) => {
        filter.addEventListener("change", applyFilters);
    });
    document.getElementById("reset-filters").addEventListener("click", () => {
        filters.forEach((filter) => { filter.value = ""; });
        applyFilters();
        searchInput.focus();
    });
    emptyReset.addEventListener("click", () => {
        filters.forEach((filter) => { filter.value = ""; });
        applyFilters();
        searchInput.focus();
    });
    previousPage.addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage -= 1;
            loadIssues();
        }
    });
    nextPage.addEventListener("click", () => {
        if (currentPage < totalPages) {
            currentPage += 1;
            loadIssues();
        }
    });
    document.getElementById("retry-load").addEventListener("click", loadIssues);
    document.getElementById("admin-filters").addEventListener("submit", (event) => {
        event.preventDefault();
        applyFilters();
    });

    document.querySelectorAll("[data-select-filter]").forEach((shortcut) => {
        shortcut.addEventListener("click", () => {
            const filterName = shortcut.dataset.selectFilter;
            const filterValue = shortcut.dataset.selectValue;
            const target = document.getElementById(`filter-${filterName}`);
            if (target && filterValue) {
                target.value = filterValue;
                applyFilters();
            } else if (target) {
                target.focus();
            }
        });
    });

    const sidebar = document.getElementById("admin-sidebar");
    const sidebarToggle = document.querySelector("[data-admin-menu-toggle]");
    const sidebarBackdrop = document.querySelector("[data-sidebar-close]");
    function setSidebarOpen(isOpen) {
        document.body.classList.toggle("sidebar-open", isOpen);
        sidebarToggle.setAttribute("aria-expanded", String(isOpen));
        sidebarBackdrop.hidden = !isOpen;
    }
    sidebarToggle.addEventListener("click", () => setSidebarOpen(!document.body.classList.contains("sidebar-open")));
    sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));
    sidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setSidebarOpen(false)));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setSidebarOpen(false);
    });

    setDashboardDate();
    window.addEventListener("resize", () => drawTrend(currentTrend));

    loadIssues();
}