// Function to fetch and update logs
async function refreshLogs() {
    try {
        const response = await fetch('/logs');
        const html = await response.text();
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        const newContent = tempDiv.querySelector('#logs-container');
        if (newContent) {
            const currentContainer = document.getElementById('logs-container');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            }
        }
    } catch (error) {}
}

// Function to fetch and update orderbook
async function refreshOrderbook() {
    try {
        const response = await fetch('/orderbook');
        const html = await response.text();
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        
        // Update stats grid
        const newStatsGrid = tempDiv.querySelector('.grid-cols-1.sm\\:grid-cols-2.lg\\:grid-cols-5');
        if (newStatsGrid) {
            const currentStatsGrid = document.querySelector('.grid-cols-1.sm\\:grid-cols-2.lg\\:grid-cols-5');
            if (currentStatsGrid) {
                currentStatsGrid.innerHTML = newStatsGrid.innerHTML;
            }
        }
        
        // Update table
        const newContent = tempDiv.querySelector('#orderbook-table-container');
        if (newContent) {
            const currentContainer = document.querySelector('#orderbook-table-container');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            }
        }
    } catch (error) {}
}

// Function to fetch and update tradebook
async function refreshTradebook() {
    try {
        const response = await fetch('/tradebook');
        const html = await response.text();
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        
        // Update stats
        const newStats = tempDiv.querySelector('.stats');
        if (newStats) {
            const currentStats = document.querySelector('.stats');
            if (currentStats) {
                currentStats.innerHTML = newStats.innerHTML;
            }
        }
        
        // Update table
        const newContent = tempDiv.querySelector('#tradebook-table-container');
        if (newContent) {
            const currentContainer = document.querySelector('#tradebook-table-container');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            }
        }
    } catch (error) {}
}

// Function to fetch and update positions
async function refreshPositions() {
    try {
        const response = await fetch('/positions');
        const html = await response.text();
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        const newContent = tempDiv.querySelector('#positions-table-container');
        if (newContent) {
            const currentContainer = document.querySelector('#positions-table-container');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            }
        }
    } catch (error) {}
}

// Function to fetch and update dashboard funds
async function refreshDashboard() {
    try {
        const response = await fetch('/dashboard');
        const html = await response.text();
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        const newContent = tempDiv.querySelector('.grid-cols-1.sm\\:grid-cols-2.lg\\:grid-cols-4');
        if (newContent) {
            const currentContainer = document.querySelector('.grid-cols-1.sm\\:grid-cols-2.lg\\:grid-cols-4');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            }
        }
    } catch (error) {}
}

