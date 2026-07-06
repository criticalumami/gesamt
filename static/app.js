// --- Gesamtkunstwerk Frontend Controller ---

// State variables
let state = {
    jobs: [],
    offices: [],
    settings: {},
    analytics: null,
    activeTab: 'global',
    searchQuery: '',
    customSearchQuery: '',
    selectedAddress: '',
    scanning: false,
    logWebSocket: null // Add WebSocket variable
};

// Constants
const PLATFORM_OPTIONS = ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com", "EURAXESS", "OEA", "Jobs for Lebanon"];
const ALL_STATUSES = ["New", "Applied", "Interviewing", "Offer", "Rejected", "Archived"];

// DOM elements
const el = {
    tabGlobalBtn: document.getElementById('tab-global-btn'),
    tabCustomBtn: document.getElementById('tab-custom-btn'),
    tabAnalyticsBtn: document.getElementById('tab-analytics-btn'),
    tabSettingsBtn: document.getElementById('tab-settings-btn'),
    panelGlobal: document.getElementById('panel-global'),
    panelCustom: document.getElementById('panel-custom'),
    panelAnalytics: document.getElementById('panel-analytics'),
    panelSettings: document.getElementById('panel-settings'),
    globalListingsGrid: document.getElementById('global-listings-grid'),
    customDirectoryGrid: document.getElementById('custom-directory-grid'),
    globalSearchInput: document.getElementById('global-search-input'),
    customSearchInput: document.getElementById('custom-search-input'),
    customAddressSelect: document.getElementById('custom-address-select'),
    scanJobBoardsBtn: document.getElementById('scan-job-boards-btn'),
    stopScanBtn: document.getElementById('stop-scan-btn'),
    clearResultsBtn: document.getElementById('clear-results-btn'),
    terminalContainer: document.getElementById('terminal-container'),
    terminalBody: document.getElementById('terminal-body'),
    terminalCloseBtn: document.getElementById('terminal-close-btn'),
    detailDrawer: document.getElementById('detail-drawer'),
    detailDrawerOverlay: document.getElementById('detail-drawer-overlay'),
    detailDrawerClose: document.getElementById('detail-drawer-close'),
    toast: document.getElementById('toast-notification')
};

// Initial setup
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initEventListeners();
    loadAllData();
});

// Tab Switcher
function initTabs() {
    const tabs = [
        { btn: el.tabGlobalBtn, panel: el.panelGlobal, name: 'global', loader: loadJobs },
        { btn: el.tabCustomBtn, panel: el.panelCustom, name: 'custom', loader: loadOffices },
        { btn: el.tabAnalyticsBtn, panel: el.panelAnalytics, name: 'analytics', loader: loadAnalytics },
        { btn: el.tabSettingsBtn, panel: el.panelSettings, name: 'settings', loader: null }
    ];

    tabs.forEach(t => {
        t.btn.addEventListener('click', () => {
            tabs.forEach(x => {
                x.btn.classList.remove('active');
                x.panel.classList.remove('active');
            });
            t.btn.classList.add('active');
            t.panel.classList.add('active');
            state.activeTab = t.name;

            if (t.loader) {
                t.loader();
            }
        });
    });
}

// Event Listeners
function initEventListeners() {
    el.globalSearchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value.toLowerCase();
        renderJobs();
    });
    el.customSearchInput.addEventListener('input', (e) => {
        state.customSearchQuery = e.target.value.toLowerCase();
        renderOffices();
    });
    el.customAddressSelect.addEventListener('change', (e) => {
        state.selectedAddress = e.target.value;
        renderOffices();
    });
    el.scanJobBoardsBtn.addEventListener('click', startGlobalScan);
    el.stopScanBtn.addEventListener('click', stopGlobalScanCall);
    el.clearResultsBtn.addEventListener('click', clearAllResults);
    el.terminalCloseBtn.addEventListener('click', () => el.terminalContainer.classList.add('hidden'));
    el.detailDrawerClose.addEventListener('click', closeDrawer);
    el.detailDrawerOverlay.addEventListener('click', closeDrawer);
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
    document.getElementById('btn-auto-expand').addEventListener('click', autoExpandKeywords);
    document.getElementById('settings-resume').addEventListener('change', uploadResumeFile);
}

