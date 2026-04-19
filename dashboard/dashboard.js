/**
 * dashboard.js — Bloomberg Terminal Live Data Engine
 * Fetches from api_server.py (Flask) and renders all panels
 */

const API = 'http://localhost:5001';
let currentMode = 'equity';
let refreshTimer = null;

// ═══════════════════════════════════════
// INIT
// ═══════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  initTabs();
  refreshAll();
  setInterval(refreshAll, 30000);  // Auto-refresh every 30s
  setInterval(updateClock, 1000);
});

function refreshAll() {
  fetchMarketStatus();
  fetchSignals();
  fetchNews(); // Runs in parallel
  fetchPositions();
  fetchHeatmap();
  fetchRisk();
  fetchML();
  fetchAltMode();
  fetchTicker();
}

// ═══════════════════════════════════════
// CLOCK + MARKET STATUS
// ═══════════════════════════════════════
function startClock() { updateClock(); }

function updateClock() {
  const now = new Date();
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
  document.getElementById('clock').textContent = ist.toTimeString().slice(0, 8);

  const h = ist.getHours(), m = ist.getMinutes();
  const isWeekday = ist.getDay() >= 1 && ist.getDay() <= 5;
  const isOpen = isWeekday && (h > 9 || (h === 9 && m >= 15)) && (h < 15 || (h === 15 && m <= 30));

  const el = document.getElementById('market-status');
  el.textContent = isOpen ? '● LIVE' : '● CLOSED';
  el.className = 'market-status ' + (isOpen ? 'open' : 'closed');
}

async function fetchMarketStatus() {
  try {
    const d = await get('/market');
    document.getElementById('nifty-val').textContent = fmt(d.nifty_ltp, 0);
    document.getElementById('nifty-chg').textContent = (d.nifty_change >= 0 ? '+' : '') + d.nifty_change.toFixed(2) + '%';
    document.getElementById('nifty-chg').className = 'idx-chg ' + (d.nifty_change >= 0 ? 'pos' : 'neg');
    document.getElementById('vix-val').textContent = d.vix?.toFixed(1) || '—';
    document.getElementById('vix-state').textContent = d.vix_state || '—';
    document.getElementById('vix-state').className = 'idx-chg ' + (d.vix < 15 ? 'pos' : d.vix > 20 ? 'neg' : '');

    const badge = document.getElementById('market-state-badge');
    badge.textContent = d.market_state || 'NEUTRAL';
    badge.className = 'vix-gauge ' + (['BULL','RECOVERY'].includes(d.market_state) ? 'bull' : ['BEAR','CRASH'].includes(d.market_state) ? 'bear' : 'neutral');
  } catch(e) {
    // API not running — use demo data
    demoMarket();
  }
}

// ═══════════════════════════════════════
// SIGNALS
// ═══════════════════════════════════════
async function fetchSignals() {
  const container = document.getElementById('signal-list');
  const sigCount  = document.getElementById('sig-count');

  // Intraday mode: fetch from /intraday endpoint
  if (currentMode === 'intraday') {
    sigCount.textContent = 'Scanning 5m...';
    container.innerHTML = '<div class="loading-pulse">Running VWAP + ORB + Supertrend scan...</div>';
    try {
      const data = await get('/intraday');
      const sigs = data.signals || [];
      const mkt = data.market_status || {};
      sigCount.textContent = sigs.length + ' signal' + (sigs.length !== 1 ? 's' : '') + ' | ' + (mkt.session || '');

      // Update sentiment bar with average score
      if (sigs.length) {
        const avgScore = sigs.reduce((a, s) => a + (s.overall_score || 50), 0) / sigs.length;
        document.getElementById('fg-fill').style.width = avgScore + '%';
        document.getElementById('fg-needle').style.left = avgScore + '%';
      }

      if (!sigs.length) {
        container.innerHTML = '<div class="empty-state">No intraday signals — ' + (mkt.session === 'ACTIVE' ? 'scanning every 5 min' : 'market ' + (mkt.session || 'closed').toLowerCase()) + '</div>';
      } else {
        container.innerHTML = '';
        sigs.forEach(sig => container.appendChild(renderSignalCard(sig)));
      }
    } catch(e) {
      container.innerHTML = '';
      demoIntraday().forEach(sig => container.appendChild(renderSignalCard(sig)));
      sigCount.textContent = '2 signals (demo)';
    }
    return;
  }

  // Crypto mode: show crypto signals in signal panel


  // Options mode: show options analysis in signal panel
  if (currentMode === 'options') {
    sigCount.textContent = 'NSE Options';
    container.innerHTML = '<div class="loading-pulse">Fetching options chain...</div>';
    try {
      const data = await get('/options');
      container.innerHTML = `
        <div class="signal-card ${data.signal === 'BULLISH' ? 'buy' : data.signal === 'BEARISH' ? 'sell' : ''}">
          <div class="sig-header">
            <span class="sig-symbol">NIFTY</span>
            <span class="sig-type ${data.signal === 'BULLISH' ? 'buy' : 'sell'}">${data.signal}</span>
            <span class="sig-conviction ${data.pcr_state?.toLowerCase() || 'neutral'}">${data.pcr_state || ''}</span>
          </div>
          <div class="score-bars">
            ${scoreBar('PCR', Math.min(100, (data.pcr||1) * 50), 'fill-tech')}
          </div>
          <div class="sig-price-row" style="flex-wrap:wrap; gap:6px;">
            <span>Max Pain: ₹${fmt(data.max_pain, 0)}</span>
            <span class="sig-target">Support: ₹${fmt(data.support_from_oi, 0)}</span>
            <span class="sig-sl">Resistance: ₹${fmt(data.resistance_from_oi, 0)}</span>
          </div>
          <div class="sig-strategy">PCR: ${data.pcr} | Put OI vs Call OI analysis</div>
        </div>
      `;
      sigCount.textContent = 'NIFTY Options';
    } catch(e) {
      container.innerHTML = `<div class="signal-card buy">
        <div class="sig-header"><span class="sig-symbol">NIFTY</span>
        <span class="sig-type buy">BULLISH</span></div>
        <div class="sig-price-row"><span>Max Pain: ₹24,050</span>
        <span class="sig-target">PCR: 1.24 (Bullish)</span></div>
        <div class="sig-strategy">Demo data — connect NSE API for live options</div>
      </div>`;
    }
    return;
  }

  // EQUITY / FOREX mode: normal signals
  try {
    const signals = await get('/signals?mode=' + currentMode);
    sigCount.textContent = signals.length + ' signal' + (signals.length !== 1 ? 's' : '');

    if (!signals.length) {
      container.innerHTML = '<div class="empty-state">No signals — market scanning every 5 min</div>';
      return;
    }

    // Update fear/greed needle
    const avgScore = signals.reduce((a, s) => a + (s.overall_score || s.confidence || 50), 0) / signals.length;
    document.getElementById('fg-fill').style.width  = avgScore + '%';
    document.getElementById('fg-needle').style.left = avgScore + '%';

    container.innerHTML = '';
    signals.forEach(sig => container.appendChild(renderSignalCard(sig)));
  } catch(e) {
    container.innerHTML = '';
    demoSignals().forEach(sig => container.appendChild(renderSignalCard(sig)));
    sigCount.textContent = '3 signals (demo)';
  }
}


