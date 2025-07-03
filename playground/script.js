document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const hostServerInput = document.getElementById('host-server');
    const wsServerInput = document.getElementById('ws-server');
    const apiKeyInput = document.getElementById('api-key');
    const connectBtn = document.getElementById('connect-btn');
    const wsStatus = document.getElementById('ws-status');
    const searchSymbolInput = document.getElementById('search-symbol');
    const searchBtn = document.getElementById('search-btn');
    const searchResultsContainer = document.getElementById('search-results-container');
    const watchlistContainer = document.getElementById('watchlist');
    const liveModeToggle = document.getElementById('live-mode-toggle');
    const refreshWatchlistBtn = document.getElementById('refresh-watchlist-btn');
    const logsContainer = document.getElementById('logs');
    const clearLogsBtn = document.getElementById('clear-logs-btn');

    // Depth Panel
    const depthPanelModal = document.getElementById('depth-panel-modal');
    const closeDepthPanelBtn = document.getElementById('close-depth-panel-btn');

    // Quote Modal
    const quoteDataModal = document.getElementById('quote-data-modal');
    const quoteDataSymbol = document.getElementById('quote-data-symbol');
    
    // History Modal
    const historicalDataModal = document.getElementById('historical-data-modal');
    const historicalDataSymbol = document.getElementById('historical-data-symbol');
    const fetchHistoricalBtn = document.getElementById('fetch-historical-btn');
    const historicalInterval = document.getElementById('historical-interval');
    const historicalFrom = document.getElementById('historical-from');
    const historicalTo = document.getElementById('historical-to');
    const historicalResults = document.getElementById('historical-data-results');
    
    // Log Filters
    const logFilterType = document.getElementById('log-filter-type');
    const logFilterWsContainer = document.getElementById('log-filter-ws-container');
    const logFilterWsDirection = document.getElementById('log-filter-ws-direction');
    const logFilterWsRecvContainer = document.getElementById('log-filter-ws-recv-container');
    const logFilterWsRecvType = document.getElementById('log-filter-ws-recv-type');
    const logFilterWsMarketDataContainer = document.getElementById('log-filter-ws-market-data-container');
    const logFilterWsMarketDataMode = document.getElementById('log-filter-ws-market-data-mode');
    const logFilterWsMarketDataExchange = document.getElementById('log-filter-ws-market-data-exchange');
    const logFilterWsMarketDataSymbol = document.getElementById('log-filter-ws-market-data-symbol');
    const logFilterApplyBtn = document.getElementById('log-filter-apply-btn');
    const logFilterResetBtn = document.getElementById('log-filter-reset-btn');
    
    // WebSocket Inspector Elements
    const logsTab = document.getElementById('logs-tab');
    const inspectorTab = document.getElementById('inspector-tab');
    const logsPanel = document.getElementById('logs-panel');
    const inspectorPanel = document.getElementById('inspector-panel');
    const inspectorContent = document.getElementById('inspector-content');
    const clearInspectorBtn = document.getElementById('clear-inspector-btn');
    const exportInspectorBtn = document.getElementById('export-inspector-btn');
    const inspectorSearch = document.getElementById('inspector-search');
    
    // WebSocket Diagnostic Elements
    const wsDiagnostics = document.getElementById('ws-diagnostics');
    const wsConnectTime = document.getElementById('ws-connect-time');
    const wsSentCount = document.getElementById('ws-sent-count');
    const wsRecvCount = document.getElementById('ws-recv-count');
    const wsLastPing = document.getElementById('ws-last-ping');
    const wsLatency = document.getElementById('ws-latency');

    // --- State ---
    let socket = null;
    let watchlist = {};
    let currentDepthSymbol = null;
    let currentQuoteSymbol = null;
    let allLogs = []; // To store all log data objects for filtering
    
    // WebSocket Inspector State
    let wsStats = {
        connectTime: null,
        messagesSent: 0,
        messagesReceived: 0,
        messageHistory: [],
        lastPingTime: null
    };

    // --- Utility Functions ---
    const showToast = (message, type = 'success') => {
        const toastContainer = document.getElementById('toast-container');
        const alertType = type === 'success' ? 'alert-success' : 'alert-error';
        const toast = document.createElement('div');
        toast.className = `alert ${alertType} shadow-lg`;
        toast.innerHTML = `<div><span>${message}</span></div>`;
        toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    };

    const addLog = (logData) => {
        const typeColor = {api: 'text-info', ws: 'text-success', error: 'text-error', info: 'text-gray-400'}[logData.type] || 'text-gray-400';
        const logElement = document.createElement('div');
        logElement.innerHTML = `<span class="text-gray-500">${new Date().toLocaleTimeString()}</span> <span class="${typeColor}">[${logData.type.toUpperCase()}]</span> ${logData.message}`;
        logsContainer.appendChild(logElement);
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        // Store log data object with its DOM element for easy filtering
        allLogs.push({ ...logData, element: logElement });
        
        // Add to WebSocket inspector if it's a WebSocket message
        if (logData.type === 'ws' && logData.parsed) {
            addToInspector(logData);
        }
    };
    
    const addToInspector = (logData) => {
        const timestamp = new Date().toISOString();
        const messageData = {
            timestamp,
            direction: logData.direction || 'unknown',
            type: logData.parsed?.type || logData.parsed?.action || 'unknown',
            data: logData.parsed,
            raw: logData.message
        };
        
        wsStats.messageHistory.push(messageData);
        
        // Keep only last 1000 messages
        if (wsStats.messageHistory.length > 1000) {
            wsStats.messageHistory.shift();
        }
        
        renderInspectorMessages();
    };
    
    const renderInspectorMessages = () => {
        const searchTerm = inspectorSearch.value.toLowerCase();
        const filteredMessages = wsStats.messageHistory.filter(msg => {
            if (!searchTerm) return true;
            return JSON.stringify(msg).toLowerCase().includes(searchTerm);
        });
        
        inspectorContent.innerHTML = filteredMessages.slice(-100).map(msg => {
            const directionColor = msg.direction === 'send' ? 'text-blue-400' : 'text-green-400';
            const typeColor = msg.type === 'market_data' ? 'text-yellow-400' : 'text-gray-300';
            return `
                <div class="mb-2 p-2 border-l-2 ${msg.direction === 'send' ? 'border-blue-500' : 'border-green-500'} bg-gray-800">
                    <div class="flex justify-between text-xs mb-1">
                        <span class="${directionColor}">${msg.direction.toUpperCase()}</span>
                        <span class="${typeColor}">${msg.type}</span>
                        <span class="text-gray-500">${new Date(msg.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <pre class="text-xs overflow-x-auto">${JSON.stringify(msg.data, null, 2)}</pre>
                </div>
            `;
        }).join('');
        
        inspectorContent.scrollTop = inspectorContent.scrollHeight;
    };

    const formatTimestamp = (ts) => {
        if (!ts || ts.toString().length < 11) return '-';
        return new Date(ts).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    };

    const formatNumber = (num, toFixed = 2) => {
        if (num === undefined || num === null) return '-';
        return num.toLocaleString('en-IN', { minimumFractionDigits: toFixed, maximumFractionDigits: toFixed });
    };

    // --- API & WebSocket Functions ---
    const makeApiRequest = async (endpoint, options = {}) => {
        addLog({type: 'api', message: `Requesting ${endpoint}...`});
        const host = hostServerInput.value || 'http://127.0.0.1:5000';
        const apiKey = apiKeyInput.value;
        if (!host || !apiKey) { showToast('Host Server and API Key are required.', 'error'); return null; }
        
        // Validate API key format
        if (apiKey.length < 10) { showToast('Invalid API key format.', 'error'); return null; }
        
        const url = `${host}/api/v1${endpoint}`;
        const headers = { 'Content-Type': 'application/json', ...options.headers };
        const body = options.body ? JSON.parse(options.body) : {};
        if(options.method === 'POST' && !body.apikey) body.apikey = apiKey;
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
        
        try {
            const response = await fetch(url, { 
                ...options, 
                headers, 
                body: JSON.stringify(body),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const result = await response.json();
            if (result.status === 'error') throw new Error(result.message || 'Request failed');
            addLog({type: 'api', message: `Success ${endpoint}: ${JSON.stringify(result)}`});
            return result;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                addLog({type: 'error', message: `API Timeout ${endpoint}: Request timed out`});
                showToast('Request timed out', 'error');
            } else {
                addLog({type: 'error', message: `API Error ${endpoint}: ${error.message}`});
                showToast(error.message, 'error');
            }
            return null;
        }
    };
    
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 5;
    const reconnectDelay = 1000;
    
    const updateWebSocketDiagnostics = () => {
        if (wsStats.connectTime) {
            wsConnectTime.textContent = new Date(wsStats.connectTime).toLocaleTimeString();
            wsDiagnostics.classList.remove('hidden');
        }
        wsSentCount.textContent = wsStats.messagesSent;
        wsRecvCount.textContent = wsStats.messagesReceived;
        
        if (wsStats.lastPingTime) {
            wsLastPing.textContent = new Date(wsStats.lastPingTime).toLocaleTimeString();
        }
        
        wsLatency.textContent = '-';
    };
    
    // Removed ping functionality for security
    
    const connectWebSocket = () => {
        if (socket && socket.readyState === WebSocket.OPEN) { socket.close(); return; }
        const wsUrl = wsServerInput.value || 'ws://127.0.0.1:8765';
        const apiKey = apiKeyInput.value;
        if (!wsUrl || !apiKey) { showToast('WebSocket Server and API Key are required.', 'error'); return; }
        
        // Validate API key format
        if (apiKey.length < 10) { showToast('Invalid API key format.', 'error'); return; }
        
        socket = new WebSocket(wsUrl);
        socket.onopen = () => {
            addLog({type: 'ws', direction: 'info', message: 'Connection opened'});
            reconnectAttempts = 0; // Reset on successful connection
            wsStats.connectTime = Date.now();
            wsStats.reconnectionCount = reconnectAttempts;
            
            const authMsg = { action: 'authenticate', api_key: apiKey };
            socket.send(JSON.stringify(authMsg));
            wsStats.messagesSent++;
            addLog({type: 'ws', direction: 'send', message: JSON.stringify(authMsg), parsed: authMsg});
            
            updateWebSocketDiagnostics();
        };
        socket.onclose = (event) => {
            addLog({type: 'ws', direction: 'info', message: `Connection closed (Code: ${event.code})`});
            wsStatus.textContent = 'Disconnected'; wsStatus.className = 'font-bold text-error'; connectBtn.textContent = 'Connect';
            currentDepthSymbol = null; currentQuoteSymbol = null;
            wsDiagnostics.classList.add('hidden');
            
            // Auto-reconnect logic
            if (reconnectAttempts < maxReconnectAttempts && event.code !== 1000) {
                reconnectAttempts++;
                addLog({type: 'info', message: `Attempting to reconnect (${reconnectAttempts}/${maxReconnectAttempts})...`});
                setTimeout(() => connectWebSocket(), reconnectDelay * reconnectAttempts);
            }
        };
        socket.onerror = (err) => {
            addLog({type: 'error', message: `WS Error: ${err.message || 'Connection failed'}`});
            showToast('WebSocket connection failed', 'error');
        };
        socket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                wsStats.messagesReceived++;
                
                addLog({type: 'ws', direction: 'recv', message: event.data, parsed: msg});
                
                if ((msg.action === "authenticate" || msg.type === "auth") && msg.status === "success") {
                    wsStatus.textContent = 'Connected'; wsStatus.className = 'font-bold text-success'; connectBtn.textContent = 'Disconnect';
                    if (liveModeToggle.checked) Object.values(watchlist).forEach(symbol => subscribe(symbol, 1));
                } else if (msg.type === 'market_data') {
                    handleMarketData(msg);
                }
                
                updateWebSocketDiagnostics();
            } catch (error) {
                addLog({type: 'error', message: `Failed to parse WebSocket message: ${error.message}`});
            }
        };
    };

    const subscribe = (symbolData, mode) => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const msg = { action: 'subscribe', symbol: symbolData.symbol, exchange: symbolData.exchange, mode: mode };
        socket.send(JSON.stringify(msg));
        wsStats.messagesSent++;
        addLog({type: 'ws', direction: 'send', message: JSON.stringify(msg), parsed: msg});
        updateWebSocketDiagnostics();
    };

    const unsubscribe = (symbolData, mode) => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const msg = { action: 'unsubscribe', symbol: symbolData.symbol, exchange: symbolData.exchange, mode: mode };
        socket.send(JSON.stringify(msg));
        wsStats.messagesSent++;
        addLog({type: 'ws', direction: 'send', message: JSON.stringify(msg), parsed: msg});
        updateWebSocketDiagnostics();
    };
    
    const handleMarketData = (data) => {
        const key = `${data.exchange}:${data.symbol}`;
        if (!watchlist[key]) return;
        if (data.data && data.data.ltp) {
             watchlist[key].ltp = data.data.ltp;
             const ltpElement = document.querySelector(`#watchlist-item-${key.replace(':', '')} [data-field="ltp"]`);
             if (ltpElement) ltpElement.textContent = formatNumber(data.data.ltp);
        }
        if (data.mode === 3 && key === currentDepthSymbol) updateDepthPanelView(data.data);
        if (data.mode === 2 && key === currentQuoteSymbol) updateQuoteView(data.data);
    };

    // --- UI Functions ---
    const renderWatchlist = () => {
        watchlistContainer.innerHTML = '';
        for (const key in watchlist) {
            const symbol = watchlist[key];
            const item = document.createElement('div');
            item.className = 'card card-compact bg-base-100 shadow-md p-2';
            item.id = `watchlist-item-${key.replace(':', '')}`;
            item.innerHTML = `<div class="flex justify-between items-center"><div><div class="font-bold">${symbol.symbol}</div><div class="text-xs text-gray-400">${symbol.exchange}</div></div><div class="font-mono text-lg" data-field="ltp">${symbol.ltp ? formatNumber(symbol.ltp) : '0.00'}</div></div><div class="flex gap-1 mt-2"><button class="btn btn-xs btn-outline btn-info flex-1" onclick="window.openQuoteModal('${key}')">Quote</button><button class="btn btn-xs btn-outline btn-info flex-1" onclick="window.openDepthPanel('${key}')">Depth</button><button class="btn btn-xs btn-outline btn-info flex-1" onclick="window.openHistoricalData('${key}')">History</button><button class="btn btn-xs btn-square btn-outline btn-error" onclick="window.removeFromWatchlist('${key}')">×</button></div>`;
            watchlistContainer.appendChild(item);
        }
    };
    
    const displaySearchResults = (results) => {
        let content = `<div class="absolute top-0 left-0 right-0 bg-base-300 p-2 rounded-lg shadow-lg z-10 max-h-60 overflow-y-auto"><button onclick="this.parentElement.remove()" class="btn btn-xs btn-circle absolute top-1 right-1">✕</button>`;
        if (results && results.length > 0) {
            results.forEach(symbol => { content += `<div class="flex justify-between items-center p-1 hover:bg-base-100 rounded"><span>${symbol.symbol} (${symbol.exchange})</span><button class="btn btn-xs btn-success" onclick="window.addToWatchlist(JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify(symbol))}')))">Add</button></div>`; });
        } else content += '<div>No symbols found.</div>';
        content += '</div>';
        searchResultsContainer.innerHTML = content;
    };
    
    const updateDepthPanelView = (data) => {
        const panel = document.getElementById('depth-panel-modal');
        const fields = panel.querySelectorAll('[data-field]');
        
        // Normalize data and map field names to match HTML data-field attributes
        const normalizedData = { 
            ...data, 
            close: data.close ?? data.prev_close, 
            bid: data.bid ?? (data.bids && data.bids[0]?.price), 
            ask: data.ask ?? (data.asks && data.asks[0]?.price),
            // Map underscore field names to match HTML data-field attributes
            totalbuyqty: data.total_buy_quantity ?? data.totalbuyqty,
            totalsellqty: data.total_sell_quantity ?? data.totalsellqty
        };
        
        fields.forEach(field => {
            const key = field.dataset.field; 
            let value = normalizedData[key]; 
            if (value === undefined || value === null) { 
                field.textContent = '-'; 
                return; 
            }
            if (key === 'ltt') { 
                field.textContent = formatTimestamp(value); 
                return; 
            }
            const toFixed = (key.includes('qty') || key === 'volume' || key === 'oi' || key === 'ltq') ? 0 : 2;
            field.textContent = formatNumber(value, toFixed);
        });
        
        const bidsContainer = panel.querySelector('#depth-panel-bids');
        const asksContainer = panel.querySelector('#depth-panel-asks');
        const formatSide = (sideData, type) => {
            const headerColor = type === 'bid' ? 'text-green-400' : 'text-red-400';
            const header = `<div class="grid grid-cols-1 ${headerColor} font-bold text-sm border-b border-gray-700 pb-1"><span>${type.toUpperCase()}S</span></div><div class="grid grid-cols-3 text-xs text-gray-400 border-b border-gray-700 pb-1"><span>${type === 'bid' ? 'Qty' : 'Price'}</span><span class="text-center">Orders</span><span class="text-right">${type === 'bid' ? 'Price' : 'Qty'}</span></div>`;
            const rows = (sideData || []).slice(0, 5).map(d => `<div class="grid grid-cols-3 font-mono ${type}-price"><span>${type === 'bid' ? formatNumber(d.quantity, 0) : formatNumber(d.price)}</span><span class="text-center">${d.orders ?? '-'}</span><span class="text-right">${type === 'bid' ? formatNumber(d.price) : formatNumber(d.quantity, 0)}</span></div>`).join('');
            return header + rows;
        };
        bidsContainer.innerHTML = formatSide(normalizedData.bids || (normalizedData.depth && normalizedData.depth.buy), 'bid');
        asksContainer.innerHTML = formatSide(normalizedData.asks || (normalizedData.depth && normalizedData.depth.sell), 'ask');
    };

    const updateQuoteView = (data) => {
        const modal = document.getElementById('quote-data-modal');
        const fields = modal.querySelectorAll('[data-field]');
        
        // Normalize data and ensure field compatibility
        const normalizedData = { 
            ...data, 
            close: data.close ?? data.prev_close,
            // Map any additional field name variations if needed
            last_quantity: data.last_quantity ?? data.ltq ?? data.last_traded_qty
        };
        
        fields.forEach(field => {
            const key = field.dataset.field; 
            let value = normalizedData[key]; 
            if (value === undefined || value === null) { 
                field.textContent = '-'; 
                return; 
            }
            if (key === 'ltt') { 
                field.textContent = formatTimestamp(value); 
                return; 
            }
            const toFixed = (key.includes('qty') || key.includes('quantity') || key === 'volume' || key === 'oi') ? 0 : 2;
            field.textContent = formatNumber(value, toFixed);
        });
    };

    // --- Global Event Handlers ---
    window.addToWatchlist = (symbol) => { const key = `${symbol.exchange}:${symbol.symbol}`; if (watchlist[key]) { showToast('Symbol already in watchlist.', 'error'); return; } watchlist[key] = { ...symbol, ltp: null }; renderWatchlist(); if (liveModeToggle.checked) subscribe(symbol, 1); searchResultsContainer.innerHTML = ''; };
    window.removeFromWatchlist = (key) => { if (currentDepthSymbol === key) closeDepthPanel(); if (currentQuoteSymbol === key) quoteDataModal.close(); if (liveModeToggle.checked) unsubscribe(watchlist[key], 1); delete watchlist[key]; renderWatchlist(); };
    window.openDepthPanel = async (key) => { const symbolData = watchlist[key]; depthPanelModal.querySelector('[data-field="symbol"]').textContent = symbolData.symbol; updateDepthPanelView({}); depthPanelModal.classList.add('modal-open'); if (liveModeToggle.checked) { currentDepthSymbol = key; subscribe(symbolData, 3); } else { const result = await makeApiRequest('/depth', { method: 'POST', body: JSON.stringify({ symbol: symbolData.symbol, exchange: symbolData.exchange }) }); if (result && result.data) updateDepthPanelView(result.data); } };
    const closeDepthPanel = () => { if (currentDepthSymbol && liveModeToggle.checked) unsubscribe(watchlist[currentDepthSymbol], 3); currentDepthSymbol = null; depthPanelModal.classList.remove('modal-open'); };
    window.openQuoteModal = async (key) => { const symbolData = watchlist[key]; quoteDataSymbol.textContent = `Quote: ${symbolData.symbol}`; updateQuoteView({}); quoteDataModal.showModal(); if(liveModeToggle.checked) { currentQuoteSymbol = key; subscribe(symbolData, 2); } else { const result = await makeApiRequest('/quotes', { method: 'POST', body: JSON.stringify({ symbol: symbolData.symbol, exchange: symbolData.exchange }) }); if (result && result.data) updateQuoteView(result.data); } };
    const closeQuoteModal = () => { if (currentQuoteSymbol && liveModeToggle.checked) unsubscribe(watchlist[currentQuoteSymbol], 2); currentQuoteSymbol = null; };
    window.openHistoricalData = (key) => { const symbolData = watchlist[key]; if (!symbolData) { console.error('Symbol data not found for key:', key); return; } historicalDataSymbol.textContent = `Historical Data: ${symbolData.symbol}`; historicalDataModal.dataset.key = key; historicalResults.innerHTML = ''; historicalDataModal.showModal(); };

    // --- Event Listeners ---
    connectBtn.addEventListener('click', connectWebSocket);
    clearLogsBtn.addEventListener('click', () => { logsContainer.innerHTML = ''; allLogs = []; });
    closeDepthPanelBtn.addEventListener('click', closeDepthPanel);
    quoteDataModal.addEventListener('close', closeQuoteModal);
    searchBtn.addEventListener('click', async () => { const query = searchSymbolInput.value.trim(); if (!query) return; const result = await makeApiRequest('/search', { method: 'POST', body: JSON.stringify({ query }) }); if (result) displaySearchResults(result.data); });
    liveModeToggle.addEventListener('change', (e) => { const isLive = e.target.checked; if(!isLive && (currentDepthSymbol || currentQuoteSymbol)) { closeDepthPanel(); quoteDataModal.close(); } Object.values(watchlist).forEach(symbol => { if (isLive) subscribe(symbol, 1); else unsubscribe(symbol, 1); }); });
    refreshWatchlistBtn.addEventListener('click', async () => { addLog({type:'info', message:'Manual refresh triggered.'}); for (const key in watchlist) { const result = await makeApiRequest('/quotes', { method: 'POST', body: JSON.stringify({ symbol: watchlist[key].symbol, exchange: watchlist[key].exchange }) }); if (result && result.data) handleMarketData({ exchange: watchlist[key].exchange, symbol: watchlist[key].symbol, data: { ltp: result.data.ltp }}); } showToast('Watchlist refreshed!'); });
    fetchHistoricalBtn.addEventListener('click', async () => { const key = historicalDataModal.dataset.key; const result = await makeApiRequest('/history', { method: 'POST', body: JSON.stringify({ symbol: watchlist[key].symbol, exchange: watchlist[key].exchange, interval: historicalInterval.value, start_date: historicalFrom.value, end_date: historicalTo.value }) }); if (result && result.data) { historicalResults.innerHTML = result.data.map(d => `<tr><td>${d.timestamp}</td><td>${d.open}</td><td>${d.high}</td><td>${d.low}</td><td>${d.close}</td><td>${d.volume}</td></tr>`).join(''); } });

    // --- Log Filtering Logic ---
    const resetFilterDropdowns = (startLevel = 1) => {
        if (startLevel <= 1) { logFilterWsContainer.classList.add('hidden'); }
        if (startLevel <= 2) { logFilterWsRecvContainer.classList.add('hidden'); }
        if (startLevel <= 3) { logFilterWsMarketDataContainer.classList.add('hidden'); }
    };

    const populateDropdown = (selectElement, values, defaultOptionText) => {
        selectElement.innerHTML = `<option value="">${defaultOptionText}</option>`;
        [...new Set(values)].sort().forEach(value => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = value;
            selectElement.appendChild(option);
        });
    };

    logFilterType.addEventListener('change', () => {
        resetFilterDropdowns(2);
        if (logFilterType.value === 'ws') logFilterWsContainer.classList.remove('hidden');
        else logFilterWsContainer.classList.add('hidden');
    });

    logFilterWsDirection.addEventListener('change', () => {
        resetFilterDropdowns(3);
        if (logFilterWsDirection.value === 'recv') {
            const recvTypes = allLogs.filter(l => l.direction === 'recv' && l.parsed).map(l => l.parsed.type || 'unknown');
            populateDropdown(logFilterWsRecvType, recvTypes, 'All Message Types');
            logFilterWsRecvContainer.classList.remove('hidden');
        } else {
            logFilterWsRecvContainer.classList.add('hidden');
        }
    });

    logFilterWsRecvType.addEventListener('change', () => {
        resetFilterDropdowns(4);
        if (logFilterWsRecvType.value === 'market_data') {
            const marketDataLogs = allLogs.filter(l => l.parsed?.type === 'market_data' && l.parsed?.data);
            populateDropdown(logFilterWsMarketDataMode, marketDataLogs.map(l => l.parsed.mode), 'All Modes');
            populateDropdown(logFilterWsMarketDataExchange, marketDataLogs.map(l => l.parsed.exchange), 'All Exchanges');
            populateDropdown(logFilterWsMarketDataSymbol, marketDataLogs.map(l => l.parsed.symbol), 'All Symbols');
            logFilterWsMarketDataContainer.classList.remove('hidden');
        } else {
            logFilterWsMarketDataContainer.classList.add('hidden');
        }
    });

    logFilterApplyBtn.addEventListener('click', () => {
        const type = logFilterType.value;
        const wsDir = logFilterWsDirection.value;
        const wsRecvType = logFilterWsRecvType.value;
        const mdMode = logFilterWsMarketDataMode.value;
        const mdExch = logFilterWsMarketDataExchange.value;
        const mdSym = logFilterWsMarketDataSymbol.value;

        allLogs.forEach(log => {
            let show = true;
            if (type && log.type !== type) show = false;
            if (show && type === 'ws' && wsDir && log.direction !== wsDir) show = false;
            if (show && wsDir === 'recv' && wsRecvType && (log.parsed?.type || 'unknown') !== wsRecvType) show = false;
            if (show && wsRecvType === 'market_data') {
                if (mdMode && log.parsed?.mode.toString() !== mdMode) show = false;
                if (mdExch && log.parsed?.exchange !== mdExch) show = false;
                if (mdSym && log.parsed?.symbol !== mdSym) show = false;
            }
            log.element.classList.toggle('hidden', !show);
        });
    });

    logFilterResetBtn.addEventListener('click', () => {
        logFilterType.value = '';
        logFilterWsDirection.value = '';
        logFilterWsRecvType.value = '';
        logFilterWsMarketDataMode.value = '';
        logFilterWsMarketDataExchange.value = '';
        logFilterWsMarketDataSymbol.value = '';
        resetFilterDropdowns(1);
        allLogs.forEach(log => log.element.classList.remove('hidden'));
    });
    
    // --- WebSocket Inspector Functions ---
    const switchTab = (activeTab) => {
        // Remove active class from all tabs
        [logsTab, inspectorTab].forEach(tab => tab.classList.remove('tab-active'));
        
        // Hide all panels
        [logsPanel, inspectorPanel].forEach(panel => panel.classList.add('hidden'));
        
        // Show active tab and panel
        activeTab.classList.add('tab-active');
        
        if (activeTab === logsTab) {
            logsPanel.classList.remove('hidden');
        } else if (activeTab === inspectorTab) {
            inspectorPanel.classList.remove('hidden');
            renderInspectorMessages();
        }
    };
    
    const exportInspectorData = () => {
        const dataStr = JSON.stringify(wsStats.messageHistory, null, 2);
        const dataBlob = new Blob([dataStr], {type: 'application/json'});
        const url = URL.createObjectURL(dataBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `websocket-messages-${new Date().toISOString().slice(0, 19)}.json`;
        link.click();
        URL.revokeObjectURL(url);
        showToast('Message history exported', 'success');
    };
    
    // --- WebSocket Inspector Event Listeners ---
    logsTab.addEventListener('click', () => switchTab(logsTab));
    inspectorTab.addEventListener('click', () => switchTab(inspectorTab));
    
    clearInspectorBtn.addEventListener('click', () => {
        wsStats.messageHistory = [];
        renderInspectorMessages();
        showToast('Inspector cleared', 'success');
    });
    exportInspectorBtn.addEventListener('click', exportInspectorData);
    inspectorSearch.addEventListener('input', renderInspectorMessages);

    // Load saved settings from localStorage
    const loadSettings = () => {
        const savedHost = localStorage.getItem('playground-host');
        const savedWsServer = localStorage.getItem('playground-ws-server');
        if (savedHost) hostServerInput.value = savedHost;
        if (savedWsServer) wsServerInput.value = savedWsServer;
    };
    
    // Save settings to localStorage
    const saveSettings = () => {
        localStorage.setItem('playground-host', hostServerInput.value);
        localStorage.setItem('playground-ws-server', wsServerInput.value);
    };
    
    // Add event listeners to save settings when changed
    hostServerInput.addEventListener('change', saveSettings);
    wsServerInput.addEventListener('change', saveSettings);
    
    // Init
    loadSettings();
    renderWatchlist();
    
    // Initialize with logs tab active
    switchTab(logsTab);
});