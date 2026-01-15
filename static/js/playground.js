/* ---------- Utilities ---------- */

function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) return '';
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const INVALID_JSON_CODE = 'INVALID_JSON';

function buildAbsoluteUrl(url) {
  try {
    return new URL(url, window.location.origin).href;
  } catch (err) {
    return url;
  }
}

/* ---------- URL Validation (SSRF Prevention) ---------- */
function isValidApiUrl(url) {
  // Only allow relative URLs starting with /api/ or /playground/
  if (url.startsWith('/api/') || url.startsWith('/playground/')) {
    return { valid: true };
  }

  // Try to parse as absolute URL
  try {
    const parsed = new URL(url, window.location.origin);

    // Only allow same origin
    if (parsed.origin !== window.location.origin) {
      return { valid: false, error: 'Only same-origin requests are allowed' };
    }

    // Block dangerous protocols
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return { valid: false, error: 'Invalid protocol. Only HTTP/HTTPS allowed' };
    }

    // Block internal/private IP ranges
    const hostname = parsed.hostname.toLowerCase();
    const blockedPatterns = [
      /^localhost$/i,
      /^127\./,
      /^10\./,
      /^172\.(1[6-9]|2[0-9]|3[0-1])\./,
      /^192\.168\./,
      /^0\.0\.0\.0$/,
      /^::1$/,
      /^\[::1\]$/,
      /^metadata\./i,
      /^169\.254\./
    ];

    for (const pattern of blockedPatterns) {
      if (pattern.test(hostname)) {
        return { valid: false, error: 'Requests to internal addresses are not allowed' };
      }
    }

    // Must be an API path
    if (!parsed.pathname.startsWith('/api/') && !parsed.pathname.startsWith('/playground/')) {
      return { valid: false, error: 'Only /api/ and /playground/ endpoints are allowed' };
    }

    return { valid: true };
  } catch (err) {
    return { valid: false, error: 'Invalid URL format' };
  }
}

function prepareRequestBody(bodyText = '', bodyType = 'json') {
  const type = bodyType || 'json';
  const trimmed = bodyText.trim();

  if (type === 'json') {
    if (!trimmed) {
      return {
        body: null,
        contentType: 'application/json'
      };
    }
    // Validate JSON
    try {
      JSON.parse(bodyText);
      return {
        body: bodyText,
        contentType: 'application/json'
      };
    } catch (err) {
      return { error: 'invalid-json' };
    }
  }

  return {
    body: trimmed ? bodyText : null,
    contentType: 'text/plain;charset=UTF-8'
  };
}



function showToast(message, type='info') {
  const toast = document.createElement('div');
  toast.className = `alert alert-${type} fixed bottom-4 right-4 w-auto shadow-lg z-50`;
  toast.style.animation = 'fadeIn 0.3s ease-in-out';
  let icon = '';
  if (type === 'success') {
    icon = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />';
  } else if (type === 'error') {
    icon = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />';
  } else if (type === 'warning') {
    icon = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />';
  }
  // Escape message to prevent XSS
  const safeMessage = escapeHtml(message);
  toast.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">${icon}</svg><span>${safeMessage}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease-in-out';
    setTimeout(() => toast.remove(), 300);
  }, 2000);
}

