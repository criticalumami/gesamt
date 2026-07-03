// --- Gesamtkunstwerk Frontend Controller ---

// State variables
let state = {
    jobs: [],
    offices: [],
    settings: {},
    activeTab: 'global',
    searchQuery: '',
    customSearchQuery: '',
    selectedAddress: '',
    scanning: false,
    logInterval: null
};

// Available job boards for checkbox rendering
const PLATFORM_OPTIONS = ["Daleel Madani", "UN Careers", "ReliefWeb", "LinkedIn", "Bayt.com", "EURAXESS", "OEA", "Jobs for Lebanon"];

// DOM elements
const el = {
    tabGlobalBtn: document.getElementById('tab-global-btn'),
    tabCustomBtn: document.getElementById('tab-custom-btn'),
    tabSettingsBtn: document.getElementById('tab-settings-btn'),
    panelGlobal: document.getElementById('panel-global'),
    panelCustom: document.getElementById('panel-custom'),
    panelSettings: document.getElementById('panel-settings'),
    globalListingsGrid: document.getElementById('global-listings-grid'),
    customDirectoryGrid: document.getElementById('custom-directory-grid'),
    globalSearchInput: document.getElementById('global-search-input'),
    customSearchInput: document.getElementById('custom-search-input'),
    customAddressSelect: document.getElementById('custom-address-select'),
    scanJobBoardsBtn: document.getElementById('scan-job-boards-btn'),
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
        { btn: el.tabGlobalBtn, panel: el.panelGlobal, name: 'global' },
        { btn: el.tabCustomBtn, panel: el.panelCustom, name: 'custom' },
        { btn: el.tabSettingsBtn, panel: el.panelSettings, name: 'settings' }
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

            // Reload relevant lists
            if (t.name === 'global') loadJobs();
            if (t.name === 'custom') loadOffices();
        });
    });
}

// Event Listeners
function initEventListeners() {
    // Search inputs
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

    // Scraper control buttons
    el.scanJobBoardsBtn.addEventListener('click', startGlobalScan);
    el.clearResultsBtn.addEventListener('click', clearAllResults);
    el.terminalCloseBtn.addEventListener('click', () => el.terminalContainer.classList.add('hidden'));

    // Drawer closing
    el.detailDrawerClose.addEventListener('click', closeDrawer);
    el.detailDrawerOverlay.addEventListener('click', closeDrawer);

    // Save configurations
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
    document.getElementById('btn-auto-expand').addEventListener('click', autoExpandKeywords);
}

// API Fetch Helpers
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
        showToast('Error loading settings: ' + e.message);
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
        showToast('Error loading jobs: ' + e.message);
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
        showToast('Error loading offices: ' + e.message);
    }
}

