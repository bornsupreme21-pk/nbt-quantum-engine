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
    'SBIN': 'PSU Banks', 'BOB': 'PSU Banks', 'PNB': 'PSU Banks', 'INDIANB': 'PSU Banks', 'BANKBARODA': 'PSU Banks', 'CANBK': 'PSU Banks', 'UNIONBANK': 'PSU Banks',
    'HDFCBANK': 'Private Banks', 'ICICIBANK': 'Private Banks', 'AXISBANK': 'Private Banks', 'KOTAKBANK': 'Private Banks',
    'DIXON': 'EMS & Semiconductors', 'KAYNES': 'EMS & Semiconductors', 'SYRMA': 'EMS & Semiconductors',
    'PFC': 'Power, Renewables & PSU', 'RECLTD': 'Power, Renewables & PSU', 'NTPC': 'Power, Renewables & PSU', 'TATAPOWER': 'Power, Renewables & PSU', 'NHPC': 'Power, Renewables & PSU'
}

GOVT_KEYWORDS = ['cabinet', 'govt', 'government', 'pib', 'ministry', 'rbi', 'sebi', 'pli', 'subsidy', 'tender', 'psu', 'railway', 'defence', 'defense', 'nhai', 'ntpc', 'budget', 'gst', 'duty', 'rate cut', 'restructuring', 'disinvestment']
BULL_KEYWORDS = ['order', 'win', 'bag', 'profit', 'surge', 'jump', 'dividend', 'bonus', 'split', 'upgrade', 'buy', 'approval', 'acquire', 'expansion', 'record', 'mou', 'partner', 'launch']
BEAR_KEYWORDS = ['loss', 'fall', 'drop', 'penalty', 'raid', 'fraud', 'downgrade', 'default', 'resign', 'pledge', 'ban', 'notice', 'probe', 'fire', 'strike', 'weak']

def classify_sector(symbol, raw_industry):
    sym = str(symbol).upper().strip()
    if sym in THEMATIC_MAP: return THEMATIC_MAP[sym]
    if pd.isna(raw_industry): return 'NSE Core Equity'
    ind = str(raw_industry).strip()
    return ind if ind not in ['Unknown', '', 'nan', 'None'] else 'NSE Core Equity'