/* ---------- DOM references ---------- */
const sidebar = document.querySelector('.sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarOverlay = document.createElement('div');
sidebarOverlay.className = 'sidebar-overlay';
document.body.appendChild(sidebarOverlay);

const sendButton = document.getElementById('sendButton');
const buttonSpinner = document.getElementById('buttonSpinner');
const buttonText = document.getElementById('buttonText');

const requestMethodSelect = document.getElementById('requestMethod');
const requestUrlInput = document.getElementById('requestUrl');
const requestBodyTextarea = document.getElementById('requestBody');
const bodyTypeSelect = document.getElementById('bodyType');

const responseContainer = document.getElementById('responseContainer');
const responseDataPre = document.getElementById('responseData');
const emptyState = document.getElementById('emptyState');
const responseStatusText = document.getElementById('responseStatusText');
const responseTimeText = document.getElementById('responseTimeText');
const successDot = document.getElementById('successDot');
const errorDot = document.getElementById('errorDot');

/* ---------- State ---------- */
let endpoints = {};
let currentEndpoint = null;
let collapsedCategories = {};

/* ---------- Init ---------- */
document.addEventListener('DOMContentLoaded', () => {
  loadApiKey();
  loadEndpoints();
  setupShortcuts();
  setupLineNumbers();
  setupPrettify();
});

/* ---------- Line Numbers ---------- */
function setupLineNumbers() {
  const requestBody = document.getElementById('requestBody');
  const lineNumbers = document.getElementById('lineNumbers');

  if (!requestBody || !lineNumbers) return;

  function updateLineNumbers() {
    const lines = requestBody.value.split('\n').length;
    let numbers = '';
    for (let i = 1; i <= lines; i++) {
      numbers += i + '\n';
    }
    lineNumbers.textContent = numbers || '1';
  }

  // Sync scroll
  requestBody.addEventListener('scroll', () => {
    lineNumbers.scrollTop = requestBody.scrollTop;
  });

  requestBody.addEventListener('input', updateLineNumbers);
  requestBody.addEventListener('change', updateLineNumbers);

  // Initial update
  updateLineNumbers();
}

function updateResponseLineNumbers(text) {
  const responseLineNumbers = document.getElementById('responseLineNumbers');
  if (!responseLineNumbers) return;

  const lines = text.split('\n').length;
  let numbers = '';
  for (let i = 1; i <= lines; i++) {
    numbers += i + '\n';
  }
  responseLineNumbers.textContent = numbers || '1';
}

/* ---------- Prettify ---------- */
function setupPrettify() {
  const prettifyBtn = document.getElementById('prettifyBtn');
  if (!prettifyBtn) return;

  prettifyBtn.addEventListener('click', () => {
    const bodyTextarea = document.getElementById('requestBody');
    try {
      const parsed = JSON.parse(bodyTextarea.value);
      bodyTextarea.value = JSON.stringify(parsed, null, 2);
      // Update line numbers
      const event = new Event('input');
      bodyTextarea.dispatchEvent(event);
      showToast('JSON prettified', 'success');
    } catch (e) {
      showToast('Invalid JSON - cannot prettify', 'error');
    }
  });

  // Setup tab switching
  setupRequestTabs();
}

/* ---------- Request Tabs ---------- */
function setupRequestTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const bodyEditorWrapper = document.getElementById('bodyEditorWrapper');
  const headersTab = document.getElementById('headersTab');

  if (!tabBtns.length) return;

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      // Update button styles
      tabBtns.forEach(b => {
        b.classList.remove('bg-base-300', 'font-semibold');
        b.classList.add('hover:bg-base-300');
      });
      btn.classList.add('bg-base-300', 'font-semibold');
      btn.classList.remove('hover:bg-base-300');

      const tab = btn.dataset.tab;
      if (tab === 'body') {
        if (bodyEditorWrapper) bodyEditorWrapper.classList.remove('hidden');
        if (headersTab) headersTab.classList.add('hidden');
      } else if (tab === 'headers') {
        if (bodyEditorWrapper) bodyEditorWrapper.classList.add('hidden');
        if (headersTab) headersTab.classList.remove('hidden');
      }
    });
  });
}