function renderSignalCard(sig) {
  const isBuy = ['BUY', 'BUY_CALL'].includes(sig.signal_type);
  const typeClass = isBuy ? 'buy' : 'sell';
  const conviction = (sig.conviction || 'MEDIUM').toLowerCase();
  const score = sig.overall_score || sig.confidence || 50;

  const card = document.createElement('div');
  card.className = `signal-card ${typeClass} ${conviction === 'high' ? 'high-conviction' : ''}`;
  card.onclick = () => showSignalModal(sig);

  const techScore = sig.technical_score || sig.confidence || 50;
  const mlScore = sig.ml_score || 0;
  const newsScore = sig.sentiment_score || 0;
  const pattScore = sig.pattern_score || 0;
  const fundScore = sig.fundamental_score || 0;

  const curr = currentMode === 'crypto' || currentMode === 'forex' ? '$' : '₹';

  card.innerHTML = `
    <div class="sig-header">
      <span class="sig-symbol">${sig.symbol}</span>
      <span class="sig-type ${typeClass}">${sig.signal_type}</span>
      <span class="sig-conviction ${conviction}">${conviction.toUpperCase()}</span>
      <span class="sig-score">${score.toFixed(0)}/100</span>
    </div>
    <div class="score-bars">
      ${techScore ? scoreBar('TECH', techScore, 'fill-tech') : ''}
      ${mlScore   ? scoreBar('ML', mlScore, 'fill-ml') : ''}
      ${newsScore ? scoreBar('NEWS', newsScore, 'fill-news') : ''}
      ${pattScore ? scoreBar('PATTERN', pattScore, 'fill-patt') : ''}
      ${fundScore ? scoreBar('FUND', fundScore, 'fill-fund') : ''}
    </div>
    <div class="sig-price-row">
      <span class="sig-entry">Entry: ${curr}${fmt(sig.entry)}</span>
      <span class="sig-target">▲ ${curr}${fmt(sig.target)}</span>
      <span class="sig-sl">▼ ${curr}${fmt(sig.stop_loss)}</span>
      <span class="sig-rr">1:${(sig.risk_reward||0).toFixed(1)}</span>
    </div>
    <div class="sig-strategy">${sig.strategy || ''} ${sig.pattern ? '| ' + sig.pattern.replace(/_/g,' ') : ''}</div>
  `;
  return card;
}

function scoreBar(label, score, cls) {
  return `
    <div class="score-row">
      <span class="score-label">${label}</span>
      <div class="score-track"><div class="score-fill ${cls}" style="width:${score}%"></div></div>
      <span class="score-num">${score.toFixed(0)}%</span>
    </div>`;
}

