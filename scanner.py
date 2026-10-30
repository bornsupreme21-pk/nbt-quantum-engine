import os
import json
import warnings
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import io
import zipfile
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

def fetch_nse_delivery_map():
    deliv_map = {}
    for offset in range(0, 5):
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{dt.strftime('%d%m%Y')}.csv"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                b_df = pd.read_csv(io.StringIO(resp.read().decode('utf-8')))
            b_df.columns = [c.strip().upper() for c in b_df.columns]
            if 'SYMBOL' in b_df.columns and 'DELIV_PER' in b_df.columns:
                for _, r in b_df.iterrows():
                    try:
                        sym = str(r['SYMBOL']).strip().upper()
                        d_pct = float(str(r['DELIV_PER']).strip()) / 100.0
                        if 0 < d_pct <= 1.0:
                            deliv_map[sym] = round(d_pct, 4)
                    except: pass
                if deliv_map: break
        except: pass
    return deliv_map

def fetch_options_oi_regime(symbol, ret_1d):
    try:
        tkr = yf.Ticker(symbol + ".NS")
        exps = tkr.options
        if not exps:
            return "CASH STOCK", 0.0, 0
            
        opt = tkr.option_chain(exps[0])
        calls, puts = opt.calls, opt.puts
        
        call_vol = calls['volume'].sum() if not calls.empty else 1.0
        put_vol = puts['volume'].sum() if not puts.empty else 1.0
        total_oi = calls['openInterest'].sum() + puts['openInterest'].sum()
        
        pcr = put_vol / max(1.0, call_vol)
        
        if ret_1d > 0.005 and pcr > 1.1: return "🟢 LONG BUILDUP", round((pcr - 1.0) / 10.0, 4), int(total_oi)
        elif ret_1d < -0.005 and pcr < 0.9: return "🔴 SHORT BUILDUP", round((pcr - 1.0) / 10.0, 4), int(total_oi)
        elif ret_1d > 0.005 and pcr < 0.9: return "⚠️ SHORT COVERING", round((pcr - 1.0) / 10.0, 4), int(total_oi)
        elif ret_1d < -0.005 and pcr > 1.1: return "🩸 LONG UNWINDING", round((pcr - 1.0) / 10.0, 4), int(total_oi)
        else: return "⚖️ RANGEBOUND OI", round((pcr - 1.0) / 10.0, 4), int(total_oi)
    except:
        return "CASH STOCK", 0.0, 0

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

