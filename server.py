import threading
import time
import ccxt
import pandas as pd
import pandas_ta as ta
import json
import os
import requests
import openai
import telebot
from duckduckgo_search import DDGS
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from datetime import datetime

# Carrega variáveis de ambiente do .env
load_dotenv()

app = Flask(__name__)

CONFIG_FILE = 'config.json'

def sanitize_value(value):
    if value is None:
        return ""
    return str(value).strip()

def load_config_from_file():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config_to_file():
    config = {
        "api_key": bot_state["api_key"],
        "secret_key": bot_state["secret_key"],
        "pairs": bot_state["pairs"],
        "is_live": bot_state["is_live"],
        "risk_mode": bot_state.get("risk_mode", "conservative"),
        "telegram_token": bot_state.get("telegram_token", ""),
        "telegram_chat_id": bot_state.get("telegram_chat_id", "")
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        print(f"Erro ao salvar config: {e}")

TRADES_FILE = 'trades.json'

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trade(trade):
    trades = load_trades()
    trades.append(trade)
    try:
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Erro ao salvar trade: {e}")

    trade_volume = trade.get("amount", 0)
    trade_value = trade.get("buy_price", 0) * trade_volume
    bot_state["total_traded_value"] = bot_state.get("total_traded_value", 0.0) + abs(trade_value)
    bot_state["trade_volume_by_symbol"].setdefault(trade["symbol"], 0.0)
    bot_state["trade_volume_by_symbol"][trade["symbol"]] += trade_volume

ACTIVE_TRADES_FILE = 'active_trades.json'
TRADE_AMOUNT_USDT = 11.0  # Valor fixo em USDT por operação

def load_active_trades():
    if os.path.exists(ACTIVE_TRADES_FILE):
        try:
            with open(ACTIVE_TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_active_trades():
    try:
        with open(ACTIVE_TRADES_FILE, 'w') as f:
            json.dump(active_trades, f, indent=4)
    except Exception as e:
        print(f"Erro ao salvar trades ativos: {e}")

def get_profits():
    trades = load_trades()
    total = sum(t.get('profit_usdt', 0) for t in trades)
    
    today = datetime.now().strftime('%Y-%m-%d')
    daily = sum(t.get('profit_usdt', 0) for t in trades if t.get('timestamp', '').startswith(today))
    
    return total, daily

# --- ESTADO GLOBAL ---
saved_config = load_config_from_file()

# Prioridade: .env > config.json > vazio
env_api_key = sanitize_value(os.getenv("BINANCE_API_KEY"))
env_secret_key = sanitize_value(os.getenv("BINANCE_SECRET_KEY"))
env_telegram_token = sanitize_value(os.getenv("TELEGRAM_TOKEN"))
env_telegram_chat_id = sanitize_value(os.getenv("TELEGRAM_CHAT_ID"))
env_openai_key = sanitize_value(os.getenv("OPENAI_API_KEY"))

bot_state = {
    "running": False,
    "connected": False,
    "api_key": env_api_key if env_api_key else saved_config.get("api_key", ""),
    "secret_key": env_secret_key if env_secret_key else saved_config.get("secret_key", ""),
    "pairs": saved_config.get("pairs", []), 
    "is_live": saved_config.get("is_live", False),
    "risk_mode": saved_config.get("risk_mode", "conservative"), # conservative, moderate, aggressive
    "telegram_token": env_telegram_token if env_telegram_token else sanitize_value(saved_config.get("telegram_token", "")),
    "telegram_chat_id": env_telegram_chat_id if env_telegram_chat_id else sanitize_value(saved_config.get("telegram_chat_id", "")),
    "openai_key": env_openai_key,
    "balance": 0.0,
    "previous_balance": 0.0,
    "total_traded_value": 0.0,
    "trade_volume_by_symbol": {},
    "brl_rate": 5.0,
    "brl_rate_updated": 0,
    "logs": [],
    "notifications": [] # Fila de notificações para o frontend
}

def refresh_brl_rate(force=False):
    last = bot_state.get("brl_rate_updated", 0)
    if not force and time.time() - last < 300:
        return
    try:
        response = requests.get("https://economia.awesomeapi.com.br/json/last/USDT-BRL", timeout=5)
        data = response.json()
        rate = float(data.get("USDTBRL", {}).get("bid", bot_state.get("brl_rate", 5.0)))
        bot_state["brl_rate"] = rate
        bot_state["brl_rate_updated"] = time.time()
    except Exception as e:
        log(f"Erro ao atualizar cotação BRL: {e}")

refresh_brl_rate(force=True)

# Dados em tempo real das moedas
# Estrutura: { 'BTC/USDT': { 'price': 0, 'rsi': 0, 'status': 'Neutro', 'pnl': 0, 'action': '-' } }
market_data = {}

# Histórico de Trades e Estado
# Estrutura: { 'BTC/USDT': { 'status': 'BOUGHT', 'price': 50000 } }
active_trades = {} 

# --- FUNÇÕES AUXILIARES (INTERNET) ---

def get_fear_and_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5)
        data = r.json()
        item = data['data'][0]
        return f"{item['value_classification']} (Índice: {item['value']})"
    except:
        return "Indisponível"

def search_web_info(query):
    try:
        with DDGS() as ddgs:
            # Busca notícias recentes sobre o tema
            results = list(ddgs.text(f"crypto news {query}", region="br-pt", timelimit="d", max_results=3))
            if not results:
                return "Nenhuma notícia recente encontrada."
            
            summary = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
            return summary
    except Exception as e:
        return f"Erro na busca web: {e}"

# --- FUNÇÕES DO ROBÔ ---

def get_exchange():
    if not bot_state["api_key"] or not bot_state["secret_key"]:
        return None
    
    try:
        exchange = ccxt.binance({
            'apiKey': bot_state["api_key"],
            'secret': bot_state["secret_key"],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            }
        })
        
        if not bot_state["is_live"]:
            exchange.set_sandbox_mode(True) # TESTNET
            
        return exchange
    except Exception as e:
        log(f"Erro ao conectar na exchange: {e}")
        return None