// ═══════════════════════════════════════
// NEWS
// ═══════════════════════════════════════
async function fetchNews() {
  const container = document.getElementById('news-feed');
  try {
    const news = await get('/news');
    const articles = news.articles || [];
    document.getElementById('news-count').textContent = articles.length + ' articles';

    // Political alerts
    const polAlerts = news.political_alerts || [];
    if (polAlerts.length) {
      const strip = document.getElementById('political-strip');
      strip.style.display = 'flex';
      document.getElementById('pol-text').textContent = '⚠️ ' + polAlerts[0].title?.slice(0, 100);
    }

    container.innerHTML = '';
    articles.slice(0, 30).forEach(a => {
      const item = document.createElement('div');
      const sent = a.sentiment || 'neutral';
      item.className = 'news-item ' + sent;
      item.innerHTML = `
        <div class="news-headline">${a.title}</div>
        <div class="news-meta">
          <span class="news-source">${a.source || ''}</span>
          <span class="news-tag ${sent}">${sent.toUpperCase()}</span>
          ${a.symbols?.length ? `<span class="news-symbol">${a.symbols.join(' ')}</span>` : ''}
        </div>
      `;
      container.appendChild(item);
    });
  } catch(e) {
    container.innerHTML = demoNews();
  }
}

// ═══════════════════════════════════════
// HEATMAP
// ═══════════════════════════════════════
async function fetchHeatmap() {
  const container = document.getElementById('heatmap');
  try {
    const data = await get('/heatmap');
    container.innerHTML = '';
    data.stocks.forEach(s => {
      const cell = document.createElement('div');
      const chgClass = s.change >= 3 ? 'heat-up3' : s.change >= 1 ? 'heat-up2' : s.change >= 0 ? 'heat-up1' :
                       s.change >= -1 ? 'heat-dn1' : s.change >= -3 ? 'heat-dn2' : 'heat-dn3';
      cell.className = 'heat-cell ' + chgClass;
      cell.innerHTML = `
        <span class="heat-tick">${s.symbol.replace('.NS','')}</span>
        <span class="heat-pct">${s.change >= 0 ? '+' : ''}${s.change?.toFixed(1)}%</span>
      `;
      cell.title = `${s.symbol}: ${s.ltp} (${s.change >= 0 ? '+' : ''}${s.change?.toFixed(2)}%)`;
      container.appendChild(cell);
    });
  } catch(e) {
    container.innerHTML = demoHeatmap();
  }
}

// ═══════════════════════════════════════
// RISK
// ═══════════════════════════════════════
async function fetchRisk() {
  try {
    const d = await get('/risk');
    document.getElementById('risk-capital').textContent = 'Rs.' + fmt(d.capital, 0);
    const deployPct = Math.min(100, (d.deployed / d.capital * 100) || 0);
    document.getElementById('risk-bar').style.width = deployPct + '%';
    document.getElementById('risk-deployed').textContent = deployPct.toFixed(0) + '%';
    const pnl = d.day_pnl || 0;
    const pnlEl = document.getElementById('risk-pnl');
    pnlEl.textContent = (pnl >= 0 ? '+' : '') + 'Rs.' + fmt(Math.abs(pnl), 0);
    pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('risk-dd').textContent = (d.drawdown || 0).toFixed(2) + '%';
    document.getElementById('risk-wr').textContent = d.win_rate ? (d.win_rate * 100).toFixed(0) + '%' : '—';
    document.getElementById('risk-trades').textContent = (d.open_trades || 0) + ' / 2';
    document.getElementById('pos-count').textContent = (d.open_trades || 0) + ' positions';
  } catch(e) { /* demo fallback below */ }
}

// ═══════════════════════════════════════
// POSITIONS
// ═══════════════════════════════════════
async function fetchPositions() {
  const container = document.getElementById('positions-panel');
  try {
    const positions = await get('/positions');
    if (!positions.length) {
      container.innerHTML = '<div class="empty-state">No open positions</div>';
      return;
    }
    container.innerHTML = '';
    positions.forEach(p => {
      const row = document.createElement('div');
      row.className = 'position-row';
      const pnl = p.unrealized_pnl || 0;
      row.innerHTML = `
        <span class="pos-symbol">${p.symbol}</span>
        <span class="pos-type ${p.signal_type.toLowerCase()}">${p.signal_type}</span>
        <span class="pos-entry">@ Rs.${fmt(p.entry_price)}</span>
        <span class="pos-pnl ${pnl >= 0 ? 'pos' : 'neg'}">${pnl >= 0 ? '+' : ''}Rs.${fmt(Math.abs(pnl), 0)}</span>
      `;
      container.appendChild(row);
    });
  } catch(e) {
    container.innerHTML = '<div class="empty-state">No open positions</div>';
  }
}

