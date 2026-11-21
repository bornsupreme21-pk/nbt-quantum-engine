import os, io, json, zipfile, warnings, datetime, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings('ignore')

THEMATIC_MAP = {
    'HAL': 'Defense & Aerospace', 'BEL': 'Defense & Aerospace', 'BDL': 'Defense & Aerospace',
    'MAZDOCK': 'Defense & Aerospace', 'COCHINSHIP': 'Defense & Aerospace', 'GRSE': 'Defense & Aerospace',
    'IRFC': 'Railways & Infra EPC', 'RVNL': 'Railways & Infra EPC', 'IRCON': 'Railways & Infra EPC',
    'RAILTEL': 'Railways & Infra EPC', 'IRCTC': 'Railways & Infra EPC',
    'SBIN': 'PSU Banks', 'BOB': 'PSU Banks', 'PNB': 'PSU Banks', 'INDIANB': 'PSU Banks',
    'BANKBARODA': 'PSU Banks', 'CANBK': 'PSU Banks', 'UNIONBANK': 'PSU Banks',
    'HDFCBANK': 'Private Banks', 'ICICIBANK': 'Private Banks', 'AXISBANK': 'Private Banks', 'KOTAKBANK': 'Private Banks',
    'DIXON': 'EMS & Semiconductors', 'KAYNES': 'EMS & Semiconductors', 'SYRMA': 'EMS & Semiconductors',
    'PFC': 'Power, Renewables & PSU', 'RECLTD': 'Power, Renewables & PSU', 'NTPC': 'Power, Renewables & PSU',
    'TATAPOWER': 'Power, Renewables & PSU', 'NHPC': 'Power, Renewables & PSU'
}

GOVT_KW = ['cabinet', 'govt', 'government', 'pib', 'ministry', 'rbi', 'pli', 'subsidy', 'tender', 'psu', 'railway', 'defence', 'defense', 'nhai', 'budget', 'gst', 'rate cut', 'disinvestment']
BULL_KW = ['order', 'win', 'bag', 'profit', 'surge', 'jump', 'dividend', 'bonus', 'split', 'upgrade', 'buy', 'approval', 'acquire', 'expansion', 'record', 'mou', 'partner', 'launch']
FOUL_KW = ['sebi', 'raid', 'fraud', 'ed ', 'enforcement directorate', 'income tax', 'penalty', 'downgrade', 'default', 'resign', 'pledge', 'ban', 'notice', 'probe', 'fire', 'strike', 'loss', 'slump', 'crash', 'cut target', 'block deal', 'insider', 'litigation', 'shutdown', 'warning']

def safe_series(block, key):
    s = block[key]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return pd.to_numeric(s, errors='coerce')

def calc_wilder_rsi(c_ser, period=14):
    s = pd.to_numeric(c_ser, errors='coerce').dropna()
    if len(s) < period + 2:
        return 50.0
    delta = s.diff().dropna()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    ag = float(gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().iloc[-1])
    al = float(loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().iloc[-1])
    if np.isnan(ag) or np.isnan(al):
        return 50.0
    if al == 0.0:
        return 100.0 if ag > 0 else 50.0
    return round(100.0 - (100.0 / (1.0 + (ag / al))), 2)

def classify_sector(symbol, raw_industry):
    sym = str(symbol).upper().strip()
    if sym in THEMATIC_MAP:
        return THEMATIC_MAP[sym]
    if pd.isna(raw_industry):
        return 'NSE Core Equity'
    ind = str(raw_industry).strip()
    return ind if ind not in ['Unknown', '', 'nan', 'None'] else 'NSE Core Equity'