// --- API & Data Loading ---
async function loadAllData() {
    await loadSettings();
    await loadJobs();
    await loadOffices();
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        if (response.ok) {
            state.settings = await response.json();
            renderSettingsPanel();
        }
    } catch (e) {
        showToast('Error loading settings: ' + e.message, 'error');
    }
}

async function loadJobs() {
    try {
        const response = await fetch('/api/jobs');
        if (response.ok) {
            state.jobs = await response.json();
            renderJobs();
        }
    } catch (e) {
        showToast('Error loading jobs: ' + e.message, 'error');
    }
}

async function loadOffices() {
    try {
        const response = await fetch('/api/offices');
        if (response.ok) {
            state.offices = await response.json();
            populateAddressDropdown();
            renderOffices();
        }
    } catch (e) {
        showToast('Error loading offices: ' + e.message, 'error');
    }
}

async function loadAnalytics() {
    el.panelAnalytics.innerHTML = '<div class="loading-state">Loading Analytics...</div>';
    try {
        const response = await fetch('/api/analytics');
        if (response.ok) {
            state.analytics = await response.json();
            renderAnalytics();
        } else {
            el.panelAnalytics.innerHTML = '<div class="empty-state">Failed to load analytics data.</div>';
        }
    } catch (e) {
        el.panelAnalytics.innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
    }
}

// --- Render Functions ---
function renderJobs() {
    const grid = el.globalListingsGrid;
    grid.innerHTML = '';

    const terms = state.searchQuery.split(/[ ,]+/).map(t => t.trim().toLowerCase()).filter(Boolean);
    const filtered = state.jobs.filter(job => {
        const text = `${job.Title} ${job.Platform} ${job.Location} ${job.Description}`.toLowerCase();
        if (terms.length === 0) return true;
        return terms.some(term => text.includes(term));
    });

    if (filtered.length === 0) {
        grid.innerHTML = '<div class="empty-state"><p class="empty-text">No matching jobs found.</p></div>';
        return;
    }

    filtered.forEach(job => {
        const card = document.createElement('div');
        card.className = 'card';
        
        const score = job["Match Score"] !== undefined ? job["Match Score"] : 0;
        const scoreClass = score < 60 ? 'card-score low-match' : 'card-score';

        const statusOptions = ALL_STATUSES.map(s => `<option value="${s}" ${job.Status === s ? 'selected' : ''}>${s}</option>`).join('');

        card.innerHTML = `
            <div class="card-clickable" onclick="openDrawer(JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify(job))}')))">
                <div class="card-header">
                    <span class="card-badge">${job.Platform}</span>
                    <span class="${scoreClass}">Match: ${score}%</span>
                </div>
                <div>
                    <h3 class="card-title">${job.Title}</h3>
                    <p class="card-description">${stripHtml(job.Description)}</p>
                </div>
                <div class="card-footer">
                    <span class="card-footer-item">📍 ${job.Location || 'N/A'}</span>
                    <span class="card-footer-item">📅 ${job.Deadline || 'N/A'}</span>
                </div>
            </div>
            <div class="card-actions">
                <select class="status-select" onchange="updateJobStatus('${job.URL}', this.value)">
                    ${statusOptions}
                </select>
            </div>
        `;
        grid.appendChild(card);
    });
}

