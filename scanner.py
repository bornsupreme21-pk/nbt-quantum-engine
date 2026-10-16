import os
import warnings
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

THEMATIC_MAP = {
    'HAL': 'Defense & Aerospace', 'BEL': 'Defense & Aerospace', 'BDL': 'Defense & Aerospace',
    'MAZDOCK': 'Defense & Aerospace', 'COCHINSHIP': 'Defense & Aerospace', 'GRSE': 'Defense & Aerospace',
    'SOLARINDS': 'Defense & Aerospace', 'PARAS': 'Defense & Aerospace', 'MTARTECH': 'Defense & Aerospace',
    'DATAPATTNS': 'Defense & Aerospace', 'ASTRAMICRO': 'Defense & Aerospace', 'ZENTEC': 'Defense & Aerospace',
    'BEML': 'Defense & Aerospace', 'MIDHANI': 'Defense & Aerospace',
    'IRFC': 'Railways & Infra EPC', 'RVNL': 'Railways & Infra EPC', 'IRCON': 'Railways & Infra EPC',
    'RAILTEL': 'Railways & Infra EPC', 'IRCTC': 'Railways & Infra EPC', 'RITES': 'Railways & Infra EPC',
    'TITAGARH': 'Railways & Infra EPC', 'JWL': 'Railways & Infra EPC', 'TEXRAIL': 'Railways & Infra EPC',
    'CONCOR': 'Railways & Infra EPC', 'NBCC': 'Railways & Infra EPC', 'NCC': 'Railways & Infra EPC',
    'LT': 'Railways & Infra EPC', 'IRB': 'Railways & Infra EPC', 'KEC': 'Railways & Infra EPC',
    'KPIL': 'Railways & Infra EPC', 'HUDCO': 'Railways & Infra EPC',
    'SBIN': 'PSU Banks', 'BOB': 'PSU Banks', 'BANKBARODA': 'PSU Banks', 'PNB': 'PSU Banks',
    'CANBK': 'PSU Banks', 'UNIONBANK': 'PSU Banks', 'INDIANB': 'PSU Banks', 'IOB': 'PSU Banks',
    'UCOBANK': 'PSU Banks', 'MAHABANK': 'PSU Banks', 'CENTRALBK': 'PSU Banks', 'BANKINDIA': 'PSU Banks',
    'IDBI': 'PSU Banks',
    'HDFCBANK': 'Private Banks', 'ICICIBANK': 'Private Banks', 'AXISBANK': 'Private Banks',
    'KOTAKBANK': 'Private Banks', 'INDUSINDBK': 'Private Banks', 'FEDERALBNK': 'Private Banks',
    'IDFCFIRSTB': 'Private Banks', 'AUBANK': 'Private Banks', 'BANDHANBNK': 'Private Banks',
    'RBLBANK': 'Private Banks', 'KARURVYSYA': 'Private Banks', 'TMB': 'Private Banks',
    'DIXON': 'EMS & Semiconductors', 'KAYNES': 'EMS & Semiconductors', 'SYRMA': 'EMS & Semiconductors',
    'AMBER': 'EMS & Semiconductors', 'PGEL': 'EMS & Semiconductors', 'AVALON': 'EMS & Semiconductors',
    'CYIENTDLM': 'EMS & Semiconductors', 'TEJASNET': 'EMS & Semiconductors',
    'PFC': 'Power, Renewables & PSU', 'RECLTD': 'Power, Renewables & PSU', 'NTPC': 'Power, Renewables & PSU',
    'POWERGRID': 'Power, Renewables & PSU', 'TATAPOWER': 'Power, Renewables & PSU', 'JSWENERGY': 'Power, Renewables & PSU',
    'NHPC': 'Power, Renewables & PSU', 'SJVN': 'Power, Renewables & PSU', 'IREDA': 'Power, Renewables & PSU',
    'SUZLON': 'Power, Renewables & PSU', 'INOXWIND': 'Power, Renewables & PSU', 'ACMESOLAR': 'Power, Renewables & PSU',
    'WAAREEENER': 'Power, Renewables & PSU', 'PREMIERENE': 'Power, Renewables & PSU', 'IEX': 'Power, Renewables & PSU'
}

