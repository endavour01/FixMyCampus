const analyticsPage = document.querySelector(".analytics-main[data-api-url]");

if (analyticsPage) {
    const filterForm = document.getElementById("analytics-filter");
    const startDate = document.getElementById("start-date");
    const endDate = document.getElementById("end-date");
    const loading = document.getElementById("analytics-loading");
    const errorState = document.getElementById("analytics-error");
    const rangeLabel = document.getElementById("analytics-range");
    const hotspotBody = document.getElementById("hotspot-body");
    const hotspotTable = document.getElementById("hotspot-table-wrap");
    const hotspotEmpty = document.getElementById("hotspot-empty");
    const charts = {};

    function formatLocation(location) {
        const floor = Number(location.floor_number) === 0 ? "Ground floor" : `Floor ${location.floor_number}`;
        return `${location.building_name} · ${location.area_name} · ${floor}`;
    }

    function formatAverage(hours) {
        if (hours === null || hours === undefined) return "—";
        if (hours >= 24) {
            const days = hours / 24;
            return `${Number.isInteger(days) ? days : days.toFixed(1)} days`;
        }
        return `${hours} hours`;
    }

    function replaceChart(name, canvasId, config) {
        if (charts[name]) charts[name].destroy();
        charts[name] = new Chart(document.getElementById(canvasId), config);
    }

    function chartOptions(horizontal = false) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: horizontal ? "y" : "x",
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (context) => `${context.parsed[horizontal ? "x" : "y"]} reports` } },
            },
            scales: {
                x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#eceee8" } },
                y: { beginAtZero: true, ticks: { precision: 0 }, grid: { display: !horizontal } },
            },
        };
    }

    function renderCharts(data) {
        const categories = data.categories;
        replaceChart("categories", "category-chart", {
            type: "bar",
            data: { labels: categories.map((item) => item.label), datasets: [{ data: categories.map((item) => item.count), backgroundColor: "#c18a16", borderRadius: 4, maxBarThickness: 42 }] },
            options: chartOptions(),
        });

        const locations = data.locations.slice(0, 12);
        replaceChart("locations", "location-chart", {
            type: "bar",
            data: { labels: locations.map(formatLocation), datasets: [{ data: locations.map((item) => item.count), backgroundColor: "#806018", borderRadius: 4, maxBarThickness: 34 }] },
            options: { ...chartOptions(true), scales: { ...chartOptions(true).scales, y: { ...chartOptions(true).scales.y, grid: { display: false } } } },
        });

        replaceChart("monthly", "monthly-chart", {
            type: "line",
            data: {
                labels: data.monthly.map((item) => {
                    const [year, month] = item.month.split("-").map(Number);
                    return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(new Date(year, month - 1, 1));
                }),
                datasets: [{ label: "Reports", data: data.monthly.map((item) => item.count), borderColor: "#b78412", backgroundColor: "rgba(204, 148, 17, 0.15)", fill: true, tension: 0.25, pointRadius: 3 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#eceee8" } } },
            },
        });
    }

    function renderHotspots(hotspots) {
        hotspotBody.replaceChildren();
        hotspots.forEach((hotspot, index) => {
            const row = document.createElement("tr");
            const rank = document.createElement("td");
            rank.textContent = `#${index + 1}`;
            const location = document.createElement("td");
            location.textContent = formatLocation(hotspot);
            const count = document.createElement("td");
            count.textContent = hotspot.unresolved;
            row.append(rank, location, count);
            hotspotBody.append(row);
        });
        hotspotTable.hidden = hotspots.length === 0;
        hotspotEmpty.hidden = hotspots.length !== 0;
    }

    function updateRange(meta) {
        if (meta.start_date && meta.end_date) rangeLabel.textContent = `${meta.start_date} through ${meta.end_date}`;
        else if (meta.start_date) rangeLabel.textContent = `From ${meta.start_date}`;
        else if (meta.end_date) rangeLabel.textContent = `Through ${meta.end_date}`;
        else rangeLabel.textContent = "All reporting dates";
    }

    async function loadAnalytics(event) {
        if (event) event.preventDefault();
        errorState.hidden = true;
        loading.hidden = false;
        const params = new URLSearchParams();
        if (startDate.value) params.set("start_date", startDate.value);
        if (endDate.value) params.set("end_date", endDate.value);

        try {
            const response = await fetch(`${analyticsPage.dataset.apiUrl}?${params}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error?.message || "Could not load analytics.");

            const { metrics, ...data } = payload.data;
            document.getElementById("metric-total").textContent = metrics.total;
            document.getElementById("metric-unresolved").textContent = metrics.unresolved;
            document.getElementById("metric-rate").textContent = `${metrics.resolution_rate}%`;
            document.getElementById("metric-average").textContent = formatAverage(metrics.average_resolution_hours);
            updateRange(payload.meta);
            renderCharts(data);
            renderHotspots(data.hotspots);
        } catch (error) {
            errorState.textContent = error.message || "Check your connection and try again.";
            errorState.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    filterForm.addEventListener("submit", loadAnalytics);
    document.getElementById("clear-dates").addEventListener("click", () => {
        startDate.value = "";
        endDate.value = "";
        loadAnalytics();
    });
    loadAnalytics();
}