function renderAnalytics() {
    const panel = el.panelAnalytics;
    const data = state.analytics;

    if (!data) {
        panel.innerHTML = '<div class="empty-state">No analytics data available.</div>';
        return;
    }

    panel.innerHTML = `
        <div class="analytics-header">
            <h2>Analytics Dashboard</h2>
        </div>
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-value">${data.kpis.total_matches}</div>
                <div class="kpi-label">Total Matches</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${data.kpis.applied_count}</div>
                <div class="kpi-label">Applications Sent</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${data.kpis.interview_count}</div>
                <div class="kpi-label">Interviews</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">${data.kpis.offer_count}</div>
                <div class="kpi-label">Offers</div>
            </div>
        </div>
        <div class="chart-grid">
            <div class="chart-container">
                <h3>Application Funnel</h3>
                <canvas id="funnel-chart"></canvas>
            </div>
            <div class="chart-container">
                <h3>Matches by Platform</h3>
                <canvas id="platform-chart"></canvas>
            </div>
        </div>
        <div class="chart-grid-full">
            <div class="chart-container">
                <h3>Applications Over Time</h3>
                <canvas id="timeline-chart"></canvas>
            </div>
        </div>
    `;

    // Init charts
    try {
        new Chart(document.getElementById('funnel-chart'), {
            type: 'bar',
            data: {
                labels: data.funnel.stages,
                datasets: [{
                    label: 'Count',
                    data: data.funnel.counts,
                    backgroundColor: ['#e5e7eb', '#9ca3af', '#6b7280', '#1f2937'],
                }]
            },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false }
        });

        new Chart(document.getElementById('platform-chart'), {
            type: 'doughnut',
            data: {
                labels: data.platforms.labels,
                datasets: [{
                    data: data.platforms.values
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });

        new Chart(document.getElementById('timeline-chart'), {
            type: 'bar',
            data: {
                labels: data.timeline.dates,
                datasets: [{
                    label: 'Applications Sent',
                    data: data.timeline.counts,
                    backgroundColor: '#6b7280'
                }]
            },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { type: 'time', time: { unit: 'day' } } } }
        });
    } catch (e) {
        console.error("Chart.js error:", e);
        showToast('Could not render charts.', 'error');
    }
}

function populateAddressDropdown() {
    const select = el.customAddressSelect;
    select.innerHTML = '<option value="">All Locations</option>';
    const addresses = new Set(state.offices.map(o => o.Address.split(',')[0].trim()).filter(Boolean));
    addresses.forEach(addr => {
        const opt = document.createElement('option');
        opt.value = addr;
        opt.textContent = addr;
        select.appendChild(opt);
    });
}

function renderOffices() {
    const grid = el.customDirectoryGrid;
    grid.innerHTML = '';

    const filtered = state.offices.filter(office => {
        const text = `${office.Name} ${office.Focus} ${office.Description} ${office.Address}`.toLowerCase();
        const matchesSearch = text.includes(state.customSearchQuery);
        const matchesAddr = !state.selectedAddress || (office.Address && office.Address.includes(state.selectedAddress));
        return matchesSearch && matchesAddr;
    });

    if (filtered.length === 0) {
        grid.innerHTML = '<div class="empty-state"><p class="empty-text">No offices match.</p></div>';
        return;
    }

    filtered.forEach(office => {
        const card = document.createElement('div');
        card.className = 'card';
        card.style.cursor = 'default';

        const emailLink = office.Email ? `<a href="mailto:${office.Email}" class="card-link">✉️ Email</a>` : '';
        const siteLink = office.Website ? `<a href="${office.Website}" target="_blank" class="card-link">🌐 Website</a>` : '';

        card.innerHTML = `
            <div>
                <div class="card-header"><span class="card-badge">${office.Focus || 'Architecture'}</span></div>
                <h3 class="card-title">${office.Name}</h3>
                <p class="card-description">${office.Description || 'No description.'}</p>
                <div class="card-footer">
                    <span class="card-footer-item">📍 ${office.Address || 'N/A'}</span>
                    <div class="card-footer-links">${siteLink}${emailLink}</div>
                </div>
            </div>
            <div class="office-card-controls">
                <div class="form-group">
                    <label>Outreach Status</label>
                    <select class="outreach-select" onchange="updateOfficeStatus('${office.Name}', this.value)">
                        <option value="Uncontacted" ${office.Status === 'Uncontacted' ? 'selected' : ''}>Uncontacted</option>
                        <option value="Portfolio Sent" ${office.Status === 'Portfolio Sent' ? 'selected' : ''}>Portfolio Sent</option>
                        <option value="In Conversation" ${office.Status === 'In Conversation' ? 'selected' : ''}>In Conversation</option>
                        <option value="Interview Scheduled" ${office.Status === 'Interview Scheduled' ? 'selected' : ''}>Interview Scheduled</option>
                        <option value="No Openings" ${office.Status === 'No Openings' ? 'selected' : ''}>No Openings</option>
                    </select>
                </div>
                <div class="form-group">
                    <textarea class="notes-textarea" placeholder="Add notes..." onblur="updateOfficeNotes('${office.Name}', this.value)">${office.Notes || ''}</textarea>
                </div>
                <button class="btn btn-secondary btn-sm w-full" id="scan-site-${office.Name}" onclick="scanOfficeWebsite('${office.Name}', '${office.Website}')">✨ Scan Website</button>
            </div>
        `;
        grid.appendChild(card);
    });
}