def log(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    bot_state["logs"].insert(0, f"[{timestamp}] {message}")
    if len(bot_state["logs"]) > 50:
        bot_state["logs"].pop()

def send_telegram_message(message):
    token = bot_state.get("telegram_token")
    chat_id = bot_state.get("telegram_chat_id")
    
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=data)
        except Exception as e:
            log(f"Erro ao enviar Telegram: {e}")

def relatorio_ia_telegram():
    """Thread do 'Sócio Digital': Lê logs, resume com IA e envia no Telegram"""
    log("🧠 Sócio Digital (IA) iniciado em background.")
    while True:
        time.sleep(21600)  # Roda a cada 6 horas (21600 segundos)
        try:
            if not bot_state["openai_key"]:
                continue

            # Pega os últimos logs da memória
            recent_logs = "\n".join(bot_state["logs"][:50])
            
            if not recent_logs.strip():
                continue

            # Chama OpenAI (GPT-3.5-turbo)
            client = openai.OpenAI(api_key=bot_state["openai_key"])
            prompt = f"Resuma essas operações de trade num tom informal de um sócio para o Telegram. Use emojis. Diga o lucro/prejuízo e o saldo atual:\n\n{recent_logs}"
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            
            resumo = response.choices[0].message.content
            send_telegram_message(f"🧠 *Relatório do Sócio Digital*\n\n{resumo}")
            
        except Exception as e:
            log(f"Erro na Thread IA: {e}")

