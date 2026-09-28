const campusMapPage = document.querySelector(".campus-map-main[data-api-url]");

if (campusMapPage) {
    const categoryFilter = document.getElementById("map-category");
    const statusFilter = document.getElementById("map-status");
    const loadingState = document.getElementById("map-loading");
    const errorState = document.getElementById("map-error");
    const mapElement = document.getElementById("campus-map");
    const noCoordinates = document.getElementById("map-no-coordinates");
    const directoryGrid = document.getElementById("directory-grid");
    const directoryEmpty = document.getElementById("directory-empty");
    let leafletMap = null;
    let markerLayer = null;

    function markerClass(count) {
        if (count >= 6) return "pin-critical";
        if (count >= 3) return "pin-high";
        if (count >= 1) return "pin-mid";
        return "pin-low";
    }

    function formatLocation(location) {
        const floor = Number(location.floor_number) === 0 ? "Ground floor" : `Floor ${location.floor_number}`;
        return `${location.building_name} · ${location.area_name} · ${floor}`;
    }

    function formatDate(value) {
        const parsed = new Date(`${value.replace(" ", "T")}Z`);
        if (Number.isNaN(parsed.getTime())) return value;
        return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed);
    }

    function locationTitle(location) {
        return `${location.building_name} · ${location.area_name}`;
    }

    function makeIssueLink(issue) {
        const link = document.createElement("a");
        link.href = campusMapPage.dataset.issueUrl.replace(/\/0$/, `/${issue.issue_id}`);
        link.textContent = `#${issue.issue_id} ${issue.title}`;
        return link;
    }

    function popupContent(location) {
        const popup = document.createElement("div");
        popup.className = "map-popup";
        const heading = document.createElement("h3");
        heading.textContent = locationTitle(location);
        const count = document.createElement("p");
        count.textContent = `${location.unresolved_count} unresolved ${location.unresolved_count === 1 ? "issue" : "issues"}`;
        popup.append(heading, count);
        if (!location.reports.length) {
            const empty = document.createElement("p");
            empty.textContent = "No reports match the selected filters.";
            popup.append(empty);
        } else {
            const list = document.createElement("ul");
            location.reports.slice(0, 6).forEach((issue) => {
                const item = document.createElement("li");
                item.append(makeIssueLink(issue));
                const status = document.createElement("span");
                status.textContent = ` · ${issue.status.replaceAll("_", " ")}`;
                item.append(status);
                list.append(item);
            });
            popup.append(list);
            if (location.report_count > 6) {
                const more = document.createElement("p");
                more.textContent = `Showing 6 of ${location.report_count} matching reports. See the list below for the latest 25.`;
                popup.append(more);
            }
        }
        return popup;
    }

    function renderMap(locations) {
        if (markerLayer) markerLayer.clearLayers();
        const mappable = locations.filter((location) => Number.isFinite(location.latitude) && Number.isFinite(location.longitude));
        if (!window.L) {
            noCoordinates.textContent = "The interactive map could not load. Use the location and report list below.";
            noCoordinates.hidden = false;
            mapElement.hidden = true;
            return;
        }

        noCoordinates.textContent = "The map is centered on campus. Configure coordinates for each location to display its marker.";
        noCoordinates.hidden = mappable.length > 0;
        mapElement.hidden = false;
        if (!leafletMap) {
            const center = [
                Number(campusMapPage.dataset.centerLat),
                Number(campusMapPage.dataset.centerLng),
            ];
            leafletMap = L.map(mapElement, { scrollWheelZoom: false })
                .setView(mappable.length ? [mappable[0].latitude, mappable[0].longitude] : center, 16);
            L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
            }).addTo(leafletMap);
            markerLayer = L.layerGroup().addTo(leafletMap);
        }

        const bounds = [];
        mappable.forEach((location) => {
            const count = location.unresolved_count;
            const colorClass = markerClass(count);
            const icon = L.divIcon({
                className: "issue-marker-shell",
                html: `<span class="issue-count-marker ${colorClass}" aria-hidden="true">${count}</span>`,
                iconSize: [36, 36],
                iconAnchor: [18, 18],
                popupAnchor: [0, -17],
            });
            const marker = L.marker([location.latitude, location.longitude], {
                icon,
                title: `${locationTitle(location)}: ${count} unresolved ${count === 1 ? "issue" : "issues"}`,
                alt: `${locationTitle(location)}, ${count} unresolved ${count === 1 ? "issue" : "issues"}`,
                keyboard: true,
            });
            marker.bindPopup(popupContent(location));
            marker.addTo(markerLayer);
            bounds.push([location.latitude, location.longitude]);
        });

        if (bounds.length === 1) leafletMap.setView(bounds[0], 17);
        else if (bounds.length > 1) leafletMap.fitBounds(bounds, { padding: [28, 28], maxZoom: 17 });
        window.requestAnimationFrame(() => leafletMap.invalidateSize());
    }

    function renderDirectory(locations) {
        directoryGrid.replaceChildren();
        directoryEmpty.hidden = locations.length !== 0;
        locations.forEach((location) => {
            const card = document.createElement("article");
            card.className = "location-card";
            const heading = document.createElement("div");
            heading.className = "location-card-heading";
            const titleGroup = document.createElement("div");
            const title = document.createElement("h3");
            title.textContent = locationTitle(location);
            const detail = document.createElement("p");
            detail.textContent = formatLocation(location);
            titleGroup.append(title, detail);
            const badge = document.createElement("span");
            badge.className = `unresolved-count ${markerClass(location.unresolved_count)}`;
            badge.textContent = `${location.unresolved_count} unresolved`;
            heading.append(titleGroup, badge);
            card.append(heading);

            if (location.reports.length) {
                const reportList = document.createElement("ul");
                reportList.className = "location-reports";
                location.reports.forEach((issue) => {
                    const item = document.createElement("li");
                    item.append(makeIssueLink(issue));
                    const status = document.createElement("span");
                    status.className = "report-status";
                    status.textContent = `${issue.status.replaceAll("_", " ")} · ${formatDate(issue.created_at)}`;
                    item.append(status);
                    reportList.append(item);
                });
                card.append(reportList);
                if (location.report_count > location.reports.length) {
                    const note = document.createElement("p");
                    note.className = "directory-note";
                    note.textContent = `Showing the latest ${location.reports.length} of ${location.report_count} matching reports.`;
                    card.append(note);
                }
            } else {
                const empty = document.createElement("p");
                empty.className = "no-matching-reports";
                empty.textContent = "No reports match the selected filters.";
                card.append(empty);
            }
            if (!Number.isFinite(location.latitude) || !Number.isFinite(location.longitude)) {
                const coordNote = document.createElement("p");
                coordNote.className = "directory-note";
                coordNote.textContent = "Map coordinates not configured.";
                card.append(coordNote);
            }
            directoryGrid.append(card);
        });
    }

    async function loadLocations() {
        errorState.hidden = true;
        loadingState.hidden = false;
        const params = new URLSearchParams({ status: statusFilter.value });
        if (categoryFilter.value) params.set("category", categoryFilter.value);
        try {
            const response = await fetch(`${campusMapPage.dataset.apiUrl}?${params}`, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error?.message || "Could not load campus reports.");
            renderDirectory(payload.data.locations);
            renderMap(payload.data.locations);
        } catch (error) {
            errorState.textContent = error.message || "Check your connection and try again.";
            errorState.hidden = false;
        } finally {
            loadingState.hidden = true;
        }
    }

    document.getElementById("map-filters").addEventListener("submit", (event) => event.preventDefault());
    categoryFilter.addEventListener("change", loadLocations);
    statusFilter.addEventListener("change", loadLocations);
    document.getElementById("map-filter-reset").addEventListener("click", () => {
        categoryFilter.value = "";
        statusFilter.value = "all";
        loadLocations();
    });
    window.addEventListener("resize", () => {
        if (leafletMap && !mapElement.hidden) leafletMap.invalidateSize();
    });
    loadLocations();
}