// ═══════════════════════════════════════
// ML PANEL
// ═══════════════════════════════════════
async function fetchML() {
  const container = document.getElementById('ml-panel');
  try {
    const data = await get('/ml');
    container.innerHTML = '';
    (data.predictions || []).forEach(p => {
      const item = document.createElement('div');
      item.className = 'ml-item';
      const rfClass = p.rf_label?.toLowerCase() || 'hold';
      item.innerHTML = `
        <span class="ml-symbol">${p.symbol}</span>
        <span class="ml-rf ${rfClass}">${p.rf_label || 'HOLD'}</span>
        <span class="ml-lstm">${p.lstm_direction || '?'} ↑${((p.lstm_up_prob||0)*100).toFixed(0)}%</span>
        <div class="ml-bar-wrap"><div class="ml-bar-fill" style="width:${((p.score||0.5)*100).toFixed(0)}%"></div></div>
        <span class="ml-conf">${((p.score||0.5)*100).toFixed(0)}%</span>
      `;
      container.appendChild(item);
    });
  } catch(e) {
    container.innerHTML = demoML();
  }
}

// ═══════════════════════════════════════
// ALT MODE — Orders / Crypto / Options
// ═══════════════════════════════════════
async function fetchAltMode() {
  const container = document.getElementById('alt-panel');
  const icon  = document.getElementById('alt-icon');
  const title = document.getElementById('alt-title');
  const count = document.getElementById('alt-count');

  // Always reset count + loading immediately to avoid stale data
  if (count) count.textContent = '';
  container.innerHTML = '<div class="loading-pulse">Loading...</div>';

  if (currentMode === 'crypto') {
    icon.textContent  = '🪙';
    title.textContent = 'CRYPTO WATCH';
    try {
      const data = await get('/crypto');
      const coins = data.coins || [];
      container.innerHTML = '';
      coins.slice(0, 12).forEach(c => {
        const chg = c.change || 0;
        const row = document.createElement('div');
        row.className = 'coin-row';
        row.innerHTML = `
          <span class="coin-name">${c.symbol.replace('USDT','')}</span>
          <span class="coin-price">$${Number(c.price||0).toLocaleString('en-US',{maximumFractionDigits:2})}</span>
          <span class="coin-chg ${chg>=0?'pos':'neg'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
        `;
        container.appendChild(row);
      });
      if (count) count.textContent = coins.length + ' coins';
      if (!coins.length) container.innerHTML = '<div class="empty-state">No crypto data</div>';
    } catch(e) {
      container.innerHTML = demoCrypto();
      if (count) count.textContent = 'demo';
    }

  } else if (currentMode === 'options') {
    icon.textContent  = '⚙️';
    title.textContent = 'OPTIONS DATA';
    try {
      const data = await get('/options');
      container.innerHTML = renderOptions(data);
      if (count) count.textContent = 'NSE live';
    } catch(e) {
      container.innerHTML = demoOptions();
      if (count) count.textContent = 'demo';
    }

  } else if (currentMode === 'intraday') {
    icon.textContent  = '⚡';
    title.textContent = 'INTRADAY METRICS';
    try {
      const data = await get('/intraday');
      const stocks = data.stocks || {};
      const mkt = data.market_status || {};
      const entries = Object.entries(stocks);
      if (count) count.textContent = entries.length + ' stocks | ' + (mkt.session || '');
      if (!entries.length) {
        container.innerHTML = '<div class="empty-state">No intraday data</div>';
      } else {
        container.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.className = 'ticker-wrap';
        const scroll = document.createElement('div');
        scroll.className = 'ticker-scroll';
        
        // Build one set of rows
        let rowsHtml = '';
        entries.forEach(([sym, d]) => {
          const ind = d.indicators || {};
          const ml = d.ml_result || {};
          const stDir = ind.st_direction === 1 ? '▲' : ind.st_direction === -1 ? '▼' : '—';
          const stCls = ind.st_direction === 1 ? 'pos' : ind.st_direction === -1 ? 'neg' : '';
          const mlCls = ml.label === 'BUY' ? 'pos' : ml.label === 'SELL' ? 'neg' : '';
          rowsHtml += `
            <div class="intraday-metric-row">
              <span class="im-sym">${sym}</span>
              <span class="im-vwap">V:${ind.vwap ? ind.vwap.toFixed(0) : '—'}</span>
              <span class="im-st ${stCls}">${stDir}</span>
              <span class="im-rsi">R:${ind.rsi7 ? ind.rsi7.toFixed(0) : '—'}</span>
              <span class="im-ml ${mlCls}">${ml.label || '?'} ${ml.confidence ? (ml.confidence*100).toFixed(0)+'%' : ''}</span>
            </div>
          `;
        });
        
        // Insert two copies to make the infinite scroll seamless
        scroll.innerHTML = rowsHtml + rowsHtml;
        wrap.appendChild(scroll);
        container.appendChild(wrap);
      }
    } catch(e) {
      container.innerHTML = '<div class="empty-state">Intraday engine loading...</div>';
      if (count) count.textContent = 'demo';
    }

  } else {
    // EQUITY / FOREX -> show Order Book
    icon.textContent  = '🗂️';
    title.textContent = 'ORDER BOOK';
    await fetchOrders(container, count);
  }
}