def telegram_polling():
    """Thread para responder mensagens no Telegram usando IA"""
    log("🤖 Chatbot Telegram iniciado.")
    
    if not bot_state["telegram_token"]:
        log("⚠️ Token do Telegram não configurado. Chatbot desativado.")
        return

    bot = telebot.TeleBot(bot_state["telegram_token"])

    @bot.message_handler(func=lambda message: True)
    def handle_message(message):
        # Verifica se é o dono do bot (segurança)
        if str(message.chat.id) != str(bot_state["telegram_chat_id"]):
            bot.reply_to(message, "⛔ Acesso negado.")
            return

        user_text = message.text
        
        if not bot_state["openai_key"]:
            bot.reply_to(message, "⚠️ Configure a chave da OpenAI para eu poder responder.")
            return

        # Notifica que está "digitando" (processando)
        bot.send_chat_action(message.chat.id, 'typing')

        try:
            # 1. Coleta dados básicos
            brl = bot_state.get("brl_rate", 5.0)
            investido_brl = bot_state.get("total_invested_usdt", 0.0) * brl
            atual_brl = bot_state.get("total_wallet_value_usdt", 0.0) * brl
            lucro_brl = atual_brl - investido_brl
            
            # 2. Verifica se precisa de busca na internet
            web_context = ""
            keywords_busca = ["previsão", "previsao", "tendencia", "noticia", "analise", "mercado", "bitcoin", "btc", "futuro", "subir", "cair"]
            if any(k in user_text.lower() for k in keywords_busca):
                bot.send_chat_action(message.chat.id, 'typing') # Renova status
                fng = get_fear_and_greed()
                news = search_web_info(user_text)
                web_context = f"""
                DADOS DA INTERNET (EM TEMPO REAL):
                - Fear & Greed Index: {fng}
                - Notícias/Buscas Recentes:
                {news}
                """

            # 3. Carrega histórico recente
            closed_trades = load_trades()
            recent_history = closed_trades[-15:] if closed_trades else []
            history_str = json.dumps(recent_history, indent=2)

            # 4. Monta o Prompt
            contexto = f"""
            Você é um Sócio Digital e Analista Sênior de Criptomoedas.
            Seu objetivo é dar conselhos estratégicos, analisar o mercado e explicar os resultados.
            
            DADOS FINANCEIROS (EM REAIS R$):
            - Total Investido: R$ {investido_brl:.2f}
            - Valor Atual: R$ {atual_brl:.2f}
            - Lucro/Prejuízo: R$ {lucro_brl:.2f}
            
            DADOS TÉCNICOS:
            - Saldo Livre: ${bot_state['balance']:.2f} USDT
            - Cotação Dólar: R$ {brl:.2f}
            - Moedas Monitoradas: {', '.join(bot_state['pairs'])}
            - Trades Ativos: {json.dumps(active_trades)}
            
            {web_context}
            
            HISTÓRICO RECENTE:
            {history_str}
            
            INSTRUÇÕES:
            - Use os dados da internet (se houver) para embasar suas previsões.
            - Se o usuário pedir previsão, cite o 'Fear & Greed Index' e notícias.
            - Seja realista, mas otimista. Use emojis.
            - Se houver prejuízo, explique tecnicamente e sugira melhorias.
            
            PERGUNTA DO USUÁRIO: {user_text}
            """

            client = openai.OpenAI(api_key=bot_state["openai_key"])
            response = client.chat.completions.create(
                model="gpt-3.5-turbo", # Pode alterar para gpt-4-turbo se tiver acesso
                messages=[{"role": "user", "content": contexto}]
            )
            
            resposta_ia = response.choices[0].message.content
            bot.reply_to(message, resposta_ia)
            
        except Exception as e:
            bot.reply_to(message, f"😵 Ocorreu um erro ao processar sua mensagem: {e}")

    # Loop infinito para garantir reconexão em caso de queda
    while True:
        try:
            # timeout e long_polling_timeout ajudam a evitar desconexões fantasmas
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            log(f"⚠️ Conexão Telegram instável. Reconectando em 5s... ({e})")
            time.sleep(5)