GOVT_KEYWORDS = ['cabinet', 'govt', 'government', 'pib', 'ministry', 'rbi', 'sebi', 'pli', 'subsidy', 'tender', 'psu', 'railway', 'defence', 'defense', 'nhai', 'ntpc', 'budget', 'gst', 'duty', 'rate cut', 'restructuring', 'disinvestment']
BULL_KEYWORDS = ['order', 'win', 'bag', 'profit', 'surge', 'jump', 'dividend', 'bonus', 'split', 'upgrade', 'buy', 'approval', 'acquire', 'expansion', 'record', 'mou', 'partner', 'launch']
BEAR_KEYWORDS = ['loss', 'fall', 'drop', 'penalty', 'raid', 'fraud', 'downgrade', 'default', 'resign', 'pledge', 'ban', 'notice', 'probe', 'fire', 'strike', 'weak']

def classify_sector(symbol, raw_industry):
    sym = str(symbol).upper().strip()
    if sym in THEMATIC_MAP:
        return THEMATIC_MAP[sym]
    ind = str(raw_industry).strip()
    if ind in ['Unknown', '', 'nan', 'None']:
        return 'Diversified / Others'
    return ind

def fetch_stock_news_catalyst(symbol, company, current_tag):
    try:
        query = urllib.parse.quote(f"{company} {symbol} NSE stock")
        url = f"https://news.google.com/rss/search?q={query}+when:2d&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text or ""
            clean_title = title.split(" - ")[0].strip()
            low_t = clean_title.lower()
            if any(k in low_t for k in GOVT_KEYWORDS):
                sentiment = "🏛️ GOVT/POLICY"
            elif any(k in low_t for k in BULL_KEYWORDS):
                sentiment = "🟢 BULL NEWS"
            elif any(k in low_t for k in BEAR_KEYWORDS):
                sentiment = "🔴 RISK NEWS"
            else:
                sentiment = "📰 NEWS"
            short_headline = clean_title[:52] + ("..." if len(clean_title) > 52 else "")
            if current_tag == "⚪ Normal Flow":
                return f"{sentiment}: {short_headline}"
            return f"{current_tag} | {sentiment}: {short_headline}"
    except Exception:
        pass
    return current_tag

def fetch_macro_data():
    macro_tickers = ['BZ=F', 'GC=F', '^INDIAVIX', '^TNX']
    data = yf.download(macro_tickers, period="5d", progress=False)
    out = []
    for t in macro_tickers:
        try:
            c = data['Close'][t].dropna()
            cur = float(c.iloc[-1])
            chg = float((c.iloc[-1] / c.iloc[-2]) - 1) if len(c) >= 2 else 0.0
            out.append({'Ticker': t, 'Live_Value': round(cur, 2), 'Daily_Change': chg})
        except Exception:
            out.append({'Ticker': t, 'Live_Value': 0.0, 'Daily_Change': 0.0})
    pd.DataFrame(out).to_csv("macro_output.csv", index=False)