def clean_and_update_universe(univ_df):
    univ_df['Symbol'] = univ_df['Symbol'].astype(str).str.strip().str.upper()
    if 'Industry' in univ_df.columns:
        bloated = ['Diversified / Microcap', 'Diversified / Emerging', '🚀 BEYOND-750: Emerging', 'Diversified / IPO']
        core_df = univ_df[~univ_df['Industry'].astype(str).str.strip().isin(bloated)].copy()
        if len(core_df) >= 400:
            univ_df = core_df.drop_duplicates(subset=['Symbol'], keep='first').head(780)

    existing = set(univ_df['Symbol'].tolist())
    new_rows = []
    for u in [
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers_in&count=100",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives_in&count=100"
    ]:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                quotes = json.loads(resp.read().decode('utf-8')).get('finance', {}).get('result', [{}])[0].get('quotes', [])
            for q in quotes:
                sym = str(q.get('symbol', '')).upper()
                if sym.endswith('.NS'):
                    cs = sym.replace('.NS', '').strip()
                    if cs and cs not in existing and len(univ_df) + len(new_rows) < 950:
                        new_rows.append({'Company': str(q.get('shortName', q.get('longName', cs))).strip(), 'Industry': '🚀 BEYOND-750: Dynamic Mover', 'Symbol': cs})
                        existing.add(cs)
        except:
            pass

    try:
        req = urllib.request.Request("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            nse_df = pd.read_csv(io.StringIO(resp.read().decode('utf-8')))
        nse_df.columns = [c.strip().upper() for c in nse_df.columns]
        if 'SERIES' in nse_df.columns:
            nse_df = nse_df[nse_df['SERIES'].astype(str).str.strip() == 'EQ']
        for _, r in nse_df.iterrows():
            cs = str(r['SYMBOL']).strip().upper()
            if cs not in existing and len(univ_df) + len(new_rows) < 1020:
                new_rows.append({'Company': str(r['NAME OF COMPANY']).strip(), 'Industry': '🚀 BEYOND-750: Emerging', 'Symbol': cs})
                existing.add(cs)
    except:
        pass

    if new_rows:
        univ_df = pd.concat([univ_df, pd.DataFrame(new_rows)], ignore_index=True)
    univ_df.to_csv("Universe_List.csv", index=False)
    return univ_df

def fetch_nse_delivery_map():
    deliv_map = {}
    for offset in range(0, 6):
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        for host in ["https://nsearchives.nseindia.com", "https://archives.nseindia.com"]:
            url = f"{host}/products/content/sec_bhavdata_full_{dt.strftime('%d%m%Y')}.csv"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    b_df = pd.read_csv(io.StringIO(resp.read().decode('utf-8')))
                b_df.columns = [c.strip().upper() for c in b_df.columns]
                if 'SYMBOL' in b_df.columns and 'DELIV_PER' in b_df.columns:
                    for _, r in b_df.iterrows():
                        try:
                            sym = str(r['SYMBOL']).strip().upper()
                            d_pct = float(str(r['DELIV_PER']).strip()) / 100.0
                            if 0 < d_pct <= 1.0:
                                deliv_map[sym] = round(d_pct, 4)
                        except:
                            pass
                    if deliv_map:
                        return deliv_map
            except:
                pass
    return deliv_map

def fetch_real_nse_fo_oi():
    """Downloads official NSE UDiFF F&O Bhavcopy for real Futures OI, OI Change %, and Stock Put-Call Ratio."""
    fo_map = {}
    for offset in range(0, 6):
        dt = datetime.date.today() - datetime.timedelta(days=offset)
        url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                zbytes = io.BytesIO(resp.read())
            with zipfile.ZipFile(zbytes) as zf:
                csv_name = [n for n in zf.namelist() if n.lower().endswith('.csv')][0]
                fodf = pd.read_csv(zf.open(csv_name), low_memory=False)
            fodf.columns = [c.strip() for c in fodf.columns]
            if 'TckrSymb' not in fodf.columns or 'FinInstrmTp' not in fodf.columns:
                continue
            stf = fodf[fodf['FinInstrmTp'].astype(str).str.strip() == 'STF'].copy()
            stf['OpnIntrst'] = pd.to_numeric(stf['OpnIntrst'], errors='coerce').fillna(0)
            stf['ChngInOpnIntrst'] = pd.to_numeric(stf['ChngInOpnIntrst'], errors='coerce').fillna(0)
            grp = stf.groupby('TckrSymb').agg(oi=('OpnIntrst', 'sum'), oi_chg=('ChngInOpnIntrst', 'sum')).reset_index()

            pcr_map = {}
            if 'OptnTp' in fodf.columns:
                sto = fodf[fodf['FinInstrmTp'].astype(str).str.strip() == 'STO'].copy()
                sto['OpnIntrst'] = pd.to_numeric(sto['OpnIntrst'], errors='coerce').fillna(0)
                piv = sto.pivot_table(index='TckrSymb', columns='OptnTp', values='OpnIntrst', aggfunc='sum', fill_value=0)
                if 'PE' in piv.columns and 'CE' in piv.columns:
                    for sym_k, r_p in piv.iterrows():
                        if r_p['CE'] > 0:
                            pcr_map[str(sym_k).strip().upper()] = round(float(r_p['PE'] / r_p['CE']), 2)

            for _, r in grp.iterrows():
                sym = str(r['TckrSymb']).strip().upper()
                oi, oi_chg = float(r['oi']), float(r['oi_chg'])
                prev_oi = max(1.0, oi - oi_chg)
                fo_map[sym] = {'oi': int(oi), 'oi_chg_pct': round(oi_chg / prev_oi, 4), 'pcr': pcr_map.get(sym, 0.0)}
            if fo_map:
                return fo_map
        except:
            pass
    return fo_map

def fetch_stock_news_catalyst(symbol, company, current_tag):
    """Exact-matched news scanner that prioritizes Foul Play / Contrariety Red Flags over routine headlines."""
    try:
        clean_co = str(company).replace('LIMITED', '').replace('LTD.', '').replace('LTD', '').strip()
        q_str = f'("{symbol}" OR "{clean_co}") NSE stock'
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_str)}+when:3d&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            root = ET.fromstring(resp.read())
        items = root.findall('.//item')[:4]
        best_title, best_sent = None, None
        first_word = clean_co.split()[0].lower() if clean_co else symbol.lower()
        for item in items:
            t = (item.find('title').text or "").split(" - ")[0].strip()
            lt = t.lower()
            if symbol.lower() not in lt and first_word not in lt:
                continue
            if any(k in lt for k in FOUL_KW):
                best_title, best_sent = t, "🚨 FOUL/RISK NEWS"
                break
            if best_title is None:
                if any(k in lt for k in GOVT_KW): best_title, best_sent = t, "🏛️ GOVT/POLICY"
                elif any(k in lt for k in BULL_KW): best_title, best_sent = t, "🟢 BULL NEWS"
                else: best_title, best_sent = t, "📰 NEWS"
        if best_title:
            short_h = best_title[:54] + ("..." if len(best_title) > 54 else "")
            return f"{best_sent}: {short_h}" if current_tag == "⚪ Normal Flow" else f"{current_tag} | {best_sent}: {short_h}"
    except:
        pass
    return current_tag