def process_data(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        
        ohlcv = exchange.fetch_ohlcv(symbol, '1m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Indicadores
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # Bollinger Bands (20, 2)
        bbands = ta.bbands(df['close'], length=20, std=2)
        
        lower_band = 0
        upper_band = 0
        
        if bbands is not None and not bbands.empty:
            # Pega as colunas dinamicamente (Lower, Mid, Upper)
            # O pandas_ta retorna algo como BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
            # Vamos pegar pela posição ou filtrar nomes
            cols = bbands.columns
            lower_col = [c for c in cols if c.startswith('BBL')][0]
            upper_col = [c for c in cols if c.startswith('BBU')][0]
            
            df = pd.concat([df, bbands], axis=1)
            lower_band = df[lower_col].iloc[-1]
            upper_band = df[upper_col].iloc[-1]

        current_rsi = df['rsi'].iloc[-1] if not df['rsi'].empty else 50
        
        return current_price, current_rsi, lower_band, upper_band
    except Exception as e:
        log(f"Erro ao processar {symbol}: {e}")
        return 0, 50, 0, 0

def bot_loop():
    log("Sistema iniciado. Aguardando configuração...")
    
    global active_trades
    active_trades = load_active_trades()
    
    while True:
        if bot_state["running"] and bot_state["pairs"]:
            refresh_brl_rate()
            exchange = get_exchange()
            if exchange:
                try:
                    # Atualiza Saldo
                    bot_state["previous_balance"] = bot_state["balance"]
                    balance = exchange.fetch_balance()
                    bot_state["balance"] = balance['total'].get('USDT', 0.0)
                    
                    if not bot_state["connected"]:
                        log(f"✅ Conexão com Binance OK! Saldo: ${bot_state['balance']:.2f}")
                    
                    bot_state["connected"] = True
                    
                    # Totais para cálculo de investimento
                    iter_invested_usdt = 0.0
                    iter_wallet_value_usdt = 0.0
                    
                    for symbol in bot_state["pairs"]:
                        price, rsi, lower_band, upper_band = process_data(exchange, symbol)
                        asset = symbol.split('/')[0]
                        coin_balance = balance['total'].get(asset, 0.0)
                        wallet_value = coin_balance * price
                        
                        # Inicializa dados se não existir
                        if symbol not in market_data:
                            market_data[symbol] = {}
                        
                        status = "Aguardando"
                        signal_color = "grey" # grey, green, red
                        action = "-"
                        pnl_str = "-"
                        
                        # Lógica de Trade
                        is_bought = False
                        buy_price = 0.0
                        
                        if symbol in active_trades and active_trades[symbol]['status'] == 'BOUGHT':
                            is_bought = True
                            buy_price = active_trades[symbol]['price']
                            
                            # Acumula totais
                            iter_invested_usdt += coin_balance * buy_price
                            iter_wallet_value_usdt += coin_balance * price

                        # --- ESTRATÉGIA DE ENTRADA (Double Confirmation) ---
                        # RSI < 30 E Preço < Banda Inferior
                        
                        risk_mode = bot_state.get("risk_mode", "conservative")
                        buy_signal = False
                        
                        if risk_mode == "conservative":
                            # Modo Prevenido: RSI < 30 E Preço < Banda Inferior
                            buy_signal = (rsi < 30) and (price < lower_band)
                        elif risk_mode == "moderate":
                            # Modo Moderado: RSI < 35 E Preço < Banda Inferior
                            buy_signal = (rsi < 35) and (price < lower_band)
                        elif risk_mode == "aggressive":
                            # Modo Audacioso: RSI < 40 E Preço < Banda Inferior (Mais sinais)
                            buy_signal = (rsi < 40) and (price < lower_band)
                        
                        if buy_signal and not is_bought:
                            # --- TRAVA DE SEGURANÇA DE SALDO (BAIXO CAPITAL) ---
                            if bot_state["balance"] < 12.0:
                                action = f"Ignorado: Saldo Baixo (${bot_state['balance']:.2f})"
                                # log(f"Sinal em {symbol} ignorado. Saldo insuficiente.")
                            else:
                                signal_color = "green"
                                status = "🟢 OPORTUNIDADE"
                                
                                amount_to_spend = TRADE_AMOUNT_USDT
                                amount_coin = amount_to_spend / price
                                
                                try:
                                    exchange.create_market_buy_order(symbol, amount_coin)
                                    active_trades[symbol] = {'status': 'BOUGHT', 'price': price}
                                    save_active_trades()
                                    action = "COMPRA (Double Conf.) 🟢"
                                    msg = f"🚀 COMPRA: {amount_coin:.5f} {symbol} (Total: ${amount_to_spend:.2f} USDT) | Preço Unitário: ${price:.2f}"
                                    log(msg)
                                    bot_state["notifications"].append({"type": "success", "msg": msg, "time": datetime.now().timestamp()})
                                    send_telegram_message(f"🟢 *COMPRA REALIZADA*\n\nMoeda: `{symbol}`\nQtd: `{amount_coin:.5f}`\nValor Gasto: `${amount_to_spend:.2f} USDT`\nPreço Unitário: `${price:.2f}`\nEstratégia: Double Confirmation")
                                    
                                    # Atualiza saldo localmente
                                    bot_state["balance"] -= amount_to_spend
                                except Exception as e:
                                    action = f"Erro Compra: {e}"
                                    log(f"Erro ao comprar {symbol}: {e}")

                        # --- ESTRATÉGIA DE SAÍDA (Gestão de Risco) ---
                        elif is_bought:
                            current_pnl_pct = ((price - buy_price) / buy_price) * 100
                            pnl_str = f"{current_pnl_pct:.2f}%"
                            
                            # Condições de Venda
                            take_profit = current_pnl_pct >= 2.0
                            stop_loss = current_pnl_pct <= -1.5
                            tech_exit = rsi > 70
                            
                            sell_reason = ""
                            if take_profit: sell_reason = "Take Profit (+2%)"
                            elif stop_loss: sell_reason = "Stop Loss (-1.5%)"
                            elif tech_exit: sell_reason = "RSI Esticado (>70)"
                            
                            if take_profit or stop_loss or tech_exit:
                                signal_color = "red"
                                status = f"🔴 VENDA: {sell_reason}"
                                
                                coin_balance = balance['total'].get(symbol.split('/')[0], 0.0)
                                if coin_balance * price > 10:
                                    exchange.create_market_sell_order(symbol, coin_balance)
                                    if symbol in active_trades:
                                        del active_trades[symbol]
                                    save_active_trades()
                                    
                                    # Calcula Lucro em USDT
                                    profit_usdt = (price - buy_price) * coin_balance
                                    
                                    # Salva Trade
                                    save_trade({
                                        'symbol': symbol,
                                        'type': 'SELL',
                                        'buy_price': buy_price,
                                        'sell_price': price,
                                        'amount': coin_balance,
                                        'profit_usdt': profit_usdt,
                                        'profit_pct': current_pnl_pct,
                                        'reason': sell_reason,
                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    })
                                    
                                    action = f"VENDA ({sell_reason}) 🔴"
                                    msg = f"💰 VENDA {symbol} | Lucro: ${profit_usdt:.2f} ({current_pnl_pct:.2f}%)"
                                    log(msg)
                                    bot_state["notifications"].append({"type": "info", "msg": msg, "time": datetime.now().timestamp()})
                                    send_telegram_message(f"🔴 *VENDA REALIZADA*\n\nMoeda: `{symbol}`\nLucro: `${profit_usdt:.2f}` ({current_pnl_pct:.2f}%)\nMotivo: {sell_reason}")
                                else:
                                    action = "Erro Venda (Saldo Baixo)"
                            else:
                                status = "Em Operação"
                                signal_color = "blue"

                        # Define Status da Carteira
                        wallet_status = "⚪ AGUARDANDO"
                        if is_bought:
                            wallet_status = "🔵 EM CARTEIRA"

                        # Atualiza dados para o Frontend
                        market_data[symbol] = {
                            'price': price,
                            'rsi': rsi,
                            'lower_band': lower_band,
                            'upper_band': upper_band,
                            'status': status,
                            'wallet_status': wallet_status,
                            'signal_color': signal_color,
                            'pnl': pnl_str,
                            'action': action,
                            'wallet_amount': coin_balance,
                            'wallet_value': wallet_value,
                            'wallet_value_brl': wallet_value * bot_state.get("brl_rate", 1.0)
                        }
                        
                        # Log periódico apenas para debug se necessário (opcional, para não poluir)
                        # log(f"Analisando {symbol}: RSI {rsi:.1f} | Preço {price:.2f} | BB_Inf {lower_band:.2f}")
                    
                    # Atualiza estado global com totais da iteração
                    bot_state["total_invested_usdt"] = iter_invested_usdt
                    bot_state["total_wallet_value_usdt"] = iter_wallet_value_usdt
                        
                except Exception as e:
                    bot_state["connected"] = False
                    log(f"Erro no loop principal: {e}")
            else:
                bot_state["connected"] = False
            
        time.sleep(10) # Loop a cada 10 segundos

# Inicia Thread do Robô
t = threading.Thread(target=bot_loop)
t.daemon = True
t.start()

# Inicia Thread do Sócio Digital (IA)
t_ia = threading.Thread(target=relatorio_ia_telegram)
t_ia.daemon = True
t_ia.start()

# Inicia Thread do Chatbot Telegram
t_chat = threading.Thread(target=telegram_polling)
t_chat.daemon = True
t_chat.start()

# --- ROTAS FLASK ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    total_profit, daily_profit = get_profits()
    
    # Pega notificações recentes (limpa as antigas da memória se quiser, ou o front filtra)
    # Vamos enviar todas e o front mostra só as novas
    
    brl_rate = bot_state.get("brl_rate", 0.0)
    return jsonify({
        'running': bot_state["running"],
        'connected': bot_state.get("connected", False),
        'balance': bot_state["balance"],
        'balance_brl': bot_state["balance"] * brl_rate,
        'previous_balance': bot_state.get("previous_balance", 0.0),
        'total_profit': total_profit,
        'daily_profit': daily_profit,
        'total_traded_value': bot_state.get("total_traded_value", 0.0),
        'total_traded_value_brl': bot_state.get("total_traded_value", 0.0) * brl_rate,
        'total_invested_usdt': bot_state.get("total_invested_usdt", 0.0),
        'total_invested_brl': bot_state.get("total_invested_usdt", 0.0) * brl_rate,
        'total_wallet_value_usdt': bot_state.get("total_wallet_value_usdt", 0.0),
        'total_wallet_value_brl': bot_state.get("total_wallet_value_usdt", 0.0) * brl_rate,
        'brl_rate': brl_rate,
        'market_data': market_data,
        'logs': bot_state["logs"],
        'notifications': bot_state["notifications"][-5:] # Envia as últimas 5
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        "api_key": bot_state["api_key"],
        "secret_key": bot_state["secret_key"],
        "pairs": bot_state["pairs"],
        "is_live": bot_state["is_live"],
        "risk_mode": bot_state.get("risk_mode", "conservative"),
        "telegram_token": bot_state.get("telegram_token", ""),
        "telegram_chat_id": bot_state.get("telegram_chat_id", "")
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    if 'api_key' in data: bot_state["api_key"] = data['api_key']
    if 'secret_key' in data: bot_state["secret_key"] = data['secret_key']
    if 'pairs' in data: bot_state["pairs"] = data['pairs']
    if 'is_live' in data: bot_state["is_live"] = data['is_live']
    if 'risk_mode' in data: bot_state["risk_mode"] = data['risk_mode']
    if 'telegram_token' in data: bot_state["telegram_token"] = sanitize_value(data['telegram_token'])
    if 'telegram_chat_id' in data: bot_state["telegram_chat_id"] = sanitize_value(data['telegram_chat_id'])
    
    # Salva no arquivo sempre que atualizar
    if 'api_key' in data or 'secret_key' in data or 'pairs' in data or 'is_live' in data or 'telegram_token' in data or 'risk_mode' in data:
        save_config_to_file()

    if 'running' in data: 
        bot_state["running"] = data['running']
        log("Estado do robô alterado para: " + ("LIGADO" if data['running'] else "DESLIGADO"))
    
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