def run_quantum_engine():
    print("1. Loading Master Universe & Memory Bank...")
    try:
        univ = pd.read_csv("Universe_List.csv")
    except Exception:
        univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    
    if 'Company' not in univ.columns and 'Company Name' in univ.columns:
        univ.rename(columns={'Company Name': 'Company'}, inplace=True)
    
    univ['Symbol'] = univ['Symbol'].astype(str).str.strip()
    univ['YF_Ticker'] = univ['Symbol'] + '.NS'
    tickers = univ['YF_Ticker'].tolist()

    memory_file = "Historical_Holdings.csv"
    today_date = pd.to_datetime(datetime.date.today())
    try:
        mem_df = pd.read_csv(memory_file)
        mem_df['Date'] = pd.to_datetime(mem_df['Date'])
        cutoff = today_date - pd.Timedelta(days=180)
        mem_df = mem_df[mem_df['Date'] >= cutoff]
    except Exception:
        mem_df = pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])

    oldest_records = {}
    if not mem_df.empty:
        oldest_df = mem_df.sort_values('Date').groupby('Symbol').first()
        oldest_records = oldest_df.to_dict('index')
    
    today_memory_records = []
    
    print(f"2. Downloading Data for {len(tickers)} stocks + Nifty Benchmark...")
    raw_data = yf.download(tickers + ['^NSEI'], period="5y", interval="1d", progress=False)
    
    nifty_ret = pd.Series(dtype=float)
    nifty_20d_return = 0.0
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        nifty_ret = nifty_c.pct_change().iloc[-252:]
        if len(nifty_c) >= 21:
            nifty_20d_return = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1)
    except Exception:
        pass

    fetch_macro_data()

    results = []
    fundamentals = {}
    try:
        tickers_obj = yf.Tickers(" ".join(tickers))
        for t in tickers:
            try: fundamentals[t] = tickers_obj.tickers[t].info
            except: fundamentals[t] = {}
    except: pass
    
    def process(row):
        symbol, ticker = row['Symbol'], row['YF_Ticker']
        try:
            c = raw_data['Close'][ticker].dropna()
            if len(c) < 60: return None
            
            h = raw_data['High'][ticker].reindex(c.index).ffill()
            l = raw_data['Low'][ticker].reindex(c.index).ffill()
            v = raw_data['Volume'][ticker].reindex(c.index).ffill()
            
            cur_close = float(c.iloc[-1])
            vol_30d = float(v.iloc[-30:].mean())
            if (vol_30d * cur_close) < 10000000: return None 
            
            is_recent_ipo = len(c) < 252
            w_52h = h.iloc[-252:] if len(h) >= 252 else h
            w_52l = l.iloc[-252:] if len(l) >= 252 else l
            h_52w = float(w_52h.max())
            l_52w = float(w_52l.min())
            h_52w_date = w_52h.idxmax().strftime('%d-%b-%Y')
            l_52w_date = w_52l.idxmin().strftime('%d-%b-%Y')
            
            dist_from_52w_low = round(((cur_close - l_52w) / l_52w), 4)
            disc_from_52w_high = round(((cur_close - h_52w) / h_52w), 4)

            ret_1d = round(((cur_close / float(c.iloc[-2])) - 1), 4) if len(c) >= 2 else 0.0
            ret_5d = round(((cur_close / float(c.iloc[-6])) - 1), 4) if len(c) >= 6 else 0.0
            ret_20d = round(((cur_close / float(c.iloc[-21])) - 1), 4) if len(c) >= 21 else 0.0
            ret_50d = round(((cur_close / float(c.iloc[-51])) - 1), 4) if len(c) >= 51 else 0.0
            rs_vs_nifty = round(ret_20d - nifty_20d_return, 4)

            ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            slope_200 = ema200 - float(c.ewm(span=200, adjust=False).mean().iloc[-20]) if len(c) >= 25 else 0.0
            
            dsr = float(v.iloc[-1]) / vol_30d if vol_30d > 0 else 1.0
            is_vdu = dsr <= 0.50
            fall_3d = (cur_close - float(c.iloc[-4])) / float(c.iloc[-4]) if len(c) >= 4 else 0.0
            wick_pct = (cur_close - float(l.iloc[-1])) / (float(h.iloc[-1]) - float(l.iloc[-1])) if (float(h.iloc[-1]) - float(l.iloc[-1])) > 0 else 0.0
            
            try:
                delta = c.diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = float(100 - (100 / (1 + rs.iloc[-1])))
            except: rsi = 50.0

            alert_type = "Standard"
            if rsi > 80: alert_type = "🚨 OVERBOUGHT (Caution)"
            elif cur_close < ema200 and slope_200 < 0: alert_type = "📉 DOWNTREND (Avoid)"
            elif fall_3d <= -0.05 and dsr >= 2.0 and wick_pct > 0.5: alert_type = "🔥 DEAD BOTTOM"
            elif is_vdu and cur_close > ema50: alert_type = "⚡ VCP + VDU"
            elif dsr >= 5.0 and cur_close < 250: alert_type = "🚀 5x VOL AWAKENING"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05): alert_type = "🛡️ PULLBACK SUPPORT"
            
            nbt_stage = "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4"

            sl_price = round(float(l.iloc[-10:].min()) * 0.99, 2)
            risk = cur_close - sl_price
            target_7 = round(cur_close * 1.07, 2)
            rr_ratio = round((target_7 - cur_close) / risk, 2) if risk > 0 else 0.0
            pos_size_5k = int(max(1, round(5000.0 / risk))) if risk > 0 else 1
            fo_ceiling = round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2)

            fund_score, accum_status = 0, "NEUTRAL"
            info = fundamentals.get(ticker, {})
            if not info:
                try: info = yf.Ticker(ticker).info
                except: info = {}
                
            raw_in = info.get('heldPercentInsiders', None)
            raw_inst = info.get('heldPercentInstitutions', None)
            raw_roe = info.get('returnOnEquity', None)
            raw_debt = info.get('debtToEquity', None)
            raw_growth = info.get('revenueGrowth', None)
            raw_q_growth = info.get('earningsQuarterlyGrowth', None)
            raw_pe = info.get('trailingPE', info.get('forwardPE', None))
            raw_bv = info.get('bookValue', None)
            raw_beta = info.get('beta', None)
            raw_div_yield = info.get('dividendYield', None)

            beta_val = round(float(raw_beta), 2) if raw_beta is not None else 1.05
            if raw_beta is None and not nifty_ret.empty and len(c) >= 252:
                try:
                    s_ret = c.pct_change().iloc[-252:]
                    aligned = pd.concat([s_ret, nifty_ret], axis=1).dropna()
                    if len(aligned) > 60:
                        cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1]
                        var = np.var(aligned.iloc[:, 1])
                        if var > 0: beta_val = round(float(np.clip(cov / var, 0.4, 2.5)), 2)
                except: pass

            events_list = []
            earnings_blackout = False
            post_earnings_breakout = False
            if is_recent_ipo:
                events_list.append("🆕 RECENT IPO")
            ex_div_ts = info.get('exDividendDate', None)
            if ex_div_ts:
                try:
                    ex_dt = datetime.datetime.fromtimestamp(int(ex_div_ts)).date()
                    days_to_div = (ex_dt - datetime.date.today()).days
                    if 0 <= days_to_div <= 10:
                        events_list.append(f"💰 EX-DIV SHIELD ({ex_dt.strftime('%d-%b')})")
                    elif -15 <= days_to_div <= 45:
                        events_list.append(f"💰 Ex-Div ({ex_dt.strftime('%d-%b')})")
                except: pass
            earnings_ts = info.get('earningsTimestamp', info.get('earningsTimestampStart', None))
            if earnings_ts:
                try:
                    e_dt = datetime.datetime.fromtimestamp(int(earnings_ts)).date()
                    days_to_earn = (e_dt - datetime.date.today()).days
                    if 0 <= days_to_earn <= 5:
                        earnings_blackout = True
                        events_list.append(f"🚨 EARNINGS BLACKOUT ({e_dt.strftime('%d-%b')})")
                    elif -5 <= days_to_earn < 0 and ret_1d > 0.015 and dsr >= 1.8:
                        post_earnings_breakout = True
                        events_list.append(f"🚀 POST-RESULT SURGE ({e_dt.strftime('%d-%b')})")
                    elif -3 <= days_to_earn <= 21:
                        events_list.append(f"📅 Board/Result ({e_dt.strftime('%d-%b')})")
                except: pass
            last_split = info.get('lastSplitDate', None)
            if last_split:
                try:
                    sp_dt = datetime.datetime.fromtimestamp(int(last_split)).date()
                    if (datetime.date.today() - sp_dt).days <= 60:
                        events_list.append(f"✂️ Split/Bonus ({sp_dt.strftime('%d-%b')})")
                except: pass
            corp_event_str = " | ".join(events_list) if events_list else "Regular Trading"

            if earnings_blackout:
                trading_verdict = "🚨 EARNINGS BLACKOUT (WAIT)"
            elif rr_ratio >= 2.0 and alert_type in ["⚡ VCP + VDU", "🚀 5x VOL AWAKENING", "🔥 DEAD BOTTOM"]:
                trading_verdict = f"🎯 STRONG BUY: ₹{round(cur_close, 2)}"
            elif rr_ratio >= 1.5 and alert_type not in ["Standard", "📉 DOWNTREND (Avoid)", "🚨 OVERBOUGHT (Caution)"]:
                trading_verdict = f"🟢 ACCUMULATE: ₹{round(cur_close, 2)}"
            elif alert_type == "🚨 OVERBOUGHT (Caution)":
                trading_verdict = "⚠️ TRIM / AVOID"
            elif alert_type == "📉 DOWNTREND (Avoid)":
                trading_verdict = "⛔ STRICT SKIP"
            else:
                trading_verdict = "⏳ WAIT"

            prom_curr = raw_in if raw_in is not None else 0.0
            fii_curr = raw_inst if raw_inst is not None else 0.0
            prom_old = oldest_records.get(symbol, {}).get('Prom_Pct', prom_curr)
            fii_old = oldest_records.get(symbol, {}).get('FII_Pct', fii_curr)
            prom_delta = round(prom_curr - prom_old, 4)
            fii_delta = round(fii_curr - fii_old, 4)
            today_memory_records.append({'Symbol': symbol, 'Date': datetime.date.today(), 'Prom_Pct': prom_curr, 'FII_Pct': fii_curr})
            
            insider_val = round(raw_in, 4) if raw_in is not None else ""
            inst_val = round(raw_inst, 4) if raw_inst is not None else ""
            roe_val = round(raw_roe, 4) if raw_roe is not None else ""
            debt_val = round(raw_debt, 2) if raw_debt is not None else ""
            pe_val = round(raw_pe, 2) if raw_pe is not None else ""
            bv_val = round(raw_bv, 2) if raw_bv is not None else ""
            div_yield_val = round(float(raw_div_yield), 4) if raw_div_yield is not None and raw_div_yield < 0.25 else (round(float(raw_div_yield)/100.0, 4) if raw_div_yield is not None else 0.0)
            
            # MATH CAP: Prevent low-base outlier spikes from exceeding ±300%
            growth_val = round(max(-3.0, min(3.0, float(raw_growth))), 4) if raw_growth is not None else ""
            q_growth_val = round(max(-3.0, min(3.0, float(raw_q_growth))), 4) if raw_q_growth is not None else ""
            
            if raw_in is not None and raw_in >= 0.50: fund_score += 30
            if raw_inst is not None and raw_inst >= 0.15: fund_score += 20
            if raw_roe is not None and raw_roe > 0.15: fund_score += 20
            if raw_debt is not None and raw_debt < 50: fund_score += 30
            
            if fund_score >= 70 and is_vdu and dist_from_52w_low < 0.30: accum_status = "💎 SILENT ACCUMULATION"
            elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"

            # 4-LOCK INSTITUTIONAL FEAR vs. TOXIC DUMP FILTER
            is_fundamentally_sound = (fund_score >= 50) or (raw_roe is not None and raw_roe >= 0.12) or (raw_in is not None and raw_in >= 0.50)
            is_toxic_dump = (ret_1d <= -0.05 and dsr >= 3.5)
            fear_event_score = 0.0
            catalyst_tag = "⚪ Normal Flow"
            if is_toxic_dump:
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
                elif -0.35 <= disc_from_52w_high <= -0.10 and rsi <= 40 and cur_close >= ema200 * 0.95:
                    fear_event_score = round(abs(disc_from_52w_high) * 300 + fund_score, 1)
                    catalyst_tag = f"💎 VALUE FEAR ZONE ({round(disc_from_52w_high*100,1)}% off High)"
                elif events_list and dsr >= 1.4:
                    fear_event_score = round(dsr * 25 + fund_score, 1)
                    catalyst_tag = f"🔥 EVENT + VOL SURGE ({round(dsr,1)}x Vol)"

            best_month, worst_month = "N/A", "N/A"
            try:
                c_monthly = c.groupby(c.index.to_period('M')).last()
                m_ret = c_monthly.pct_change().dropna()
                if len(m_ret) > 12:
                    m_names = m_ret.index.strftime('%B')
                    m_avg = m_ret.groupby(m_names).mean()
                    best_month = m_avg.idxmax()
                    worst_month = m_avg.idxmin()
            except: pass

            thematic_sector = classify_sector(symbol, row.get('Industry', 'Unknown'))

            return {
                'Symbol': symbol, 'Company': row.get('Company', symbol), 'Industry': thematic_sector,
                'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 'Entry Trigger': round(cur_close, 2),
                'Stop Loss': sl_price, 'Target 7%': target_7, 'F&O Ceiling': fo_ceiling,
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date, '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'R:R Ratio': rr_ratio, 'Pos Size (₹5k Risk)': pos_size_5k, 'RS vs Nifty': rs_vs_nifty,
                'Opportunity Score': fund_score, 'Stage': nbt_stage,
                'Accumulation Status': accum_status, 'Promoter Holding': insider_val, 'Promoter Delta': prom_delta,
                'FII/DII': inst_val, 'FII Delta': fii_delta, 'Dist from 52W Low': dist_from_52w_low, 'Disc from 52W High': disc_from_52w_high,
                'Debt-to-Eq': debt_val, 'Growth': growth_val, 'ROE': roe_val, 'PE Ratio': pe_val, 'Book Value': bv_val,
                'Div Yield': div_yield_val, 'QoQ Growth': q_growth_val, 'Volume Profile': "VDU" if is_vdu else "Normal",
                'Corp Event': corp_event_str, 'Catalyst Impact': catalyst_tag, 'Fear_Event_Score': fear_event_score,
                'Beta': beta_val, 'Ret_1D': ret_1d, 'Ret_5D': ret_5d, 'Ret_20D': ret_20d, 'Ret_50D': ret_50d,
                'Best_Month': best_month, 'Worst_Month': worst_month
            }
        except Exception: return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process, row): row for _, row in univ.iterrows()}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return
    
    new_mem_df = pd.DataFrame(today_memory_records)
    combined_mem = pd.concat([mem_df, new_mem_df]).drop_duplicates(subset=['Symbol', 'Date'], keep='last')
    combined_mem.to_csv(memory_file, index=False)

    # 3. SELECT SNIPER CANDIDATES & ENRICH WITH LIVE OVERNIGHT/INTRADAY NEWS HEADLINES
    top_swings = df[df['Trading Verdict'].str.contains("BUY|ACCUMULATE")].sort_values(by=["Trading Verdict", "R:R Ratio"], ascending=[False, False]).head(15)
    used_syms = set(top_swings['Symbol'].tolist())
    
    top_inc = df[(df['Accumulation Status'] != "NEUTRAL") & (~df['Symbol'].isin(used_syms))].sort_values(by="Opportunity Score", ascending=False).head(15)
    used_syms.update(top_inc['Symbol'].tolist())
    
    fear_candidates = df[(df['Fear_Event_Score'] > 0) & (~df['Symbol'].isin(used_syms))].sort_values(by="Fear_Event_Score", ascending=False).head(10)
    if len(fear_candidates) < 10:
        extra_needed = 10 - len(fear_candidates)
        fallback_fear = df[(~df['Symbol'].isin(used_syms)) & (~df['Symbol'].isin(fear_candidates['Symbol'])) & (df['Opportunity Score'] >= 50) & (~df['Catalyst Impact'].str.contains("TOXIC"))].sort_values(by="Ret_1D", ascending=True).head(extra_needed)
        fear_candidates = pd.concat([fear_candidates, fallback_fear])

    core_portfolio = {'PFC', 'RELIANCE', 'IRFC', 'IRB', 'MSUMI', 'NMDC', 'ITC', 'BEL'}
    priority_news_syms = set(top_swings['Symbol']).union(set(top_inc['Symbol'])).union(set(fear_candidates['Symbol'])).union(core_portfolio)
    event_syms = set(df[df['Corp Event'] != "Regular Trading"]['Symbol'].head(25))
    all_news_syms = priority_news_syms.union(event_syms)

    print(f"3. Harvesting Overnight & Intraday News Headlines for {len(all_news_syms)} priority stocks...")
    news_indices = df[df['Symbol'].isin(all_news_syms)].index.tolist()
    with ThreadPoolExecutor(max_workers=8) as news_exec:
        future_to_idx = {
            news_exec.submit(fetch_stock_news_catalyst, df.at[i, 'Symbol'], df.at[i, 'Company'], df.at[i, 'Catalyst Impact']): i
            for i in news_indices
        }
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                df.at[idx, 'Catalyst Impact'] = fut.result()
            except Exception:
                pass

    top_swings = df.loc[top_swings.index]
    top_inc = df.loc[top_inc.index]
    fear_candidates = df.loc[fear_candidates.index]

    # 1. SWINGS OUTPUT (Aligned perfectly with V11 Google Sheet)
    sw_cols = ["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "Pos Size (₹5k Risk)", "RS vs Nifty", "F&O Ceiling", "52W High", "52W High Date", "52W Low", "52W Low Date", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value", "Corp Event", "Catalyst Impact"]
    sw_df = df[sw_cols].sort_values(by="Trading Verdict", ascending=False)
    sw_df.to_csv("swings_output.csv", index=False)

    # 2. INCUBATOR OUTPUT
    inc_cols = ["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Div Yield", "Volume Profile", "Corp Event", "Catalyst Impact"]
    inc_df = df[df['Accumulation Status'] != "NEUTRAL"][inc_cols].sort_values(by="Opportunity Score", ascending=False)
    inc_df.to_csv("incubator_output.csv", index=False)

    # 3. SNIPER OUTPUT (40 Rows, 12 Columns aligned perfectly)
    sniper_rows = []
    for _, r in top_swings.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "MOMENTUM SWING", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], r['R:R Ratio'], r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in top_inc.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "10X MULTIBAGGER", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*2, 2), 5.0, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in fear_candidates.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "⚡ CONTRARIAN FEAR DIP / EVENT", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*1.10, 2), round(max(2.0, r['R:R Ratio']), 2), r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
        
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Trigger Price", "Stop Loss", "Target", "R:R Ratio", "RS vs Nifty", "52W High", "52W Low", "Catalyst / Fear Diagnosis", "Corporate Event"]).to_csv("sniper_output.csv", index=False)
    
    # 4. PROMOTER OUTPUT
    promoter_cols = ["Symbol", "Company", "Opportunity Score", "Promoter Holding", "Promoter Delta", "FII/DII", "FII Delta", "Debt-to-Eq", "ROE", "Div Yield", "Industry", "Beta", "Ret_20D", "Disc from 52W High"]
    df[promoter_cols].sort_values(by="Promoter Holding", ascending=False).to_csv("promoter_output.csv", index=False)

    # 5. SECTOR OUTPUT
    sector_df = df.groupby('Industry').agg(
        Total_Stocks=('Symbol', 'count'),
        Uptrend_Count=('Stage', lambda x: (x == 'PHASE 2: MARKUP').sum()),
        Avg_1D_Flow=('Ret_1D', lambda x: round(x.mean() * 100, 2)),
        Avg_5D_Flow=('Ret_5D', lambda x: round(x.mean() * 100, 2)),
        Avg_Money_Flow=('Ret_20D', lambda x: round(x.mean() * 100, 2)),
        Avg_50D_Flow=('Ret_50D', lambda x: round(x.mean() * 100, 2)),
        Hist_Best_Month=('Best_Month', lambda x: x.mode()[0] if not x.empty else "N/A"),
        Hist_Worst_Month=('Worst_Month', lambda x: x.mode()[0] if not x.empty else "N/A")
    ).reset_index()
    sector_df['ISAD (Breadth %)'] = round((sector_df['Uptrend_Count'] / sector_df['Total_Stocks']) * 100, 1)
    sector_df['Sector Status'] = np.where(sector_df['ISAD (Breadth %)'] > 40, "🔥 DOMINANT", np.where(sector_df['ISAD (Breadth %)'] < 15, "⚠️ WASHOUT", "🔄 EMERGING"))
    
    def get_cycle(industry):
        i = str(industry).lower()
        if any(x in i for x in ['defense', 'railway', 'capital goods', 'infrastructure', 'power']): return "Govt Capex & Defense Supercycle"
        if any(x in i for x in ['bank', 'financial', 'realt', 'auto']): return "Rate Cut & Credit Expansion Cycle"
        if any(x in i for x in ['ems', 'semiconductor', 'it ', 'technology', 'telecom']): return "PLI Manufacturing & Digital Export Cycle"
        if any(x in i for x in ['fmcg', 'consumer', 'pharma', 'healthcare']): return "Defensive Consumption & Margin Expansion"
        return "Idiosyncratic / Stock Specific"
        
    sector_df['2-Year Macro Prediction'] = sector_df['Industry'].apply(get_cycle)
    final_sector_cols = ['Industry', 'Sector Status', 'ISAD (Breadth %)', 'Avg_1D_Flow', 'Avg_5D_Flow', 'Avg_Money_Flow', 'Avg_50D_Flow', 'Hist_Best_Month', 'Hist_Worst_Month', '2-Year Macro Prediction']
    sector_df[final_sector_cols].sort_values(by=['ISAD (Breadth %)', 'Avg_1D_Flow'], ascending=[False, False]).to_csv("sector_output.csv", index=False)

if __name__ == "__main__":
    run_quantum_engine()
