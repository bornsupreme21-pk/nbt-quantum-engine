import os
import json
import warnings
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import io
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

THEMATIC_MAP = {
    'HAL': 'Defense & Aerospace', 'BEL': 'Defense & Aerospace', 'BDL': 'Defense & Aerospace', 'MAZDOCK': 'Defense & Aerospace', 'COCHINSHIP': 'Defense & Aerospace', 'GRSE': 'Defense & Aerospace',
    'IRFC': 'Railways & Infra EPC', 'RVNL': 'Railways & Infra EPC', 'IRCON': 'Railways & Infra EPC', 'RAILTEL': 'Railways & Infra EPC', 'IRCTC': 'Railways & Infra EPC',
    'SBIN': 'PSU Banks', 'BOB': 'PSU Banks', 'PNB': 'PSU Banks', 'HDFCBANK': 'Private Banks', 'ICICIBANK': 'Private Banks', 'AXISBANK': 'Private Banks',
    'DIXON': 'EMS & Semiconductors', 'KAYNES': 'EMS & Semiconductors', 'SYRMA': 'EMS & Semiconductors',
    'PFC': 'Power, Renewables & PSU', 'RECLTD': 'Power, Renewables & PSU', 'NTPC': 'Power, Renewables & PSU', 'TATAPOWER': 'Power, Renewables & PSU'
}

GOVT_KEYWORDS = ['cabinet', 'govt', 'government', 'pib', 'ministry', 'rbi', 'sebi', 'pli', 'subsidy', 'tender', 'psu', 'railway', 'defence', 'defense', 'nhai', 'ntpc', 'budget', 'gst', 'duty', 'rate cut', 'restructuring', 'disinvestment']
BULL_KEYWORDS = ['order', 'win', 'bag', 'profit', 'surge', 'jump', 'dividend', 'bonus', 'split', 'upgrade', 'buy', 'approval', 'acquire', 'expansion', 'record', 'mou', 'partner', 'launch']
BEAR_KEYWORDS = ['loss', 'fall', 'drop', 'penalty', 'raid', 'fraud', 'downgrade', 'default', 'resign', 'pledge', 'ban', 'notice', 'probe', 'fire', 'strike', 'weak']

def classify_sector(symbol, raw_industry):
    sym = str(symbol).upper().strip()
    if sym in THEMATIC_MAP: return THEMATIC_MAP[sym]
    ind = str(raw_industry).strip()
    return ind if ind not in ['Unknown', '', 'nan', 'None'] else 'Diversified / IPO'

