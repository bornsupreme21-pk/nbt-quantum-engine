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
        if len(core_df) >= 500:
            univ_df = core_df.drop_duplicates(subset=['Symbol'], keep='first').head(780)
    
    existing_symbols = set(univ_df['Symbol'].tolist())
    new_rows = []
    yf_urls = [
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers_in&count=25",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives_in&count=25"
    ]
    for u in yf_urls:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            quotes = data.get('finance', {}).get('result', [{}])[0].get('quotes', [])
            for q in quotes:
                sym = str(q.get('symbol', '')).upper()
                if sym.endswith('.NS'):
                    clean_sym = sym.replace('.NS', '').strip()
                    if clean_sym and clean_sym not in existing_symbols and len(univ_df) + len(new_rows) < 800:
                        name = str(q.get('shortName', q.get('longName', clean_sym))).strip()
                        new_rows.append({'Company': name, 'Industry': '🚀 BEYOND-750: Dynamic Mover', 'Symbol': clean_sym})
                        existing_symbols.add(clean_sym)
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
        except:
            pass

    alpha_records = []
    for _, row in df.iterrows():
        sym = str(row['Symbol']).strip().upper()
        tkr = sym + ".NS"
        if tkr not in raw_data['Close'].columns:
            continue
        c = raw_data['Close'][tkr].dropna()
        if len(c) < 120:
            continue
        h = raw_data['High'][tkr].reindex(c.index).ffill()
        l = raw_data['Low'][tkr].reindex(c.index).ffill()
        v = raw_data['Volume'][tkr].reindex(c.index).fillna(0)

        cur_c = float(c.iloc[-1])
        if cur_c < 10.0 or int((v.iloc[-20:] <= 0).sum()) > 2:
            continue

        vol_20d = float(v.iloc[-20:].mean())
        last_vol = float(v.iloc[-1])
        adtv_20d_cr = round((vol_20d * cur_c) / 10000000.0, 2)
        if adtv_20d_cr < 0.50:
            continue

        if adtv_20d_cr >= 25.0:
            cap_group = "Group A (Large)"
        elif adtv_20d_cr >= 8.0:
            cap_group = "Group B (Mid)"
        elif adtv_20d_cr >= 2.0:
            cap_group = "Group C (Small)"
        else:
            cap_group = "Group D (Micro)"

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
        ema50_ser = c.ewm(span=50, adjust=False).mean()
        ema200_ser = c.ewm(span=200, adjust=False).mean()
        ema20 = float(ema20_ser.iloc[-1])
        ema20_prev5 = float(ema20_ser.iloc[-6]) if len(ema20_ser) >= 6 else ema20
        ema50 = float(ema50_ser.iloc[-1])
        ema200 = float(ema200_ser.iloc[-1])

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
        has_pos_catalyst = ("BULL NEWS" in cat_impact) or ("GOVT/POLICY" in cat_impact) or ("POST-RESULT SURGE" in corp_event) or ("WHALE" in corp_event) or ("FII" in corp_event)

        e1_pre_breakout = (
            cur_c >= ema20 and ema20 >= ema20_prev5 and
            cur_c >= high_20d * 0.94 and cur_c <= high_20d * 1.015 and
            (is_bb_contracting or is_atr_declining) and
            rs_20d >= -0.01 and 48.0 <= rsi_val <= 67.5
        )
        e2_accumulation = (
            up_dn_vol_ratio >= 1.35 and deliv_pct >= 0.46 and
            upper_half_days >= 6 and rs_vs_sector >= 0.0 and cur_c >= ema50
        )
        e3_momentum = (
            cur_c > high_5d_prev and 0.01 <= r_1d <= 0.052 and
            vol_mult >= 1.50 and today_rng_pos >= 0.72 and rs_5d > 0 and rsi_val <= 70.0
        )
        e4_dip_recovery = (
            -0.10 <= pullback_from_10d <= -0.028 and cur_c >= ema200 and
            (abs(cur_c - ema20) / ema20 <= 0.025 or abs(cur_c - ema50) / ema50 <= 0.025) and
            r_1d > 0.004 and today_rng_pos >= 0.60 and last_vol <= vol_20d * 1.35
        )
        e5_rs_leader = (
            rs_5d > 0.012 and rs_20d > 0.025 and rs_60d > 0.03 and
            rs_vs_sector > 0.01 and rs_5d >= (rs_20d / 4.5) and cur_c >= ema20 and rsi_val <= 70.0
        )
        e6_catalyst = (
            has_pos_catalyst and not has_neg_warning and
            r_1d > 0.005 and (vol_mult >= 1.25 or deliv_pct >= 0.48)
        )

        tags = []
        if e1_pre_breakout: tags.append("🔥 PRE-BREAKOUT VCP")
        if e2_accumulation: tags.append("🐋 ACCUMULATION")
        if e3_momentum:
            mom_stage = "Early 1-3%" if r_1d <= 0.03 else "Estab 3-5%"
            tags.append(f"🚀 IGNITION ({mom_stage})")
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
    if adf.empty:
        return

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
        bucket_str = f"🏆 TOP #{rank_i} BOARD ({tier_label} • {r['Cap_Group']})"
        inv_rule = f"Hold > VWAP & ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:42]}"
        out_rows.append([
            r['Symbol'], bucket_str, r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
            r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
            r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
            r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
        ])

    engine_defs = [
        ('E1', '🔭 E1: PRE-BREAKOUT VCP'),
        ('E2', '🔭 E2: ACCUMULATION'),
        ('E3', '🔭 E3: MOMENTUM IGNITION'),
        ('E4', '🔭 E4: SMART DIP RECOVERY'),
        ('E5', '🔭 E5: RS LEADER'),
        ('E6', '🔭 E6: CATALYST HUNTER')
    ]
    for e_col, e_label in engine_defs:
        e_sub = adf[adf[e_col] & (~adf['Has_Neg_Warning'])].sort_values(by=['Alpha_Score', 'Up_Down_Vol_Ratio'], ascending=[False, False]).head(3)
        for _, r in e_sub.iterrows():
            inv_rule = f"Reject if < ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:45]}"
            out_rows.append([
                r['Symbol'], f"{e_label} ({r['Cap_Group']})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
                r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
                r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
                r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
            ])

    near_miss_df = adf[(adf['Alpha_Score'] >= 65.0) & (adf['Alpha_Score'] < 75.0) & (~adf['Has_Neg_Warning'])].sort_values(by='Alpha_Score', ascending=False).head(15)
    near_miss_df[['Symbol', 'Alpha_Score']].to_csv("Alpha_Near_Miss.csv", index=False)
    for _, r in near_miss_df.head(8).iterrows():
        inv_rule = f"Promote if > ₹{r['Entry_Trigger']} & Vol > 1.5x | {r['Cat_Text'][:38]}"
        out_rows.append([
            r['Symbol'], f"📈 NEAR-MISS WATCH ({r['Cap_Group']})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'],
            r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'],
            r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'],
            r['EOD_Vol_Mult'], r['Avg_Vol_20D'], inv_rule
        ])

    cols = [
        "Symbol", "Hunter_Bucket", "Alpha_Score", "Confluence_Tags", "RSI_14",
        "Up_Down_Vol_Ratio", "Delivery_Pct", "RS_20D", "ADTV_20D_Cr",
        "Entry_Trigger", "Stop_Loss", "Target", "RR_Ratio",
        "EOD_Vol_Mult", "Avg_Vol_20D", "Catalyst_Invalidation"
    ]
    pd.DataFrame(out_rows, columns=cols).to_csv("RAW_ALPHA_HUNTER.csv", index=False)

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
            with open('fundamentals_cache.json', 'r') as f:
                fundamentals = json.load(f)
        except: fundamentals = {}

    valid_cached_count = sum(1 for v in fundamentals.values() if isinstance(v, dict) and (v.get('heldPercentInsiders') or v.get('returnOnEquity') or v.get('trailingPE')))
    is_eod_heavy_run = (current_mins_global >= (16 * 60 + 20)) or (valid_cached_count < 150)

    if is_eod_heavy_run:
        def fetch_one_info(t):
            try:
                inf = yf.Ticker(t).info
                if isinstance(inf, dict) and len(inf) > 5:
                    return t, inf
            except: pass
            return t, None
        with ThreadPoolExecutor(max_workers=10) as info_exec:
            for t_sym, inf_data in info_exec.map(fetch_one_info, tickers):
                if inf_data:
                    fundamentals[t_sym] = inf_data
        try:
            with open('fundamentals_cache.json', 'w') as f:
                json.dump(fundamentals, f)
        except: pass

    download_period = "2y" if is_eod_heavy_run else "1y"
    try: raw_data = yf.download(tickers + ['^NSEI'], period=download_period, interval="1d", progress=False)
    except: return 
    
    nifty_20d_return = 0.0
    nifty_ret_clean = pd.Series(dtype=float)
    nifty_var = 0.0
    try:
        nifty_c = raw_data['Close']['^NSEI'].dropna()
        if len(nifty_c) < 30:
            n_dl = yf.download('^NSEI', period="1y", interval="1d", progress=False)
            nifty_c = n_dl['Close']['^NSEI'].dropna() if isinstance(n_dl['Close'], pd.DataFrame) else n_dl['Close'].dropna()
        if len(nifty_c) >= 21:
            nifty_20d_return = float((nifty_c.iloc[-1] / nifty_c.iloc[-21]) - 1)
        nifty_c_clean = nifty_c.copy()
        nifty_c_clean.index = pd.to_datetime(nifty_c_clean.index).tz_localize(None).normalize()
        nifty_ret_clean = nifty_c_clean.pct_change().dropna()
        nifty_var = float(nifty_ret_clean.var())
    except: pass

    fo_universe = {"RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL", "LT", "BAJFINANCE", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA", "ULTRACEMCO", "NTPC", "TATAMOTORS", "TITAN", "POWERGRID", "ONGC", "M&M", "COALINDIA", "BAJAJFINSV", "ASIANPAINT", "ADANIPORTS", "HCLTECH", "TATAPOWER", "PFC", "RECLTD", "HAL", "BEL", "DIVISLAB", "PERSISTENT", "MPHASIS", "BSE"}

    results = []
    def process(row):
        symbol = str(row['Symbol']).strip().upper()
        ticker = symbol + '.NS'
        info = fundamentals.get(ticker, {}) if isinstance(fundamentals.get(ticker), dict) else {}
        
        raw_comp = row.get('Company')
        if pd.isna(raw_comp) or not str(raw_comp).strip() or str(raw_comp).strip().lower() == 'nan' or str(raw_comp).strip() == symbol:
            company_name = info.get('shortName') or info.get('longName') or symbol
        else:
            company_name = str(raw_comp).strip()
        
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
            
            is_penny_spike = False
            if turnover_30d < 10000000:
                if turnover_30d >= 1500000 and ((last_vol >= vol_30d * 2.0 and ret_1d >= 0.025) or (cur_close * last_vol >= 5000000 and ret_1d >= 0.035)):
                    is_penny_spike = True
                else:
                    return None

            is_recent_ipo = len(c) < 180
            try:
                w_52h = h.iloc[-252:] if len(h) >= 252 else h
                w_52l = l.iloc[-252:] if len(l) >= 252 else l
                h_52w, l_52w = float(w_52h.max()), float(w_52l.min())
                h_52w_date = w_52h.idxmax().strftime('%d-%b-%Y')
                l_52w_date = w_52l.idxmin().strftime('%d-%b-%Y')
                dist_from_52w_low = round(((cur_close - l_52w) / l_52w), 4)
                disc_from_52w_high = round(((cur_close - h_52w) / h_52w), 4)
            except:
                h_52w, l_52w, h_52w_date, l_52w_date = cur_close, cur_close, "N/A", "N/A"
                dist_from_52w_low, disc_from_52w_high = 0.0, 0.0

            ret_5d = round(((cur_close / float(c.iloc[-6])) - 1), 4) if len(c) >= 6 else 0.0
            ret_20d = round(((cur_close / float(c.iloc[-21])) - 1), 4) if len(c) >= 21 else 0.0
            rs_vs_nifty = round(ret_20d - nifty_20d_return, 4)

            beta_val = None
            try:
                if len(c) >= 30 and not nifty_ret_clean.empty and nifty_var > 0:
                    c_clean = c.copy()
                    c_clean.index = pd.to_datetime(c_clean.index).tz_localize(None).normalize()
                    stk_ret = c_clean.pct_change().dropna()
                    aligned = pd.concat([stk_ret, nifty_ret_clean], axis=1).ffill().dropna()
                    if len(aligned) >= 30:
                        s_arr = aligned.iloc[-245:, 0].values
                        n_arr = aligned.iloc[-245:, 1].values
                        n_v = np.var(n_arr, ddof=1)
                        if n_v > 0:
                            raw_b = float(np.cov(s_arr, n_arr, ddof=1)[0, 1] / n_v)
                            beta_val = round(max(0.15, min(2.50, raw_b)), 2)
            except: pass
            if beta_val is None:
                beta_val = 1.00 if is_recent_ipo else 0.95

            ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ema200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            slope_200 = ema200 - float(c.ewm(span=200, adjust=False).mean().iloc[-20]) if len(c) >= 25 else 0.0
            
            projected_vol = last_vol * 1.35 
            dsr = projected_vol / vol_30d if vol_30d > 0 else 1.0
            is_vdu = dsr <= 0.55
            
            try:
                delta = c.diff()
                gain = delta.where(delta > 0, 0.0)
                loss = -delta.where(delta < 0, 0.0)
                avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
                avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
                rs = avg_gain / avg_loss
                rsi = float(100 - (100 / (1 + rs)).iloc[-1])
                if np.isnan(rsi): rsi = 50.0
            except: rsi = 50.0

            raw_in, raw_inst = info.get('heldPercentInsiders'), info.get('heldPercentInstitutions')
            raw_roe, raw_debt = info.get('returnOnEquity'), info.get('debtToEquity')
            raw_growth, raw_q_growth = info.get('revenueGrowth'), info.get('earningsQuarterlyGrowth')
            raw_pe, raw_bv = info.get('trailingPE', info.get('forwardPE')), info.get('bookValue')
            
            saved_latest = latest_valid_records.get(symbol, {})
            if (raw_in is None or float(raw_in) == 0.0) and saved_latest.get('Prom_Pct', 0) > 0:
                raw_in = float(saved_latest['Prom_Pct'])
            if (raw_inst is None or float(raw_inst) == 0.0) and saved_latest.get('FII_Pct', 0) > 0:
                raw_inst = float(saved_latest['FII_Pct'])

            pe_val = float(raw_pe) if raw_pe is not None else 0.0
            bv_val = float(raw_bv) if raw_bv is not None else 0.0
            final_roe = float(raw_roe) if raw_roe is not None else ((cur_close / (pe_val * bv_val)) if pe_val > 0 and bv_val > 0 else None)
            raw_dy = float(info.get('dividendYield', 0) or 0)
            normalized_dy = (raw_dy / 100.0 if raw_dy > 0.5 else raw_dy) if raw_dy > 0 else 0.0

            prom_curr = float(raw_in) if raw_in else 0.0
            fii_curr = float(raw_inst) if raw_inst else 0.0
            prom_old = float(oldest_records.get(symbol, {}).get('Prom_Pct', prom_curr))
            fii_old = float(oldest_records.get(symbol, {}).get('FII_Pct', fii_curr))
            
            prom_delta = round(prom_curr - prom_old, 4) if prom_curr > 0 else 0.0
            fii_delta = round(fii_curr - fii_old, 4) if fii_curr > 0 else 0.0
            if prom_curr > 0 or fii_curr > 0:
                today_memory_records.append({'Symbol': symbol, 'Date': datetime.date.today(), 'Prom_Pct': prom_curr, 'FII_Pct': fii_curr})

            if symbol in nse_deliv_map:
                deliv_pct = nse_deliv_map[symbol]
            else:
                inst_base = min(0.65, max(0.32, 0.38 + (fii_curr * 0.35) + (wick_pct * 0.15)))
                deliv_pct = round(inst_base, 4)

            sector_name = classify_sector(symbol, row.get('Industry', 'Unknown'))
            is_bank_or_fin = any(k in sector_name.lower() for k in ['bank', 'financial', 'nbfc', 'insurance'])

            fund_score, accum_status, dust_gem_score = 0, "NEUTRAL", 0
            debt_val = round(float(raw_debt), 2) if raw_debt is not None else 0.0
            
            if prom_curr >= 0.50: fund_score += 30
            elif prom_curr >= 0.35: fund_score += 15
            if fii_curr >= 0.15: fund_score += 20
            elif fii_curr >= 0.08: fund_score += 10
            if final_roe and final_roe > 0.15: fund_score += 20
            elif final_roe is None and deliv_pct >= 0.45: fund_score += 20
            if debt_val < 50 or is_bank_or_fin: fund_score += 30
            elif raw_debt is None and cur_close > ema200: fund_score += 30
            
            if fund_score >= 70 and is_vdu and dist_from_52w_low < 0.30: accum_status = "💎 SILENT ACCUMULATION"
            elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"

            roe_num = float(final_roe) if final_roe is not None else 0.12
            total_smart_ownership = prom_curr + fii_curr
            passes_quality_gate = (
                fund_score >= 50 and
                (roe_num >= 0.08 or final_roe is None) and
                (debt_val < 85 or is_bank_or_fin or raw_debt is None) and
                (pe_val < 95 or is_bank_or_fin or pe_val == 0.0) and
                (total_smart_ownership >= 0.38 or deliv_pct >= 0.45) and
                cur_close >= ema200 * 0.97
            )

            fo_regime = "CASH STOCK"
            oi_chg_pct = 0.0
            oi_total = 0
            if symbol in fo_universe:
                if ret_1d > 0.005 and dsr > 1.2 and deliv_pct > 0.45:
                    fo_regime = "🟢 LONG BUILDUP"
                    oi_chg_pct = round(dsr * 0.02, 4) 
                elif ret_1d < -0.005 and dsr > 1.2:
                    fo_regime = "🔴 SHORT BUILDUP"
                    oi_chg_pct = round(dsr * 0.02, 4) 
                elif ret_1d > 0.005 and dsr < 0.8 and deliv_pct < 0.40:
                    fo_regime = "⚠️ SHORT COVERING"
                    oi_chg_pct = round(-dsr * 0.015, 4)
                elif ret_1d < -0.005 and dsr < 0.8:
                    fo_regime = "🩸 LONG UNWINDING"
                    oi_chg_pct = round(-dsr * 0.015, 4)
                else:
                    fo_regime = "⚖️ RANGEBOUND OI"
                    oi_chg_pct = round((dsr - 1.0) * 0.01, 4)
                oi_total = int(vol_30d * 3.5)

            is_breakout = (cur_close > float(h.iloc[-21:-1].max())) if len(h) >= 21 else False
            is_launchpad_coil = (
                passes_quality_gate and cur_close >= ema20 * 0.995 and ema20 >= ema50 * 0.985 and
                50.0 <= rsi <= 68.0 and 0.015 <= ret_20d <= 0.18 and disc_from_52w_high >= -0.18 and deliv_pct >= 0.42 and ret_1d >= -0.015
            )
            is_day1_pocket_pivot = (
                passes_quality_gate and 0.01 <= ret_1d <= 0.06 and dsr >= 1.3 and cur_close >= ema20 and cur_close >= ema50 and
                48.0 <= rsi <= 69.0 and ret_20d <= 0.18 and wick_pct >= 0.58
            )
            is_capitulation = False
            alert_type = "Standard"
            
            if rsi > 73 or ret_20d > 0.22:
                alert_type = "🚨 OVEREXTENDED (Train Left - Wait)"
            elif is_launchpad_coil:
                alert_type = "🎯 LAUNCHPAD COIL (Pre-Breakout)"
            elif is_day1_pocket_pivot:
                alert_type = "🔥 DAY-1 POCKET PIVOT (Fresh Motion)"
            elif is_breakout and dsr > 1.2 and rsi <= 70 and passes_quality_gate:
                alert_type = "🚀 20D BREAKOUT (Early Stage)"
            elif is_penny_spike and rsi <= 70 and passes_quality_gate:
                alert_type = "🌋 QUALITY MICROCAP AWAKENING"
            elif is_penny_spike or (is_breakout and not passes_quality_gate):
                alert_type = "⚠️ SPECULATIVE SPIKE (Weak Fund)"
            elif is_vdu and cur_close > ema50 and 44 <= rsi <= 66 and passes_quality_gate:
                alert_type = "⚡ VCP + VDU TIGHT COIL"
            elif ret_1d <= -0.05 and rsi <= 35 and (wick_pct > 0.35 or dsr >= 1.5):
                is_capitulation = True
                alert_type = "💥 CAPITULATION BOUNCE"
            elif cur_close < ema200 and slope_200 < 0:
                alert_type = "📉 DOWNTREND (Avoid)"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05) and rsi >= 44 and passes_quality_gate:
                alert_type = "🛡️ 50-EMA PULLBACK SUPPORT"

            try:
                prev_c = c.shift(1)
                tr1 = h.iloc[-14:] - l.iloc[-14:]
                tr2 = (h.iloc[-14:] - prev_c.iloc[-14:]).abs()
                tr3 = (l.iloc[-14:] - prev_c.iloc[-14:]).abs()
                true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr14 = float(true_range.mean())
            except:
                atr14 = cur_close * 0.02

            if is_capitulation:
                sl_price = round(float(l.iloc[-1]) * 0.98, 2)
                target_7 = round(cur_close + (4.0 * atr14), 2)
            else:
                swing_stop = max(cur_close - (1.8 * atr14), cur_close * 0.962)
                sl_price = round(min(swing_stop, cur_close * 0.985), 2)
                target_7 = round(cur_close + max(cur_close * 0.075, 3.2 * atr14), 2)

            risk = max(0.01, cur_close - sl_price)
            rr_ratio = round((target_7 - cur_close) / risk, 2)

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

            launchpad_score = round(
                (fund_score * 0.40) +
                (deliv_pct * 100 * 0.25) +
                ((1.0 + max(-0.30, disc_from_52w_high)) * 100 * 0.20) +
                (max(0, 70 - abs(rsi - 60)) * 0.15), 2
            )

            sort_priority = 6
            if earnings_blackout:
                trading_verdict, sort_priority = "🚨 EARNINGS BLACKOUT (WAIT)", 5
            elif alert_type in ["🎯 LAUNCHPAD COIL (Pre-Breakout)", "🔥 DAY-1 POCKET PIVOT (Fresh Motion)", "🚀 20D BREAKOUT (Early Stage)", "🌋 QUALITY MICROCAP AWAKENING"]:
                trading_verdict, sort_priority = f"🎯 STRONG BUY: ₹{round(cur_close, 2)}", 1
            elif alert_type in ["⚡ VCP + VDU TIGHT COIL", "🛡️ 50-EMA PULLBACK SUPPORT"]:
                trading_verdict, sort_priority = f"🟢 ACCUMULATE: ₹{round(cur_close, 2)}", 2
            elif is_capitulation:
                trading_verdict, sort_priority = f"⚡ CONTRARIAN BOUNCE: ₹{round(cur_close, 2)}", 3
            elif alert_type in ["🚨 OVEREXTENDED (Train Left - Wait)", "⚠️ SPECULATIVE SPIKE (Weak Fund)"]:
                trading_verdict, sort_priority = "⚠️ AVOID / CHECK FUNDAMENTALS", 4
            elif alert_type == "📉 DOWNTREND (Avoid)":
                trading_verdict, sort_priority = "⛔ STRICT SKIP", 6
            else:
                trading_verdict, sort_priority = "⏳ WAIT", 3

            if final_roe and final_roe >= 0.15: dust_gem_score += 25
            elif final_roe and final_roe >= 0.10: dust_gem_score += 10
            if prom_curr >= 0.50: dust_gem_score += 15
            if fii_curr >= 0.15: dust_gem_score += 15
            if debt_val < 30: dust_gem_score += 15
            if disc_from_52w_high <= -0.30: dust_gem_score += 30
            elif disc_from_52w_high <= -0.20: dust_gem_score += 20
            elif disc_from_52w_high <= -0.12: dust_gem_score += 10
            if prom_delta > 0.005: dust_gem_score += 20
            if fii_delta > 0.01: dust_gem_score += 20
            if 0 < pe_val < 25: dust_gem_score += 15

            fear_event_score = 0.0
            catalyst_tag = "⚪ Normal Flow"
            
            if is_launchpad_coil:
                catalyst_tag = f"🎯 PRE-BREAKOUT COIL (RSI {int(rsi)} • Deliv {int(deliv_pct*100)}% • {round(disc_from_52w_high*100,1)}% from 52W High)"
            elif is_day1_pocket_pivot:
                catalyst_tag = f"🔥 DAY-1 IGNITION (+{round(ret_1d*100,1)}% 1D • {round(dsr,1)}x Vol • Fresh Motion)"
            elif is_capitulation:
                fear_event_score = 1000 + fund_score
                catalyst_tag = f"💥 CAPITULATION REVERSAL ({round(ret_1d*100,1)}% Drop • Bounce Incoming)"
            elif ret_1d <= -0.05 and dsr >= 3.5:
                catalyst_tag = "⛔ TOXIC STANDALONE DUMP (AVOID)"
            elif passes_quality_gate and not earnings_blackout:
                if post_earnings_breakout:
                    fear_event_score = round(dsr * 35 + fund_score, 1)
                    catalyst_tag = f"🚀 POST-EARNINGS BREAKOUT ({round(ret_1d*100,1)}% • {round(dsr,1)}x Vol)"
                elif -0.08 <= ret_1d <= -0.025 and cur_close >= ema200 * 0.97 and dsr < 3.2:
                    fear_event_score = round(abs(ret_1d) * 1000 + fund_score, 1)
                    catalyst_tag = f"😱 FEAR DIP ({round(ret_1d*100,1)}% 1D) • Intact 200-EMA"
                elif -0.12 <= ret_5d <= -0.045 and rsi <= 42 and cur_close >= ema200 * 0.95:
                    fear_event_score = round(abs(ret_5d) * 800 + fund_score, 1)
                    catalyst_tag = f"🌊 SECTOR CONTAGION DIP ({round(ret_5d*100,1)}% 5D • RSI {int(rsi)})"

            expected_beta_move = beta_val * nifty_20d_return if nifty_20d_return else 0
            alpha_spread = ret_1d - expected_beta_move
            if rsi >= 72 and ret_1d > 0.02: machine_pred = "⚠️ OVEREXTENDED (Profit Booking)"
            elif is_launchpad_coil or is_day1_pocket_pivot: machine_pred = "🚀 EARLY MOTION LAUNCHPAD (+Alpha)"
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
                'Symbol': symbol, 'Company': company_name, 'Industry': sector_name,
                'Is_Microcap_Spike': is_penny_spike,
                'Sort_Priority': sort_priority, 'Launchpad_Score': launchpad_score,
                'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 
                'Entry Trigger': round(cur_close, 2), 'Stop Loss': sl_price, 'Target 7%': target_7, 'RSI_14': round(rsi, 2),
                'Delivery_Pct': deliv_pct, 'Last_Vol': last_vol,
                'FO_Regime': fo_regime, 'OI_Total': oi_total, 'OI_Chg_Pct': oi_chg_pct, 'Machine_Prediction': machine_pred,
                '52W High Disc %': disc_from_52w_high,
                'F&O Ceiling': round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2), 
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date, '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'R:R Ratio': rr_ratio, 'Pos Size (₹5k Risk)': int(max(1, round(5000.0 / risk))) if risk > 0 else 1, 'RS vs Nifty': rs_vs_nifty,
                'Opportunity Score': fund_score, 'Dust_Gem_Score': dust_gem_score, 'Stage': "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4", 
                'Accumulation Status': accum_status, 
                'Promoter Holding': round(prom_curr, 4), 'Promoter Delta': prom_delta,
                'FII/DII': round(fii_curr, 4), 'FII Delta': fii_delta, 
                'Dist from 52W Low': dist_from_52w_low, 'Disc from 52W High': disc_from_52w_high,
                'Debt-to-Eq': debt_val if debt_val > 0 else 0.0, 'Growth': round(max(-3.0, min(3.0, float(raw_growth))), 4) if raw_growth else 0.0, 
                'ROE': round(final_roe, 4) if final_roe else 0.0, 'PE Ratio': round(pe_val, 2) if pe_val > 0 else 0.0, 
                'Book Value': round(bv_val, 2) if bv_val > 0 else 0.0,
                'Div Yield': round(normalized_dy, 4), 
                'QoQ Growth': round(max(-3.0, min(3.0, float(raw_q_growth))), 4) if raw_q_growth else 0.0, 'Volume Profile': "VDU" if is_vdu else "Normal",
                'Corp Event': " | ".join(events_list) if events_list else "Regular Trading", 'Catalyst Impact': catalyst_tag, 'Fear_Event_Score': fear_event_score,
                'Beta': beta_val, 'Ret_1D': ret_1d, 'Ret_5D': ret_5d, 'Ret_20D': ret_20d, 'Ret_50D': round(((cur_close / float(c.iloc[-51])) - 1), 4) if len(c) >= 51 else 0.0,
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
    
    if today_memory_records:
        pd.concat([mem_df, pd.DataFrame(today_memory_records)]).drop_duplicates(subset=['Symbol', 'Date'], keep='last').to_csv("Historical_Holdings.csv", index=False)

    eligible_swings = df[df['Sort_Priority'] <= 2].sort_values(by=["Launchpad_Score", "Sort_Priority", "R:R Ratio"], ascending=[False, True, False])
    if len(eligible_swings) < 15:
        fallback_swings = df[(df['Stage'] == 'PHASE 2: MARKUP') & (df['RSI_14'].between(48, 69)) & (df['Opportunity Score'] >= 50)].sort_values(by="Launchpad_Score", ascending=False)
        eligible_swings = pd.concat([eligible_swings, fallback_swings]).drop_duplicates(subset=['Symbol'], keep='first')
    core_swings = eligible_swings[~eligible_swings['Is_Microcap_Spike']].head(20)
    micro_swings = eligible_swings[eligible_swings['Is_Microcap_Spike']].head(5)
    top_swings = pd.concat([core_swings, micro_swings]).sort_values(by=["Launchpad_Score", "Sort_Priority"], ascending=[False, True]).head(25)
    used_syms = set(top_swings['Symbol'].tolist())
    
    top_inc = df[(df['Accumulation Status'] != "NEUTRAL") & (df['Sort_Priority'] <= 3) & (~df['Symbol'].isin(used_syms))].sort_values(by=["Opportunity Score", "Launchpad_Score"], ascending=[False, False]).head(20)
    if len(top_inc) < 15:
        fb_inc = df[(df['Opportunity Score'] >= 60) & (~df['Symbol'].isin(used_syms))].sort_values(by=["Opportunity Score", "Launchpad_Score"], ascending=[False, False]).head(20)
        top_inc = pd.concat([top_inc, fb_inc]).drop_duplicates(subset=['Symbol'], keep='first').head(20)
    used_syms.update(top_inc['Symbol'].tolist())
    
    fear_candidates = df[(df['Fear_Event_Score'] > 0) & (~df['Symbol'].isin(used_syms))].sort_values(by="Fear_Event_Score", ascending=False).head(40)
    used_syms.update(fear_candidates['Symbol'].tolist())
    dust_gems = df[(df['Disc from 52W High'] <= -0.15) & (~df['Symbol'].isin(used_syms))].sort_values(by="Dust_Gem_Score", ascending=False).head(40)

    core_portfolio = {'PFC', 'RELIANCE', 'IRFC', 'IRB', 'MSUMI', 'NMDC', 'ITC', 'BEL'}
    all_news_syms = set(top_swings['Symbol']).union(set(top_inc['Symbol'])).union(set(fear_candidates['Symbol'])).union(set(dust_gems['Symbol'])).union(core_portfolio).union(set(df[df['Corp Event'] != "Regular Trading"]['Symbol'].head(25)))

    with ThreadPoolExecutor(max_workers=8) as news_exec:
        future_to_idx = {news_exec.submit(fetch_stock_news_catalyst, df.at[i, 'Symbol'], df.at[i, 'Company'], df.at[i, 'Catalyst Impact']): i for i in df[df['Symbol'].isin(all_news_syms)].index.tolist()}
        for fut in as_completed(future_to_idx):
            try: df.at[future_to_idx[fut], 'Catalyst Impact'] = fut.result()
            except: pass

    fo_df = df[df['FO_Regime'] != "CASH STOCK"].sort_values(by="OI_Total", ascending=False)
    if fo_df.empty:
        fo_df = df[df['Symbol'].isin(fo_universe)]
    fo_df[["Symbol", "Company", "Entry Trigger", "Ret_1D", "FO_Regime", "OI_Chg_Pct", "OI_Total", "RSI_14", "Volume Profile", "Machine_Prediction", "52W High Disc %", "Industry"]].to_csv("RAW_FO_DECRYPTOR.csv", index=False)

    df.loc[top_swings.index].sort_values(by=["Launchpad_Score", "Sort_Priority"], ascending=[False, True])[["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "Pos Size (₹5k Risk)", "RSI_14", "RS vs Nifty", "F&O Ceiling", "52W High", "52W High Date", "52W Low", "52W Low Date", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value", "Corp Event", "Catalyst Impact"]].to_csv("RAW_SWINGS.csv", index=False)
    df.loc[top_inc.index].sort_values(by=["Opportunity Score", "Launchpad_Score"], ascending=[False, False])[["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Div Yield", "Volume Profile", "Corp Event", "Catalyst Impact"]].to_csv("RAW_INCUBATOR.csv", index=False)

    sniper_rows = []
    for _, r in df.loc[top_swings.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], f"🚀 SWING: {r['Alert Type']}", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], r['RSI_14'], r['R:R Ratio'], r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[top_inc.index].iterrows():
        inc_sl = round(r['Entry Trigger'] * 0.96, 2)
        inc_tgt = round(r['Entry Trigger'] * 1.08, 2)
        sniper_rows.append([r['Symbol'], r['Company'], f"💎 COMPOUNDER ({r['Accumulation Status']})", r['Entry Trigger'], inc_sl, inc_tgt, r['RSI_14'], 2.0, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[fear_candidates.index].iterrows():
        fear_sl = round(r['Entry Trigger'] * 0.955, 2)
        fear_tgt = round(r['Entry Trigger'] * 1.075, 2)
        sniper_rows.append([r['Symbol'], r['Company'], "⚡ EVENT / 200-EMA FEAR BOUNCE", r['Entry Trigger'], fear_sl, fear_tgt, r['RSI_14'], 1.67, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
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

    export_alpha_hunter(df, raw_data)

if __name__ == "__main__":
    run_quantum_engine()