def clean_and_update_universe(univ_df):
    univ_df['Symbol'] = univ_df['Symbol'].astype(str).str.strip().str.upper()
    if 'Industry' in univ_df.columns:
        bloated_tags = ['Diversified / Microcap', 'Diversified / Emerging', '🚀 BEYOND-750: Emerging', 'Diversified / IPO']
        core_df = univ_df[~univ_df['Industry'].astype(str).str.strip().isin(bloated_tags)].copy()
        if len(core_df) >= 400:
            univ_df = core_df.drop_duplicates(subset=['Symbol'], keep='first').head(780)
    
    existing_symbols = set(univ_df['Symbol'].tolist())
    new_rows = []
    yf_urls = [
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers_in&count=100",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives_in&count=100"
    ]
    for u in yf_urls:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            quotes = data.get('finance', {}).get('result', [{}])[0].get('quotes', [])
            for q in quotes:
                sym = str(q.get('symbol', '')).upper()
                if sym.endswith('.NS'):
                    clean_sym = sym.replace('.NS', '').strip()
                    if clean_sym and clean_sym not in existing_symbols and len(univ_df) + len(new_rows) < 950:
                        name = str(q.get('shortName', q.get('longName', clean_sym))).strip()
                        new_rows.append({'Company': name, 'Industry': '🚀 BEYOND-750: Dynamic Mover', 'Symbol': clean_sym})
                        existing_symbols.add(clean_sym)
        except: pass

    try:
        req = urllib.request.Request("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as response:
            nse_df = pd.read_csv(io.StringIO(response.read().decode('utf-8')))
        nse_df.columns = [c.strip().upper() for c in nse_df.columns]
        if 'SERIES' in nse_df.columns:
            nse_df = nse_df[nse_df['SERIES'].astype(str).str.strip() == 'EQ']
        for _, row in nse_df.iterrows():
            sym = str(row['SYMBOL']).strip().upper()
            if sym not in existing_symbols and len(univ_df) + len(new_rows) < 1050:
                new_rows.append({'Company': str(row['NAME OF COMPANY']).strip(), 'Industry': '🚀 BEYOND-750: Emerging', 'Symbol': sym})
                existing_symbols.add(sym)
    except: pass

    if new_rows:
        univ_df = pd.concat([univ_df, pd.DataFrame(new_rows)], ignore_index=True)
    univ_df.to_csv("Universe_List.csv", index=False)
    return univ_df

def fetch_nse_delivery_map():
    deliv_map = {}
    for offset in range(0, 5):
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        for host in ["https://nsearchives.nseindia.com", "https://archives.nseindia.com"]:
            url = f"{host}/products/content/sec_bhavdata_full_{dt.strftime('%d%m%Y')}.csv"
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
                    if deliv_map: return deliv_map
            except: pass
    return deliv_map

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
            elif d_str in old_hist_map and "Adv" in old_hist_map[d_str].get('Market_Breadth_Summary', ''):
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

def export_alpha_hunter(df, raw_data):
    if df.empty or 'Close' not in raw_data.columns:
        return
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        n_ret_5d = float((nifty_c.iloc[-1] / nifty_c.iloc[-6]) - 1) if len(nifty_c) >= 6 else 0.0
        n_ret_20d = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1) if len(nifty_c) >= 21 else 0.0
        n_ret_60d = float((nifty_c.iloc[-1] / nifty_c.iloc[-61]) - 1) if len(nifty_c) >= 61 else 0.0
    except:
        n_ret_5d, n_ret_20d, n_ret_60d = 0.0, 0.0, 0.0

    sec_20d_map = df.groupby('Industry')['Ret_20D'].mean().to_dict() if 'Ret_20D' in df.columns else {}
    sec_5d_map = df.groupby('Industry')['Ret_5D'].mean().to_dict() if 'Ret_5D' in df.columns else {}

    prev_near_miss = {}
    if os.path.exists("Alpha_Near_Miss.csv"):
        try:
            nm_df = pd.read_csv("Alpha_Near_Miss.csv")
            for _, r in nm_df.iterrows():
                prev_near_miss[str(r['Symbol']).strip().upper()] = float(r.get('Alpha_Score', 0))
        except: pass

    alpha_records = []
    for _, row in df.iterrows():
        sym = str(row['Symbol']).strip().upper()
        tkr = sym + ".NS"
        if tkr not in raw_data['Close'].columns: continue
        c = raw_data['Close'][tkr].dropna()
        if len(c) < 120: continue
        
        h = raw_data['High'][tkr].reindex(c.index).ffill()
        l = raw_data['Low'][tkr].reindex(c.index).ffill()
        v = raw_data['Volume'][tkr].reindex(c.index).fillna(0)

        cur_c = float(c.iloc[-1])
        if cur_c < 10.0 or int((v.iloc[-20:] <= 0).sum()) > 2: continue

        vol_20d = float(v.iloc[-20:].mean())
        last_vol = float(v.iloc[-1])
        adtv_20d_cr = round((vol_20d * cur_c) / 10000000.0, 2)
        if adtv_20d_cr < 0.50: continue

        if adtv_20d_cr >= 25.0: cap_group = "Group A (Large)"
        elif adtv_20d_cr >= 8.0: cap_group = "Group B (Mid)"
        elif adtv_20d_cr >= 2.0: cap_group = "Group C (Small)"
        else: cap_group = "Group D (Micro)"

        r_1d = float((cur_c / c.iloc[-2]) - 1) if len(c) >= 2 else 0.0
        r_5d = float((cur_c / c.iloc[-6]) - 1) if len(c) >= 6 else 0.0
        r_20d = float((cur_c / c.iloc[-21]) - 1) if len(c) >= 21 else 0.0
        r_60d = float((cur_c / c.iloc[-61]) - 1) if len(c) >= 61 else 0.0

        rs_5d = r_5d - n_ret_5d
        rs_20d = r_20d - n_ret_20d
        rs_60d = r_60d - n_ret_60d
        sec_name = str(row.get('Industry', 'NSE Core Equity'))
        rs_vs_sector = r_20d - sec_20d_map.get(sec_name, n_ret_20d)
        sec_5d_strength = sec_5d_map.get(sec_name, 0.0)

        ema20_ser = c.ewm(span=20, adjust=False).mean()
        ema20 = float(ema20_ser.iloc[-1])
        ema20_prev5 = float(ema20_ser.iloc[-6]) if len(ema20_ser) >= 6 else ema20
        ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])

        std20 = c.rolling(20).std()
        bb_width = (4.0 * std20) / ema20_ser
        bb_curr = float(bb_width.iloc[-1]) if not np.isnan(bb_width.iloc[-1]) else 0.10
        bb_avg20 = float(bb_width.iloc[-20:].mean()) if len(bb_width) >= 20 else bb_curr
        is_bb_contracting = bb_curr <= (bb_avg20 * 0.92)

        prev_c = c.shift(1)
        tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        atr5 = float(tr.iloc[-5:].mean())
        atr20 = float(tr.iloc[-20:].mean())
        atr14 = float(tr.iloc[-14:].mean())
        is_atr_declining = atr5 <= (atr20 * 0.92)

        c_diff_10 = c.diff().iloc[-10:]
        v_10 = v.iloc[-10:]
        up_vol_10 = float(v_10[c_diff_10 > 0].sum())
        dn_vol_10 = float(v_10[c_diff_10 < 0].sum())
        up_dn_vol_ratio = round(min(5.0, up_vol_10 / max(1.0, dn_vol_10)), 2) if dn_vol_10 > 0 else 2.50

        rng_10 = (h.iloc[-10:] - l.iloc[-10:]).replace(0, np.nan)
        pos_10 = ((c.iloc[-10:] - l.iloc[-10:]) / rng_10).fillna(0.5)
        upper_half_days = int((pos_10 >= 0.50).sum())
        today_rng_pos = float(pos_10.iloc[-1])

        vol_mult = round(last_vol / max(1.0, vol_20d), 2)
        deliv_pct = float(row.get('Delivery_Pct', 0.45))
        rsi_val = float(row.get('RSI_14', 50.0))

        high_20d = float(h.iloc[-21:-1].max()) if len(h) >= 21 else float(h.max())
        high_5d_prev = float(h.iloc[-6:-1].max()) if len(h) >= 6 else float(h.iloc[-2])
        high_10d = float(h.iloc[-10:].max())
        pullback_from_10d = (cur_c - high_10d) / high_10d if high_10d > 0 else 0.0

        corp_event = str(row.get('Corp Event', 'Regular Trading'))
        cat_impact = str(row.get('Catalyst Impact', '⚪ Normal Flow'))
        has_neg_warning = ("RISK NEWS" in cat_impact) or ("TOXIC" in cat_impact) or ("EARNINGS" in corp_event and r_1d < 0)
        has_pos_catalyst = ("BULL NEWS" in cat_impact) or ("GOVT/POLICY" in cat_impact) or ("POST-RESULT SURGE" in corp_event)

        e1_pre_breakout = (cur_c >= ema20 and ema20 >= ema20_prev5 and cur_c >= high_20d * 0.94 and cur_c <= high_20d * 1.015 and (is_bb_contracting or is_atr_declining) and rs_20d >= -0.01 and 48.0 <= rsi_val <= 67.5)
        e2_accumulation = (up_dn_vol_ratio >= 1.35 and deliv_pct >= 0.46 and upper_half_days >= 6 and rs_vs_sector >= 0.0 and cur_c >= ema50)
        e3_momentum = (cur_c > high_5d_prev and 0.01 <= r_1d <= 0.052 and vol_mult >= 1.50 and today_rng_pos >= 0.72 and rs_5d > 0 and rsi_val <= 70.0)
        e4_dip_recovery = (-0.10 <= pullback_from_10d <= -0.028 and cur_c >= ema200 and (abs(cur_c - ema20) / ema20 <= 0.025 or abs(cur_c - ema50) / ema50 <= 0.025) and r_1d > 0.004 and today_rng_pos >= 0.60 and last_vol <= vol_20d * 1.35)
        e5_rs_leader = (rs_5d > 0.012 and rs_20d > 0.025 and rs_60d > 0.03 and rs_vs_sector > 0.01 and rs_5d >= (rs_20d / 4.5) and cur_c >= ema20 and rsi_val <= 70.0)
        e6_catalyst = (has_pos_catalyst and not has_neg_warning and r_1d > 0.005 and (vol_mult >= 1.25 or deliv_pct >= 0.48))

        tags = []
        if e1_pre_breakout: tags.append("🔥 PRE-BREAKOUT VCP")
        if e2_accumulation: tags.append("🐋 ACCUMULATION")
        if e3_momentum: tags.append(f"🚀 IGNITION ({'Early' if r_1d <= 0.03 else 'Estab'})")
        if e4_dip_recovery: tags.append("🛡️ DIP RECOVERY")
        if e5_rs_leader: tags.append("⚡ RS LEADER")
        if e6_catalyst: tags.append("📰 CATALYST")

        swing_low_5d = float(l.iloc[-5:].min())
        raw_sl = max(swing_low_5d * 0.992, cur_c - (1.6 * atr14), cur_c * 0.962)
        sl_price = round(min(raw_sl, cur_c * 0.985), 2)
        risk = max(0.01, cur_c - sl_price)
        target_price = round(cur_c + max(risk * 2.25, 3.2 * atr14, cur_c * 0.055), 2)
        rr_ratio = round((target_price - cur_c) / risk, 2)

        alpha_records.append({
            'Symbol': sym, 'Cap_Group': cap_group, 'Close': cur_c, 'Ret_1D': r_1d,
            'RSI_14': round(rsi_val, 2), 'Up_Down_Vol_Ratio': up_dn_vol_ratio,
            'Delivery_Pct': round(deliv_pct, 4), 'RS_20D': round(rs_20d, 4),
            'RS_5D': round(rs_5d, 4), 'RS_vs_Sec': round(rs_vs_sector, 4),
            'Sec_5D': sec_5d_strength, 'ADTV_20D_Cr': adtv_20d_cr,
            'Entry_Trigger': round(cur_c * 1.002 if e1_pre_breakout else cur_c, 2),
            'Stop_Loss': sl_price, 'Target': target_price, 'RR_Ratio': rr_ratio,
            'EOD_Vol_Mult': vol_mult, 'Avg_Vol_20D': int(max(1, round(vol_20d))),
            'Fund_Score_Raw': float(row.get('Opportunity Score', 50)),
            'Has_Neg_Warning': has_neg_warning, 'Has_Pos_Catalyst': has_pos_catalyst,
            'E1': e1_pre_breakout, 'E2': e2_accumulation, 'E3': e3_momentum,
            'E4': e4_dip_recovery, 'E5': e5_rs_leader, 'E6': e6_catalyst,
            'Engine_Count': len(tags),
            'Confluence_Tags': " + ".join(tags) if tags else "📊 BASE SCAN",
            'Cat_Text': cat_impact
        })

    adf = pd.DataFrame(alpha_records)
    if adf.empty: return

    adf['Pct_Vol'] = adf.groupby('Cap_Group')['Up_Down_Vol_Ratio'].rank(pct=True) * 0.6 + adf.groupby('Cap_Group')['EOD_Vol_Mult'].rank(pct=True) * 0.4
    adf['Pct_Deliv'] = adf.groupby('Cap_Group')['Delivery_Pct'].rank(pct=True)
    adf['Pct_RS'] = adf.groupby('Cap_Group')['RS_20D'].rank(pct=True) * 0.6 + adf.groupby('Cap_Group')['RS_5D'].rank(pct=True) * 0.4

    scores = []
    for _, r in adf.iterrows():
        s_price = 15.0 if (52 <= r['RSI_14'] <= 67 and r['Ret_1D'] >= 0) else (11.0 if 46 <= r['RSI_14'] <= 70 else 6.0)
        s_vol = round(min(15.0, float(r['Pct_Vol']) * 15.0 + (2.0 if r['Up_Down_Vol_Ratio'] >= 1.5 else 0.0)), 1)
        s_deliv = round(min(10.0, float(r['Pct_Deliv']) * 10.0 + (1.5 if r['Delivery_Pct'] >= 0.50 else 0.0)), 1)
        s_rs = round(min(15.0, float(r['Pct_RS']) * 15.0 + (2.0 if r['RS_5D'] > 0 and r['RS_20D'] > 0 else 0.0)), 1)
        s_sec = 10.0 if (r['Sec_5D'] > 0.005 and r['RS_vs_Sec'] > 0) else (7.0 if r['RS_vs_Sec'] >= 0 else 4.0)
        s_setup = min(15.0, 7.0 * min(1, r['Engine_Count']) + 4.0 * max(0, r['Engine_Count'] - 1))
        s_fund = round(min(10.0, (r['Fund_Score_Raw'] / 100.0) * 10.0), 1)
        s_cat = 5.0 if r['Has_Pos_Catalyst'] else (0.0 if r['Has_Neg_Warning'] else 2.5)
        s_rr = 5.0 if (r['RR_Ratio'] >= 2.0 and r['ADTV_20D_Cr'] >= 2.0) else (2.5 if r['RR_Ratio'] >= 1.6 else 0.0)
        scores.append(round(min(100.0, s_price + s_vol + s_deliv + s_rs + s_sec + s_setup + s_fund + s_cat + s_rr), 1))

    adf['Alpha_Score'] = scores

    for idx in adf.index:
        sym = adf.at[idx, 'Symbol']
        cur_sc = adf.at[idx, 'Alpha_Score']
        if sym in prev_near_miss and cur_sc >= 75.0:
            old_sc = prev_near_miss[sym]
            adf.at[idx, 'Confluence_Tags'] = f"🚀 PROMOTED ({old_sc:.0f}→{cur_sc:.0f}) | " + adf.at[idx, 'Confluence_Tags']

    adf['Passes_Gate'] = (~adf['Has_Neg_Warning']) & (adf['ADTV_20D_Cr'] >= 2.0) & (adf['RR_Ratio'] >= 2.0) & (adf['Engine_Count'] >= 1)

    out_rows = []
    top5_pool = adf[adf['Passes_Gate']].sort_values(by=['Alpha_Score', 'Engine_Count', 'Up_Down_Vol_Ratio'], ascending=[False, False, False]).head(5)
    for rank_i, (_, r) in enumerate(top5_pool.iterrows(), 1):
        tier_label = "Elite 85+" if r['Alpha_Score'] >= 85 else ("Strong 75+" if r['Alpha_Score'] >= 75 else "Developing")
        bucket_str = f"🏆 TOP #{rank_i} BOARD ({tier_label} • {r['Cap_Group'][:7]})"
        inv_rule = f"Hold > VWAP & ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:42]}"
        out_rows.append([
            r['Symbol'], bucket_str, r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
            r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
            r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
            r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
        ])

    engine_defs = [
        ('E1', '🔭 E1: PRE-BREAKOUT VCP'), ('E2', '🔭 E2: ACCUMULATION'), ('E3', '🔭 E3: MOMENTUM IGNITION'),
        ('E4', '🔭 E4: SMART DIP RECOVERY'), ('E5', '🔭 E5: RS LEADER'), ('E6', '🔭 E6: CATALYST HUNTER')
    ]
    for e_col, e_label in engine_defs:
        e_sub = adf[adf[e_col] & (~adf['Has_Neg_Warning'])].sort_values(by=['Alpha_Score', 'Up_Down_Vol_Ratio'], ascending=[False, False]).head(3)
        for _, r in e_sub.iterrows():
            inv_rule = f"Reject if < ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:45]}"
            out_rows.append([
                r['Symbol'], f"{e_label} ({r['Cap_Group'][:7]})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
                r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
                r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
                r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
            ])

    near_miss_df = adf[(adf['Alpha_Score'] >= 65.0) & (adf['Alpha_Score'] < 75.0) & (~adf['Has_Neg_Warning'])].sort_values(by='Alpha_Score', ascending=False).head(15)
    near_miss_df[['Symbol', 'Alpha_Score']].to_csv("Alpha_Near_Miss.csv", index=False)
    for _, r in near_miss_df.head(8).iterrows():
        inv_rule = f"Promote if > ₹{r['Entry_Trigger']} & Vol > 1.5x | {r['Cat_Text'][:38]}"
        out_rows.append([
            r['Symbol'], f"📈 NEAR-MISS WATCH ({r['Cap_Group'][:7]})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
            r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
            r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
            r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
        ])

    cols = ["Symbol", "Hunter_Bucket", "Alpha_Score", "Confluence_Tags", "RSI_14", "Up_Down_Vol_Ratio", "Delivery_Pct", "RS_20D", "ADTV_20D_Cr", "Entry_Trigger", "Stop_Loss", "Target", "RR_Ratio", "EOD_Vol_Mult", "Avg_Vol_20D", "Catalyst_Invalidation"]
    pd.DataFrame(out_rows, columns=cols).to_csv("RAW_ALPHA_HUNTER.csv", index=False)