// Renderers
function renderJobs() {
    const grid = el.globalListingsGrid;
    grid.innerHTML = '';

    // Apply client side search/filter
    const filtered = state.jobs.filter(job => {
        const text = `${job.Title} ${job.Platform} ${job.Location} ${job.Description}`.toLowerCase();
        return text.includes(state.searchQuery);
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <p class="empty-text">No matching jobs found in feed.</p>
            </div>`;
        return;
    }

    filtered.forEach(job => {
        const card = document.createElement('div');
        card.className = 'card';
        card.addEventListener('click', () => openDrawer(job));

        // Format date/deadline
        const score = job["Match Score"] !== undefined ? job["Match Score"] : 0;
        const scoreClass = score < 60 ? 'card-score low-match' : 'card-score';

        card.innerHTML = `
            <div class="card-header">
                <span class="card-badge">${job.Platform}</span>
                <span class="${scoreClass}">Match: ${score}%</span>
            </div>
            <div>
                <h3 class="card-title">${job.Title}</h3>
                <div class="card-company">${job.Platform.includes("OEA - ") ? job.Platform.replace("OEA - ", "") : "Target Job"}</div>
                <p class="card-description">${stripHtml(job.Description)}</p>
            </div>
            <div class="card-footer">
                <span class="card-footer-item">📍 ${job.Location || 'Lebanon'}</span>
                <span class="card-footer-item">📅 ${job.Deadline || 'See listing'}</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

function populateAddressDropdown() {
    const select = el.customAddressSelect;
    select.innerHTML = '<option value="">All Locations / Neighborhoods</option>';
    
    // Extract unique neighborhoods/addresses
    const addresses = new Set();
    state.offices.forEach(office => {
        if (office.Address) {
            // Take the last part of address as neighborhood, or full string if short
            const parts = office.Address.split(',');
            const neighborhood = parts[0].trim();
            if (neighborhood) addresses.add(neighborhood);
        }
    });

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
        grid.innerHTML = `
            <div class="empty-state">
                <p class="empty-text">No offices match your search criteria.</p>
            </div>`;
        return;
    }

    filtered.forEach(office => {
        const card = document.createElement('div');
        card.className = 'card';
        card.style.cursor = 'default';

        const emailLink = office.Email ? `<a href="mailto:${office.Email}" style="color:var(--accent-color); font-size:13px; text-decoration:none;">✉️ ${office.Email}</a>` : '';
        const siteLink = office.Website ? `<a href="${office.Website}" target="_blank" style="color:var(--accent-color); font-size:13px; text-decoration:none;">🌐 Website</a>` : '';

        card.innerHTML = `
            <div>
                <div class="card-header">
                    <span class="card-badge" style="background-color:rgba(59,130,246,0.1); color:var(--accent-color);">${office.Focus || 'Architecture'}</span>
                </div>
                <h3 class="card-title" style="margin-bottom:8px;">${office.Name}</h3>
                <p class="card-description" style="-webkit-line-clamp: 4; font-size:13px; margin-bottom:12px;">${office.Description || 'No description available.'}</p>
                
                <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:16px;">
                    <div style="font-size:12px; color:var(--text-secondary);">📍 ${office.Address || 'Beirut, Lebanon'}</div>
                    <div style="display:flex; gap:16px; margin-top:4px;">
                        ${siteLink}
                        ${emailLink}
                    </div>
                </div>
            </div>

            <div class="office-card-controls">
                <div class="outreach-row">
                    <label for="outreach-${office.Name}">Outreach Status</label>
                    <select class="outreach-select" id="outreach-${office.Name}" onchange="updateOfficeStatus('${office.Name}', this.value)">
                        <option value="Uncontacted" ${office.Status === 'Uncontacted' ? 'selected' : ''}>Uncontacted</option>
                        <option value="Portfolio Sent" ${office.Status === 'Portfolio Sent' ? 'selected' : ''}>Portfolio Sent</option>
                        <option value="In Conversation" ${office.Status === 'In Conversation' ? 'selected' : ''}>In Conversation</option>
                        <option value="Interview Scheduled" ${office.Status === 'Interview Scheduled' ? 'selected' : ''}>Interview Scheduled</option>
                        <option value="No Openings" ${office.Status === 'No Openings' ? 'selected' : ''}>No Openings</option>
                    </select>
                </div>
                <div class="form-group" style="margin-bottom:4px;">
                    <textarea class="notes-textarea" placeholder="Add private application details or tracking notes..." onblur="updateOfficeNotes('${office.Name}', this.value)">${office.Notes || ''}</textarea>
                </div>
                <button class="btn btn-secondary btn-sm w-full" id="scan-site-${office.Name}" onclick="scanOfficeWebsite('${office.Name}', '${office.Website}')">✨ Scan Website via AI</button>
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

    // Check correct match logic radio button
    const isAnd = set.keyword_mode === 'AND';
    document.querySelector('input[name="match-logic"][value="AND"]').checked = isAnd;
    document.querySelector('input[name="match-logic"][value="OR"]').checked = !isAnd;

    // Render Platform checkboxes
    const container = document.getElementById('settings-platforms-checkboxes');
    container.innerHTML = '';
    const active = set.platforms || [];
    
    PLATFORM_OPTIONS.forEach(p => {
        const label = document.createElement('label');
        const checked = active.includes(p) ? 'checked' : '';
        label.innerHTML = `<input type="checkbox" name="platform-chk" value="${p}" ${checked}> ${p}`;
        container.appendChild(label);
    });
}

// Save Settings
async function saveSettings() {
    const keywords = document.getElementById('settings-keywords').value.split(',').map(x => x.trim()).filter(Boolean);
    const locations = document.getElementById('settings-locations').value.split(',').map(x => x.trim()).filter(Boolean);
    const ai_enabled = document.getElementById('settings-ai-enabled').checked;
    const scheduler_enabled = document.getElementById('settings-scheduler-enabled').checked;
    const gemini_api_key = document.getElementById('settings-api-key').value.trim();
    const gemini_model = document.getElementById('settings-model').value;
    const profile_summary = document.getElementById('settings-profile').value.trim();
    const keyword_mode = document.querySelector('input[name="match-logic"]:checked').value;

    const platforms = [];
    document.querySelectorAll('input[name="platform-chk"]:checked').forEach(chk => {
        platforms.push(chk.value);
    });

    const payload = {
        keywords,
        locations,
        platforms,
        ai_enabled,
        scheduler_enabled,
        gemini_api_key,
        gemini_model,
        profile_summary,
        keyword_mode
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
            const txt = await response.text();
            showToast('Failed to save settings: ' + txt);
        }
    } catch (e) {
        showToast('Error saving settings: ' + e.message);
    }
}

// Update Outreach Details
async function updateOfficeStatus(officeName, status) {
    try {
        const response = await fetch('/api/offices/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: officeName, status: status })
        });
        if (!response.ok) {
            showToast('Failed to update status');
        } else {
            // Find and update local state
            const office = state.offices.find(o => o.Name === officeName);
            if (office) office.Status = status;
        }
    } catch (e) {
        showToast('Error updating office: ' + e.message);
    }
}

async function updateOfficeNotes(officeName, notes) {
    try {
        const response = await fetch('/api/offices/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: officeName, notes: notes })
        });
        if (!response.ok) {
            showToast('Failed to update notes');
        } else {
            const office = state.offices.find(o => o.Name === officeName);
            if (office) office.Notes = notes;
        }
    } catch (e) {
        showToast('Error updating office: ' + e.message);
    }
}

// Scraper Triggering
async function startGlobalScan() {
    if (state.scanning) return;
    
    state.scanning = true;
    el.scanJobBoardsBtn.disabled = true;
    el.scanJobBoardsBtn.textContent = 'Scanning...';
    el.terminalContainer.classList.remove('hidden');
    el.terminalBody.textContent = 'Starting pipeline execution background thread...\n';

    try {
        const response = await fetch('/api/scan', { method: 'POST' });
        if (response.ok) {
            // Poll for logs
            state.logInterval = setInterval(pollTerminalLogs, 1000);
        } else {
            const text = await response.text();
            el.terminalBody.textContent += `Failed to start scan: ${text}\n`;
            stopGlobalScanUI();
        }
    } catch (e) {
        el.terminalBody.textContent += `Connection error: ${e.message}\n`;
        stopGlobalScanUI();
    }
}

async function pollTerminalLogs() {
    try {
        const response = await fetch('/api/logs');
        if (response.ok) {
            const data = await response.json();
            el.terminalBody.textContent = data.logs || 'No output.';
            
            // Auto scroll to bottom
            el.terminalBody.scrollTop = el.terminalBody.scrollHeight;

            if (data.status === 'idle') {
                el.terminalBody.textContent += '\nPipeline Execution Complete.\n';
                stopGlobalScanUI();
                loadJobs(); // Refresh matched jobs list
            }
        }
    } catch (e) {
        console.error('Log polling failed', e);
    }
}

function stopGlobalScanUI() {
    state.scanning = false;
    clearInterval(state.logInterval);
    el.scanJobBoardsBtn.disabled = false;
    el.scanJobBoardsBtn.textContent = 'Scan Job Boards';
}

async function clearAllResults() {
    if (!confirm('Are you sure you want to clear all matching jobs from the database?')) return;
    
    try {
        const response = await fetch('/api/jobs', { method: 'DELETE' });
        if (response.ok) {
            showToast('All matching jobs cleared.');
            loadJobs();
        }
    } catch (e) {
        showToast('Failed to clear results: ' + e.message);
    }
}

// Office Website AI Scraper
async function scanOfficeWebsite(name, website) {
    const btn = document.getElementById(`scan-site-${name}`);
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Scanning Website...';

    showToast(`AI is scanning ${name} careers section...`);
    try {
        const response = await fetch('/api/scan/office', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, website })
        });
        
        if (response.ok) {
            const res = await response.json();
            if (res.success) {
                showToast(`Website scan complete! Found ${res.roles ? res.roles.length : 0} matching roles.`);
                loadJobs();
            } else {
                showToast(`Scan Failed: ${res.error || 'Unknown error'}`);
            }
        } else {
            showToast('Server returned an error running website scan');
        }
    } catch (e) {
        showToast('Failed to connect to scan endpoint: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// Gemini AI Keyword Expansion
async function autoExpandKeywords() {
    const btn = document.getElementById('btn-auto-expand');
    btn.disabled = true;
    btn.textContent = 'Expanding...';

    try {
        const response = await fetch('/api/keywords/expand', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                document.getElementById('settings-keywords').value = data.keywords.join(', ');
                showToast('Keywords expanded! Make sure to click Save configurations.');
            } else {
                showToast('Expansion Failed: ' + data.error);
            }
        } else {
            showToast('Server failed to expand keywords');
        }
    } catch (e) {
        showToast('Error during expansion: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Auto-Expand';
    }
}

// Drawer Controller
function openDrawer(job) {
    document.getElementById('detail-drawer-title').textContent = job.Title;
    document.getElementById('detail-drawer-company').textContent = job.Platform.includes("OEA - ") ? job.Platform.replace("OEA - ", "") : "Target Job";
    document.getElementById('detail-drawer-location').textContent = job.Location || 'Lebanon';
    document.getElementById('detail-drawer-deadline').textContent = job.Deadline || 'See listing';
    document.getElementById('detail-drawer-platform').textContent = job.Platform;
    
    // Render HTML description safely
    const descBox = document.getElementById('detail-drawer-description');
    descBox.innerHTML = cleanJobDescriptionHtml(job.Description);

    // Render AI Score box if available
    const aiBox = document.getElementById('detail-drawer-ai-box');
    const score = job["Match Score"];
    if (score !== undefined && state.settings.ai_enabled !== false) {
        aiBox.classList.remove('hidden');
        document.getElementById('detail-drawer-ai-score').textContent = score;
        document.getElementById('detail-drawer-ai-reason').innerHTML = `<strong>Match Reason:</strong> ${job["Match Reason"] || 'N/A'}`;
        document.getElementById('detail-drawer-ai-reqs').innerHTML = `<strong>Requirements:</strong> ${job["Key Requirements"] || 'N/A'}`;
    } else {
        aiBox.classList.add('hidden');
    }

    // Set apply URL link
    const applyBtn = document.getElementById('detail-drawer-apply-btn');
    applyBtn.href = job.URL || '#';
    if (job.URL) {
        applyBtn.classList.remove('hidden');
    } else {
        applyBtn.classList.add('hidden');
    }

    // Slide in
    el.detailDrawerOverlay.classList.add('active');
    el.detailDrawer.classList.add('active');
}

function closeDrawer() {
    el.detailDrawerOverlay.classList.remove('active');
    el.detailDrawer.classList.remove('active');
}

// Util helpers
function stripHtml(html) {
    if (!html) return '';
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return doc.body.textContent || "";
}

function cleanJobDescriptionHtml(desc) {
    if (!desc) return 'No details available.';
    // Convert newlines to paragraphs if not html
    if (!desc.includes('<p>') && !desc.includes('<div') && !desc.includes('<br')) {
        return desc.split('\n\n').map(p => `<p style="margin-bottom:12px;">${p.replace(/\n/g, '<br>')}</p>`).join('');
    }
    return desc;
}

function showToast(message) {
    el.toast.textContent = message;
    el.toast.classList.add('show');
    setTimeout(() => {
        el.toast.classList.remove('show');
    }, 3000);
}