async function fetchOrders(container, countEl) {
  try {
    // Use /orders/today — single clean endpoint
    const allOrders = await get('/orders/today');
    if (countEl) countEl.textContent = allOrders.length + ' today';

    if (!allOrders.length) {
      container.innerHTML = '<div class="empty-state">📦 No orders today — signals run at market open</div>';
      return;
    }
    container.innerHTML = '';
    allOrders.forEach(order => container.appendChild(renderOrderRow(order)));
  } catch(e) {
    container.innerHTML = '<div class="empty-state">📦 Connect bot to see orders</div>';
    if (countEl) countEl.textContent = '0 today';
  }
}

function renderOrderRow(order) {
  const row = document.createElement('div');
  const isBuy = ['BUY','BUY_CALL'].includes(order.signal_type);
  const pnl = order.unrealized_pnl || order.realized_pnl || 0;
  const pnlPct = order.current_pnl_pct || 0;
  const isOpen = ['PENDING','PLACED','FILLED'].includes(order.status);

  // Status color
  const statusColors = {
    PENDING: '#64748b', PLACED: '#f0a500', FILLED: '#1a8fff',
    CLOSED: '#00d084', CANCELLED: '#ff3a5c'
  };
  const statusColor = statusColors[order.status] || '#64748b';

  row.className = 'order-row';
  row.innerHTML = `
    <div class="order-header">
      <span class="order-sym">${order.symbol}</span>
      <span class="order-type ${isBuy ? 'buy' : 'sell'}">${order.signal_type}</span>
      ${order.news_headline ? '<span class="order-news-badge" title="' + order.news_headline + '">📰 NEWS</span>' : ''}
      <span class="order-status" style="color:${statusColor}">${order.status}</span>
    </div>
    <div class="order-prices">
      <span>E: Rs.${fmt(order.entry_price)}</span>
      <span class="pos">T: Rs.${fmt(order.target_price)}</span>
      <span class="neg">SL: Rs.${fmt(order.stop_loss)}</span>
      <span style="color:${pnl>=0?'var(--green)':'var(--red)'}">${pnl>=0?'+':''}Rs.${fmt(Math.abs(pnl),0)}
        <span style="font-size:9px">(${pnlPct>=0?'+':''}${pnlPct?.toFixed(1)}%)</span>
      </span>
    </div>
    <div class="order-meta">
      <span>${order.strategy || ''} • Score: ${(order.overall_score||order.confidence||0).toFixed(0)}</span>
      ${order.pattern ? '<span style="color:var(--accent)">' + order.pattern.replace(/_/g,' ') + '</span>' : ''}
      ${isOpen ? `<button class="order-close-btn" onclick="closeOrderManual(${order.id})">Close</button>` : ''}
    </div>
  `;
  return row;
}

async function closeOrderManual(orderId) {
  const price = prompt('Enter exit price:');
  if (!price) return;
  try {
    const res = await fetch(API + '/orders/' + orderId + '/close', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({exit_price: parseFloat(price), reason: 'MANUAL'})
    });
    const data = await res.json();
    alert('Order closed! P&L: Rs.' + (data.pnl||0).toFixed(0));
    fetchAltMode();
    fetchRisk();
  } catch(e) {
    alert('Error closing order');
  }
}

function renderOptions(data) {
  return `<div class="risk-panel">
    <div class="risk-row"><span>Max Pain</span><span class="risk-val">₹${fmt(data.max_pain, 0)}</span></div>
    <div class="risk-row"><span>PCR</span><span class="risk-val">${data.pcr} (${data.pcr_state})</span></div>
    <div class="risk-row"><span>Support OI</span><span class="risk-val">₹${fmt(data.support_from_oi, 0)}</span></div>
    <div class="risk-row"><span>Resistance OI</span><span class="risk-val">₹${fmt(data.resistance_from_oi, 0)}</span></div>
    <div class="risk-row"><span>Signal</span><span class="risk-val" style="color:${data.signal==='BULLISH'?'var(--green)':'var(--red)'}">${data.signal}</span></div>
  </div>`;
}

// ═══════════════════════════════════════
// TICKER
// ═══════════════════════════════════════
async function fetchTicker() {
  try {
    const data = await get('/heatmap');
    const stocks = data.stocks || [];
    const html = stocks.map(s => `
      <div class="tick-item">
        <span class="tick-sym">${s.symbol.replace('.NS','')}</span>
        <span class="tick-price">₹${fmt(s.ltp)}</span>
        <span class="tick-chg ${s.change >= 0 ? 'pos' : 'neg'}">${s.change >= 0 ? '▲' : '▼'}${Math.abs(s.change).toFixed(2)}%</span>
      </div>
    `).join('');
    // Duplicate for infinite scroll
    document.getElementById('ticker-scroll').innerHTML = html + html;
  } catch(e) { /* silent fail */ }
}

