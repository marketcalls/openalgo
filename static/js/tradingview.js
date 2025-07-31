document.addEventListener('DOMContentLoaded', function() {
    // Initialize all DOM elements first
    const symbolInput = document.getElementById('symbol');
    const exchangeSelect = document.getElementById('exchange');
    const productSelect = document.getElementById('product');
    const searchResults = document.getElementById('searchResults');
    const loadingIndicator = document.querySelector('.loading-indicator');
    const tradingviewForm = document.getElementById('tradingview-form');
    let debounceTimeout;

    // Set default values and generate JSON
    if (symbolInput && exchangeSelect && productSelect) {
        symbolInput.value = 'ETERNAL';
        exchangeSelect.value = 'NSE';
        productSelect.value = 'MIS';
        
        // Auto-generate JSON on load
        generateJSON();
    }

    // Symbol input handler
    if (symbolInput) {
        symbolInput.addEventListener('input', function(e) {
            clearTimeout(debounceTimeout);
            const query = e.target.value.trim();
            const exchange = exchangeSelect ? exchangeSelect.value : '';
            
            if (query.length < 2) {
                if (searchResults) {
                    searchResults.classList.add('hidden');
                }
                return;
            }
            
            debounceTimeout = setTimeout(() => {
                fetchSearchResults(query, exchange);
            }, 300);
        });
    }

    // Exchange select handler
    if (exchangeSelect) {
        exchangeSelect.addEventListener('change', function(e) {
            const query = symbolInput ? symbolInput.value.trim() : '';
            if (query.length >= 2) {
                fetchSearchResults(query, e.target.value);
            }
            generateJSON();
        });
    }

    // Product type change handler
    if (productSelect) {
        productSelect.addEventListener('change', generateJSON);
    }

    // Click outside search results handler
    document.addEventListener('click', function(e) {
        if (searchResults && symbolInput && 
            !symbolInput.contains(e.target) && 
            !searchResults.contains(e.target)) {
            searchResults.classList.add('hidden');
        }
    });

    // Form submit handler
    if (tradingviewForm) {
        tradingviewForm.addEventListener('submit', function(e) {
            e.preventDefault();
            generateJSON();
        });
    }

    async function fetchSearchResults(query, exchange) {
        if (!searchResults || !loadingIndicator) return;

        try {
            loadingIndicator.style.display = 'block';
            const response = await fetch(`/search/api/search?q=${encodeURIComponent(query)}&exchange=${encodeURIComponent(exchange)}`);
            const data = await response.json();
            
            searchResults.innerHTML = '';
            
            if (data.results && data.results.length > 0) {
                data.results.forEach(result => {
                    const div = document.createElement('div');
                    div.className = 'menu-item p-3 hover:bg-base-200';
                    div.innerHTML = `
                        <div class="flex items-center justify-between">
                            <span class="font-medium">${result.symbol}</span>
                            <span class="badge badge-${result.exchange.toLowerCase()}">${result.exchange}</span>
                        </div>
                        <div class="text-sm text-base-content/70 mt-1">${result.name || ''}</div>
                        <div class="text-xs text-base-content/60 mt-1">Token: ${result.token}</div>
                    `;
                    div.addEventListener('click', () => {
                        if (symbolInput && exchangeSelect) {
                            symbolInput.value = result.symbol;
                            exchangeSelect.value = result.exchange;
                            searchResults.classList.add('hidden');
                            generateJSON();
                        }
                    });
                    searchResults.appendChild(div);
                });
                searchResults.classList.remove('hidden');
            } else {
                searchResults.classList.add('hidden');
            }
        } catch (error) {
            console.error('Error:', error);
            showToast('Error fetching search results');
        } finally {
            loadingIndicator.style.display = 'none';
        }
    }

    function generateJSON() {
        if (!symbolInput || !exchangeSelect || !productSelect) return;

        const formData = {
            symbol: symbolInput.value,
            exchange: exchangeSelect.value,
            product: productSelect.value
        };

        fetch('/tradingview/', {
            method: 'POST',
            body: JSON.stringify(formData),
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            }
        })
        .then(response => response.json().then(data => ({status: response.status, data: data})))
        .then(({status, data}) => {
            if (status === 404 && data.error === 'API key not found') {
                showToast('Please set up your API key in the API Key section first', 'warning', true);
                return;
            }
            if (status !== 200) {
                throw new Error(data.error || 'Network response was not ok');
            }
            
            // Reconstruct the JSON object in the correct order with exact symbol
            let orderedData = {
                "apikey": data.apikey,
                "strategy": data.strategy,
                "symbol": symbolInput.value,
                "action": data.action,
                "exchange": exchangeSelect.value,
                "pricetype": data.pricetype,
                "product": productSelect.value,
                "quantity": data.quantity,
                "position_size": data.position_size
            };
            
            const jsonOutput = document.getElementById('json-output');
            if (jsonOutput) {
                const formattedJson = JSON.stringify(orderedData, null, 2);
                jsonOutput.textContent = formattedJson;
                Prism.highlightElement(jsonOutput);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error generating JSON');
        });
    }

    // Copy webhook URL handler
    const webhookCopyBtn = document.getElementById('copy-webhook');
    if (webhookCopyBtn) {
        webhookCopyBtn.addEventListener('click', function() {
            const webhookURL = document.getElementById('webhookURL');
            const alert = document.getElementById('webhookCopyAlert');
            if (webhookURL && alert) {
                copyText(webhookURL.textContent.trim(), this, alert);
            }
        });
    }

    // Copy JSON handler
    const copyJsonBtn = document.getElementById('copy-json');
    if (copyJsonBtn) {
        copyJsonBtn.addEventListener('click', function() {
            const jsonOutput = document.getElementById('json-output');
            const alert = document.getElementById('copy-success-alert');
            if (jsonOutput && alert) {
                copyText(jsonOutput.textContent, this, alert);
            }
        });
    }

    function copyText(text, button, alert) {
        const originalText = button.innerHTML;
        
        navigator.clipboard.writeText(text).then(() => {
            alert.classList.remove('hidden');
            button.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                Copied!
            `;
            
            setTimeout(() => {
                alert.classList.add('hidden');
                button.innerHTML = originalText;
            }, 2000);
        }).catch(() => {
            showToast('Failed to copy text');
        });
    }

    function showToast(message, type = 'error', withLink = false) {
        const toast = document.createElement('div');
        toast.className = 'toast toast-end';
        
        let alertClass = type === 'warning' ? 'alert-warning' : 'alert-error';
        let content = message;
        
        if (withLink) {
            content = `
                ${message}
                <a href="/apikey" class="btn btn-sm btn-primary ml-2">Go to API Key Setup</a>
            `;
        }
        
        toast.innerHTML = `
            <div class="alert ${alertClass} flex items-center">
                <span>${content}</span>
            </div>
        `;
        
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    }
});