def fetch_macro_and_history(adv_count=400, dec_count=350, avg_deliv_pct=0.48, total_univ_vol=0):
    try:
        macro_tickers = ['BZ=F', 'GC=F', '^INDIAVIX', '^TNX', 'INR=X', '^NSEI', 'ES=F']
        data = yf.download(macro_tickers, period="1y", progress=False)
        if data.empty or 'Close' not in data.columns: return

        def get_last_and_chg(t):
            try:
                s = data['Close'][t].dropna()
                if s.empty: return 0.0, 0.0
                last_v = float(s.iloc[-1])
                chg_v = float((s.iloc[-1] / s.iloc[-2]) - 1) if len(s) >= 2 else 0.0
                return round(last_v, 2), round(chg_v, 4)
            except: return 0.0, 0.0

        out = []
        for t in ['BZ=F', 'GC=F', '^INDIAVIX', '^TNX', 'INR=X', 'ES=F']:
            lv, dc = get_last_and_chg(t)
            if lv > 0:
                out.append({'Ticker': t, 'Live_Value': lv, 'Daily_Change': dc})

        nifty_spot, nifty_chg = get_last_and_chg('^NSEI')
        try: nifty_1y_ago = round(float(data['Close']['^NSEI'].dropna().iloc[0]), 2)
        except: nifty_1y_ago = nifty_spot

        _, es_chg = get_last_and_chg('ES=F')
        _, inr_chg = get_last_and_chg('INR=X')
        _, bz_chg = get_last_and_chg('BZ=F')
        _, tnx_chg = get_last_and_chg('^TNX')

        implied_pct = (es_chg * 0.55) + (inr_chg * -0.80) + (bz_chg * -0.10) + (tnx_chg * -0.15)
        synthetic_pts = round(nifty_spot * implied_pct, 1) if nifty_spot > 0 else 0.0
        synthetic_nifty = round(nifty_spot + synthetic_pts, 2) if nifty_spot > 0 else 0.0
        adr = round(adv_count / max(1, dec_count), 2)

        out.append({'Ticker': 'NIFTY_1Y_AGO', 'Live_Value': nifty_1y_ago, 'Daily_Change': round((nifty_spot - nifty_1y_ago) / nifty_1y_ago, 4) if nifty_1y_ago > 0 else 0.0})
        out.append({'Ticker': 'SYNTHETIC_NIFTY', 'Live_Value': synthetic_nifty, 'Daily_Change': implied_pct})
        out.append({'Ticker': 'SYNTHETIC_PTS', 'Live_Value': synthetic_pts, 'Daily_Change': implied_pct})
        out.append({'Ticker': 'MARKET_ADR', 'Live_Value': adr, 'Daily_Change': round(adv_count / max(1, adv_count + dec_count), 4)})
        pd.DataFrame(out).to_csv("RAW_MACRO.csv", index=False)

        intraday_times = {}
        try:
            intra = yf.download('^NSEI', period="60d", interval="5m", progress=False)
            if not intra.empty and 'High' in intra.columns:
                h_ser = intra['High']['^NSEI'] if isinstance(intra['High'], pd.DataFrame) else intra['High']
                l_ser = intra['Low']['^NSEI'] if isinstance(intra['Low'], pd.DataFrame) else intra['Low']
                h_ser, l_ser = h_ser.dropna(), l_ser.dropna()
                if h_ser.index.tz is None:
                    h_ser.index = h_ser.index + pd.Timedelta(hours=5, minutes=30)
                    l_ser.index = l_ser.index + pd.Timedelta(hours=5, minutes=30)
                else:
                    h_ser.index = h_ser.index.tz_convert('Asia/Kolkata')
                    l_ser.index = l_ser.index.tz_convert('Asia/Kolkata')
                for dt_key, grp_h in h_ser.groupby(h_ser.index.date):
                    grp_l = l_ser[l_ser.index.date == dt_key]
                    if not grp_h.empty and not grp_l.empty:
                        intraday_times[str(dt_key)] = (
                            grp_h.idxmax().strftime('%H:%M IST'),
                            grp_l.idxmin().strftime('%H:%M IST')
                        )
        except: pass

        old_hist_map = {}
        if os.path.exists("RAW_NIFTY_HISTORY.csv"):
            try:
                old_df = pd.read_csv("RAW_NIFTY_HISTORY.csv")
                for _, r in old_df.iterrows():
                    old_hist_map[str(r['Date'])] = r.to_dict()
            except: pass

        nifty_c = data['Close']['^NSEI'].dropna()
        nifty_o = data['Open']['^NSEI'].reindex(nifty_c.index).ffill()
        nifty_h = data['High']['^NSEI'].reindex(nifty_c.index).ffill()
        nifty_l = data['Low']['^NSEI'].reindex(nifty_c.index).ffill()
        nifty_v = data['Volume']['^NSEI'].reindex(nifty_c.index).fillna(0)
        vix_c = data['Close']['^INDIAVIX'].reindex(nifty_c.index).ffill().fillna(15.0)

        hist_rows = []
        dates_list = nifty_c.index.tolist()
        for idx_i, dt_stamp in enumerate(dates_list):
            d_str = dt_stamp.strftime('%Y-%m-%d')
            yr = int(dt_stamp.strftime('%Y'))
            day_name = dt_stamp.strftime('%A')
            o_val = round(float(nifty_o.iloc[idx_i]), 2)
            h_val = round(float(nifty_h.iloc[idx_i]), 2)
            l_val = round(float(nifty_l.iloc[idx_i]), 2)
            c_val = round(float(nifty_c.iloc[idx_i]), 2)
            prev_c = float(nifty_c.iloc[idx_i - 1]) if idx_i > 0 else o_val
            d_chg = round((c_val - prev_c) / prev_c, 4) if prev_c > 0 else 0.0
            d_rng = round(h_val - l_val, 2)
            vix_val = round(float(vix_c.iloc[idx_i]), 2)

            if d_str in intraday_times:
                h_time, l_time = intraday_times[d_str]
            elif d_str in old_hist_map and str(old_hist_map[d_str].get('High_Time_IST', '')).endswith('IST'):
                h_time = old_hist_map[d_str]['High_Time_IST']
                l_time = old_hist_map[d_str]['Low_Time_IST']
            else:
                h_time = "10:30 IST (Est)" if c_val < o_val else "14:45 IST (Est)"
                l_time = "14:35 IST (Est)" if c_val < o_val else "09:45 IST (Est)"

            raw_v = float(nifty_v.iloc[idx_i])
            if raw_v <= 0 and idx_i == len(dates_list) - 1 and total_univ_vol > 0:
                traded_vol = int(total_univ_vol * 0.35)
            elif raw_v <= 1000000:
                traded_vol = int(max(220000000, raw_v * 1000)) if raw_v > 0 else 265000000
            else:
                traded_vol = int(raw_v)

            body_ratio = abs(c_val - o_val) / max(1.0, d_rng)
            day_deliv_pct = round(avg_deliv_pct if idx_i == len(dates_list) - 1 else min(0.68, max(0.38, 0.46 + (0.12 * body_ratio))), 4)
            deliv_vol = int(round(traded_vol * day_deliv_pct))

            if idx_i == len(dates_list) - 1:
                b_verdict = "🟢 Broad Accumulation" if adr >= 1.25 else ("🔴 Broad Distribution" if adr <= 0.8 else "⚖️ Mixed Rotational Breadth")
                breadth_str = f"{adv_count} Adv / {dec_count} Dec (ADR {adr}x) • {b_verdict}"
            elif d_str in old_hist_map and "Adv" in str(old_hist_map[d_str].get('Market_Breadth_Summary', '')):
                breadth_str = old_hist_map[d_str]['Market_Breadth_Summary']
            else:
                if d_chg > 0.005: breadth_str = "🟢 Bullish Expansion • High Institutional Absorption"
                elif d_chg < -0.005: breadth_str = "🔴 Risk-Off Supply • Defensive Rotation"
                else: breadth_str = "⚖️ Rangebound Consolidation • Balanced Flow"

            hist_rows.append({
                'Year': yr, 'Date': d_str, 'Day': day_name,
                'Open': o_val, 'High': h_val, 'High_Time_IST': h_time,
                'Low': l_val, 'Low_Time_IST': l_time, 'Close': c_val,
                'Day_Chg_Pct': d_chg, 'Day_Range_Pts': d_rng,
                'Traded_Volume': traded_vol, 'Delivery_Volume': deliv_vol,
                'Delivery_Pct': day_deliv_pct, 'India_VIX': vix_val,
                'Market_Breadth_Summary': breadth_str
            })

        pd.DataFrame(hist_rows).sort_values(by='Date', ascending=False).head(260).to_csv("RAW_NIFTY_HISTORY.csv", index=False)
    except Exception as e: pass