// ═══════════════════════════════════════
// MODAL
// ═══════════════════════════════════════
function showSignalModal(sig) {
  const content = document.getElementById('modal-content');
  const isBuy = ['BUY', 'BUY_CALL'].includes(sig.signal_type);
  content.innerHTML = `
    <h2 style="color:${isBuy ? 'var(--green)' : 'var(--red)'}; font-family:var(--mono); margin-bottom:12px;">
      ${sig.signal_type} — ${sig.symbol}
    </h2>
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size:12px;">
      <div><div style="color:var(--text3); font-size:10px;">ENTRY</div><div style="font-family:var(--mono); font-size:18px; font-weight:700;">₹${fmt(sig.entry)}</div></div>
      <div><div style="color:var(--text3); font-size:10px;">TARGET</div><div style="font-family:var(--mono); font-size:18px; color:var(--green);">₹${fmt(sig.target)}</div></div>
      <div><div style="color:var(--text3); font-size:10px;">STOP LOSS</div><div style="font-family:var(--mono); font-size:18px; color:var(--red);">₹${fmt(sig.stop_loss)}</div></div>
      <div><div style="color:var(--text3); font-size:10px;">RISK:REWARD</div><div style="font-family:var(--mono); font-size:18px; color:var(--accent);">1:${(sig.risk_reward||0).toFixed(1)}</div></div>
    </div>
    <div style="margin:12px 0; padding:10px; background:var(--bg3); border-radius:6px; font-size:11px; line-height:1.6;">
      ${sig.reason || ''}
    </div>
    ${sig.news_headline ? `<div style="font-size:10px; color:var(--text3); font-style:italic; padding:6px 0; border-top:1px solid var(--border);">📰 "${sig.news_headline}"</div>` : ''}
    <div style="font-size:10px; color:var(--text3); margin-top:10px;">
      ${sig.quantity ? `Qty: ${sig.quantity} shares | Investment: ₹${fmt(sig.investment, 0)} | Risk: ₹${fmt(sig.risk_amount, 0)}` : ''}
    </div>
    <div style="margin-top:12px; padding:6px 10px; background:rgba(255,214,10,.1); border-radius:6px; font-size:10px; color:var(--yellow);">
      ⚠️ This is a ${sig.paper_trade !== false ? 'PAPER TRADE signal' : 'LIVE TRADE signal'}. Always verify before placing an order.
    </div>
  `;
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

// ═══════════════════════════════════════
// TABS
// ═══════════════════════════════════════
function initTabs() {
  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;

      // Immediately reset both panels to loading so there's no stale flash
      document.getElementById('signal-list').innerHTML = '<div class="loading-pulse">Switching mode...</div>';
      document.getElementById('sig-count').textContent = '';
      document.getElementById('alt-panel').innerHTML  = '<div class="loading-pulse">Loading...</div>';
      document.getElementById('alt-count').textContent = '';

      // Then fetch fresh data
      fetchSignals();
      fetchAltMode();
    });
  });
}

// ═══════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════
async function get(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(res.status);
  return res.json();
}

function fmt(n, dec = 2) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

// ═══════════════════════════════════════
// DEMO DATA (when API offline)
// ═══════════════════════════════════════
function demoMarket() {
  document.getElementById('nifty-val').textContent = '24,123';
  document.getElementById('nifty-chg').textContent = '+0.83%';
  document.getElementById('nifty-chg').className = 'idx-chg pos';
  document.getElementById('vix-val').textContent = '13.2';
  document.getElementById('vix-state').textContent = 'CALM';
  document.getElementById('market-state-badge').textContent = 'BULL';
  document.getElementById('market-state-badge').className = 'vix-gauge bull';
}

function demoSignals() {
  return [
    { symbol:'INFY', signal_type:'BUY', mode:'EQUITY', strategy:'BREAKOUT', conviction:'HIGH',
      overall_score:88, technical_score:82, ml_score:88, sentiment_score:84, pattern_score:90, fundamental_score:72,
      entry:1319, target:1369, stop_loss:1294, risk_reward:2.0, risk_pct:1.9, return_pct:3.8,
      quantity:3, investment:3957, risk_amount:75, paper_trade:true,
      reason:'Bullish breakout above Rs.1,314 resistance with 2.1x volume surge',
      pattern:'BULL_FLAG', news_headline:'Infosys wins $500M US contract', rf_label:'BUY', lstm_direction:'UP' },
    { symbol:'HDFCBANK', signal_type:'BUY', mode:'EQUITY', strategy:'SR_BOUNCE', conviction:'MEDIUM',
      overall_score:74, technical_score:70, ml_score:68, sentiment_score:60, pattern_score:75, fundamental_score:65,
      entry:795, target:824, stop_loss:781, risk_reward:2.0, risk_pct:1.8, return_pct:3.6,
      quantity:6, investment:4773, risk_amount:86, paper_trade:true,
      reason:'Support bounce at Rs.793 in SIDEWAYS market | RSI 46',
      pattern:'HAMMER', rf_label:'BUY', lstm_direction:'UP' },
    { symbol:'ITC', signal_type:'BUY', mode:'EQUITY', strategy:'RSI_REVERSAL', conviction:'MEDIUM',
      overall_score:70, technical_score:68, sentiment_score:52,
      entry:303, target:314, stop_loss:298, risk_reward:2.0, risk_pct:1.7, return_pct:3.4,
      quantity:16, investment:4854, risk_amount:81, paper_trade:true,
      reason:'RSI 51 from oversold zone | Support hold at Rs.303' },
  ];
}