def fetch_macro_and_history(adv_count=400, dec_count=350, avg_deliv_pct=0.48):
    regime_label = "⚖️ BALANCED REGIME"
    try:
        data = yf.download(['BZ=F', 'GC=F', '^INDIAVIX', '^TNX', 'INR=X', '^NSEI', 'ES=F'], period="1y", progress=False)
        if data.empty or 'Close' not in data.columns:
            return regime_label

        def get_lc(t):
            try:
                s = safe_series(data['Close'], t).dropna()
                if s.empty: return 0.0, 0.0
                return round(float(s.iloc[-1]), 2), round(float((s.iloc[-1] / s.iloc[-2]) - 1), 4) if len(s) >= 2 else 0.0
            except:
                return 0.0, 0.0

        out = []
        for t in ['BZ=F', 'GC=F', '^INDIAVIX', '^TNX', 'INR=X', 'ES=F']:
            lv, dc = get_lc(t)
            if lv > 0: out.append({'Ticker': t, 'Live_Value': lv, 'Daily_Change': dc})

        nifty_spot, nifty_chg = get_lc('^NSEI')
        vix_live, _ = get_lc('^INDIAVIX')
        try: nifty_1y_ago = round(float(safe_series(data['Close'], '^NSEI').dropna().iloc[0]), 2)
        except: nifty_1y_ago = nifty_spot

        _, es_chg = get_lc('ES=F'); _, inr_chg = get_lc('INR=X'); _, bz_chg = get_lc('BZ=F'); _, tnx_chg = get_lc('^TNX')
        implied_pct = (es_chg * 0.55) + (inr_chg * -0.80) + (bz_chg * -0.10) + (tnx_chg * -0.15)
        synthetic_pts = round(nifty_spot * implied_pct, 1) if nifty_spot > 0 else 0.0
        synthetic_nifty = round(nifty_spot + synthetic_pts, 2) if nifty_spot > 0 else 0.0
        adr = round(adv_count / max(1, dec_count), 2)

        if vix_live >= 20.0 or (nifty_chg <= -0.01 and adr < 0.65):
            regime_label = f"🔴 RISK-OFF / HIGH FEAR (VIX {vix_live} • ADR {adr}x — Tighten Stops)"
        elif nifty_chg >= 0.004 and adr < 0.85:
            regime_label = f"⚠️ NARROW LARGE-CAP RALLY (ADR {adr}x • VIX {vix_live} — Avoid Small-Cap Chasing)"
        elif nifty_chg >= 0.003 and adr >= 1.25 and vix_live < 18.0:
            regime_label = f"🟢 BROAD INSTITUTIONAL BULL (ADR {adr}x • VIX {vix_live} — Full Size)"
        elif vix_live >= 16.0:
            regime_label = f"🟠 ELEVATED VIX CHOP (VIX {vix_live} • ADR {adr}x — Selective A+ Only)"
        else:
            regime_label = f"⚖️ ROTATIONAL CONSOLIDATION (ADR {adr}x • VIX {vix_live})"

        out.append({'Ticker': 'NIFTY_1Y_AGO', 'Live_Value': nifty_1y_ago, 'Daily_Change': round((nifty_spot - nifty_1y_ago) / nifty_1y_ago, 4) if nifty_1y_ago > 0 else 0.0})
        out.append({'Ticker': 'SYNTHETIC_NIFTY', 'Live_Value': synthetic_nifty, 'Daily_Change': implied_pct})
        out.append({'Ticker': 'SYNTHETIC_PTS', 'Live_Value': synthetic_pts, 'Daily_Change': implied_pct})
        out.append({'Ticker': 'MARKET_ADR', 'Live_Value': adr, 'Daily_Change': round(adv_count / max(1, adv_count + dec_count), 4)})
        out.append({'Ticker': 'MARKET_REGIME', 'Live_Value': regime_label, 'Daily_Change': vix_live})
        pd.DataFrame(out).to_csv("RAW_MACRO.csv", index=False)

        intraday_times = {}
        try:
            intra = yf.download('^NSEI', period="60d", interval="5m", progress=False)
            if not intra.empty and 'High' in intra.columns:
                hs = (safe_series(intra['High'], '^NSEI') if isinstance(intra['High'], pd.DataFrame) else pd.to_numeric(intra['High'], errors='coerce')).dropna()
                ls = (safe_series(intra['Low'], '^NSEI') if isinstance(intra['Low'], pd.DataFrame) else pd.to_numeric(intra['Low'], errors='coerce')).dropna()
                hs.index = (hs.index + pd.Timedelta(hours=5, minutes=30)) if hs.index.tz is None else hs.index.tz_convert('Asia/Kolkata')
                ls.index = (ls.index + pd.Timedelta(hours=5, minutes=30)) if ls.index.tz is None else ls.index.tz_convert('Asia/Kolkata')
                for dt_key, grp_h in hs.groupby(hs.index.date):
                    grp_l = ls[ls.index.date == dt_key]
                    if not grp_h.empty and not grp_l.empty:
                        intraday_times[str(dt_key)] = (grp_h.idxmax().strftime('%H:%M IST'), grp_l.idxmin().strftime('%H:%M IST'))
        except:
            pass

        old_hist_map = {}
        if os.path.exists("RAW_NIFTY_HISTORY.csv"):
            try:
                for _, r in pd.read_csv("RAW_NIFTY_HISTORY.csv").iterrows():
                    old_hist_map[str(r['Date'])] = r.to_dict()
            except:
                pass

        nc = safe_series(data['Close'], '^NSEI').dropna()
        no = safe_series(data['Open'], '^NSEI').reindex(nc.index).ffill()
        nh = safe_series(data['High'], '^NSEI').reindex(nc.index).ffill()
        nl = safe_series(data['Low'], '^NSEI').reindex(nc.index).ffill()
        nv = safe_series(data['Volume'], '^NSEI').reindex(nc.index).fillna(0)
        vc = safe_series(data['Close'], '^INDIAVIX').reindex(nc.index).ffill().fillna(15.0)
        med_v = float(nv[nv > 0].median()) if (nv > 0).any() else 300000.0

        hist_rows = []
        dates_list = nc.index.tolist()
        for idx_i, dt_s in enumerate(dates_list):
            d_str = dt_s.strftime('%Y-%m-%d')
            o_v, h_v, l_v, c_v = round(float(no.iloc[idx_i]), 2), round(float(nh.iloc[idx_i]), 2), round(float(nl.iloc[idx_i]), 2), round(float(nc.iloc[idx_i]), 2)
            prev_c = float(nc.iloc[idx_i - 1]) if idx_i > 0 else o_v
            d_chg = round((c_v - prev_c) / prev_c, 4) if prev_c > 0 else 0.0
            d_rng = round(h_v - l_v, 2)

            if d_str in intraday_times:
                h_t, l_t = intraday_times[d_str]
            elif d_str in old_hist_map and "Est" not in str(old_hist_map[d_str].get('High_Time_IST', '')) and str(old_hist_map[d_str].get('High_Time_IST', '')).endswith('IST'):
                h_t, l_t = old_hist_map[d_str]['High_Time_IST'], old_hist_map[d_str]['Low_Time_IST']
            else:
                h_t, l_t = "EOD Archive", "EOD Archive"

            raw_v = float(nv.iloc[idx_i])
            if raw_v <= 0: raw_v = med_v
            traded_vol = int(raw_v * 1000) if raw_v <= 2000000 else int(raw_v)
            day_deliv = round(avg_deliv_pct if idx_i == len(dates_list) - 1 else min(0.65, max(0.40, 0.46 + (0.10 * abs(c_v - o_v) / max(1.0, d_rng)))), 4)

            if idx_i == len(dates_list) - 1:
                b_str = f"{adv_count} Adv / {dec_count} Dec (ADR {adr}x) • {regime_label.split('(')[0].strip()}"
            elif d_str in old_hist_map and "Adv" in str(old_hist_map[d_str].get('Market_Breadth_Summary', '')):
                b_str = old_hist_map[d_str]['Market_Breadth_Summary']
            else:
                b_str = "🟢 Bullish Expansion" if d_chg > 0.005 else ("🔴 Risk-Off Supply" if d_chg < -0.005 else "⚖️ Rangebound Flow")

            hist_rows.append({
                'Year': int(dt_s.strftime('%Y')), 'Date': d_str, 'Day': dt_s.strftime('%A'),
                'Open': o_v, 'High': h_v, 'High_Time_IST': h_t, 'Low': l_v, 'Low_Time_IST': l_t,
                'Close': c_v, 'Day_Chg_Pct': d_chg, 'Day_Range_Pts': d_rng, 'Traded_Volume': traded_vol,
                'Delivery_Volume': int(round(traded_vol * day_deliv)), 'Delivery_Pct': day_deliv,
                'India_VIX': round(float(vc.iloc[idx_i]), 2), 'Market_Breadth_Summary': b_str
            })
        pd.DataFrame(hist_rows).sort_values(by='Date', ascending=False).head(260).to_csv("RAW_NIFTY_HISTORY.csv", index=False)
    except:
        pass
    return regime_label