/* ---------- API key visibility & copy ---------- */
document.getElementById('apiKeyToggle').addEventListener('click', () => {
  const apiKeyInput = document.getElementById('globalApiKey');
  const eyeIcon = document.getElementById('eyeIcon');
  if (apiKeyInput.type === 'password') {
    apiKeyInput.type = 'text';
    eyeIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242" />`;
  } else {
    apiKeyInput.type = 'password';
    eyeIcon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>`;
  }
});

document.getElementById('copyApiKeyBtn').addEventListener('click', () => {
  const apiKey = document.getElementById('globalApiKey').value;
  if (apiKey) {
    navigator.clipboard.writeText(apiKey);
    showToast('API key copied!', 'success');
  } else {
    showToast('No API key to copy', 'error');
  }
});

/* ---------- Sidebar toggle & overlay ---------- */
function toggleSidebar() {
  sidebar.classList.toggle('open');
  sidebarOverlay.classList.toggle('open');
  document.body.style.overflow = sidebar.classList.contains('open') ? 'hidden' : '';
}

sidebarToggle.addEventListener('click', toggleSidebar);
sidebarOverlay.addEventListener('click', toggleSidebar);

/* Close sidebar on mobile when an endpoint clicked - delegated after rendering endpoints */

/* ---------- Collapsed categories state ---------- */
function getDefaultCollapsedState(categories) {
  const collapsed = {};
  Object.keys(categories).forEach(category => {
    // Account category is expanded by default, all others are collapsed
    collapsed[category] = category.toLowerCase() !== 'account';
  });
  return collapsed;
}

function toggleCategory(categoryName, headerElement, contentElement) {
  const isCollapsed = !headerElement.classList.contains('collapsed');

  collapsedCategories[categoryName] = isCollapsed;

  if (isCollapsed) {
    headerElement.classList.add('collapsed');
    contentElement.classList.add('collapsed');
  } else {
    headerElement.classList.remove('collapsed');
    contentElement.classList.remove('collapsed');
  }
}

/* ---------- Load endpoints ---------- */
async function loadEndpoints() {
  try {
    const resp = await fetch('/playground/endpoints');
    if (!resp.ok) throw new Error('Failed to load endpoints');
    endpoints = await resp.json();
    renderEndpoints(endpoints);
    // Auto-select first endpoint if present
    setTimeout(() => {
      const first = document.querySelector('.endpoint-item');
      if (first) first.click();
    }, 100);
  } catch (err) {
    console.error(err);
    showToast('Failed to load endpoints', 'error');
  }
}

function renderEndpoints(data, forceExpand = false) {
  const container = document.getElementById('endpointsList');
  container.innerHTML = '';

  let collapsed;
  if (forceExpand) {
    collapsed = {};
  } else {
    // Use in-memory state or default
    if (Object.keys(collapsedCategories).length === 0) {
      collapsed = getDefaultCollapsedState(data);
      collapsedCategories = { ...collapsed };
    } else {
      collapsed = { ...collapsedCategories };
    }
  }

  Object.keys(data).forEach(category => {
    const categoryDiv = document.createElement('div');
    categoryDiv.className = 'category-item mb-4';

    // Category header with chevron
    const header = document.createElement('div');
    header.className = `category-header ${collapsed[category] ? 'collapsed' : ''}`;
    header.innerHTML = `
      <span>${escapeHtml(category)}</span>
      <svg class="chevron" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    `;

    // Category content wrapper
    const content = document.createElement('div');
    content.className = `category-content ${collapsed[category] ? 'collapsed' : ''}`;

    // Add endpoints to content
    data[category].forEach(endpoint => {
      const endpointDiv = document.createElement('div');
      endpointDiv.className = 'endpoint-item rounded px-2 py-1.5 mb-1 cursor-pointer hover:bg-base-200 transition-colors';
      const method = (endpoint.method || 'POST').toUpperCase();
      const methodClass = `method-${method.toLowerCase()}`;
      endpointDiv.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="method-badge ${methodClass}">${escapeHtml(method)}</span>
          <span class="text-xs font-medium truncate">${escapeHtml(endpoint.name || '')}</span>
        </div>
      `;
      endpointDiv.addEventListener('click', (e) => {
        e.stopPropagation();
        document.querySelectorAll('.endpoint-item').forEach(el => el.classList.remove('active'));
        endpointDiv.classList.add('active');
        selectEndpoint(endpoint, endpointDiv);
        if (window.innerWidth < 1024) toggleSidebar();
      });
      content.appendChild(endpointDiv);
    });

    // Toggle category on header click
    header.addEventListener('click', () => {
      toggleCategory(category, header, content);
    });

    categoryDiv.appendChild(header);
    categoryDiv.appendChild(content);
    container.appendChild(categoryDiv);
  });
}