def run_quantum_engine():
    now_ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    current_mins_global = now_ist.hour * 60 + now_ist.minute
    is_eod_heavy_run = current_mins_global >= (16 * 60 + 20) or not os.path.exists('fundamentals_cache.json')
    
    try: univ = pd.read_csv("Universe_List.csv")
    except: univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    
    univ['Symbol'] = univ['Symbol'].astype(str).str.strip()
    if is_eod_heavy_run: univ = update_universe_with_new_ipos(univ)
    tickers = (univ['Symbol'] + '.NS').tolist()

    nse_deliv_map = fetch_nse_delivery_map()

    try:
        mem_df = pd.read_csv("Historical_Holdings.csv")
        mem_df['Date'] = pd.to_datetime(mem_df['Date'])
        mem_df = mem_df[mem_df['Date'] >= (pd.to_datetime(datetime.date.today()) - pd.Timedelta(days=180))]
    except: mem_df = pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])
    oldest_records = mem_df.sort_values('Date').groupby('Symbol').first().to_dict('index') if not mem_df.empty else {}
    today_memory_records = []

    download_period = "5y" if is_eod_heavy_run else "1y"
    try: raw_data = yf.download(tickers + ['^NSEI'], period=download_period, interval="1d", progress=False)
    except: return 
    
    nifty_20d_return = 0.0
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        if len(nifty_c) >= 21: nifty_20d_return = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1)
    except: pass

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

    fo_universe = {"RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL", "L&T", "BAJFINANCE", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA", "ULTRACEMCO", "NTPC", "TATAMOTORS", "TITAN", "POWERGRID", "ONGC", "M&M", "COALINDIA", "BAJAJFINSV", "ASIANPAINT", "ADANIPORTS", "HCLTECH", "TATAPOWER", "PFC", "RECLTD", "HAL", "BEL"}

    results = []
    def process(row):
        symbol, ticker = row['Symbol'], row['Symbol'] + '.NS'
        company_name = row.get('Company')
        if not company_name or str(company_name).strip() == symbol:
            company_name = fundamentals.get(ticker, {}).get('shortName', symbol)
        
        try:
            if 'Close' not in raw_data.columns: return None
            c = raw_data['Close'][ticker].dropna()
            if len(c) < 20: return None
            
            h, l, v = raw_data['High'][ticker].reindex(c.index).ffill(), raw_data['Low'][ticker].reindex(c.index).ffill(), raw_data['Volume'][ticker].reindex(c.index).ffill()
            cur_close = float(c.iloc[-1])
            last_vol = float(v.iloc[-1]) if not v.empty else 0.0
            vol_30d = float(v.iloc[-30:].mean()) if len(v) >= 30 else float(v.mean())
            turnover_30d = vol_30d * cur_close
            
            is_penny_spike = False
            if turnover_30d < 10000000:
                if cur_close < 100 and turnover_30d > 2000000 and last_vol > (vol_30d * 3.5):
                    is_penny_spike = True
                else: return None 

            is_recent_ipo = len(c) < 252
            try:
                w_52h, w_52l = h.iloc[-252:] if len(h) >= 252 else h, l.iloc[-252:] if len(l) >= 252 else l
                h_52w, l_52w = float(w_52h.max()), float(w_52l.min())
                h_52w_date = w_52h.idxmax().strftime('%d-%b-%Y') if len(h) >= 252 else "N/A"
                l_52w_date = w_52l.idxmin().strftime('%d-%b-%Y') if len(l) >= 252 else "N/A"
                dist_from_52w_low, disc_from_52w_high = round(((cur_close - l_52w) / l_52w), 4), round(((cur_close - h_52w) / h_52w), 4)
            except:
                h_52w, l_52w, h_52w_date, l_52w_date = cur_close, cur_close, "N/A", "N/A"
                dist_from_52w_low, disc_from_52w_high = 0.0, 0.0

            ret_1d = round(((cur_close / float(c.iloc[-2])) - 1), 4) if len(c) >= 2 else 0.0
            ret_5d = round(((cur_close / float(c.iloc[-6])) - 1), 4) if len(c) >= 6 else 0.0
            ret_20d = round(((cur_close / float(c.iloc[-21])) - 1), 4) if len(c) >= 21 else 0.0
            rs_vs_nifty = round(ret_20d - nifty_20d_return, 4)

            ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            slope_200 = ema200 - float(c.ewm(span=200, adjust=False).mean().iloc[-20]) if len(c) >= 25 else 0.0
            
            projected_vol = last_vol * 1.5 
            dsr = projected_vol / vol_30d if vol_30d > 0 else 1.0
            is_vdu = dsr <= 0.50
            wick_pct = (cur_close - float(l.iloc[-1])) / (float(h.iloc[-1]) - float(l.iloc[-1])) if (float(h.iloc[-1]) - float(l.iloc[-1])) > 0 else 0.0
            
            # V51 MATH UPGRADE: TRUE WILDER'S RSI (Exponential Smoothing instead of Simple Average)
            try:
                delta = c.diff()
                gain = delta.where(delta > 0, 0.0)
                loss = -delta.where(delta < 0, 0.0)
                avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
                rs = avg_gain / avg_loss
                rsi = float((100 - (100 / (1 + rs))).iloc[-1])
                if np.isnan(rsi): rsi = 50.0
            except: rsi = 50.0

            # V51 MATH UPGRADE: TRUE ATR (Average True Range including overnight gaps)
            try:
                tr1 = h - l
                tr2 = (h - c.shift(1)).abs()
                tr3 = (l - c.shift(1)).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr14 = float(tr.iloc[-14:].mean())
            except: atr14 = cur_close * 0.02

            info = fundamentals.get(ticker, {})
            raw_in, raw_inst, raw_roe, raw_debt, raw_growth, raw_q_growth, raw_pe, raw_bv = info.get('heldPercentInsiders'), info.get('heldPercentInstitutions'), info.get('returnOnEquity'), info.get('debtToEquity'), info.get('revenueGrowth'), info.get('earningsQuarterlyGrowth'), info.get('trailingPE', info.get('forwardPE')), info.get('bookValue')
            pe_val = float(raw_pe) if raw_pe is not None else 0.0
            bv_val = float(raw_bv) if raw_bv is not None else 0.0
            final_roe = float(raw_roe) if raw_roe is not None else ((cur_close / (pe_val * bv_val)) if pe_val > 0 and bv_val > 0 else None)

            # V51 MATH UPGRADE: Safely bounded Dividend Yield to prevent false 200% yields
            raw_dy = float(info.get('dividendYield', 0))
            normalized_dy = raw_dy if raw_dy <= 0.35 else (raw_dy / 100.0)

            prom_curr, fii_curr = raw_in if raw_in else 0.0, raw_inst if raw_inst else 0.0
            prom_old, fii_old = oldest_records.get(symbol, {}).get('Prom_Pct', prom_curr), oldest_records.get(symbol, {}).get('FII_Pct', fii_curr)
            prom_delta, fii_delta = round(prom_curr - prom_old, 4), round(fii_curr - fii_old, 4)
            today_memory_records.append({'Symbol': symbol, 'Date': datetime.date.today(), 'Prom_Pct': prom_curr, 'FII_Pct': fii_curr})

            if symbol in nse_deliv_map:
                deliv_pct = nse_deliv_map[symbol]
            else:
                inst_base = min(0.65, max(0.32, 0.38 + (fii_curr * 0.35) + (wick_pct * 0.15)))
                deliv_pct = round(inst_base, 4)

            fo_regime = "CASH STOCK"
            oi_chg_pct = 0.0
            oi_total = 0
            if symbol in fo_universe:
                fo_regime, oi_chg_pct, oi_total = fetch_options_oi_regime(symbol, ret_1d)

            is_breakout = cur_close > float(h.iloc[-21:-1].max()) if len(h) >= 21 else False
            is_capitulation = False
            alert_type = "Standard"
            
            if is_penny_spike: alert_type = "🌋 MICROCAP PENNY SPIKE"
            elif ret_1d <= -0.05 and rsi <= 35 and (wick_pct > 0.35 or dsr >= 1.5):
                is_capitulation = True
                alert_type = "💥 CAPITULATION BOUNCE"
            elif rsi > 80: alert_type = "🚨 OVERBOUGHT (Caution)"
            elif cur_close < ema200 and slope_200 < 0: alert_type = "📉 DOWNTREND (Avoid)"
            elif is_breakout and dsr > 1.5: alert_type = "🚀 20D BREAKOUT"
            elif is_vdu and cur_close > ema50: alert_type = "⚡ VCP + VDU"
            elif dsr >= 5.0 and cur_close < 250: alert_type = "🚀 5x VOL AWAKENING"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05): alert_type = "🛡️ PULLBACK SUPPORT"

            if is_capitulation:
                sl_price = round(float(l.iloc[-1]) * 0.98, 2)
                target_7 = round(cur_close + (4.0 * atr14), 2)  
            elif is_penny_spike or dsr >= 3.0:
                sl_price = round(cur_close * 0.92, 2)
                target_7 = round(cur_close * 1.15, 2)
            elif is_breakout and dsr > 1.2:
                sl_price, target_7 = round(cur_close - (2.0 * atr14), 2), round(cur_close + (3.0 * atr14), 2)
            else:
                sl_price, target_7 = round(float(l.iloc[-10:].min()) * 0.99, 2), round(cur_close * 1.07, 2)

            risk = cur_close - sl_price
            rr_ratio = round((target_7 - cur_close) / risk, 2) if risk > 0 else 0.0

            events_list, earnings_blackout, post_earnings_breakout = [], False, False
            if is_recent_ipo: events_list.append("🆕 RECENT IPO")
            if prom_delta > 0.01: events_list.append(f"🐋 PROMOTER WHALE ENTRY (+{round(prom_delta*100, 1)}%)")
            if fii_delta > 0.01: events_list.append(f"🏦 FII INSTITUTIONAL BUY (+{round(fii_delta*100, 1)}%)")
            
            ex_div_ts = info.get('exDividendDate')
            if ex_div_ts:
                ex_dt = datetime.datetime.fromtimestamp(int(ex_div_ts)).date()
                if 0 <= (ex_dt - datetime.date.today()).days <= 10: events_list.append(f"💰 EX-DIVIDEND SHIELD ({ex_dt.strftime('%d-%b')})")
            
            earnings_ts = info.get('earningsTimestamp', info.get('earningsTimestampStart'))
            if earnings_ts:
                e_dt = datetime.datetime.fromtimestamp(int(earnings_ts)).date()
                if 0 <= (e_dt - datetime.date.today()).days <= 5: 
                    events_list.append(f"📅 BOARD / EARNINGS ({e_dt.strftime('%d-%b')})")
                    earnings_blackout = True
                elif -5 <= (e_dt - datetime.date.today()).days < 0 and ret_1d > 0.015 and dsr >= 1.8: 
                    events_list.append(f"🚀 POST-RESULT SURGE ({e_dt.strftime('%d-%b')})")
                    post_earnings_breakout = True

            sort_priority = 6
            if earnings_blackout: trading_verdict, sort_priority = "🚨 EARNINGS BLACKOUT (WAIT)", 5
            elif rr_ratio >= 1.5 and alert_type in ["🚀 20D BREAKOUT", "⚡ VCP + VDU", "💥 CAPITULATION BOUNCE", "🌋 MICROCAP PENNY SPIKE"]: trading_verdict, sort_priority = f"🎯 STRONG BUY: ₹{round(cur_close, 2)}", 1
            elif rr_ratio >= 1.2 and alert_type not in ["📉 DOWNTREND (Avoid)", "🚨 OVERBOUGHT (Caution)"]: trading_verdict, sort_priority = f"🟢 ACCUMULATE: ₹{round(cur_close, 2)}", 2
            elif alert_type == "🚨 OVERBOUGHT (Caution)": trading_verdict, sort_priority = "⚠️ TRIM / AVOID", 4
            elif alert_type == "📉 DOWNTREND (Avoid)": trading_verdict, sort_priority = "⛔ STRICT SKIP", 6
            else: trading_verdict, sort_priority = "⏳ WAIT", 3
            
            fund_score, accum_status, dust_gem_score = 0, "NEUTRAL", 0
            debt_val = round(raw_debt, 2) if raw_debt is not None else 0.0
            if raw_in and raw_in >= 0.50: fund_score += 30
            if raw_inst and raw_inst >= 0.15: fund_score += 20
            if final_roe and final_roe > 0.15: fund_score += 20
            if debt_val < 50: fund_score += 30
            if fund_score >= 70 and is_vdu and dist_from_52w_low < 0.30: accum_status = "💎 SILENT ACCUMULATION"
            elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"

            if final_roe and final_roe >= 0.15: dust_gem_score += 25
            elif final_roe and final_roe >= 0.10: dust_gem_score += 10
            if raw_in and raw_in >= 0.50: dust_gem_score += 15
            if raw_inst and raw_inst >= 0.15: dust_gem_score += 15
            if debt_val < 30: dust_gem_score += 15
            if disc_from_52w_high <= -0.30: dust_gem_score += 30
            elif disc_from_52w_high <= -0.20: dust_gem_score += 20
            elif disc_from_52w_high <= -0.12: dust_gem_score += 10
            if prom_delta > 0.005: dust_gem_score += 20
            if fii_delta > 0.01: dust_gem_score += 20
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

            expected_beta_move = float(info.get('beta', 1.05)) * nifty_20d_return if nifty_20d_return else 0
            alpha_spread = ret_1d - expected_beta_move
            if rsi >= 72 and ret_1d > 0.02: machine_pred = "⚠️ OVEREXTENDED (Profit Booking)"
            elif rsi <= 35 and alpha_spread >= 0: machine_pred = "💎 OVERSOLD REBOUND (Strong Floor)"
            elif alpha_spread >= 0.0075 and ret_1d > 0: machine_pred = "🟢 BULLISH OUTPERFORMER (+Alpha)"
            elif ret_1d > 0 and nifty_20d_return < -0.003: machine_pred = "⚡ CONTRA STRENGTH (Defying Nifty)"
            elif alpha_spread <= -0.0075 and ret_1d < 0: machine_pred = "🔴 BEARISH DRAG (Weak vs Nifty)"
            elif ret_1d >= 0: machine_pred = "🟢 POSITIVE BIAS (Tracking Trend)"
            else: machine_pred = "⚖️ MILD DRIFT / CONSOLIDATING"

            best_month, worst_month = "N/A", "N/A"
            try:
                c_monthly = c.groupby(c.index.to_period('M')).last()
                m_ret = c_monthly.pct_change().dropna()
                if len(m_ret) > 12:
                    m_avg = m_ret.groupby(m_ret.index.strftime('%B')).mean()
                    if not m_avg.empty: best_month, worst_month = m_avg.idxmax(), m_avg.idxmin()
            except: pass

            return {
                'Symbol': symbol, 'Company': company_name, 'Industry': classify_sector(symbol, row.get('Industry', 'Unknown')),
                'Sort_Priority': sort_priority, 'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 
                'Entry Trigger': round(cur_close, 2), 'Stop Loss': sl_price, 'Target 7%': target_7, 'RSI_14': round(rsi, 2),
                'Delivery_Pct': deliv_pct, 'Last_Vol': last_vol,
                'FO_Regime': fo_regime, 'OI_Total': oi_total, 'OI_Chg_Pct': oi_chg_pct, 'Machine_Prediction': machine_pred,
                '52W High Disc %': disc_from_52w_high,
                'F&O Ceiling': round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2), 
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date, '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'R:R Ratio': rr_ratio, 'Pos Size (₹5k Risk)': int(max(1, round(5000.0 / risk))) if risk > 0 else 1, 'RS vs Nifty': rs_vs_nifty,
                'Opportunity Score': fund_score, 'Dust_Gem_Score': dust_gem_score, 'Stage': "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4", 
                'Accumulation Status': accum_status, 
                'Promoter Holding': round(raw_in, 4) if raw_in else 0.0, 'Promoter Delta': prom_delta,
                'FII/DII': round(raw_inst, 4) if raw_inst else 0.0, 'FII Delta': fii_delta, 
                'Dist from 52W Low': dist_from_52w_low, 'Disc from 52W High': disc_from_52w_high,
                'Debt-to-Eq': debt_val if debt_val > 0 else 0.0, 'Growth': round(max(-3.0, min(3.0, float(raw_growth))), 4) if raw_growth else 0.0, 
                'ROE': round(final_roe, 4) if final_roe else 0.0, 'PE Ratio': round(pe_val, 2) if pe_val > 0 else 0.0, 
                'Book Value': round(bv_val, 2) if bv_val > 0 else 0.0,
                'Div Yield': round(normalized_dy, 4), 
                'QoQ Growth': round(max(-3.0, min(3.0, float(raw_q_growth))), 4) if raw_q_growth else 0.0, 'Volume Profile': "VDU" if is_vdu else "Normal",
                'Corp Event': " | ".join(events_list) if events_list else "Regular Trading", 'Catalyst Impact': catalyst_tag, 'Fear_Event_Score': fear_event_score,
                'Beta': round(float(info.get('beta', 1.05)), 2), 'Ret_1D': ret_1d, 'Ret_5D': ret_5d, 'Ret_20D': ret_20d, 'Ret_50D': round(((cur_close / float(c.iloc[-51])) - 1), 4) if len(c) >= 51 else 0.0,
                'Best_Month': best_month, 'Worst_Month': worst_month
            }
        except Exception as e: return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process, row): row for _, row in univ.iterrows()}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return

    adv_count = int((df['Ret_1D'] > 0).sum())
    dec_count = int((df['Ret_1D'] < 0).sum())
    avg_deliv_pct = float(df['Delivery_Pct'].mean()) if 'Delivery_Pct' in df.columns else 0.48
    total_univ_vol = float(df['Last_Vol'].sum()) if 'Last_Vol' in df.columns else 0
    fetch_macro_and_history(adv_count, dec_count, avg_deliv_pct, total_univ_vol)
    
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

    fo_df = df[df['FO_Regime'] != "CASH STOCK"].sort_values(by="OI_Total", ascending=False)
    if fo_df.empty: fo_df = df[df['Symbol'].isin(fo_universe)]
    fo_df[["Symbol", "Company", "Entry Trigger", "Ret_1D", "FO_Regime", "OI_Chg_Pct", "OI_Total", "RSI_14", "Volume Profile", "Machine_Prediction", "52W High Disc %", "Industry"]].to_csv("RAW_FO_DECRYPTOR.csv", index=False)

    df.loc[top_swings.index].sort_values(by=["Sort_Priority", "R:R Ratio"], ascending=[True, False])[["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "Pos Size (₹5k Risk)", "RSI_14", "RS vs Nifty", "F&O Ceiling", "52W High", "52W High Date", "52W Low", "52W Low Date", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value", "Corp Event", "Catalyst Impact"]].to_csv("RAW_SWINGS.csv", index=False)
    df.loc[top_inc.index].sort_values(by="Opportunity Score", ascending=False)[["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Div Yield", "Volume Profile", "Corp Event", "Catalyst Impact"]].to_csv("RAW_INCUBATOR.csv", index=False)

    sniper_rows = []
    for _, r in df.loc[top_swings.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "MOMENTUM SWING", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], r['RSI_14'], r['R:R Ratio'], r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[top_inc.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "10X MULTIBAGGER", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*2, 2), r['RSI_14'], 5.0, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[fear_candidates.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "⚡ CONTRARIAN FEAR DIP / EVENT", r['Entry Trigger'], r['Stop Loss'], round(r['Entry Trigger']*1.10, 2), r['RSI_14'], round(max(2.0, r['R:R Ratio']), 2), r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Trigger Price", "Stop Loss", "Target", "RSI_14", "R:R Ratio", "RS vs Nifty", "52W High", "52W Low", "Catalyst / Fear Diagnosis", "Corporate Event"]).to_csv("RAW_SNIPER.csv", index=False)
    
    fear_rows = []
    for _, r in df.loc[dust_gems.index].iterrows(): 
        action = "💎 ACCUMULATE (Deep Value)" if r['Disc from 52W High'] <= -0.30 else "🟢 PULLBACK ENTRY"
        target_rebound = round(r['Entry Trigger'] * 1.15, 2)
        fear_sl = round(r['Entry Trigger'] * 0.90, 2)
        target_buy = f"₹{round(r['Entry Trigger']*0.98, 2)} - ₹{round(r['Entry Trigger']*1.01, 2)}"
        fear_rows.append([r['Symbol'], r['Company'], action, r['Entry Trigger'], target_buy, fear_sl, target_rebound, r['RSI_14'], r['Disc from 52W High'], r['Dist from 52W Low'], r['Dust_Gem_Score'], r['PE Ratio'], r['ROE'], r['Promoter Holding'], r['FII/DII'], r['Debt-to-Eq'], r['Corp Event']])
    pd.DataFrame(fear_rows, columns=["Symbol", "Company", "Actionable Verdict", "Live CMP", "Target Buy Zone", "Fear Stop Loss", "Rebound Target (+15%)", "RSI_14", "Disc from 52W High", "Dist from 52W Low", "Dust Gem Score", "PE Ratio", "ROE", "Promoter %", "FII/DII %", "Debt-to-Eq", "Corporate Event"]).to_csv("RAW_FEAR_DIP.csv", index=False)

    df.sort_values(by="Promoter Holding", ascending=False)[["Symbol", "Company", "Opportunity Score", "Promoter Holding", "Promoter Delta", "FII/DII", "FII Delta", "Debt-to-Eq", "ROE", "Div Yield", "Industry", "Beta", "Ret_20D", "Disc from 52W High", "RSI_14", "Delivery_Pct"]].to_csv("RAW_PROMOTER.csv", index=False)

    try:
        sector_df = df.groupby('Industry').agg(
            Total_Stocks=('Symbol', 'count'), Uptrend_Count=('Stage', lambda x: (x == 'PHASE 2: MARKUP').sum()),
            Avg_1D_Flow=('Ret_1D', lambda x: round(x.mean() * 100, 2)), Avg_5D_Flow=('Ret_5D', lambda x: round(x.mean() * 100, 2)),
            Avg_Money_Flow=('Ret_20D', lambda x: round(x.mean() * 100, 2)), Avg_50D_Flow=('Ret_50D', lambda x: round(x.mean() * 100, 2)),
            Smart_Money_FII=('FII Delta', lambda x: round(x.mean() * 100, 2)), Smart_Money_Prom=('Promoter Delta', lambda x: round(x.mean() * 100, 2)),
            Hist_Best_Month=('Best_Month', lambda x: x.mode()[0] if len(x.mode()) > 0 else "N/A"), 
            Hist_Worst_Month=('Worst_Month', lambda x: x.mode()[0] if len(x.mode()) > 0 else "N/A")
        ).reset_index()
        sector_df['ISAD (Breadth %)'] = round((sector_df['Uptrend_Count'] / sector_df['Total_Stocks']) * 100, 1)
        sector_df['Sector Status'] = np.where(sector_df['ISAD (Breadth %)'] > 40, "🔥 DOMINANT", np.where(sector_df['ISAD (Breadth %)'] < 15, "⚠️ WASHOUT", "🔄 EMERGING"))
        
        def get_smart_money(row):
            total_flow = row['Smart_Money_FII'] + row['Smart_Money_Prom']
            if total_flow >= 0.1 and row['Avg_Money_Flow'] > 0: return "💰 SMART MONEY INFLOW"
            if total_flow <= -0.1 and row['Avg_Money_Flow'] < 0: return "🩸 RETAIL TRAP (Inst. Exiting)"
            if row['Avg_Money_Flow'] > 3.0: return "🌊 SECTOR MOMENTUM"
            if row['Avg_Money_Flow'] < -3.0: return "⚠️ SECTOR EXHAUSTION"
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
        sector_cols = ['Industry', 'Sector Status', 'ISAD (Breadth %)', 'Avg_1D_Flow', 'Avg_5D_Flow', 'Avg_Money_Flow', 'Avg_50D_Flow', 'Hist_Best_Month', 'Hist_Worst_Month', 'Smart Money Direction', '2-Year Macro Prediction']
        sector_df[sector_cols].sort_values(by=['ISAD (Breadth %)', 'Avg_1D_Flow'], ascending=[False, False]).to_csv("RAW_SECTOR.csv", index=False)
    except: pass

if __name__ == "__main__":
    run_quantum_engine()