def update_universe_with_new_ipos(univ_df):
    try:
        req = urllib.request.Request("https://archives.nseindia.com/content/equities/EQUITY_L.csv", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            nse_df = pd.read_csv(io.StringIO(response.read().decode('utf-8')))
        nse_df = nse_df[nse_df[' SERIES'] == 'EQ']
        existing_symbols = set(univ_df['Symbol'].str.upper())
        new_rows = [{'Company': str(row[' NAME OF COMPANY']).strip(), 'Industry': 'Diversified / IPO', 'Symbol': str(row['SYMBOL']).strip().upper()} for _, row in nse_df.iterrows() if str(row['SYMBOL']).strip().upper() not in existing_symbols]
        if new_rows:
            univ_df = pd.concat([univ_df, pd.DataFrame(new_rows)], ignore_index=True)
            univ_df.to_csv("Universe_List.csv", index=False)
    except: pass
    return univ_df

def fetch_stock_news_catalyst(symbol, company, current_tag):
    try:
        query = urllib.parse.quote(f"{company} {symbol} NSE stock")
        url = f"https://news.google.com/rss/search?q={query}+when:2d&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            root = ET.fromstring(response.read())
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text or ""
            clean_title = title.split(" - ")[0].strip()
            low_t = clean_title.lower()
            if any(k in low_t for k in GOVT_KEYWORDS): sentiment = "🏛️ GOVT/POLICY"
            elif any(k in low_t for k in BULL_KEYWORDS): sentiment = "🟢 BULL NEWS"
            elif any(k in low_t for k in BEAR_KEYWORDS): sentiment = "🔴 RISK NEWS"
            else: sentiment = "📰 NEWS"
            short_headline = clean_title[:52] + ("..." if len(clean_title) > 52 else "")
            if current_tag == "⚪ Normal Flow": return f"{sentiment}: {short_headline}"
            return f"{current_tag} | {sentiment}: {short_headline}"
    except: pass
    return current_tag

def fetch_macro_data():
    macro_tickers = ['BZ=F', 'GC=F', '^INDIAVIX', '^TNX']
    data = yf.download(macro_tickers, period="5d", progress=False)
    out = [{'Ticker': t, 'Live_Value': round(float(data['Close'][t].dropna().iloc[-1]), 2), 'Daily_Change': float((data['Close'][t].dropna().iloc[-1] / data['Close'][t].dropna().iloc[-2]) - 1) if len(data['Close'][t].dropna()) >= 2 else 0.0} for t in macro_tickers if not data['Close'][t].dropna().empty]
    pd.DataFrame(out).to_csv("RAW_MACRO.csv", index=False)

def run_quantum_engine():
    now_ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    current_mins_global = now_ist.hour * 60 + now_ist.minute
    
    # EOD Heavy Run triggers post 4:20 PM IST (Safely after 4:15 PM Trade Mod Ends)
    is_eod_heavy_run = current_mins_global >= (16 * 60 + 20) or not os.path.exists('fundamentals_cache.json')
    
    try: univ = pd.read_csv("Universe_List.csv")
    except: univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    
    univ['Symbol'] = univ['Symbol'].astype(str).str.strip()
    if is_eod_heavy_run: univ = update_universe_with_new_ipos(univ)
    tickers = (univ['Symbol'] + '.NS').tolist()

    try:
        mem_df = pd.read_csv("Historical_Holdings.csv")
        mem_df['Date'] = pd.to_datetime(mem_df['Date'])
        mem_df = mem_df[mem_df['Date'] >= (pd.to_datetime(datetime.date.today()) - pd.Timedelta(days=180))]
    except: mem_df = pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])
    oldest_records = mem_df.sort_values('Date').groupby('Symbol').first().to_dict('index') if not mem_df.empty else {}
    today_memory_records = []

    download_period = "5y" if is_eod_heavy_run else "1y"
    raw_data = yf.download(tickers + ['^NSEI'], period=download_period, interval="1d", progress=False)
    
    nifty_20d_return = 0.0
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        if len(nifty_c) >= 21: nifty_20d_return = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1)
    except: pass
    fetch_macro_data()

    fundamentals = {}
    if is_eod_heavy_run:
        try:
            tickers_obj = yf.Tickers(" ".join(tickers))
            for t in tickers:
                try: fundamentals[t] = tickers_obj.tickers[t].info
                except: fundamentals[t] = {}
            with open('fundamentals_cache.json', 'w') as f: json.dump(fundamentals, f)
        except: pass
    else:
        try:
            with open('fundamentals_cache.json', 'r') as f: fundamentals = json.load(f)
        except: fundamentals = {}

    results = []
    def process(row):
        symbol, ticker = row['Symbol'], row['Symbol'] + '.NS'
        try:
            c = raw_data['Close'][ticker].dropna()
            if len(c) < 20: return None
            
            h, l, v = raw_data['High'][ticker].reindex(c.index).ffill(), raw_data['Low'][ticker].reindex(c.index).ffill(), raw_data['Volume'][ticker].reindex(c.index).ffill()
            cur_close = float(c.iloc[-1])
            vol_30d = float(v.iloc[-30:].mean()) if len(v) >= 30 else float(v.mean())
            if (vol_30d * cur_close) < 10000000: return None 
            
            w_52h, w_52l = h.iloc[-252:] if len(h) >= 252 else h, l.iloc[-252:] if len(l) >= 252 else l
            h_52w, l_52w = float(w_52h.max()), float(w_52l.min())
            dist_from_52w_low, disc_from_52w_high = round(((cur_close - l_52w) / l_52w), 4), round(((cur_close - h_52w) / h_52w), 4)

            ret_1d = round(((cur_close / float(c.iloc[-2])) - 1), 4) if len(c) >= 2 else 0.0
            ret_5d = round(((cur_close / float(c.iloc[-6])) - 1), 4) if len(c) >= 6 else 0.0
            ret_20d = round(((cur_close / float(c.iloc[-21])) - 1), 4) if len(c) >= 21 else 0.0
            rs_vs_nifty = round(ret_20d - nifty_20d_return, 4)

            ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            slope_200 = ema200 - float(c.ewm(span=200, adjust=False).mean().iloc[-20]) if len(c) >= 25 else 0.0
            
            # SEBI 385 MINUTE TRADING DAY
            current_mins = now_ist.hour * 60 + now_ist.minute
            market_open_mins = 9 * 60 + 15
            market_close_mins = 15 * 60 + 40
            
            if current_mins < market_open_mins: trading_mins = 15
            elif current_mins > market_close_mins: trading_mins = 385
            else: trading_mins = current_mins - market_open_mins

            projected_vol = float(v.iloc[-1]) * (385.0 / max(15, trading_mins)) if current_mins < market_close_mins else float(v.iloc[-1])
            dsr = projected_vol / vol_30d if vol_30d > 0 else 1.0
            is_vdu = dsr <= 0.50
            wick_pct = (cur_close - float(l.iloc[-1])) / (float(h.iloc[-1]) - float(l.iloc[-1])) if (float(h.iloc[-1]) - float(l.iloc[-1])) > 0 else 0.0
            
            try:
                delta = c.diff()
                rsi = float(100 - (100 / (1 + ((delta.where(delta > 0, 0)).rolling(14).mean() / (-delta.where(delta < 0, 0)).rolling(14).mean()).iloc[-1])))
            except: rsi = 50.0

            is_breakout = cur_close > float(h.iloc[-21:-1].max()) if len(h) >= 21 else False
            is_capitulation = False
            alert_type = "Standard"
            
            # CAPITULATION & REBOUND ALGORITHM
            if ret_1d <= -0.05 and rsi <= 35 and (wick_pct > 0.35 or dsr >= 1.5):
                is_capitulation = True
                alert_type = "💥 CAPITULATION BOUNCE"
            elif rsi > 80: alert_type = "🚨 OVERBOUGHT (Caution)"
            elif cur_close < ema200 and slope_200 < 0: alert_type = "📉 DOWNTREND (Avoid)"
            elif is_breakout and dsr > 1.5: alert_type = "🚀 20D BREAKOUT"
            elif is_vdu and cur_close > ema50: alert_type = "⚡ VCP + VDU"
            elif dsr >= 5.0 and cur_close < 250: alert_type = "🚀 5x VOL AWAKENING"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05): alert_type = "🛡️ PULLBACK SUPPORT"

            atr14 = float((h.iloc[-14:] - l.iloc[-14:]).mean()) if len(h) >= 14 else cur_close * 0.02
            if is_capitulation:
                sl_price = round(float(l.iloc[-1]) * 0.98, 2)
                target_7 = round(cur_close + (4.0 * atr14), 2)
            elif is_breakout and dsr > 1.2:
                sl_price, target_7 = round(cur_close - (2.0 * atr14), 2), round(cur_close + (3.0 * atr14), 2)
            else:
                sl_price, target_7 = round(float(l.iloc[-10:].min()) * 0.99, 2), round(cur_close * 1.07, 2)

            risk = cur_close - sl_price
            rr_ratio = round((target_7 - cur_close) / risk, 2) if risk > 0 else 0.0

            info = fundamentals.get(ticker, {})
            raw_in, raw_inst, raw_roe, raw_debt, raw_growth, raw_q_growth, raw_pe, raw_bv = info.get('heldPercentInsiders'), info.get('heldPercentInstitutions'), info.get('returnOnEquity'), info.get('debtToEquity'), info.get('revenueGrowth'), info.get('earningsQuarterlyGrowth'), info.get('trailingPE', info.get('forwardPE')), info.get('bookValue')
            pe_val = float(raw_pe) if raw_pe is not None else 0.0
            bv_val = float(raw_bv) if raw_bv is not None else 0.0
            final_roe = float(raw_roe) if raw_roe is not None else ((cur_close / (pe_val * bv_val)) if pe_val > 0 and bv_val > 0 else None)
            
            events_list, earnings_blackout, post_earnings_breakout = [], False, False
            ex_div_ts = info.get('exDividendDate')
            if ex_div_ts:
                ex_dt = datetime.datetime.fromtimestamp(int(ex_div_ts)).date()
                if 0 <= (ex_dt - datetime.date.today()).days <= 10: events_list.append(f"💰 EX-DIV SHIELD ({ex_dt.strftime('%d-%b')})")
            earnings_ts = info.get('earningsTimestamp', info.get('earningsTimestampStart'))
            if earnings_ts:
                e_dt = datetime.datetime.fromtimestamp(int(earnings_ts)).date()
                if 0 <= (e_dt - datetime.date.today()).days <= 5: earnings_blackout = True
                elif -5 <= (e_dt - datetime.date.today()).days < 0 and ret_1d > 0.015 and dsr >= 1.8: post_earnings_breakout = True

            sort_priority = 6
            if earnings_blackout: trading_verdict, sort_priority = "🚨 EARNINGS BLACKOUT (WAIT)", 5
            elif rr_ratio >= 1.5 and alert_type in ["🚀 20D BREAKOUT", "⚡ VCP + VDU", "💥 CAPITULATION BOUNCE"]: trading_verdict, sort_priority = f"🎯 STRONG BUY: ₹{round(cur_close, 2)}", 1
            elif rr_ratio >= 1.2 and alert_type not in ["📉 DOWNTREND (Avoid)", "🚨 OVERBOUGHT (Caution)"]: trading_verdict, sort_priority = f"🟢 ACCUMULATE: ₹{round(cur_close, 2)}", 2
            elif alert_type == "🚨 OVERBOUGHT (Caution)": trading_verdict, sort_priority = "⚠️ TRIM / AVOID", 4
            elif alert_type == "📉 DOWNTREND (Avoid)": trading_verdict, sort_priority = "⛔ STRICT SKIP", 6
            else: trading_verdict, sort_priority = "⏳ WAIT", 3

            prom_curr, fii_curr = raw_in if raw_in else 0.0, raw_inst if raw_inst else 0.0
            prom_old, fii_old = oldest_records.get(symbol, {}).get('Prom_Pct', prom_curr), oldest_records.get(symbol, {}).get('FII_Pct', fii_curr)
            prom_delta, fii_delta = round(prom_curr - prom_old, 4), round(fii_curr - fii_old, 4)
            today_memory_records.append({'Symbol': symbol, 'Date': datetime.date.today(), 'Prom_Pct': prom_curr, 'FII_Pct': fii_curr})
            
            fund_score, accum_status, dust_gem_score = 0, "NEUTRAL", 0
            debt_val = round(raw_debt, 2) if raw_debt is not None else 0.0
            if raw_in and raw_in >= 0.50: fund_score += 30
            if raw_inst and raw_inst >= 0.15: fund_score += 20
            if final_roe and final_roe > 0.15: fund_score += 20
            if debt_val < 50: fund_score += 30
            if fund_score >= 70 and is_vdu and dist_from_52w_low < 0.30: accum_status = "💎 SILENT ACCUMULATION"
            elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"

            # DUST-TO-DIAMONDS GEMS SCORE 
            if final_roe and final_roe >= 0.15: dust_gem_score += 25
            elif final_roe and final_roe >= 0.10: dust_gem_score += 10
            if raw_in and raw_in >= 0.50: dust_gem_score += 15
            if raw_inst and raw_inst >= 0.15: dust_gem_score += 15
            if debt_val < 30: dust_gem_score += 15
            if disc_from_52w_high <= -0.30: dust_gem_score += 30
            elif disc_from_52w_high <= -0.20: dust_gem_score += 20
            elif disc_from_52w_high <= -0.12: dust_gem_score += 10
            if 0 < pe_val < 25: dust_gem_score += 15

            is_fundamentally_sound = (fund_score >= 50) or (final_roe and final_roe >= 0.12)
            fear_event_score = 0.0
            catalyst_tag = "⚪ Normal Flow"
            
            if is_capitulation:
                fear_event_score = 1000 + fund_score
                catalyst_tag = f"💥 CAPITULATION REVERSAL ({round(ret_1d*100,1)}% Drop • Bounce Incoming)"
            elif ret_1d <= -0.05 and dsr >= 3.5:
                catalyst_tag = "⛔ TOXIC STANDALONE DUMP (AVOID)"
            elif is_fundamentally_sound and not earnings_blackout:
                if post_earnings_breakout:
                    fear_event_score = round(dsr * 35 + fund_score, 1)
                    catalyst_tag = f"🚀 POST-EARNINGS BREAKOUT ({round(ret_1d*100,1)}% • {round(dsr,1)}x Vol)"
                elif -0.08 <= ret_1d <= -0.025 and cur_close >= ema200 * 0.97 and dsr < 3.2:
                    fear_event_score = round(abs(ret_1d) * 1000 + fund_score, 1)
                    catalyst_tag = f"😱 FEAR DIP ({round(ret_1d*100,1)}% 1D) • Intact 200-EMA"
                elif -0.12 <= ret_5d <= -0.045 and rsi <= 42 and cur_close >= ema200 * 0.95:
                    fear_event_score = round(abs(ret_5d) * 800 + fund_score, 1)
                    catalyst_tag = f"🌊 SECTOR CONTAGION DIP ({round(ret_5d*100,1)}% 5D • RSI {int(rsi)})"

            best_month, worst_month = "N/A", "N/A"
            try:
                c_monthly = c.groupby(c.index.to_period('M')).last()
                m_ret = c_monthly.pct_change().dropna()
                if len(m_ret) > 12:
                    m_avg = m_ret.groupby(m_ret.index.strftime('%B')).mean()
                    best_month, worst_month = m_avg.idxmax(), m_avg.idxmin()
            except: pass

            return {
                'Symbol': symbol, 'Company': row.get('Company', symbol), 'Industry': classify_sector(symbol, row.get('Industry', 'Unknown')),
                'Sort_Priority': sort_priority, 'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 
                'Entry Trigger': round(cur_close, 2), 'Stop Loss': sl_price, 'Target 7%': target_7, 
                'F&O Ceiling': round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2), 
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date, '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'R:R Ratio': rr_ratio, 'Pos Size (₹5k Risk)': int(max(1, round(5000.0 / risk))) if risk > 0 else 1, 'RS vs Nifty': rs_vs_nifty,
                'Opportunity Score': fund_score, 'Dust_Gem_Score': dust_gem_score, 'Stage': "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4", 
                'Accumulation Status': accum_status, 
                'Promoter Holding': round(raw_in, 4) if raw_in else "", 'Promoter Delta': prom_delta,
                'FII/DII': round(raw_inst, 4) if raw_inst else "", 'FII Delta': fii_delta, 
                'Dist from 52W Low': dist_from_52w_low, 'Disc from 52W High': disc_from_52w_high,
                'Debt-to-Eq': debt_val if debt_val > 0 else "", 'Growth': round(max(-3.0, min(3.0, float(raw_growth))), 4) if raw_growth else "", 
                'ROE': round(final_roe, 4) if final_roe else "", 'PE Ratio': round(pe_val, 2) if pe_val > 0 else "", 
                'Book Value': round(bv_val, 2) if bv_val > 0 else "",
                'Div Yield': round(float(info.get('dividendYield', 0)), 4) if info.get('dividendYield') else 0.0, 
                'QoQ Growth': round(max(-3.0, min(3.0, float(raw_q_growth))), 4) if raw_q_growth else "", 'Volume Profile': "VDU" if is_vdu else "Normal",
                'Corp Event': " | ".join(events_list) if events_list else "Regular Trading", 'Catalyst Impact': catalyst_tag, 'Fear_Event_Score': fear_event_score,
                'Beta': round(float(info.get('beta', 1.05)), 2), 'Ret_1D': ret_1d, 'Ret_5D': ret_5d, 'Ret_20D': ret_20d, 'Ret_50D': round(((cur_close / float(c.iloc[-51])) - 1), 4) if len(c) >= 51 else 0.0,
                'Best_Month': best_month, 'Worst_Month': worst_month
            }
        except: return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process, row): row for _, row in univ.iterrows()}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return
    
    if is_eod_heavy_run:
        pd.concat([mem_df, pd.DataFrame(today_memory_records)]).drop_duplicates(subset=['Symbol', 'Date'], keep='last').to_csv("Historical_Holdings.csv", index=False)

    top_swings = df[df['Sort_Priority'] <= 2].sort_values(by=["Sort_Priority", "R:R Ratio"], ascending=[True, False]).head(20)
    used_syms = set(top_swings['Symbol'].tolist())
    
    top_inc = df[(df['Accumulation Status'] != "NEUTRAL") & (df['Sort_Priority'] <= 3) & (~df['Symbol'].isin(used_syms))].sort_values(by=["Opportunity Score", "Sort_Priority", "R:R Ratio"], ascending=[False, True, False]).head(20)
    used_syms.update(top_inc['Symbol'].tolist())
    
    fear_candidates = df[(df['Fear_Event_Score'] > 0) & (~df['Symbol'].isin(used_syms))].sort_values(by="Fear_Event_Score", ascending=False).head(40)
    dust_gems = df[(df['Disc from 52W High'] <= -0.15) & (~df['Symbol'].isin(used_syms))].sort_values(by="Dust_Gem_Score", ascending=False).head(40)

    core_portfolio = {'PFC', 'RELIANCE', 'IRFC', 'IRB', 'MSUMI', 'NMDC', 'ITC', 'BEL'}
    all_news_syms = set(top_swings['Symbol']).union(set(top_inc['Symbol'])).union(set(fear_candidates['Symbol'])).union(set(dust_gems['Symbol'])).union(core_portfolio).union(set(df[df['Corp Event'] != "Regular Trading"]['Symbol'].head(25)))

    with ThreadPoolExecutor(max_workers=8) as news_exec:
        future_to_idx = {news_exec.submit(fetch_stock_news_catalyst, df.at[i, 'Symbol'], df.at[i, 'Company'], df.at[i, 'Catalyst Impact']): i for i in df[df['Symbol'].isin(all_news_syms)].index.tolist()}
        for fut in as_completed(future_to_idx):
            try: df.at[future_to_idx[fut], 'Catalyst Impact'] = fut.result()
            except: pass

    # 1. SWINGS OUTPUT
    sw_cols = ["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "Pos Size (₹5k Risk)", "RS vs Nifty", "F&O Ceiling", "52W High", "52W High Date", "52W Low", "52W Low Date", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value", "Corp Event", "Catalyst Impact"]
    df.loc[top_swings.index].sort_values(by=["Sort_Priority", "R:R Ratio"], ascending=[True, False])[sw_cols].to_csv("RAW_SWINGS.csv", index=False)

    # 2. INCUBATOR OUTPUT
    inc_cols = ["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Div Yield", "Volume Profile", "Corp Event", "Catalyst Impact"]
    df.loc[top_inc.index].sort_values(by="Opportunity Score", ascending=False)[inc_cols].to_csv("RAW_INCUBATOR.csv", index=False)

    # 3. SNIPER OUTPUT
    sniper_rows = []
    for _, r in df.loc[top_swings.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "MOMENTUM SWING", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], r['R:R Ratio'], r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[top_inc.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "10X MULTIBAGGER", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*2, 2), 5.0, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[fear_candidates.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "⚡ CONTRARIAN FEAR DIP / EVENT", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*1.10, 2), round(max(2.0, r['R:R Ratio']), 2), r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Trigger Price", "Stop Loss", "Target", "R:R Ratio", "RS vs Nifty", "52W High", "52W Low", "Catalyst / Fear Diagnosis", "Corporate Event"]).to_csv("RAW_SNIPER.csv", index=False)
    
    # 4. FEAR DIP HUNTER OUTPUT (Gems in the Dust) -> Output exactly as RAW_FEAR_DIP.csv
    fear_rows = []
    for _, r in df.loc[dust_gems.index].iterrows(): fear_rows.append([r['Symbol'], r['Company'], r['Entry Trigger'], r['Disc from 52W High'], r['Dist from 52W Low'], r['Dust_Gem_Score'], r['PE Ratio'], r['ROE'], r['Promoter Holding'], r['FII/DII'], r['Debt-to-Eq'], r['Corp Event']])
    pd.DataFrame(fear_rows, columns=["Symbol", "Company", "Live CMP", "Disc from 52W High", "Dist from 52W Low", "Dust Gem Score", "PE Ratio", "ROE", "Promoter %", "FII/DII %", "Debt-to-Eq", "Corporate Event"]).to_csv("RAW_FEAR_DIP.csv", index=False)

    # 5. PROMOTER OUTPUT
    promoter_cols = ["Symbol", "Company", "Opportunity Score", "Promoter Holding", "Promoter Delta", "FII/DII", "FII Delta", "Debt-to-Eq", "ROE", "Div Yield", "Industry", "Beta", "Ret_20D", "Disc from 52W High"]
    df.sort_values(by="Promoter Holding", ascending=False)[promoter_cols].to_csv("RAW_PROMOTER.csv", index=False)

    # 6. SECTOR OUTPUT
    sector_df = df.groupby('Industry').agg(
        Total_Stocks=('Symbol', 'count'), Uptrend_Count=('Stage', lambda x: (x == 'PHASE 2: MARKUP').sum()),
        Avg_1D_Flow=('Ret_1D', lambda x: round(x.mean() * 100, 2)), Avg_5D_Flow=('Ret_5D', lambda x: round(x.mean() * 100, 2)),
        Avg_Money_Flow=('Ret_20D', lambda x: round(x.mean() * 100, 2)), Avg_50D_Flow=('Ret_50D', lambda x: round(x.mean() * 100, 2)),
        Smart_Money_FII=('FII Delta', lambda x: round(x.mean() * 100, 2)), Smart_Money_Prom=('Promoter Delta', lambda x: round(x.mean() * 100, 2)),
        Hist_Best_Month=('Best_Month', lambda x: x.mode()[0] if not x.empty else "N/A"), Hist_Worst_Month=('Worst_Month', lambda x: x.mode()[0] if not x.empty else "N/A")
    ).reset_index()
    sector_df['ISAD (Breadth %)'] = round((sector_df['Uptrend_Count'] / sector_df['Total_Stocks']) * 100, 1)
    sector_df['Sector Status'] = np.where(sector_df['ISAD (Breadth %)'] > 40, "🔥 DOMINANT", np.where(sector_df['ISAD (Breadth %)'] < 15, "⚠️ WASHOUT", "🔄 EMERGING"))
    
    def get_smart_money(row):
        total_flow = row['Smart_Money_FII'] + row['Smart_Money_Prom']
        if total_flow > 0.5 and row['Avg_Money_Flow'] > 0: return "💰 SMART MONEY INFLOW"
        if total_flow < -0.5: return "🩸 RETAIL TRAP (Inst. Exiting)"
        return "⚖️ NEUTRAL FLOW"
    sector_df['Smart Money Direction'] = sector_df.apply(get_smart_money, axis=1)

    def get_cycle(industry):
        i = str(industry).lower()
        if any(x in i for x in ['defense', 'railway', 'capital goods', 'infrastructure', 'power']): return "Govt Capex & Defense Supercycle"
        if any(x in i for x in ['bank', 'financial', 'realt', 'auto']): return "Rate Cut & Credit Expansion Cycle"
        if any(x in i for x in ['ems', 'semiconductor', 'it ', 'technology', 'telecom']): return "PLI Manufacturing & Digital Export Cycle"
        if any(x in i for x in ['fmcg', 'consumer', 'pharma', 'healthcare']): return "Defensive Consumption & Margin Expansion"
        return "Idiosyncratic / Stock Specific"
        
    sector_df['2-Year Macro Prediction'] = sector_df['Industry'].apply(get_cycle)
    
    # OUTPUT ALL 11 COLUMNS TO SECTOR TIME MACHINE
    sector_cols = ['Industry', 'Sector Status', 'ISAD (Breadth %)', 'Avg_1D_Flow', 'Avg_5D_Flow', 'Avg_Money_Flow', 'Avg_50D_Flow', 'Hist_Best_Month', 'Hist_Worst_Month', 'Smart Money Direction', '2-Year Macro Prediction']
    sector_df[sector_cols].sort_values(by=['ISAD (Breadth %)', 'Avg_1D_Flow'], ascending=[False, False]).to_csv("RAW_SECTOR.csv", index=False)

if __name__ == "__main__":
    run_quantum_engine()