/* ---------- Update GET hint visibility ---------- */
function updateGetHintVisibility() {
  const getHint = document.getElementById('getRequestHint');
  const method = requestMethodSelect?.value;
  if (getHint) {
    if (method === 'GET') {
      getHint.classList.remove('hidden');
      getHint.classList.add('flex');
    } else {
      getHint.classList.add('hidden');
      getHint.classList.remove('flex');
    }
  }
}

/* ---------- Endpoint selection ---------- */
function selectEndpoint(endpoint, element) {
  document.querySelectorAll('.endpoint-item').forEach(el => el.classList.remove('active'));
  if (element) element.classList.add('active');

  currentEndpoint = endpoint;
  const bodyTextarea = document.getElementById('requestBody');
  const apiKey = document.getElementById("globalApiKey").value;

  document.getElementById("requestMethod").value = endpoint.method || 'GET';
  document.getElementById("requestUrl").value = endpoint.path || '';

  // Update GET hint visibility
  updateGetHintVisibility();

  // Populate from endpoint
  // For GET requests with params, show them in the body as reference
  if (endpoint.method === 'GET' && endpoint.params) {
    const params = { ...endpoint.params };
    if (apiKey && !params.apikey) {
      params.apikey = apiKey;
    }
    bodyTextarea.value = JSON.stringify(params, null, 2);
  } else if (endpoint.body) {
    const body = { ...endpoint.body };
    if (apiKey && !body.apikey) {
      body.apikey = apiKey;
    }
    bodyTextarea.value = JSON.stringify(body, null, 2);
  } else {
    // If no body but we have API key, add it to an empty object
    bodyTextarea.value = apiKey ? JSON.stringify({ apikey: apiKey }, null, 2) : '';
  }

  // Make sure body textarea is always editable
  bodyTextarea.disabled = false;
  bodyTextarea.classList.remove('opacity-50');

  // Update line numbers
  const event = new Event('input');
  bodyTextarea.dispatchEvent(event);
}


/* ---------- Send request ---------- */

// Maximum size for syntax highlighting (100KB)
const MAX_HIGHLIGHT_SIZE = 100 * 1024;

function syntaxHighlight(json) {
  if (typeof json !== 'string') json = JSON.stringify(json, null, 2);

  // Skip syntax highlighting for large responses to prevent browser hang
  if (json.length > MAX_HIGHLIGHT_SIZE) {
    return escapeHtml(json);
  }

  json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
    let cls = 'json-number';
    if (/^"/.test(match)) {
      if (/:$/.test(match)) cls = 'json-key';
      else cls = 'json-string';
    } else if (/true|false/.test(match)) cls = 'json-boolean';
    else if (/null/.test(match)) cls = 'json-null';
    return '<span class="' + cls + '">' + match + '</span>';
  });
}