def export_smart_sip_vault(df, raw_data):
    core_vault_syms = [
        "RELIANCE", "HDFCBANK", "LT", "HAL", "BEL", 
        "TATAPOWER", "RVNL", "CDSL", "DIXON", "NETWEB", 
        "VOLTAS", "TITAN", "ZOMATO", "GROWW", "KPITTECH"
    ]
    if os.path.exists("Smart_SIP_Vault_List.csv"):
        try:
            custom_list = pd.read_csv("Smart_SIP_Vault_List.csv")['Symbol'].tolist()
            core_vault_syms.extend([s.strip().upper() for s in custom_list])
            core_vault_syms = list(set(core_vault_syms))
        except: pass

    sip_records = []
    for sym in core_vault_syms:
        tkr = sym + ".NS"
        if tkr not in raw_data['Close'].columns: continue
        c = raw_data['Close'][tkr].dropna()
        if len(c) < 50: continue
        
        h = raw_data['High'][tkr].reindex(c.index).ffill()
        l = raw_data['Low'][tkr].reindex(c.index).ffill()
        
        cur_c = float(c.iloc[-1])
        ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1]) if len(c) >= 200 else cur_c
        
        try: high_52w = float(h.iloc[-252:].max())
        except: high_52w = cur_c
        
        disc_52w = round(((cur_c - high_52w) / high_52w), 4) if high_52w > 0 else 0.0
        dist_200ema = round(((cur_c - ema200) / ema200), 4) if ema200 > 0 else 0.0
        
        try:
            delta = c.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
            rs = avg_gain / avg_loss
            rsi_14 = float(100 - (100 / (1 + rs)).iloc[-1])
            if np.isnan(rsi_14): rsi_14 = 50.0
        except: rsi_14 = 50.0

        action = "⏳ ACCUMULATING CASH (Wait)"
        if dist_200ema <= 0.02 or disc_52w <= -0.15 or rsi_14 <= 35:
            action = "💰 DEPLOY SIP CAPITAL NOW"

        row_match = df[df['Symbol'] == sym]
        if not row_match.empty:
            comp = str(row_match.iloc[0].get('Company', sym))
            roe = float(row_match.iloc[0].get('ROE', 0.0))
            debt = float(row_match.iloc[0].get('Debt-to-Eq', 0.0))
        else:
            comp, roe, debt = sym, 0.0, 0.0

        sip_records.append({
            'Symbol': sym, 'Company': comp, 'Action_Status': action,
            'Live_CMP': cur_c, 'EMA_200': round(ema200, 2),
            'Dist_200EMA': dist_200ema, 'Disc_52W': disc_52w,
            'RSI_14': round(rsi_14, 2), 'ROE': roe, 'Debt_Eq': debt
        })

    if sip_records:
        pd.DataFrame(sip_records).to_csv("RAW_SMART_SIP.csv", index=False)