function renderSettingsPanel() {
    const set = state.settings;
    document.getElementById('settings-keywords').value = (set.keywords || []).join(', ');
    document.getElementById('settings-locations').value = (set.locations || []).join(', ');
    document.getElementById('settings-ai-enabled').checked = set.ai_enabled !== false;
    document.getElementById('settings-scheduler-enabled').checked = set.scheduler_enabled === true;
    document.getElementById('settings-api-key').value = set.gemini_api_key || '';
    document.getElementById('settings-model').value = set.gemini_model || 'gemini-flash-latest';
    document.getElementById('settings-profile').value = set.profile_summary || '';
    document.querySelector('input[name="match-logic"][value="AND"]').checked = set.keyword_mode === 'AND';
    document.querySelector('input[name="match-logic"][value="OR"]').checked = set.keyword_mode !== 'AND';

    const container = document.getElementById('settings-platforms-checkboxes');
    container.innerHTML = '';
    const active = set.platforms || [];
    PLATFORM_OPTIONS.forEach(p => {
        container.innerHTML += `<label><input type="checkbox" name="platform-chk" value="${p}" ${active.includes(p) ? 'checked' : ''}> ${p}</label>`;
    });
}

// --- API Actions ---
async function saveSettings() {
    const payload = {
        keywords: document.getElementById('settings-keywords').value.split(',').map(x => x.trim()).filter(Boolean),
        locations: document.getElementById('settings-locations').value.split(',').map(x => x.trim()).filter(Boolean),
        ai_enabled: document.getElementById('settings-ai-enabled').checked,
        scheduler_enabled: document.getElementById('settings-scheduler-enabled').checked,
        gemini_api_key: document.getElementById('settings-api-key').value.trim(),
        gemini_model: document.getElementById('settings-model').value,
        profile_summary: document.getElementById('settings-profile').value.trim(),
        keyword_mode: document.querySelector('input[name="match-logic"]:checked').value,
        platforms: Array.from(document.querySelectorAll('input[name="platform-chk"]:checked')).map(chk => chk.value)
    };

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Settings saved successfully!');
            state.settings = payload;
        } else {
            throw new Error(await response.text());
        }
    } catch (e) {
        showToast('Error saving settings: ' + e.message, 'error');
    }
}