async function sendRequest() {
  const method = requestMethodSelect.value;
  let fetchUrl = requestUrlInput.value.trim();
  if (!fetchUrl) {
    showToast('Please provide an endpoint URL', 'warning');
    return;
  }

  // Validate URL to prevent SSRF attacks
  const urlValidation = isValidApiUrl(fetchUrl);
  if (!urlValidation.valid) {
    showToast(urlValidation.error, 'error');
    return;
  }

  // UI lock
  sendButton.disabled = true;
  if (buttonSpinner) buttonSpinner.classList.remove('hidden');
  if (buttonText) buttonText.textContent = 'Sending...';
  const buttonIcon = document.getElementById('buttonIcon');
  if (buttonIcon) buttonIcon.classList.add('hidden');
  document.getElementById('responseLoading')?.classList.remove('hidden');

  const startTime = Date.now();
  try {
    const options = { method, headers: { 'Accept': 'application/json' } };

    // Add CSRF token for non-GET requests
    if (method !== 'GET') {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      if (csrfToken) {
        options.headers['X-CSRFToken'] = csrfToken;
      }
    }

    const bodyType = bodyTypeSelect ? bodyTypeSelect.value : 'json';

    if (method === 'GET') {
      // For GET requests, parse body as query params
      const bodyText = requestBodyTextarea.value.trim();
      if (bodyText) {
        try {
          const params = JSON.parse(bodyText);
          const url = new URL(fetchUrl, window.location.origin);
          Object.entries(params).forEach(([key, value]) => {
            // Only add non-empty values (skip null, undefined, empty strings)
            if (value !== null && value !== undefined && value !== '' && String(value).trim() !== '') {
              url.searchParams.append(key, String(value));
            }
          });
          fetchUrl = url.toString();
        } catch (e) {
          showToast('Invalid JSON for query parameters', 'error');
          throw new Error(INVALID_JSON_CODE);
        }
      }
    } else {
      // For non-GET requests, use body
      const bodyResult = prepareRequestBody(requestBodyTextarea.value || '', bodyType);
      if (bodyResult?.error === 'invalid-json') {
        showToast('Invalid JSON body. Please fix errors before sending.', 'error');
        throw new Error(INVALID_JSON_CODE);
      }
      if (bodyResult.body !== null) {
        options.body = bodyResult.body;
        options.headers['Content-Type'] = bodyResult.contentType;
      }
    }

    const resp = await fetch(fetchUrl, options);
    const time = Date.now() - startTime;

    let data;
    const contentType = resp.headers.get('content-type');
    try {
      if (contentType && contentType.includes('application/json')) {
        data = await resp.json();
      } else {
        const text = await resp.text();
        data = { text: text, contentType: contentType };
      }
    } catch (e) {
      data = { text: await resp.text(), error: 'Failed to parse response' };
    }

    // headers capture
    const hdrs = {};
    resp.headers.forEach((v,k) => hdrs[k] = v);
    displayResponse(resp.status, data, time, hdrs);
  } catch (err) {
    const time = Date.now() - startTime;
    if (err?.message === INVALID_JSON_CODE) return;
    displayResponse(0, { error: err.message }, time);
  } finally {
    sendButton.disabled = false;
    if (buttonSpinner) buttonSpinner.classList.add('hidden');
    if (buttonText) buttonText.textContent = 'Send';
    const buttonIcon = document.getElementById('buttonIcon');
    if (buttonIcon) buttonIcon.classList.remove('hidden');
    document.getElementById('responseLoading')?.classList.add('hidden');
  }
}

function displayResponse(status, data, time, headers = {}) {
  // status / time updates
  const statusColor = status >= 200 && status < 300 ? 'text-success' : status >= 400 ? 'text-error' : '';
  responseStatusText.textContent = status ? `${status} ${status >= 200 && status < 300 ? 'OK' : 'Error'}` : 'Error';
  responseStatusText.className = `text-xs font-mono ${statusColor}`;
  responseTimeText.textContent = `${time}ms`;

  // badge / dots (for compatibility)
  if (successDot && errorDot) {
    if (status >= 200 && status < 300) {
      successDot.classList.remove('hidden'); errorDot.classList.add('hidden');
    } else if (status >= 400) {
      errorDot.classList.remove('hidden'); successDot.classList.add('hidden');
    } else {
      successDot.classList.add('hidden'); errorDot.classList.add('hidden');
    }
  }

  // response content
  emptyState.classList.add('hidden');
  responseDataPre.classList.remove('hidden');

  let responseText;
  if (typeof data === 'string') {
    responseText = data;
  } else {
    responseText = JSON.stringify(data, null, 2);
  }

  // Update size display
  const sizeInBytes = new Blob([responseText]).size;
  const responseSizeText = document.getElementById('responseSizeText');
  if (responseSizeText) {
    if (sizeInBytes >= 1024) {
      responseSizeText.textContent = `${(sizeInBytes / 1024).toFixed(1)}KB`;
    } else {
      responseSizeText.textContent = `${sizeInBytes}B`;
    }
  }

  // Update line numbers
  updateResponseLineNumbers(responseText);

  // Check size and show warning for large responses
  const sizeInKB = (responseText.length / 1024).toFixed(2);
  if (responseText.length > MAX_HIGHLIGHT_SIZE) {
    // Show plain text for large responses
    responseDataPre.innerHTML = escapeHtml(responseText);
    showToast(`Large response (${sizeInKB} KB) - syntax highlighting disabled for performance`, 'info');
  } else {
    // Apply syntax highlighting for smaller responses
    if (typeof data === 'string') {
      responseDataPre.innerHTML = escapeHtml(data);
    } else {
      responseDataPre.innerHTML = syntaxHighlight(data);
    }
  }
}