def run_quantum_engine():
    now_ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    current_mins_global = now_ist.hour * 60 + now_ist.minute
    
    try: univ = pd.read_csv("Universe_List.csv")
    except: univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    
    univ = clean_and_update_universe(univ)
    tickers = (univ['Symbol'] + '.NS').tolist()
    nse_deliv_map = fetch_nse_delivery_map()

    try:
        mem_df = pd.read_csv("Historical_Holdings.csv")
        mem_df['Date'] = pd.to_datetime(mem_df['Date'])
        mem_df = mem_df[mem_df['Date'] >= (pd.to_datetime(datetime.date.today()) - pd.Timedelta(days=365))]
    except: mem_df = pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])
    
    valid_mem = mem_df[(mem_df['Prom_Pct'] > 0) | (mem_df['FII_Pct'] > 0)] if not mem_df.empty else pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])
    oldest_records = valid_mem.sort_values('Date').groupby('Symbol').first().to_dict('index') if not valid_mem.empty else {}
    latest_valid_records = valid_mem.sort_values('Date').groupby('Symbol').last().to_dict('index') if not valid_mem.empty else {}
    today_memory_records = []

    fundamentals = {}
    if os.path.exists('fundamentals_cache.json'):
        try:
            with open('fundamentals_cache.json', 'r') as f: fundamentals = json.load(f)
        except: fundamentals = {}

    valid_cached_count = sum(1 for v in fundamentals.values() if isinstance(v, dict) and (v.get('heldPercentInsiders') or v.get('returnOnEquity') or v.get('trailingPE')))
    is_eod_heavy_run = (current_mins_global >= (16 * 60 + 20)) or (valid_cached_count < 150)

    if is_eod_heavy_run:
        def fetch_one_info(t):
            try:
                inf = yf.Ticker(t).info
                if isinstance(inf, dict) and len(inf) > 5: return t, inf
            except: pass
            return t, None
        with ThreadPoolExecutor(max_workers=10) as info_exec:
            for t_sym, inf_data in info_exec.map(fetch_one_info, tickers):
                if inf_data: fundamentals[t_sym] = inf_data
        try:
            with open('fundamentals_cache.json', 'w') as f: json.dump(fundamentals, f)
        except: pass

    download_period = "2y" if is_eod_heavy_run else "1y"
    try: raw_data = yf.download(tickers + ['^NSEI'], period=download_period, interval="1d", progress=False)
    except: return 
    
    nifty_20d_return, nifty_var = 0.0, 0.0
    nifty_ret_clean = pd.Series(dtype=float)
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        if len(nifty_c) < 30:
            n_dl = yf.download('^NSEI', period="1y", interval="1d", progress=False)
            nifty_c = n_dl['Close']['^NSEI'].dropna() if isinstance(n_dl['Close'], pd.DataFrame) else n_dl['Close'].dropna()
        if len(nifty_c) >= 21: nifty_20d_return = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1)
        nifty_c_clean = nifty_c.copy()
        nifty_c_clean.index = pd.to_datetime(nifty_c_clean.index).tz_localize(None).normalize()
        nifty_ret_clean = nifty_c_clean.pct_change().dropna()
        nifty_var = float(nifty_ret_clean.var())
    except: pass

    fo_universe = {"RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL", "LT", "BAJFINANCE", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA", "ULTRACEMCO", "NTPC", "TATAMOTORS", "TITAN", "POWERGRID", "ONGC", "M&M", "COALINDIA", "BAJAJFINSV", "ASIANPAINT", "ADANIPORTS", "HCLTECH", "TATAPOWER", "PFC", "RECLTD", "HAL", "BEL"}
    results = []

    def process(row):
        symbol = str(row['Symbol']).strip().upper()
        ticker = symbol + '.NS'
        info = fundamentals.get(ticker, {}) if isinstance(fundamentals.get(ticker), dict) else {}
        raw_comp = row.get('Company')
        if pd.isna(raw_comp) or not str(raw_comp).strip() or str(raw_comp).strip().lower() == 'nan' or str(raw_comp).strip() == symbol:
            company_name = info.get('shortName') or info.get('longName') or symbol
        else: company_name = str(raw_comp).strip()
        
        try:
            if 'Close' not in raw_data.columns or ticker not in raw_data['Close'].columns: return None
            c = raw_data['Close'][ticker].dropna()
            if len(c) < 20: return None
            
            h, l, v = raw_data['High'][ticker].reindex(c.index).ffill(), raw_data['Low'][ticker].reindex(c.index).ffill(), raw_data['Volume'][ticker].reindex(c.index).ffill()
            cur_close = float(c.iloc[-1])
            last_vol = float(v.iloc[-1]) if not v.empty else 0.0
            vol_30d = float(v.iloc[-30:].mean()) if len(v) >= 30 else float(v.mean())
            turnover_30d = vol_30d * cur_close
            ret_1d = round(((cur_close / float(c.iloc[-2])) - 1), 4) if len(c) >= 2 else 0.0
            wick_pct = (cur_close - float(l.iloc[-1])) / (float(h.iloc[-1]) - float(l.iloc[-1])) if (float(h.iloc[-1]) - float(l.iloc[-1])) > 0 else 0.0
            
            is_liquid = turnover_30d >= 10000000
            is_penny_spike = False
            if not is_liquid:
                if turnover_30d >= 1500000 and ((last_vol >= vol_30d * 2.0 and ret_1d >= 0.025) or (cur_close * last_vol >= 5000000 and ret_1d >= 0.035)):
                    is_penny_spike = True
            
            sector_name = classify_sector(symbol, row.get('Industry', 'Unknown'))
            is_dynamic_mover = "BEYOND" in sector_name.upper()
            if is_dynamic_mover and not is_liquid and not is_
