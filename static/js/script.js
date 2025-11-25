let isRunning = false;

let lastNotificationTime = 0;

// Função para atualizar dados da tela
async function updateDashboard() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Atualiza Saldos e Lucros
        document.getElementById('balanceDisplay').innerText = `$${data.balance.toFixed(2)}`;
        document.getElementById('totalProfitDisplay').innerText = `$${data.total_profit.toFixed(2)}`;
        document.getElementById('dailyProfitDisplay').innerText = `$${data.daily_profit.toFixed(2)}`;
        
        // Cor do Lucro Diário
        const dailyEl = document.getElementById('dailyProfitDisplay');
        if (data.daily_profit >= 0) dailyEl.className = 'text-success';
        else dailyEl.className = 'text-danger';

        // Notificações (Toasts)
        if (data.notifications && data.notifications.length > 0) {
            const latest = data.notifications[data.notifications.length - 1];
            if (latest.time > lastNotificationTime) {
                lastNotificationTime = latest.time;
                showToast(latest.msg, latest.type);
            }
        }

        // Atualiza Status da Conexão
        const connStatus = document.getElementById('connectionStatus');
        if (data.connected) {
            connStatus.className = 'alert alert-success py-2 text-center mb-3';
            connStatus.innerHTML = '<small>⚡ API Conectada & Rodando</small>';
        } else {
            if (data.running) {
                 connStatus.className = 'alert alert-danger py-2 text-center mb-3';
                 connStatus.innerHTML = '<small>❌ Erro de Conexão</small>';
            } else {
                 connStatus.className = 'alert alert-secondary py-2 text-center mb-3';
                 connStatus.innerHTML = '<small>🔌 Desconectado</small>';
            }
        }

        // Atualiza Botão de Status
        const btnToggle = document.getElementById('btnToggle');
        if (data.running) {
            btnToggle.classList.remove('btn-danger');
            btnToggle.classList.add('btn-success');
            btnToggle.innerText = "ROBÔ LIGADO (Clique p/ Parar)";
            isRunning = true;
        } else {
            btnToggle.classList.remove('btn-success');
            btnToggle.classList.add('btn-danger');
            btnToggle.innerText = "ROBÔ PARADO (Clique p/ Iniciar)";
            isRunning = false;
        }

        // Atualiza Tabela
        const tbody = document.getElementById('marketTableBody');
        tbody.innerHTML = '';

        if (Object.keys(data.market_data).length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Nenhuma moeda monitorada ou aguardando dados...</td></tr>';
        } else {
            for (const [symbol, info] of Object.entries(data.market_data)) {
                const tr = document.createElement('tr');
                
                // Cor do PnL
                let pnlClass = '';
                if (info.pnl.includes('-')) pnlClass = 'text-muted';
                else if (parseFloat(info.pnl) >= 0) pnlClass = 'text-success fw-bold';
                else pnlClass = 'text-danger fw-bold';

                // Sinal Visual (Bolinhas)
                let signalDot = '⚪'; // Default grey
                if (info.signal_color === 'green') signalDot = '🟢';
                else if (info.signal_color === 'red') signalDot = '🔴';
                else if (info.signal_color === 'blue') signalDot = '🔵'; // Em operação

                // Cor do Status da Carteira
                let walletClass = 'text-muted';
                if (info.wallet_status.includes('EM CARTEIRA')) walletClass = 'text-primary fw-bold';

                tr.innerHTML = `
                    <td class="fs-4 text-center">${signalDot}</td>
                    <td><span class="badge bg-secondary">${symbol}</span></td>
                    <td class="${walletClass}"><small>${info.wallet_status}</small></td>
                    <td>$${info.price.toFixed(4)}</td>
                    <td>${info.rsi.toFixed(2)}</td>
                    <td class="text-info">$${info.lower_band.toFixed(4)}</td>
                    <td class="text-warning">$${info.upper_band.toFixed(4)}</td>
                    <td class="${pnlClass}">${info.pnl}</td>
                    <td><small>${info.status}</small></td>
                `;
                tbody.appendChild(tr);
            }
        }

        // Atualiza Logs
        const logsArea = document.getElementById('logsArea');
        logsArea.innerHTML = data.logs.map(log => `<div>${log}</div>`).join('');

    } catch (error) {
        console.error("Erro ao buscar dados:", error);
    }
}

// Botão Salvar Configuração
document.getElementById('btnSave').addEventListener('click', async () => {
    const apiKey = document.getElementById('apiKey').value;
    const secretKey = document.getElementById('secretKey').value;
    const isLive = document.getElementById('liveModeToggle').checked;
    const riskMode = document.getElementById('riskMode').value;
    const telegramToken = document.getElementById('telegramToken').value;
    const telegramChatId = document.getElementById('telegramChatId').value;
    
    // Pega todas as checkboxes marcadas
    const selectedOptions = Array.from(document.querySelectorAll('.pair-checkbox:checked')).map(cb => cb.value);

    if (!apiKey || !secretKey) {
        alert("Por favor, preencha as chaves da API.");
        return;
    }

    if (selectedOptions.length === 0) {
        alert("Selecione pelo menos uma moeda.");
        return;
    }

    await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            api_key: apiKey,
            secret_key: secretKey,
            pairs: selectedOptions,
            is_live: isLive,
            risk_mode: riskMode,
            telegram_token: telegramToken,
            telegram_chat_id: telegramChatId
        })
    });

    alert("Configuração Salva!");
});

// Botão Ligar/Desligar
document.getElementById('btnToggle').addEventListener('click', async () => {
    const newState = !isRunning;
    
    await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ running: newState })
    });

    // Atualiza imediatamente
    updateDashboard();
});

// Função para carregar configuração salva ao abrir a página
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();

        if (data.api_key) document.getElementById('apiKey').value = data.api_key;
        if (data.secret_key) document.getElementById('secretKey').value = data.secret_key;
        if (data.is_live !== undefined) document.getElementById('liveModeToggle').checked = data.is_live;
        if (data.risk_mode) document.getElementById('riskMode').value = data.risk_mode;
        if (data.telegram_token) document.getElementById('telegramToken').value = data.telegram_token;
        if (data.telegram_chat_id) document.getElementById('telegramChatId').value = data.telegram_chat_id;
        
        if (data.pairs && data.pairs.length > 0) {
            // Desmarca todas primeiro
            document.querySelectorAll('.pair-checkbox').forEach(cb => cb.checked = false);
            // Marca as salvas
            data.pairs.forEach(pair => {
                const cb = document.querySelector(`.pair-checkbox[value="${pair}"]`);
                if (cb) cb.checked = true;
            });
        }
    } catch (error) {
        console.error("Erro ao carregar configuração:", error);
    }
}

// Função auxiliar para mostrar Toast
function showToast(message, type) {
    const toastEl = document.getElementById('liveToast');
    const toastBody = document.getElementById('toastBody');
    const toastHeader = toastEl.querySelector('.toast-header');
    
    toastBody.innerText = message;
    
    if (type === 'success') {
        toastHeader.className = 'toast-header bg-success text-white';
    } else if (type === 'info') {
        toastHeader.className = 'toast-header bg-info text-dark';
    } else {
        toastHeader.className = 'toast-header bg-secondary text-white';
    }

    const toast = new bootstrap.Toast(toastEl);
    toast.show();
}

// Atualiza a cada 2 segundos
setInterval(updateDashboard, 2000);
updateDashboard();
loadConfig();