// Function to fetch and update analyzer
async function refreshAnalyzer() {
    try {
        // Update stats
        const statsResponse = await fetch('/analyzer/stats');
        const statsData = await statsResponse.json();
        
        const totalRequests = document.getElementById('total-requests');
        const totalIssues = document.getElementById('total-issues');
        const uniqueSymbols = document.getElementById('unique-symbols');
        const activeSources = document.getElementById('active-sources');

        if (totalRequests) totalRequests.textContent = statsData.total_requests;
        if (totalIssues) totalIssues.textContent = statsData.issues.total;
        if (uniqueSymbols) uniqueSymbols.textContent = statsData.symbols.length;
        if (activeSources) activeSources.textContent = Object.keys(statsData.sources).length;

        // Update requests table
        const requestsResponse = await fetch('/analyzer/requests');
        const requestsData = await requestsResponse.json();
        
        const tbody = document.getElementById('requests-table');
        if (tbody && requestsData.requests) {
            tbody.innerHTML = requestsData.requests.map(request => {
                let details = '';
                if (request.api_type === 'cancelorder') {
                    details = `OrderID: ${request.orderid || request.request_data.orderid}`;
                } else if (request.api_type === 'cancelallorder') {
                    details = 'Cancel All Orders';
                    if (request.response_data && request.response_data.canceled_orders) {
                        details += ` (${request.response_data.canceled_orders.length} orders)`;
                    }
                } else if (request.api_type === 'closeposition') {
                    details = 'Close All Positions';
                } else if (request.api_type === 'modifyorder') {
                    details = `Modify Order - OrderID: ${request.orderid || request.request_data.orderid}`;
                    if (request.symbol) {
                        details += ` - ${request.symbol}`;
                    }
                } else {
                    details = `${request.symbol || ''} ${request.quantity ? `(${request.quantity})` : ''}`;
                    if (request.api_type === 'placesmartorder' && request.position_size) {
                        details += ` [Size: ${request.position_size}]`;
                    }
                }

                return `
                    <tr class="hover:bg-base-200">
                        <td class="text-sm">${request.timestamp}</td>
                        <td class="badge-cell">
                            <div class="badge-container">
                                <div class="badge badge-primary">${request.api_type}</div>
                            </div>
                        </td>
                        <td class="badge-cell">
                            <div class="badge-container">
                                <div class="badge badge-neutral truncate">${request.source}</div>
                            </div>
                        </td>
                        <td class="font-medium">${details}</td>
                        <td class="badge-cell">
                            ${request.exchange ? `
                                <div class="badge-container">
                                    <div class="badge ${getExchangeBadgeColor(request.exchange)}">
                                        ${request.exchange}
                                    </div>
                                </div>
                            ` : ''}
                        </td>
                        <td class="badge-cell">
                            ${request.action ? `
                                <div class="badge-container">
                                    <div class="badge ${request.action === 'BUY' ? 'badge-success' : 'badge-error'}">
                                        ${request.action}
                                    </div>
                                </div>
                            ` : ''}
                        </td>
                        <td class="badge-cell">
                            <div class="badge-container">
                                <div class="badge ${request.analysis.issues ? 'badge-warning' : 'badge-success'}">
                                    ${request.analysis.issues ? 'Issues' : 'Valid'}
                                </div>
                            </div>
                        </td>
                        <td class="badge-cell">
                            <div class="badge-container">
                                <button class="btn btn-sm btn-primary view-details"
                                        data-request="${encodeURIComponent(JSON.stringify(request.request_data))}"
                                        data-response="${encodeURIComponent(JSON.stringify(request.response_data))}">
                                    View
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
            
            // Reattach click handlers after updating table content
            document.querySelectorAll('.view-details').forEach(button => {
                button.addEventListener('click', function() {
                    try {
                        const requestData = JSON.parse(decodeURIComponent(this.getAttribute('data-request')));
                        const responseData = JSON.parse(decodeURIComponent(this.getAttribute('data-response')));
                        // Remove apikey from request data if present
                        if (requestData.apikey) {
                            delete requestData.apikey;
                        }

                        document.getElementById('request-data').textContent = JSON.stringify(requestData, null, 2);
                        document.getElementById('response-data').textContent = JSON.stringify(responseData, null, 2);
                        document.getElementById('requestModal').showModal();
                    } catch (error) {}
                });
            });
        }
    } catch (error) {}
}

// Helper function to get exchange badge color
function getExchangeBadgeColor(exchange) {
    const colors = {
        'NSE': 'badge-accent',
        'BSE': 'badge-neutral',
        'NFO': 'badge-secondary',
        'MCX': 'badge-primary'
    };
    return colors[exchange] || 'badge-ghost';
}

// Make refreshCurrentPageContent available globally
window.refreshCurrentPageContent = function() {
    const path = window.location.pathname;
    if (path.includes('/logs')) {
        refreshLogs();
    } else if (path.includes('/orderbook')) {
        refreshOrderbook();
    } else if (path.includes('/tradebook')) {
        refreshTradebook();
    } else if (path.includes('/positions')) {
        refreshPositions();
    } else if (path === '/dashboard' || path === '/') {
        refreshDashboard();
    } else if (path.includes('/analyzer')) {
        refreshAnalyzer();
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
    var alertSound = document.getElementById('alert-sound');
    var isOnAnalyzerPage = window.location.pathname.includes('/analyzer');

    socket.on('connect', function() {});
    socket.on('disconnect', function() {});

    // Password change notification
    socket.on('password_change', function(data) {
        playAlertSound();
        showToast(data.message, 'info');
        //refreshCurrentPageContent();
    });

    // Master contract download notification
    socket.on('master_contract_download', function(data) {
        playAlertSound();
        showToast(`Master Contract: ${data.message}`, 'info');
        //refreshCurrentPageContent();
    });

    // Cancel order notification
    socket.on('cancel_order_event', function(data) {
        playAlertSound();
        showToast(`Cancel Order ID: ${data.orderid}`, 'warning');
        if (isOnAnalyzerPage) {
            refreshAnalyzer();
        } else {
            refreshCurrentPageContent();
        }
    });

    // Modify order notification
    socket.on('modify_order_event', function(data) {
        playAlertSound();
        const message = data.status === 'success' 
            ? `Order Modified Successfully - Order ID: ${data.orderid}`
            : `Failed to Modify Order - Order ID: ${data.orderid}`;
        showToast(message, data.status === 'success' ? 'success' : 'error');
        if (isOnAnalyzerPage) {
            refreshAnalyzer();
        } else {
            //refreshOrderbook();
            refreshCurrentPageContent();
        }
    });

    // Close position notification
    socket.on('close_position_event', function(data) {
        playAlertSound();
        showToast(data.message, data.status === 'success' ? 'success' : 'error');
        if (isOnAnalyzerPage) {
            refreshAnalyzer();
        } else {
            // Add a 1-second delay before refreshing content
            setTimeout(() => {
                refreshCurrentPageContent();
            }, 1000);
        }
    });

    // Order placement notification
    socket.on('order_event', function(data) {
        playAlertSound();
        const type = data.action.toUpperCase() === 'BUY' ? 'success' : 'error';
        
        // Show toast notification
        showToast(`${data.action.toUpperCase()} Order Placed for Symbol: ${data.symbol}, Order ID: ${data.orderid}`, type);
        
        // For batch orders (basket/split), only refresh on the last order
        if (!data.batch_order || data.is_last_order) {
            if (isOnAnalyzerPage) {
                refreshAnalyzer();
            } else {
                // Add a 1-second delay before refreshing content
                setTimeout(() => {
                    refreshCurrentPageContent();
                }, 1000);
            }
        }
    });

    // Generic order notification handler
    socket.on('order_notification', function(data) {
        playAlertSound();
        
        // Determine notification type based on status
        let type = 'info';
        if (data.status && typeof data.status === 'string') {
            if (data.status.toLowerCase().includes('success')) {
                type = 'success';
            } else if (data.status.toLowerCase().includes('error') || data.status.toLowerCase().includes('reject')) {
                type = 'error';
            } else if (data.status.toLowerCase().includes('pending')) {
                type = 'warning';
            }
        }

        // Create notification message
        let message = '';
        if (data.symbol) {
            message += `${data.symbol}: `;
        }
        if (data.status) {
            message += data.status;
        }
        if (data.message) {
            message += data.message;
        }

        showToast(message, type);
    });

    // Analyzer update notification
    socket.on('analyzer_update', function(data) {
        playAlertSound();
        let message = '';
        let type = data.response.status === 'success' ? 'success' : 'error';

        if (data.request.api_type === 'cancelorder') {
            message = `Cancel Order - Order ID: ${data.request.orderid}`;
        } else if (data.request.api_type === 'cancelallorder') {
            if (data.response.status === 'error') {
                message = `Error: ${data.response.message}`;
            } else {
                message = 'Cancel All Orders';
                if (data.response.canceled_orders) {
                    message += ` - Canceled ${data.response.canceled_orders.length} orders`;
                }
            }
        } else if (data.request.api_type === 'closeposition') {
            if (data.response.status === 'error') {
                message = `Error: ${data.response.message}`;
            } else {
                message = data.response.message || 'All Open Positions will be Squared Off';
            }
            if (!isOnAnalyzerPage) {
                refreshPositions();
            }
        } else if (data.request.api_type === 'modifyorder') {
            if (data.response.status === 'error') {
                message = `Error: ${data.response.message}`;
            } else {
                message = `Order Modified Successfully - Order ID: ${data.request.orderid}`;
                if (data.request.symbol) {
                    message += ` - ${data.request.symbol}`;
                }
            }
            if (!isOnAnalyzerPage) {
                refreshOrderbook();
            }
        } else {
            const action = data.request.action || '';
            const symbol = data.request.symbol || '';
            const quantity = data.request.quantity || '';
            const orderid = data.response.orderid || '';
            
            if (data.response.status === 'error') {
                message = `Error: ${data.response.message}`;
                if (symbol) message = `${symbol} - ${message}`;
            } else {
                message = `${action} Order Placed for Symbol: ${symbol}`;
                if (quantity) message += `, Qty: ${quantity}`;
                if (orderid) message += `, Order ID: ${orderid}`;
                
                if (data.request.api_type === 'placesmartorder' && data.request.position_size) {
                    message += `, Size: ${data.request.position_size}`;
                }
            }
        }
        
        showToast(message, type);
        if (isOnAnalyzerPage) {
            refreshAnalyzer();
        }
    });

    // Helper function to play alert sound
    function playAlertSound() {
        if (alertSound) {
            alertSound.play().catch(function(error) {});
        }
    }

    // Initial page load - set up click handlers
    if (isOnAnalyzerPage) {
        document.querySelectorAll('.view-details').forEach(button => {
            button.addEventListener('click', function() {
                try {
                    const requestData = JSON.parse(decodeURIComponent(this.getAttribute('data-request')));
                    const responseData = JSON.parse(decodeURIComponent(this.getAttribute('data-response')));
                    console.log(responseData);

                    // Remove apikey from request data if present
                    if (requestData.apikey) {
                        delete requestData.apikey;
                    }
                    
                    document.getElementById('request-data').textContent = JSON.stringify(requestData, null, 2);
                    document.getElementById('response-data').textContent = JSON.stringify(responseData, null, 2);
                    document.getElementById('requestModal').showModal();
                } catch (error) {}
            });
        });

        // Initial analyzer refresh
        refreshAnalyzer();
    }
});

// Functions for mobile menu toggle
function toggleMobileMenu() {
    var menu = document.getElementById('mobile-menu');
    menu.classList.remove('-translate-x-full');
    document.querySelector('button[onclick="toggleMobileMenu()"]').style.display = 'none';
}

function closeMobileMenu() {
    var menu = document.getElementById('mobile-menu');
    menu.classList.add('-translate-x-full');
    document.querySelector('button[onclick="toggleMobileMenu()"]').style.display = 'block';
}