/* ---------- Copy response / cURL ---------- */
document.getElementById('copyResponseButton').addEventListener('click', () => {
  const text = responseDataPre?.textContent || '';
  if (text) {
    navigator.clipboard.writeText(text);
    showToast('Response copied!', 'success');
  } else showToast('No response to copy', 'warning');
});

document.getElementById('copyCurlButton').addEventListener('click', async () => {
  const method = requestMethodSelect.value;
  let url = requestUrlInput.value.trim();
  if (!url) return showToast('No URL to copy', 'warning');

  const headers = { 'Accept': 'application/json' };
  const bodyType = bodyTypeSelect ? bodyTypeSelect.value : 'json';
  let bodyText = '';

  if (method === 'GET') {
    // For GET, append query params to URL
    const bodyContent = requestBodyTextarea.value.trim();
    if (bodyContent) {
      try {
        const params = JSON.parse(bodyContent);
        const urlObj = new URL(url, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
          if (value !== null && value !== undefined && value !== '') {
            urlObj.searchParams.append(key, value);
          }
        });
        url = urlObj.toString();
      } catch (e) {
        showToast('Invalid JSON for query parameters', 'error');
        return;
      }
    }
  } else {
    const bodyResult = prepareRequestBody(requestBodyTextarea.value || '', bodyType);
    if (bodyResult?.error === 'invalid-json') {
      showToast('Invalid JSON body. Fix it before copying cURL.', 'error');
      return;
    }
    if (bodyResult.body !== null) {
      bodyText = bodyResult.body;
      headers['Content-Type'] = bodyResult.contentType;
    }
  }

  const absoluteUrl = buildAbsoluteUrl(url);
  let curl = `curl -X ${method} "${absoluteUrl}"`;
  Object.entries(headers).forEach(([k,v]) => {
    if (v) curl += ` -H "${k}: ${v}"`;
  });
  if (bodyText) curl += ` -d '${bodyText.replace(/'/g, "'\\''")}'`;

  try {
    await navigator.clipboard.writeText(curl);
    showToast('Copied as cURL', 'success');
  } catch (e) {
    showToast('Failed to copy cURL', 'error');
  }
});

/* ---------- Resize handles (no persistence) ---------- */
const horizontalResizeHandle = document.getElementById('horizontalResizeHandle');
const sidebarResizeHandle = document.createElement('div');
if (window.innerWidth >= 1024 && sidebar) {
  sidebarResizeHandle.className = 'resize-handle';
  sidebar.appendChild(sidebarResizeHandle);
}

let isResizingSidebar = false, isResizingHorizontal = false, lastDownX = 0, lastDownY = 0, sidebarWidth = 0, requestSectionHeight = 0;
const requestSection = document.getElementById('requestSection');

if (sidebarResizeHandle) {
  sidebarResizeHandle.addEventListener('mousedown', (e) => {
    isResizingSidebar = true; lastDownX = e.clientX; sidebarWidth = sidebar.offsetWidth;
    document.body.classList.add('noselect'); document.body.style.cursor = 'col-resize';
    sidebarResizeHandle.classList.add('active'); e.preventDefault();
  });
}

if (horizontalResizeHandle) {
  horizontalResizeHandle.addEventListener('mousedown', (e) => {
    isResizingHorizontal = true; lastDownY = e.clientY; requestSectionHeight = requestSection.offsetHeight;
    document.body.classList.add('noselect'); document.body.style.cursor = 'row-resize';
    horizontalResizeHandle.classList.add('active'); e.preventDefault();
  });
}