function demoNews() {
  const items = [
    { sentiment:'positive', title:'Infosys wins $500M digital transformation deal from US bank', source:'ET Markets', symbols:['INFY'] },
    { sentiment:'negative', title:'Adani Group stocks slip after OCCRP report surfaces', source:'LiveMint', symbols:['ADANIENT'] },
    { sentiment:'positive', title:'HDFC Bank Q4 results beat estimates; NIM improves to 3.8%', source:'MoneyControl', symbols:['HDFCBANK'] },
    { sentiment:'neutral', title:'RBI holds repo rate steady at 6.5%, policy remains accommodative', source:'Business Standard', symbols:[] },
    { sentiment:'positive', title:'Reliance Q4 profit up 18% YoY, Jio adds 8M subscribers', source:'ET Markets', symbols:['RELIANCE'] },
    { sentiment:'negative', title:'Global tech selloff drags IT stocks lower', source:'Financial Express', symbols:['TCS','WIPRO'] },
  ];
  return items.map(a => `
    <div class="news-item ${a.sentiment}">
      <div class="news-headline">${a.title}</div>
      <div class="news-meta">
        <span class="news-source">${a.source}</span>
        <span class="news-tag ${a.sentiment}">${a.sentiment.toUpperCase()}</span>
        ${a.symbols.length ? `<span class="news-symbol">${a.symbols.join(' ')}</span>` : ''}
      </div>
    </div>
  `).join('');
}

function demoHeatmap() {
  const stocks = [
    ['RELIANCE',1.2],['TCS',-0.4],['INFY',2.1],['HDFCBANK',0.3],['ICICIBANK',-1.1],
    ['SBIN',0.7],['ITC',1.5],['WIPRO',-0.2],['AXISBANK',0.9],['LT',1.8],
  ];
  return stocks.map(([sym, chg]) => {
    const cls = chg >= 2?'heat-up3':chg>=0.5?'heat-up2':chg>=0?'heat-up1':chg>=-0.5?'heat-dn1':chg>=-2?'heat-dn2':'heat-dn3';
    return `<div class="heat-cell ${cls}"><span class="heat-tick">${sym.slice(0,5)}</span><span class="heat-pct">${chg>=0?'+':''}${chg.toFixed(1)}%</span></div>`;
  }).join('');
}

function demoML() {
  const data = [
    {symbol:'INFY', rf:'BUY', lstm:'UP', conf:88},
    {symbol:'TCS', rf:'HOLD', lstm:'UP', conf:64},
    {symbol:'SBIN', rf:'SELL', lstm:'DOWN', conf:71},
    {symbol:'ITC', rf:'BUY', lstm:'FLAT', conf:62},
    {symbol:'LT', rf:'BUY', lstm:'UP', conf:79},
  ];
  return data.map(d => `
    <div class="ml-item">
      <span class="ml-symbol">${d.symbol}</span>
      <span class="ml-rf ${d.rf.toLowerCase()}">${d.rf}</span>
      <span class="ml-lstm">${d.lstm}</span>
      <div class="ml-bar-wrap"><div class="ml-bar-fill" style="width:${d.conf}%"></div></div>
      <span class="ml-conf">${d.conf}%</span>
    </div>
  `).join('');
}

function demoCrypto() {
  return [
    ['BTC',62840,1.2],['ETH',3480,0.8],['BNB',582,-0.3],['SOL',152,3.1],['XRP',0.52,-1.2],
  ].map(([c,p,chg]) => `
    <div class="coin-row">
      <span class="coin-name">${c}</span>
      <span class="coin-price">$${p.toLocaleString()}</span>
      <span class="coin-chg ${chg>=0?'pos':'neg'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
    </div>
  `).join('');
}

function demoOptions() {
  return `<div class="risk-panel">
    <div class="risk-row"><span>Max Pain</span><span class="risk-val">₹24,050</span></div>
    <div class="risk-row"><span>PCR</span><span class="risk-val">1.24 (BULLISH)</span></div>
    <div class="risk-row"><span>Support OI</span><span class="risk-val">₹23,900</span></div>
    <div class="risk-row"><span>Resistance OI</span><span class="risk-val">₹24,200</span></div>
    <div class="risk-row"><span>Signal</span><span class="risk-val" style="color:var(--green)">BULLISH</span></div>
  </div>`;
}

function demoIntraday() {
  return [
    { symbol:'RELIANCE', signal_type:'BUY', mode:'INTRADAY', strategy:'VWAP_BAND', conviction:'HIGH',
      overall_score:82, technical_score:82, ml_score:78, sentiment_score:50,
      entry:1343.20, target:1356.63, stop_loss:1336.49, risk_reward:2.0, risk_pct:0.5, return_pct:1.0,
      quantity:4, investment:5372, risk_amount:27, paper_trade:true,
      reason:'VWAP -2sig reversal | RSI(7) 32 | Vol 1.8x',
      vwap:1340.50, orb_high:1348, orb_low:1335, rsi:32, vol_ratio:1.8 },
    { symbol:'TCS', signal_type:'BUY', mode:'INTRADAY', strategy:'ORB', conviction:'MEDIUM',
      overall_score:73, technical_score:73, ml_score:65, sentiment_score:50,
      entry:3542.50, target:3577.93, stop_loss:3524.79, risk_reward:2.0, risk_pct:0.5, return_pct:1.0,
      quantity:1, investment:3542, risk_amount:18, paper_trade:true,
      reason:'ORB breakout above 3540 | Vol 2.1x | Supertrend UP',
      vwap:3535, orb_high:3540, orb_low:3518, rsi:58, vol_ratio:2.1 },
  ];
}