async function updateJobStatus(url, status) {
    try {
        const response = await fetch('/api/jobs/update_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, status })
        });
        if (!response.ok) throw new Error('Failed to update status');
        
        const job = state.jobs.find(j => j.URL === url);
        if (job) job.Status = status;
        showToast(`Status updated to ${status}`);
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function updateOfficeStatus(officeName, status) {
    try {
        const response = await fetch('/api/offices/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: officeName, status: status })
        });
        if (!response.ok) throw new Error('Failed to update status');
        const office = state.offices.find(o => o.Name === officeName);
        if (office) office.Status = status;
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function updateOfficeNotes(officeName, notes) {
    try {
        const response = await fetch('/api/offices/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: officeName, notes: notes })
        });
        if (!response.ok) throw new Error('Failed to update notes');
        const office = state.offices.find(o => o.Name === officeName);
        if (office) office.Notes = notes;
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function startGlobalScan() {
    if (state.scanning) return;
    state.scanning = true;
    el.scanJobBoardsBtn.classList.add('hidden');
    el.stopScanBtn.classList.remove('hidden');
    el.terminalContainer.classList.remove('hidden');
    el.terminalBody.textContent = 'Starting pipeline...';

    connectLogWebSocket(); // Connect to WebSocket

    const searchVal = el.globalSearchInput.value.trim();
    const settingsVal = (state.settings.keywords || []).join(', ');
    let url = '/api/scan';
    if (searchVal && searchVal.toLowerCase() !== settingsVal.toLowerCase()) {
        url += '?override_keywords=' + encodeURIComponent(searchVal);
    }

    try {
        const response = await fetch(url, { method: 'POST' });
        if (!response.ok) {
            el.terminalBody.textContent += `\nFailed to start scan: ${await response.text()}`;
            stopGlobalScanUI();
        }
    } catch (e) {
        el.terminalBody.textContent += `\nConnection error: ${e.message}`;
        stopGlobalScanUI();
    }
}

function stopGlobalScanUI() {
    state.scanning = false;
    disconnectLogWebSocket(); // Disconnect WebSocket
    el.scanJobBoardsBtn.classList.remove('hidden');
    el.stopScanBtn.classList.add('hidden');
}

function connectLogWebSocket() {
    if (state.logWebSocket && state.logWebSocket.readyState === WebSocket.OPEN) {
        return;
    }
    
    const ws_protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    const ws_url = ws_protocol + window.location.host + "/ws/logs";
    state.logWebSocket = new WebSocket(ws_url);

    state.logWebSocket.onopen = (event) => {
        console.log("WebSocket connected:", event);
        el.terminalBody.textContent = ''; // Clear terminal on new connection
    };

    state.logWebSocket.onmessage = (event) => {
        el.terminalBody.textContent += event.data + '\n';
        el.terminalBody.scrollTop = el.terminalBody.scrollHeight;
        if (event.data.includes("Pipeline Execution Complete.")) {
            stopGlobalScanUI();
            loadJobs();
        }
    };

    state.logWebSocket.onclose = (event) => {
        console.log("WebSocket disconnected:", event);
        if (state.scanning) { // If scan was active, it means it finished or was interrupted
            el.terminalBody.textContent += '\nPipeline Execution Complete.';
            stopGlobalScanUI();
            loadJobs();
        }
    };

    state.logWebSocket.onerror = (event) => {
        console.error("WebSocket error:", event);
        showToast('WebSocket connection error. Check console for details.', 'error');
    };
}

function disconnectLogWebSocket() {
    if (state.logWebSocket) {
        state.logWebSocket.close();
        state.logWebSocket = null;
    }
}

async function stopGlobalScanCall() {
    el.stopScanBtn.disabled = true;
    el.stopScanBtn.textContent = 'Stopping...';
    try {
        await fetch('/api/scan/stop', { method: 'POST' });
        showToast('Scan stop requested.');
    } catch (e) {
        showToast('Error stopping scan: ' + e.message, 'error');
    } finally {
        el.stopScanBtn.disabled = false;
        el.stopScanBtn.textContent = 'Stop Scan';
    }
}

async function clearAllResults() {
    if (!confirm('Are you sure you want to clear all jobs?')) return;
    try {
        await fetch('/api/jobs', { method: 'DELETE' });
        showToast('All jobs cleared.');
        loadJobs();
    } catch (e) {
        showToast('Failed to clear results: ' + e.message, 'error');
    }
}

async function scanOfficeWebsite(name, website) {
    const btn = document.getElementById(`scan-site-${name}`);
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    showToast(`AI is scanning ${name}...`);
    try {
        const response = await fetch('/api/scan/office', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, website })
        });
        const res = await response.json();
        if (res.success) {
            showToast(`Scan complete! Found ${res.roles ? res.roles.length : 0} roles.`);
            loadJobs();
        } else {
            throw new Error(res.error || 'Unknown scan error');
        }
    } catch (e) {
        showToast(`Scan Failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '✨ Scan Website';
    }
}

async function autoExpandKeywords() {
    const btn = document.getElementById('btn-auto-expand');
    btn.disabled = true;
    btn.textContent = 'Expanding...';
    try {
        const response = await fetch('/api/keywords/expand', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            document.getElementById('settings-keywords').value = data.keywords.join(', ');
            showToast('Keywords expanded! Click Save to store them.');
        } else {
            throw new Error(data.error);
        }
    } catch (e) {
        showToast('Expansion Failed: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Auto-Expand';
    }
}

// --- Drawer & Utils ---
function openDrawer(job) {
    document.getElementById('detail-drawer-title').textContent = job.Title;
    document.getElementById('detail-drawer-company').textContent = job.Platform.includes("OEA - ") ? job.Platform.replace("OEA - ", "") : "Target Job";
    document.getElementById('detail-drawer-location').textContent = job.Location || 'N/A';
    document.getElementById('detail-drawer-deadline').textContent = job.Deadline || 'N/A';
    document.getElementById('detail-drawer-platform').textContent = job.Platform;
    document.getElementById('detail-drawer-description').innerHTML = cleanJobDescriptionHtml(job.Description);

    const aiBox = document.getElementById('detail-drawer-ai-box');
    if (job["Match Score"] !== undefined && state.settings.ai_enabled !== false) {
        aiBox.classList.remove('hidden');
        document.getElementById('detail-drawer-ai-score').textContent = job["Match Score"];
        document.getElementById('detail-drawer-ai-reason').innerHTML = `<strong>Match Reason:</strong> ${job["Match Reason"] || 'N/A'}`;
        document.getElementById('detail-drawer-ai-reqs').innerHTML = `<strong>Requirements:</strong> ${job["Key Requirements"] || 'N/A'}`;
    } else {
        aiBox.classList.add('hidden');
    }

    const applyBtn = document.getElementById('detail-drawer-apply-btn');
    applyBtn.href = job.URL || '#';
    applyBtn.classList.toggle('hidden', !job.URL);

    el.detailDrawerOverlay.classList.add('active');
    el.detailDrawer.classList.add('active');
}

function closeDrawer() {
    el.detailDrawerOverlay.classList.remove('active');
    el.detailDrawer.classList.remove('active');
}

function stripHtml(html) {
    if (!html) return '';
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return doc.body.textContent || "";
}

function cleanJobDescriptionHtml(desc) {
    if (!desc) return 'No details available.';
    if (!desc.includes('<p>') && !desc.includes('<br')) {
        return desc.split('\n').map(p => `<p>${p}</p>`).join('');
    }
    return desc;
}

function showToast(message, type = 'success') {
    el.toast.textContent = message;
    el.toast.className = `toast show ${type}`;
    setTimeout(() => {
        el.toast.classList.remove('show');
    }, 3000);
}

async function uploadResumeFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    if (!document.getElementById('settings-api-key').value.trim()) {
        showToast('Please enter and save a Gemini API Key first.', 'error');
        e.target.value = '';
        return;
    }

    showToast('Uploading and parsing resume...');
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/resume/upload', { method: 'POST', body: formData });
        const data = await response.json();
        if (response.ok && data.success) {
            document.getElementById('settings-profile').value = data.profile_summary;
            document.getElementById('settings-keywords').value = data.keywords.join(', ');
            showToast('Resume parsed! Click Save to store changes.');
        } else {
            throw new Error(data.detail || data.error || 'Unknown parsing error');
        }
    } catch (err) {
        showToast(`Upload Failed: ${err.message}`, 'error');
    } finally {
        e.target.value = '';
    }
}