document.addEventListener('mousemove', (e) => {
  if (isResizingSidebar) {
    const deltaX = e.clientX - lastDownX;
    const newWidth = Math.max(240, Math.min(500, sidebarWidth + deltaX));
    sidebar.style.width = `${newWidth}px`; sidebar.style.flex = '0 0 auto';
  } else if (isResizingHorizontal) {
    const deltaY = e.clientY - lastDownY;
    const newHeight = Math.max(200, requestSectionHeight + deltaY);
    requestSection.style.flex = '0 0 auto'; requestSection.style.height = `${newHeight}px`;
  }
});

document.addEventListener('mouseup', () => {
  if (isResizingSidebar) { isResizingSidebar = false; document.body.classList.remove('noselect'); document.body.style.cursor = ''; sidebarResizeHandle.classList.remove('active'); }
  if (isResizingHorizontal) { isResizingHorizontal = false; document.body.classList.remove('noselect'); document.body.style.cursor = ''; horizontalResizeHandle.classList.remove('active'); }
});

/* ---------- Search endpoints with debounce ---------- */
let searchTimeout;
document.getElementById('searchEndpoints').addEventListener('input', (e) => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    const term = e.target.value.toLowerCase();
    if (!term) {
      renderEndpoints(endpoints);
      return;
    }
    const filtered = {};
    Object.keys(endpoints).forEach(category => {
      const matches = endpoints[category].filter(ep => (ep.name||'').toLowerCase().includes(term) || (ep.path||'').toLowerCase().includes(term));
      if (matches.length) filtered[category] = matches;
    });
    // Force expand all categories when searching
    renderEndpoints(filtered, true);
  }, 250);
});

/* ---------- Keyboard shortcuts ---------- */
function setupShortcuts() {
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      sendRequest();
    }
  });
}

/* ---------- Mobile / FAB ---------- */
const mobileFab = document.getElementById('mobileFab');
if (mobileFab) mobileFab.addEventListener('click', () => { showToast('Sending request...', 'info'); sendRequest(); });

document.getElementById('mobileSend').addEventListener('click', () => {
  const mobileMethod = document.getElementById('mobileRequestMethod').value;
  requestMethodSelect.value = mobileMethod;
  sendRequest();
});

/* ---------- API key load ---------- */
async function loadApiKey() {
  try {
    const resp = await fetch('/playground/api-key');
    if (resp.ok) {
      const data = await resp.json();
      const apiKeyInput = document.getElementById('globalApiKey');
      const apiKeyWarning = document.getElementById('apiKeyWarning');
      apiKeyInput.value = data.api_key || '';
      apiKeyInput.placeholder = data.api_key ? 'API key loaded' : 'No API key found';

      // Show/hide warning based on API key presence
      if (!data.api_key) {
        apiKeyWarning.classList.remove('hidden');
      } else {
        apiKeyWarning.classList.add('hidden');
      }
    } else {
      showToast('Failed to load API key', 'error');
    }
  } catch (err) {
    console.error('Error loading API key:', err);
    showToast('Error loading API key', 'error');
  }
}

/* ---------- Small helpers ---------- */
document.getElementById('sendButton').addEventListener('click', sendRequest);

// Update GET hint when method changes
if (requestMethodSelect) {
  requestMethodSelect.addEventListener('change', updateGetHintVisibility);
}

// Reset body button
document.getElementById('resetBodyBtn').addEventListener('click', () => {
  if (!currentEndpoint) {
    showToast('No endpoint selected', 'warning');
    return;
  }

  const bodyTextarea = document.getElementById('requestBody');
  const apiKey = document.getElementById("globalApiKey").value;

  // Reset to endpoint defaults
  if (currentEndpoint.method === 'GET' && currentEndpoint.params) {
    const params = { ...currentEndpoint.params };
    if (apiKey) {
      params.apikey = apiKey;
    }
    bodyTextarea.value = JSON.stringify(params, null, 2);
  } else if (currentEndpoint.body) {
    const body = { ...currentEndpoint.body };
    if (apiKey) {
      body.apikey = apiKey;
    }
    bodyTextarea.value = JSON.stringify(body, null, 2);
  } else {
    bodyTextarea.value = apiKey ? JSON.stringify({ apikey: apiKey }, null, 2) : '';
  }

  showToast('Reset to default values', 'success');
});