function demoSectors() {
  const sectors = [
    ['IT','▲ 1.2%','pos'],['Banking','▼ 0.4%','neg'],['FMCG','▲ 0.8%','pos'],
    ['Auto','▲ 1.5%','pos'],['Pharma','▼ 0.2%','neg'],['Energy','▲ 0.3%','pos'],
  ];
  return sectors.map(([s,c,cls])=> `
    <div class="coin-row">
      <span class="coin-name">${s}</span>
      <span class="coin-chg ${cls}">${c}</span>
    </div>
  `).join('');
}

// ═══════════════════════════════════════
// AI DESK WIDGET
// ═══════════════════════════════════════
function toggleAIChat() {
  const win = document.getElementById('ai-chat-window');
  win.classList.toggle('open');
  if (win.classList.contains('open')) {
    document.getElementById('ai-input').focus();
  }
}

function handleAIKey(e) {
  if (e.key === 'Enter') {
    sendAIChat();
  }
}

async function sendAIChat() {
  const input = document.getElementById('ai-input');
  const text = input.value.trim();
  if (!text) return;

  appendAIMessage(text, 'user', 'YOU', '', '');
  input.value = '';

  const typing = document.getElementById('ai-typing');
  const chatBody = document.getElementById('ai-chat-body');
  typing.classList.add('active');
  chatBody.scrollTop = chatBody.scrollHeight;

  let data;
  try {
    const res = await fetch(API + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: text})
    });
    data = await res.json();
  } catch (err) {
    typing.classList.remove('active');
    appendAIMessage('Connection error: Is api_server.py running?', 'bot', 'HQ', '', '#ff3a5c');
    return;
  }

  typing.classList.remove('active');

  if (data.error) {
    appendAIMessage('⚠️ ' + data.error, 'bot', 'HQ', '', '#ff3a5c');
    return;
  }

  // Build ordered list of personas to render
  const personas = [
    {
      obj: data.technical_analyst,
      avatar: 'TA',
      color: '#1a8fff'
    },
    {
      obj: data.risk_manager,
      avatar: 'RM',
      color: '#f0a500'
    },
    {
      obj: data.head_quant,
      avatar: 'HQ',
      color: (data.head_quant && data.head_quant.verdict === 'TRADE') ? '#00d084' : '#ff3a5c',
      isVerdict: true
    }
  ];

  // Render personas one by one with typing animation between each
  function renderNext(index) {
    if (index >= personas.length) return;
    const p = personas[index];
    if (!p.obj) { renderNext(index + 1); return; }

    // Show typing dots
    typing.classList.add('active');
    chatBody.scrollTop = chatBody.scrollHeight;

    setTimeout(() => {
      typing.classList.remove('active');

      let label = p.obj.name || p.avatar;
      if (p.isVerdict && p.obj.verdict) {
        label += p.obj.verdict === 'TRADE' ? ' · ✅ TRADE' : ' · ❌ NO TRADE';
      }
      appendAIMessage(p.obj.opinion, 'bot', p.avatar, label, p.color);

      // Wait before showing next persona
      setTimeout(() => renderNext(index + 1), 400);
    }, 900);
  }

  renderNext(0);
}

function appendAIMessage(text, sender, avatarLabel, nameLabel, avatarColor) {
  const chatBody = document.getElementById('ai-chat-body');
  const msg = document.createElement('div');
  msg.className = `ai-msg ${sender}`;

  const avatar = document.createElement('div');
  avatar.className = 'ai-msg-avatar';
  avatar.textContent = avatarLabel || (sender === 'user' ? 'YOU' : 'HQ');
  if (avatarColor) avatar.style.background = avatarColor;

  const right = document.createElement('div');
  right.style.display = 'flex';
  right.style.flexDirection = 'column';
  right.style.gap = '2px';

  if (nameLabel && sender === 'bot') {
    const name = document.createElement('div');
    name.style.cssText = 'font-size:9px;color:#64748b;font-family:var(--mono);letter-spacing:1px;';
    name.textContent = nameLabel;
    right.appendChild(name);
  }

  const bubble = document.createElement('div');
  bubble.className = 'ai-msg-text';
  bubble.textContent = text;
  right.appendChild(bubble);

  msg.appendChild(avatar);
  msg.appendChild(right);

  const typing = document.getElementById('ai-typing');
  chatBody.insertBefore(msg, typing);
  chatBody.scrollTop = chatBody.scrollHeight;
}