def export_alpha_hunter(df, raw_data):
    if df.empty or 'Close' not in raw_data.columns:
        return
    try:
        nc = safe_series(raw_data['Close'], '^NSEI').dropna()
        n5 = float((nc.iloc[-1] / nc.iloc[-6]) - 1) if len(nc) >= 6 else 0.0
        n20 = float((nc.iloc[-1] / nc.iloc[-21]) - 1) if len(nc) >= 21 else 0.0
        n60 = float((nc.iloc[-1] / nc.iloc[-61]) - 1) if len(nc) >= 61 else 0.0
    except:
        n5, n20, n60 = 0.0, 0.0, 0.0

    sec20 = df.groupby('Industry')['Ret_20D'].mean().to_dict()
    sec5 = df.groupby('Industry')['Ret_5D'].mean().to_dict()
    prev_nm = {}
    if os.path.exists("Alpha_Near_Miss.csv"):
        try:
            for _, r in pd.read_csv("Alpha_Near_Miss.csv").iterrows():
                prev_nm[str(r['Symbol']).strip().upper()] = float(r.get('Alpha_Score', 0))
        except:
            pass

    recs = []
    for _, row in df.iterrows():
        sym = str(row['Symbol']).strip().upper()
        tkr = sym + ".NS"
        if tkr not in raw_data['Close'].columns: continue
        c = safe_series(raw_data['Close'], tkr).dropna()
        if len(c) < 120: continue
        h, l, v = safe_series(raw_data['High'], tkr).reindex(c.index).ffill(), safe_series(raw_data['Low'], tkr).reindex(c.index).ffill(), safe_series(raw_data['Volume'], tkr).reindex(c.index).fillna(0)

        cur_c = float(c.iloc[-1])
        if cur_c < 10.0 or int((v.iloc[-20:] <= 0).sum()) > 2: continue
        vol20, last_vol = float(v.iloc[-20:].mean()), float(v.iloc[-1])
        adtv_cr = round((vol20 * cur_c) / 1e7, 2)
        if adtv_cr < 0.50: continue

        cap_grp = "Group A (Large)" if adtv_cr >= 25.0 else ("Group B (Mid)" if adtv_cr >= 8.0 else ("Group C (Small)" if adtv_cr >= 2.0 else "Group D (Micro)"))
        r1 = float((cur_c / c.iloc[-2]) - 1) if len(c) >= 2 else 0.0
        r5 = float((cur_c / c.iloc[-6]) - 1) if len(c) >= 6 else 0.0
        r20 = float((cur_c / c.iloc[-21]) - 1) if len(c) >= 21 else 0.0
        r60 = float((cur_c / c.iloc[-61]) - 1) if len(c) >= 61 else 0.0
        rs5, rs20, rs60 = r5 - n5, r20 - n20, r60 - n60
        sec = str(row.get('Industry', 'NSE Core Equity'))
        rs_sec, sec5_s = r20 - sec20.get(sec, n20), sec5.get(sec, 0.0)

        e20s = c.ewm(span=20, adjust=False).mean()
        ema20, ema20_p5 = float(e20s.iloc[-1]), float(e20s.iloc[-6]) if len(e20s) >= 6 else float(e20s.iloc[-1])
        ema50, ema200 = float(c.ewm(span=50, adjust=False).mean().iloc[-1]), float(c.ewm(span=200, adjust=False).mean().iloc[-1])

        bbw = (4.0 * c.rolling(20).std()) / e20s
        bb_cur = float(bbw.iloc[-1]) if not np.isnan(bbw.iloc[-1]) else 0.10
        bb_avg = float(bbw.iloc[-20:].mean()) if len(bbw) >= 20 else bb_cur

        pc = c.shift(1)
        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr5, atr14, atr20 = float(tr.iloc[-5:].mean()), float(tr.iloc[-14:].mean()), float(tr.iloc[-20:].mean())

        cd10, v10 = c.diff().iloc[-10:], v.iloc[-10:]
        up10, dn10 = float(v10[cd10 > 0].sum()), float(v10[cd10 < 0].sum())
        ud_ratio = round(min(5.0, up10 / max(1.0, dn10)), 2) if dn10 > 0 else 2.50

        rng10 = (h.iloc[-10:] - l.iloc[-10:]).replace(0, np.nan)
        pos10 = ((c.iloc[-10:] - l.iloc[-10:]) / rng10).fillna(0.5)
        uh_days, today_pos = int((pos10 >= 0.50).sum()), float(pos10.iloc[-1])

        vol_mult = round(last_vol / max(1.0, vol20), 2)
        deliv_pct, rsi_val = float(row.get('Delivery_Pct', 0.45)), float(row.get('RSI_14', 50.0))
        h20 = float(h.iloc[-21:-1].max()) if len(h) >= 21 else float(h.max())
        h5p = float(h.iloc[-6:-1].max()) if len(h) >= 6 else float(h.iloc[-2])
        pb10 = (cur_c - float(h.iloc[-10:].max())) / max(0.01, float(h.iloc[-10:].max()))

        corp, cat = str(row.get('Corp Event', 'Regular Trading')), str(row.get('Catalyst Impact', '⚪ Normal Flow'))
        has_neg = ("FOUL/RISK" in cat) or ("TOXIC" in cat) or ("EARNINGS" in corp and r1 < 0)
        has_pos = ("BULL NEWS" in cat) or ("GOVT/POLICY" in cat) or ("POST-RESULT" in corp)

        e1 = (cur_c >= ema20 and ema20 >= ema20_p5 and cur_c >= h20 * 0.94 and cur_c <= h20 * 1.015 and (bb_cur <= bb_avg * 0.92 or atr5 <= atr20 * 0.92) and rs20 >= -0.01 and 48.0 <= rsi_val <= 67.5)
        e2 = (ud_ratio >= 1.35 and deliv_pct >= 0.46 and uh_days >= 6 and rs_sec >= 0.0 and cur_c >= ema50)
        e3 = (cur_c > h5p and 0.01 <= r1 <= 0.052 and vol_mult >= 1.50 and today_pos >= 0.72 and rs5 > 0 and rsi_val <= 70.0)
        e4 = (-0.10 <= pb10 <= -0.028 and cur_c >= ema200 and (abs(cur_c - ema20) / ema20 <= 0.025 or abs(cur_c - ema50) / ema50 <= 0.025) and r1 > 0.004 and today_pos >= 0.60 and last_vol <= vol20 * 1.35)
        e5 = (rs5 > 0.012 and rs20 > 0.025 and rs60 > 0.03 and rs_sec > 0.01 and rs5 >= (rs20 / 4.5) and cur_c >= ema20 and rsi_val <= 70.0)
        e6 = (has_pos and not has_neg and r1 > 0.005 and (vol_mult >= 1.25 or deliv_pct >= 0.48))

        tags = []
        if e1: tags.append("🔥 PRE-BREAKOUT VCP")
        if e2: tags.append("🐋 ACCUMULATION")
        if e3: tags.append(f"🚀 IGNITION ({'Early' if r1 <= 0.03 else 'Estab'})")
        if e4: tags.append("🛡️ DIP RECOVERY")
        if e5: tags.append("⚡ RS LEADER")
        if e6: tags.append("📰 CATALYST")

        sl = round(min(max(float(l.iloc[-5:].min()) * 0.992, cur_c - 1.6 * atr14, cur_c * 0.962), cur_c * 0.985), 2)
        risk = max(0.01, cur_c - sl)
        tgt = round(cur_c + max(risk * 2.25, 3.2 * atr14, cur_c * 0.055), 2)

        recs.append({
            'Symbol': sym, 'Cap_Group': cap_grp, 'Close': cur_c, 'Ret_1D': r1, 'RSI_14': round(rsi_val, 2),
            'Up_Down_Vol_Ratio': ud_ratio, 'Delivery_Pct': round(deliv_pct, 4), 'RS_20D': round(rs20, 4),
            'RS_5D': round(rs5, 4), 'RS_vs_Sec': round(rs_sec, 4), 'Sec_5D': sec5_s, 'ADTV_20D_Cr': adtv_cr,
            'Entry_Trigger': round(cur_c * 1.002 if e1 else cur_c, 2), 'Stop_Loss': sl, 'Target': tgt,
            'RR_Ratio': round((tgt - cur_c) / risk, 2), 'EOD_Vol_Mult': vol_mult, 'Avg_Vol_20D': int(max(1, round(vol20))),
            'Fund_Score_Raw': float(row.get('Opportunity Score', 50)), 'Has_Neg': has_neg, 'Has_Pos': has_pos,
            'E1': e1, 'E2': e2, 'E3': e3, 'E4': e4, 'E5': e5, 'E6': e6,
            'Engine_Count': len(tags), 'Confluence_Tags': " + ".join(tags) if tags else "📊 BASE SCAN", 'Cat_Text': cat
        })

    adf = pd.DataFrame(recs)
    if adf.empty: return

    adf['Pct_Vol'] = adf.groupby('Cap_Group')['Up_Down_Vol_Ratio'].rank(pct=True) * 0.6 + adf.groupby('Cap_Group')['EOD_Vol_Mult'].rank(pct=True) * 0.4
    adf['Pct_Deliv'] = adf.groupby('Cap_Group')['Delivery_Pct'].rank(pct=True)
    adf['Pct_RS'] = adf.groupby('Cap_Group')['RS_20D'].rank(pct=True) * 0.6 + adf.groupby('Cap_Group')['RS_5D'].rank(pct=True) * 0.4

    scores = []
    for _, r in adf.iterrows():
        sp = 15.0 if (52 <= r['RSI_14'] <= 67 and r['Ret_1D'] >= 0) else (11.0 if 46 <= r['RSI_14'] <= 70 else 6.0)
        sv = round(min(15.0, float(r['Pct_Vol']) * 15.0 + (2.0 if r['Up_Down_Vol_Ratio'] >= 1.5 else 0.0)), 1)
        sd = round(min(10.0, float(r['Pct_Deliv']) * 10.0 + (1.5 if r['Delivery_Pct'] >= 0.50 else 0.0)), 1)
        sr = round(min(15.0, float(r['Pct_RS']) * 15.0 + (2.0 if r['RS_5D'] > 0 and r['RS_20D'] > 0 else 0.0)), 1)
        ss = 10.0 if (r['Sec_5D'] > 0.005 and r['RS_vs_Sec'] > 0) else (7.0 if r['RS_vs_Sec'] >= 0 else 4.0)
        su = min(15.0, 7.0 * min(1, r['Engine_Count']) + 4.0 * max(0, r['Engine_Count'] - 1))
        sf = round(min(10.0, (r['Fund_Score_Raw'] / 100.0) * 10.0), 1)
        sc = 5.0 if r['Has_Pos'] else (0.0 if r['Has_Neg'] else 2.5)
        srr = 5.0 if (r['RR_Ratio'] >= 2.0 and r['ADTV_20D_Cr'] >= 2.0) else (2.5 if r['RR_Ratio'] >= 1.6 else 0.0)
        scores.append(round(min(100.0, sp + sv + sd + sr + ss + su + sf + sc + srr), 1))
    adf['Alpha_Score'] = scores

    for idx in adf.index:
        sym, csc = adf.at[idx, 'Symbol'], adf.at[idx, 'Alpha_Score']
        if sym in prev_nm and csc >= 75.0:
            adf.at[idx, 'Confluence_Tags'] = f"🚀 PROMOTED ({prev_nm[sym]:.0f}→{csc:.0f}) | " + adf.at[idx, 'Confluence_Tags']

    adf['Passes_Gate'] = (~adf['Has_Neg']) & (adf['ADTV_20D_Cr'] >= 2.0) & (adf['RR_Ratio'] >= 2.0) & (adf['Engine_Count'] >= 1)

    # Strictly deduplicated Top 5 + Engines E1-E6 + Near-Miss (Zero duplicate rows!)
    out_rows, used = [], set()
    for rk, (_, r) in enumerate(adf[adf['Passes_Gate']].sort_values(by=['Alpha_Score', 'Engine_Count', 'Up_Down_Vol_Ratio'], ascending=[False, False, False]).head(5).iterrows(), 1):
        used.add(r['Symbol'])
        tl = "Elite 85+" if r['Alpha_Score'] >= 85 else ("Strong 75+" if r['Alpha_Score'] >= 75 else "Developing")
        out_rows.append([r['Symbol'], f"🏆 TOP #{rk} BOARD ({tl} • {r['Cap_Group'][:7]})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'], r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'], r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'], r['EOD_Vol_Mult'], r['Avg_Vol_20D'], f"Hold > VWAP & ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:42]}"])

    for ec, el in [('E1', '🔭 E1: PRE-BREAKOUT VCP'), ('E2', '🔭 E2: ACCUMULATION'), ('E3', '🔭 E3: MOMENTUM IGNITION'), ('E4', '🔭 E4: SMART DIP RECOVERY'), ('E5', '🔭 E5: RS LEADER'), ('E6', '🔭 E6: CATALYST HUNTER')]:
        for _, r in adf[adf[ec] & (~adf['Has_Neg']) & (~adf['Symbol'].isin(used))].sort_values(by=['Alpha_Score', 'Up_Down_Vol_Ratio'], ascending=[False, False]).head(3).iterrows():
            used.add(r['Symbol'])
            out_rows.append([r['Symbol'], f"{el} ({r['Cap_Group'][:7]})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'], r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'], r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'], r['EOD_Vol_Mult'], r['Avg_Vol_20D'], f"Reject if < ₹{r['Stop_Loss']} SL | {r['Cat_Text'][:45]}"])

    nm_df = adf[(adf['Alpha_Score'] >= 65.0) & (adf['Alpha_Score'] < 75.0) & (~adf['Has_Neg']) & (~adf['Symbol'].isin(used))].sort_values(by='Alpha_Score', ascending=False).head(15)
    nm_df[['Symbol', 'Alpha_Score']].to_csv("Alpha_Near_Miss.csv", index=False)
    for _, r in nm_df.head(8).iterrows():
        out_rows.append([r['Symbol'], f"📈 NEAR-MISS WATCH ({r['Cap_Group'][:7]})", r['Alpha_Score'], r['Confluence_Tags'], r['RSI_14'], r['Up_Down_Vol_Ratio'], r['Delivery_Pct'], r['RS_20D'], r['ADTV_20D_Cr'], r['Entry_Trigger'], r['Stop_Loss'], r['Target'], r['RR_Ratio'], r['EOD_Vol_Mult'], r['Avg_Vol_20D'], f"Promote if > ₹{r['Entry_Trigger']} & Vol > 1.5x | {r['Cat_Text'][:38]}"])

    pd.DataFrame(out_rows, columns=["Symbol", "Hunter_Bucket", "Alpha_Score", "Confluence_Tags", "RSI_14", "Up_Down_Vol_Ratio", "Delivery_Pct", "RS_20D", "ADTV_20D_Cr", "Entry_Trigger", "Stop_Loss", "Target", "RR_Ratio", "EOD_Vol_Mult", "Avg_Vol_20D", "Catalyst_Invalidation"]).to_csv("RAW_ALPHA_HUNTER.csv", index=False)

def export_smart_sip_vault(df, raw_data, fund_cache):
    core_syms = ["RELIANCE", "HDFCBANK", "LT", "HAL", "BEL", "TATAPOWER", "RVNL", "CDSL", "DIXON", "NETWEB", "VOLTAS", "TITAN", "ETERNAL", "GROWW", "KPITTECH"]
    if os.path.exists("Smart_SIP_Vault_List.csv"):
        try:
            for s in pd.read_csv("Smart_SIP_Vault_List.csv")['Symbol'].dropna().tolist():
                cs = str(s).strip().upper()
                if cs and cs not in core_syms: core_syms.append(cs)
        except:
            pass

    missing = [s + ".NS" for s in core_syms if 'Close' not in raw_data.columns or (s + ".NS") not in raw_data['Close'].columns]
    extra = {}
    for mt in missing:
        try:
            dl = yf.download(mt, period="1y", interval="1d", progress=False)
            if not dl.empty: extra[mt] = dl
        except:
            pass

    sip_recs = []
    for sym in core_syms:
        tkr = sym + ".NS"
        if 'Close' in raw_data.columns and tkr in raw_data['Close'].columns:
            c, h, l = safe_series(raw_data['Close'], tkr).dropna(), safe_series(raw_data['High'], tkr), safe_series(raw_data['Low'], tkr)
        elif tkr in extra:
            dl = extra[tkr]
            c = (safe_series(dl['Close'], tkr) if isinstance(dl['Close'], pd.DataFrame) else pd.to_numeric(dl['Close'], errors='coerce')).dropna()
            h = safe_series(dl['High'], tkr) if isinstance(dl['High'], pd.DataFrame) else pd.to_numeric(dl['High'], errors='coerce')
            l = safe_series(dl['Low'], tkr) if isinstance(dl['Low'], pd.DataFrame) else pd.to_numeric(dl['Low'], errors='coerce')
        else:
            continue
        if len(c) < 30: continue
        h, l = h.reindex(c.index).ffill(), l.reindex(c.index).ffill()

        cur_c = round(float(c.iloc[-1]), 2)
        ema20 = round(float(c.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
        ema50 = round(float(c.ewm(span=50, adjust=False).mean().iloc[-1]), 2)
        ema200 = round(float(c.ewm(span=200, adjust=False).mean().iloc[-1]), 2) if len(c) >= 100 else ema50
        rsi_14 = calc_wilder_rsi(c, 14)

        w_h, w_l = (h.iloc[-252:] if len(h) >= 252 else h), (l.iloc[-252:] if len(l) >= 252 else l)
        high_52w, low_52w = round(float(w_h.max()), 2), round(float(w_l.min()), 2)

        sup60, sup20 = (float(l.iloc[-60:].quantile(0.12)) if len(l) >= 60 else float(l.min())), float(l.iloc[-20:].min())
        low_emas = [e for e in [ema20, ema50, ema200] if e <= cur_c * 1.01]
        sup_z = round(max(low_52w, min(cur_c * 0.99, 0.50 * sup60 + 0.30 * sup20 + 0.20 * (max(low_emas) if low_emas else sup60))), 2)
        res60, res20 = (float(h.iloc[-60:].quantile(0.90)) if len(h) >= 60 else float(h.max())), float(h.iloc[-20:].max())
        res_z = round(min(high_52w, max(cur_c * 1.01, 0.50 * res60 + 0.50 * res20)), 2)

        info = fund_cache.get(tkr, {}) if isinstance(fund_cache.get(tkr), dict) else {}
        if not info or ('freeCashflow' not in info and 'bookValue' not in info and 'targetLowPrice' not in info):
            try:
                li = yf.Ticker(tkr).info
                if isinstance(li, dict) and len(li) > 5: info = li
            except:
                pass

        rm_df = df[df['Symbol'] == sym] if not df.empty else pd.DataFrame()
        if not rm_df.empty:
            rm = rm_df.iloc[0]
            comp, sec = str(rm.get('Company', sym)), str(rm.get('Industry', info.get('sector', 'NSE Core')))
            roe, debt_eq, deliv = float(info.get('returnOnEquity') or rm.get('ROE') or 0.0), float(rm.get('Debt-to-Eq') or 0.0), float(rm.get('Delivery_Pct') or 0.45)
            own = min(1.0, float(rm.get('Promoter Holding') or 0.0) + float(rm.get('FII/DII') or 0.0))
        else:
            comp, sec = str(info.get('shortName') or info.get('longName') or sym), str(info.get('sector') or 'NSE Core')
            roe, debt_eq, deliv = float(info.get('returnOnEquity') or 0.0), float(info.get('debtToEquity') or 0.0), 0.48
            own = min(1.0, float(info.get('heldPercentInsiders') or 0.0) + float(info.get('heldPercentInstitutions') or 0.0))

        is_fin = any(k in sec.lower() for k in ['bank', 'financial', 'nbfc', 'insurance']) or sym in ['HDFCBANK', 'GROWW', 'CDSL']
        bv, feps = float(info.get('bookValue') or 0.0), float(info.get('forwardEps') or info.get('trailingEps') or 0.0)
        fcf, ocf = float(info.get('freeCashflow') or 0.0), float(info.get('operatingCashflow') or 0.0)
        cash_r, tdebt, sh_out = float(info.get('totalCash') or 0.0), float(info.get('totalDebt') or 0.0), float(info.get('sharesOutstanding') or 0.0)

        tech_fl = min(cur_c * 0.98, 0.65 * sup_z + 0.35 * ema20) if (cur_c < ema50 and ema50 < ema200) else min(cur_c * 1.02, 0.30 * ema50 + 0.45 * ema200 + 0.25 * sup_z)
        fest = []
        if is_fin:
            if bv > 0: fest.append(bv * min(4.5, max(1.6, (roe if roe > 0 else 0.14) * 14.5)))
            if feps > 0: fest.append(feps * 18.0)
            fin_h = f"{f'P/B {cur_c/bv:.1f}x' if bv > 0 else 'Fin/NBFC'} | ROE {roe*100:.1f}% | Book ₹{bv:.0f} | Bank/Fin"
        else:
            ncps = ((cash_r - tdebt) / sh_out) if sh_out > 0 else 0.0
            cfv = fcf if fcf > 0 else (ocf * 0.75 if ocf > 0 else 0.0)
            if cfv > 0 and sh_out > 0: fest.append((cfv / sh_out) * (22.0 if roe >= 0.20 else 16.0) + max(0.0, ncps))
            if feps > 0: fest.append(feps * (26.0 if roe >= 0.22 else (20.0 if roe >= 0.14 else 15.0)))
            cf_cr, cf_lbl = ((fcf / 1e7, "FCF") if fcf != 0 else (ocf / 1e7, "OCF"))
            fin_h = f"{cf_lbl} ₹{cf_cr:,.0f}Cr | Cash ₹{cash_r/1e7:,.0f}Cr | ROE {roe*100:.1f}% | D/E {debt_eq:.1f}"

        f_anc = max(cur_c * 0.72, min(cur_c * 1.05, float(np.median(fest)))) if fest else tech_fl * (1.02 if roe >= 0.18 else 0.96)
        t_low, t_mean = float(info.get('targetLowPrice') or 0.0), float(info.get('targetMeanPrice') or 0.0)
        rec_k = str(info.get('recommendationKey') or 'hold').upper().replace('_', ' ')
        s_base = t_low if t_low > 0 else (t_mean * 0.80 if t_mean > 0 else tech_fl)
        s_fl = max(cur_c * 0.75, min(cur_c * 1.05, s_base * (1.02 if (deliv >= 0.50 and own >= 0.60) else (0.97 if deliv < 0.35 else 1.0))))
        t_str = f"Floor ₹{t_low:.0f}" if t_low > 0 else (f"Mean ₹{t_mean:.0f}" if t_mean > 0 else "Tech Floor")
        st_flow = f"{rec_k} ({t_str}) | Deliv {deliv*100:.1f}% | Own {own*100:.0f}%"

        m_price = round(max(low_52w * 0.92, min(high_52w * 0.92, 0.40 * tech_fl + 0.35 * f_anc + 0.25 * s_fl)), 2)
        sip_recs.append({
            'Symbol': sym, 'Company': comp, 'Live_CMP': cur_c, 'Machine_Accum': m_price,
            'EMA_20': ema20, 'EMA_50': ema50, 'EMA_200': ema200, 'Support_Zone': sup_z, 'Resistance_Zone': res_z,
            'High_52W': high_52w, 'Low_52W': low_52w, 'RSI_14': rsi_14, 'Fin_Health': fin_h, 'Street_Flow': st_flow,
            'ROE': round(roe, 4), 'Debt_Eq': round(debt_eq, 2), 'Delivery_Pct': round(deliv, 4)
        })
    if sip_recs:
        pd.DataFrame(sip_recs).to_csv("RAW_SMART_SIP.csv", index=False)
