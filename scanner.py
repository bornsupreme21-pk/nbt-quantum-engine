import os, json, warnings, datetime
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from quantum_modules import (
    safe_series, calc_wilder_rsi, classify_sector, clean_and_update_universe,
    fetch_nse_delivery_map, fetch_real_nse_fo_oi, fetch_stock_news_catalyst,
    fetch_macro_and_history, export_alpha_hunter, export_smart_sip_vault
)

warnings.filterwarnings('ignore')

def run_quantum_engine():
    now_ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    current_mins = now_ist.hour * 60 + now_ist.minute

    try: univ = pd.read_csv("Universe_List.csv")
    except: univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    univ = clean_and_update_universe(univ)
    tickers = (univ['Symbol'] + '.NS').tolist()

    nse_deliv_map = fetch_nse_delivery_map()
    real_fo_map = fetch_real_nse_fo_oi()

    try:
        mem_df = pd.read_csv("Historical_Holdings.csv")
        mem_df['Date'] = pd.to_datetime(mem_df['Date'])
        mem_df = mem_df[mem_df['Date'] >= (pd.to_datetime(datetime.date.today()) - pd.Timedelta(days=365))]
    except:
        mem_df = pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])

    valid_mem = mem_df[(mem_df['Prom_Pct'] > 0) | (mem_df['FII_Pct'] > 0)] if not mem_df.empty else pd.DataFrame(columns=['Symbol', 'Date', 'Prom_Pct', 'FII_Pct'])
    oldest_rec = valid_mem.sort_values('Date').groupby('Symbol').first().to_dict('index') if not valid_mem.empty else {}
    latest_rec = valid_mem.sort_values('Date').groupby('Symbol').last().to_dict('index') if not valid_mem.empty else {}
    today_mem = []

    fundamentals = {}
    if os.path.exists('fundamentals_cache.json'):
        try:
            with open('fundamentals_cache.json', 'r') as f: fundamentals = json.load(f)
        except: fundamentals = {}

    valid_cached = sum(1 for v in fundamentals.values() if isinstance(v, dict) and (v.get('heldPercentInsiders') or v.get('returnOnEquity') or v.get('trailingPE')))
    is_eod_heavy = (current_mins >= (16 * 60 + 20)) or (valid_cached < 150)

    if is_eod_heavy:
        def fetch_one_info(t):
            try:
                inf = yf.Ticker(t).info
                if isinstance(inf, dict) and len(inf) > 5: return t, inf
            except: pass
            return t, None
        with ThreadPoolExecutor(max_workers=10) as ex:
            for t_sym, inf_d in ex.map(fetch_one_info, tickers):
                if inf_d: fundamentals[t_sym] = inf_d
        try:
            with open('fundamentals_cache.json', 'w') as f: json.dump(fundamentals, f)
        except: pass

    try: raw_data = yf.download(tickers + ['^NSEI'], period=("2y" if is_eod_heavy else "1y"), interval="1d", progress=False)
    except: return

    nifty_20d_ret, nifty_var, nifty_ret_clean = 0.0, 0.0, pd.Series(dtype=float)
    try:
        nc = safe_series(raw_data['Close'], '^NSEI').dropna()
        if len(nc) >= 21: nifty_20d_ret = float((nc.iloc[-1] / nc.iloc[-21]) - 1)
        ncc = nc.copy(); ncc.index = pd.to_datetime(ncc.index).tz_localize(None).normalize()
        nifty_ret_clean = ncc.pct_change().dropna()
        nifty_var = float(nifty_ret_clean.var())
    except: pass

    fallback_fo = {"RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL", "LT", "BAJFINANCE", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA", "ULTRACEMCO", "NTPC", "TATAMOTORS", "TITAN", "POWERGRID", "ONGC", "M&M", "COALINDIA", "BAJAJFINSV", "ASIANPAINT", "ADANIPORTS", "HCLTECH", "TATAPOWER", "PFC", "RECLTD", "HAL", "BEL"}
    results = []

    def process(row):
        symbol = str(row['Symbol']).strip().upper()
        ticker = symbol + '.NS'
        info = fundamentals.get(ticker, {}) if isinstance(fundamentals.get(ticker), dict) else {}
        rc = row.get('Company')
        company_name = (info.get('shortName') or info.get('longName') or symbol) if (pd.isna(rc) or not str(rc).strip() or str(rc).strip().lower() == 'nan' or str(rc).strip() == symbol) else str(rc).strip()
        try:
            if 'Close' not in raw_data.columns or ticker not in raw_data['Close'].columns: return None
            c = safe_series(raw_data['Close'], ticker).dropna()
            if len(c) < 20: return None
            h, l, v = safe_series(raw_data['High'], ticker).reindex(c.index).ffill(), safe_series(raw_data['Low'], ticker).reindex(c.index).ffill(), safe_series(raw_data['Volume'], ticker).reindex(c.index).fillna(0)

            cur_close = float(c.iloc[-1])
            last_vol = float(v.iloc[-1]) if not v.empty else 0.0
            vol_30d = float(v.iloc[-30:].mean()) if len(v) >= 30 else float(v.mean())
            turnover_30d = vol_30d * cur_close
            ret_1d = round(((cur_close / float(c.iloc[-2])) - 1), 4) if len(c) >= 2 else 0.0
            wick_pct = (cur_close - float(l.iloc[-1])) / (float(h.iloc[-1]) - float(l.iloc[-1])) if (float(h.iloc[-1]) - float(l.iloc[-1])) > 0 else 0.0

            is_liquid = turnover_30d >= 10000000
            is_penny_spike = (not is_liquid) and (turnover_30d >= 1500000 and ((last_vol >= vol_30d * 2.0 and ret_1d >= 0.025) or (cur_close * last_vol >= 5000000 and ret_1d >= 0.035)))
            sector_name = classify_sector(symbol, row.get('Industry', 'Unknown'))
            if "BEYOND" in sector_name.upper() and not is_liquid and not is_penny_spike: return None

            is_recent_ipo = len(c) < 180
            w_52h, w_52l = (h.iloc[-252:] if len(h) >= 252 else h), (l.iloc[-252:] if len(l) >= 252 else l)
            h_52w, l_52w = float(w_52h.max()), float(w_52l.min())
            h_52w_date, l_52w_date = w_52h.idxmax().strftime('%d-%b-%Y'), w_52l.idxmin().strftime('%d-%b-%Y')
            dist_52l = round((cur_close - l_52w) / max(0.01, l_52w), 4)
            disc_52h = round((cur_close - h_52w) / max(0.01, h_52w), 4)

            ret_5d = round(((cur_close / float(c.iloc[-6])) - 1), 4) if len(c) >= 6 else 0.0
            ret_20d = round(((cur_close / float(c.iloc[-21])) - 1), 4) if len(c) >= 21 else 0.0
            ret_50d = round(((cur_close / float(c.iloc[-51])) - 1), 4) if len(c) >= 51 else 0.0
            rs_vs_nifty = round(ret_20d - nifty_20d_ret, 4)

            beta_val = None
            try:
                if len(c) >= 30 and not nifty_ret_clean.empty and nifty_var > 0:
                    cc = c.copy(); cc.index = pd.to_datetime(cc.index).tz_localize(None).normalize()
                    al = pd.concat([cc.pct_change().dropna(), nifty_ret_clean], axis=1).ffill().dropna()
                    if len(al) >= 30:
                        nv = np.var(al.iloc[-245:, 1].values, ddof=1)
                        if nv > 0: beta_val = round(max(0.15, min(2.50, float(np.cov(al.iloc[-245:, 0].values, al.iloc[-245:, 1].values, ddof=1)[0, 1] / nv))), 2)
            except: pass
            if beta_val is None: beta_val = 1.00 if is_recent_ipo else 1.05

            ema20, ema50, ema200 = float(c.ewm(span=20, adjust=False).mean().iloc[-1]), float(c.ewm(span=50, adjust=False).mean().iloc[-1]), float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            slope_200 = ema200 - float(c.ewm(span=200, adjust=False).mean().iloc[-20]) if len(c) >= 25 else 0.0
            dsr = (last_vol * 1.25) / vol_30d if vol_30d > 0 else 1.0
            is_vdu = dsr <= 0.55

            # True Wilder 14D RSI (Fixes frozen 50.00 across all 896 stocks!)
            rsi = calc_wilder_rsi(c, 14)

            # Sanitized Ownership & Fundamental Outliers
            raw_in, raw_inst = info.get('heldPercentInsiders'), info.get('heldPercentInstitutions')
            saved = latest_rec.get(symbol, {})
            if (raw_in is None or float(raw_in) <= 0.0) and saved.get('Prom_Pct', 0) > 0: raw_in = float(saved['Prom_Pct'])
            if (raw_inst is None or float(raw_inst) <= 0.0) and saved.get('FII_Pct', 0) > 0: raw_inst = float(saved['FII_Pct'])

            prom_curr = min(0.99, max(0.0, float(raw_in))) if raw_in else 0.0
            fii_curr = min(0.95, max(0.0, float(raw_inst))) if raw_inst else 0.0
            if prom_curr + fii_curr > 1.0: fii_curr = round(max(0.0, 1.0 - prom_curr), 4)

            prom_old = float(oldest_rec.get(symbol, {}).get('Prom_Pct', prom_curr))
            fii_old = float(oldest_rec.get(symbol, {}).get('FII_Pct', fii_curr))
            prom_delta = round(prom_curr - prom_old, 4) if prom_curr > 0 else 0.0
            fii_delta = round(fii_curr - fii_old, 4) if fii_curr > 0 else 0.0
            if prom_curr > 0 or fii_curr > 0: today_mem.append({'Symbol': symbol, 'Date': datetime.date.today(), 'Prom_Pct': prom_curr, 'FII_Pct': fii_curr})

            pe_val = float(info.get('trailingPE') or info.get('forwardPE') or 0.0)
            bv_val = float(info.get('bookValue') or 0.0)
            raw_roe = info.get('returnOnEquity')
            final_roe = float(raw_roe) if raw_roe is not None else ((cur_close / (pe_val * bv_val)) if pe_val > 0 and bv_val > 0 else 0.0)
            final_roe = round(max(-1.0, min(1.50, final_roe)), 4)

            raw_debt = info.get('debtToEquity')
            debt_val = round(min(999.0, max(0.0, float(raw_debt))), 2) if raw_debt is not None else 0.0
            raw_dy = float(info.get('dividendYield', 0) or 0)
            norm_dy = round(min(0.15, (raw_dy / 100.0 if raw_dy > 0.25 else raw_dy)), 4) if raw_dy > 0 else 0.0
            raw_growth = float(info.get('revenueGrowth') or 0.0)
            raw_q_growth = float(info.get('earningsQuarterlyGrowth') or 0.0)

            deliv_pct = nse_deliv_map[symbol] if symbol in nse_deliv_map else round(min(0.65, max(0.32, 0.38 + (fii_curr * 0.30) + (wick_pct * 0.12))), 4)
            is_bank_or_fin = any(k in sector_name.lower() for k in ['bank', 'financial', 'nbfc', 'insurance'])

            # Granular Continuous Fundamental Score (0-99.5, eliminates 20-way ties at 100!)
            sc_own = min(25.0, (prom_curr * 25.0) + (fii_curr * 35.0))
            sc_roe = min(25.0, max(0.0, final_roe * 95.0)) if final_roe > 0 else 0.0
            sc_debt = 20.0 if (is_bank_or_fin or debt_val <= 15) else max(0.0, 20.0 - (debt_val * 0.18))
            sc_grw = min(15.0, max(0.0, (max(raw_growth, raw_q_growth) + 0.05) * 45.0))
            sc_del = min(15.0, max(0.0, (deliv_pct - 0.25) * 40.0))
            fund_score = round(min(99.5, sc_own + sc_roe + sc_debt + sc_grw + sc_del), 1)

            accum_status = "💎 SILENT ACCUMULATION" if (fund_score >= 68 and is_vdu and dist_52l < 0.35) else ("🟢 STRONG HOLDINGS" if fund_score >= 68 else "NEUTRAL")
            passes_quality = (fund_score >= 48 and (final_roe >= 0.08 or final_roe == 0.0) and (debt_val < 90 or is_bank_or_fin) and (pe_val < 95 or is_bank_or_fin or pe_val == 0.0) and cur_close >= ema200 * 0.96)

            # Real NSE F&O Futures Open Interest & Put-Call Ratio (with transparent proxy fallback)
            fo_regime, oi_chg_pct, oi_total = "CASH STOCK", 0.0, 0
            if symbol in real_fo_map:
                fi = real_fo_map[symbol]
                oi_total, oi_chg_pct, pcr = fi['oi'], fi['oi_chg_pct'], fi['pcr']
                if ret_1d > 0.004 and oi_chg_pct > 0.01: fo_regime = f"🟢 LONG BUILDUP (PCR {pcr})"
                elif ret_1d < -0.004 and oi_chg_pct > 0.01: fo_regime = f"🔴 SHORT BUILDUP (PCR {pcr})"
                elif ret_1d > 0.004 and oi_chg_pct < -0.01: fo_regime = f"⚠️ SHORT COVERING (PCR {pcr})"
                elif ret_1d < -0.004 and oi_chg_pct < -0.01: fo_regime = f"🩸 LONG UNWINDING (PCR {pcr})"
                else: fo_regime = f"⚖️ RANGEBOUND OI (PCR {pcr})"
            elif not real_fo_map and symbol in fallback_fo:
                oi_total = int(vol_30d * 3.5)
                if ret_1d > 0.005 and dsr > 1.2 and deliv_pct > 0.45: fo_regime, oi_chg_pct = "🟢 LONG BUILDUP (Proxy)", round(dsr * 0.02, 4)
                elif ret_1d < -0.005 and dsr > 1.2: fo_regime, oi_chg_pct = "🔴 SHORT BUILDUP (Proxy)", round(dsr * 0.02, 4)
                elif ret_1d > 0.005 and dsr < 0.8: fo_regime, oi_chg_pct = "⚠️ SHORT COVERING (Proxy)", round(-dsr * 0.015, 4)
                elif ret_1d < -0.005 and dsr < 0.8: fo_regime, oi_chg_pct = "🩸 LONG UNWINDING (Proxy)", round(-dsr * 0.015, 4)
                else: fo_regime, oi_chg_pct = "⚖️ RANGEBOUND (Proxy)", round((dsr - 1.0) * 0.01, 4)

            pc = c.shift(1)
            tr = pd.concat([(h.iloc[-14:] - l.iloc[-14:]), (h.iloc[-14:] - pc.iloc[-14:]).abs(), (l.iloc[-14:] - pc.iloc[-14:]).abs()], axis=1).max(axis=1)
            atr14 = float(tr.mean()) if not tr.empty else cur_close * 0.02
            atr_pct = round(atr14 / max(0.01, cur_close), 4)

            is_brk = (cur_close > float(h.iloc[-21:-1].max())) if len(h) >= 21 else False
            is_lp = (passes_quality and cur_close >= ema20 * 0.995 and ema20 >= ema50 * 0.985 and 50.0 <= rsi <= 68.0 and 0.015 <= ret_20d <= 0.18 and disc_52h >= -0.18 and deliv_pct >= 0.42 and ret_1d >= -0.015)
            is_piv = (passes_quality and 0.01 <= ret_1d <= 0.06 and dsr >= 1.3 and cur_close >= ema20 and cur_close >= ema50 and 48.0 <= rsi <= 69.0 and ret_20d <= 0.18 and wick_pct >= 0.58)
            is_cap = False
            if rsi > 73 or ret_20d > 0.22: alert_type = "🚨 OVEREXTENDED (Train Left - Wait)"
            elif is_lp: alert_type = "🎯 LAUNCHPAD COIL (Pre-Breakout)"
            elif is_piv: alert_type = "🔥 DAY-1 POCKET PIVOT (Fresh Motion)"
            elif is_brk and dsr > 1.2 and rsi <= 70 and passes_quality: alert_type = "🚀 20D BREAKOUT (Early Stage)"
            elif is_penny_spike and rsi <= 70 and passes_quality: alert_type = "🌋 QUALITY MICROCAP AWAKENING"
            elif is_penny_spike or (is_brk and not passes_quality): alert_type = "⚠️ SPECULATIVE SPIKE (Weak Fund)"
            elif is_vdu and cur_close > ema50 and 44 <= rsi <= 66 and passes_quality: alert_type = "⚡ VCP + VDU TIGHT COIL"
            elif ret_1d <= -0.05 and rsi <= 35 and (wick_pct > 0.35 or dsr >= 1.5): is_cap, alert_type = True, "💥 CAPITULATION BOUNCE"
            elif cur_close < ema200 and slope_200 < 0: alert_type = "📉 DOWNTREND (Avoid)"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05) and rsi >= 44 and passes_quality: alert_type = "🛡️ 50-EMA PULLBACK SUPPORT"
            else: alert_type = "Standard"

            sl_price = round(float(l.iloc[-1]) * 0.98, 2) if is_cap else round(min(max(cur_close - 1.8 * atr14, cur_close * 0.955), cur_close * 0.982), 2)
            target_7 = round(cur_close + (4.0 * atr14), 2) if is_cap else round(cur_close + max(cur_close * 0.075, 3.2 * atr14), 2)
            risk = max(0.01, cur_close - sl_price)
            rr_ratio = round((target_7 - cur_close) / risk, 2)

            events_list, e_blk, post_e = [], False, False
            if is_recent_ipo: events_list.append("🆕 RECENT IPO")
            if prom_delta > 0.01: events_list.append(f"🐋 PROMOTER BUY (+{round(prom_delta*100,1)}%)")
            if fii_delta > 0.01: events_list.append(f"🏦 FII BUY (+{round(fii_delta*100,1)}%)")
            ex_ts = info.get('exDividendDate')
            if ex_ts:
                ex_dt = datetime.datetime.fromtimestamp(int(ex_ts)).date()
                if 0 <= (ex_dt - datetime.date.today()).days <= 10: events_list.append(f"💰 EX-DIV ({ex_dt.strftime('%d-%b')})")
            e_ts = info.get('earningsTimestamp', info.get('earningsTimestampStart'))
            if e_ts:
                e_dt = datetime.datetime.fromtimestamp(int(e_ts)).date()
                if 0 <= (e_dt - datetime.date.today()).days <= 5: events_list.append(f"📅 EARNINGS ({e_dt.strftime('%d-%b')})"); e_blk = True
                elif -5 <= (e_dt - datetime.date.today()).days < 0 and ret_1d > 0.015 and dsr >= 1.8: events_list.append(f"🚀 POST-RESULT ({e_dt.strftime('%d-%b')})"); post_e = True

            if e_blk: verdict, sp = "🚨 EARNINGS BLACKOUT (WAIT)", 5
            elif alert_type in ["🎯 LAUNCHPAD COIL (Pre-Breakout)", "🔥 DAY-1 POCKET PIVOT (Fresh Motion)", "🚀 20D BREAKOUT (Early Stage)", "🌋 QUALITY MICROCAP AWAKENING"]: verdict, sp = f"🎯 STRONG BUY: ₹{round(cur_close,2)}", 1
            elif alert_type in ["⚡ VCP + VDU TIGHT COIL", "🛡️ 50-EMA PULLBACK SUPPORT"]: verdict, sp = f"🟢 ACCUMULATE: ₹{round(cur_close,2)}", 2
            elif is_cap: verdict, sp = f"⚡ CONTRARIAN BOUNCE: ₹{round(cur_close,2)}", 3
            elif alert_type in ["🚨 OVEREXTENDED (Train Left - Wait)", "⚠️ SPECULATIVE SPIKE (Weak Fund)"]: verdict, sp = "⚠️ AVOID / CHECK FUNDAMENTALS", 4
            elif alert_type == "📉 DOWNTREND (Avoid)": verdict, sp = "⛔ STRICT SKIP", 6
            else: verdict, sp = "⏳ WAIT", 3

            dust_score = (25 if final_roe >= 0.15 else (10 if final_roe >= 0.10 else 0)) + (15 if prom_curr >= 0.50 else 0) + (15 if fii_curr >= 0.15 else 0) + (15 if debt_val < 30 else 0) + (30 if disc_52h <= -0.30 else (20 if disc_52h <= -0.20 else (10 if disc_52h <= -0.12 else 0))) + (15 if 0 < pe_val < 25 else 0)
            fear_score, cat_tag = 0.0, "⚪ Normal Flow"
            if is_lp: cat_tag = f"🎯 PRE-BREAKOUT COIL (RSI {int(rsi)} • Deliv {int(deliv_pct*100)}%)"
            elif is_piv: cat_tag = f"🔥 DAY-1 IGNITION (+{round(ret_1d*100,1)}% • {round(dsr,1)}x Vol)"
            elif is_cap: fear_score, cat_tag = 1000 + fund_score, f"💥 CAPITULATION REVERSAL ({round(ret_1d*100,1)}% • RSI {int(rsi)})"
            elif ret_1d <= -0.045 and dsr >= 2.8: cat_tag = "⛔ TOXIC DISTRIBUTION DUMP (FOUL PLAY RISK)"
            elif passes_quality and not e_blk:
                if post_e: fear_score, cat_tag = round(dsr * 35 + fund_score, 1), f"🚀 POST-EARNINGS SURGE (+{round(ret_1d*100,1)}%)"
                elif -0.08 <= ret_1d <= -0.025 and cur_close >= ema200 * 0.97 and dsr < 2.8: fear_score, cat_tag = round(abs(ret_1d) * 1000 + fund_score, 1), f"😱 FEAR DIP ({round(ret_1d*100,1)}%) • Intact 200-EMA"
                elif -0.12 <= ret_5d <= -0.045 and rsi <= 42 and cur_close >= ema200 * 0.95: fear_score, cat_tag = round(abs(ret_5d) * 800 + fund_score, 1), f"🌊 CONTAGION DIP ({round(ret_5d*100,1)}% 5D • RSI {int(rsi)})"

            alpha_sp = ret_1d - (beta_val * (nifty_20d_ret / 20.0))
            if rsi >= 72 and ret_1d > 0.02: m_pred = "⚠️ OVEREXTENDED (Profit Booking)"
            elif is_lp or is_piv: m_pred = "🚀 EARLY MOTION LAUNCHPAD (+Alpha)"
            elif rsi <= 35 and alpha_sp >= 0: m_pred = "💎 OVERSOLD REBOUND (Strong Floor)"
            elif alpha_sp >= 0.0075 and ret_1d > 0: m_pred = "🟢 BULLISH OUTPERFORMER (+Alpha)"
            elif ret_1d > 0 and nifty_20d_ret < -0.003: m_pred = "⚡ CONTRA STRENGTH (Defying Nifty)"
            elif alpha_sp <= -0.0075 and ret_1d < 0: m_pred = "🔴 BEARISH DRAG (Weak vs Nifty)"
            elif ret_1d >= 0: m_pred = "🟢 POSITIVE BIAS (Tracking Trend)"
            else: m_pred = "⚖️ MILD DRIFT / CONSOLIDATING"

            best_m, worst_m = "N/A", "N/A"
            try:
                m_ret = c.groupby(c.index.to_period('M')).last().pct_change().dropna()
                if len(m_ret) > 10:
                    m_avg = m_ret.groupby(m_ret.index.strftime('%B')).mean()
                    if not m_avg.empty: best_m, worst_m = m_avg.idxmax(), m_avg.idxmin()
            except: pass

            return {
                'Symbol': symbol, 'Company': company_name, 'Industry': sector_name, 'Is_Microcap_Spike': is_penny_spike,
                'Sort_Priority': sp, 'Trading Verdict': verdict, 'Alert Type': alert_type, 'Entry Trigger': round(cur_close, 2),
                'Stop Loss': sl_price, 'Target 7%': target_7, 'RSI_14': rsi, 'Delivery_Pct': deliv_pct, 'Last_Vol': last_vol,
                'ATR_Pct': atr_pct, 'FO_Regime': fo_regime, 'OI_Total': oi_total, 'OI_Chg_Pct': oi_chg_pct, 'Machine_Prediction': m_pred,
                '52W High Disc %': disc_52h, 'F&O Ceiling': round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2),
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date, '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'R:R Ratio': rr_ratio, 'Pos Size (₹5k Risk)': int(max(1, round(5000.0 / risk))), 'RS vs Nifty': rs_vs_nifty,
                'Opportunity Score': fund_score, 'Dust_Gem_Score': dust_score, 'Stage': "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4",
                'Accumulation Status': accum_status, 'Promoter Holding': round(prom_curr, 4), 'Promoter Delta': prom_delta,
                'FII/DII': round(fii_curr, 4), 'FII Delta': fii_delta, 'Dist from 52W Low': dist_52l, 'Disc from 52W High': disc_52h,
                'Debt-to-Eq': debt_val, 'Growth': round(max(-3.0, min(3.0, raw_growth)), 4), 'ROE': final_roe, 'PE Ratio': round(pe_val, 2),
                'Book Value': round(bv_val, 2), 'Div Yield': norm_dy, 'QoQ Growth': round(max(-3.0, min(3.0, raw_q_growth)), 4),
                'Volume Profile': "VDU" if is_vdu else "Normal", 'Corp Event': " | ".join(events_list) if events_list else "Regular Trading",
                'Catalyst Impact': cat_tag, 'Fear_Event_Score': fear_score, 'Beta': beta_val, 'Ret_1D': ret_1d, 'Ret_5D': ret_5d,
                'Ret_20D': ret_20d, 'Ret_50D': ret_50d, 'Best_Month': best_m, 'Worst_Month': worst_m
            }
        except: return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in as_completed({ex.submit(process, row): row for _, row in univ.iterrows()}):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return

    adv_count, dec_count = int((df['Ret_1D'] > 0).sum()), int((df['Ret_1D'] < 0).sum())
    fetch_macro_and_history(adv_count, dec_count, float(df['Delivery_Pct'].mean()))
    if today_mem:
        pd.concat([mem_df, pd.DataFrame(today_mem)]).drop_duplicates(subset=['Symbol', 'Date'], keep='last').to_csv("Historical_Holdings.csv", index=False)

    elig = df[df['Sort_Priority'] <= 2].sort_values(by=["Sort_Priority", "R:R Ratio"], ascending=[True, False])
    if len(elig) < 15:
        elig = pd.concat([elig, df[(df['Stage'] == 'PHASE 2: MARKUP') & (df['RSI_14'].between(46, 69)) & (df['Opportunity Score'] >= 50)]]).drop_duplicates(subset=['Symbol'], keep='first')
    top_swings = pd.concat([elig[~elig['Is_Microcap_Spike']].head(20), elig[elig['Is_Microcap_Spike']].head(5)]).sort_values(by=["Sort_Priority"]).head(25)
    used_syms = set(top_swings['Symbol'].tolist())

    top_inc = df[(df['Accumulation Status'] != "NEUTRAL") & (df['Sort_Priority'] <= 3) & (~df['Symbol'].isin(used_syms))].sort_values(by=["Opportunity Score", "ROE"], ascending=[False, False]).head(20)
    if len(top_inc) < 15:
        top_inc = pd.concat([top_inc, df[(df['Opportunity Score'] >= 55) & (~df['Symbol'].isin(used_syms))].sort_values(by=["Opportunity Score", "ROE"], ascending=[False, False]).head(20)]).drop_duplicates(subset=['Symbol']).head(20)
    used_syms.update(top_inc['Symbol'].tolist())

    fear_cand = df[(df['Fear_Event_Score'] > 0) & (~df['Symbol'].isin(used_syms))].sort_values(by="Fear_Event_Score", ascending=False).head(40)
    used_syms.update(fear_cand['Symbol'].tolist())
    dust_gems = df[(df['Disc from 52W High'] <= -0.15) & (~df['Symbol'].isin(used_syms))].sort_values(by="Dust_Gem_Score", ascending=False).head(40)

    core_watch = {'PFC', 'RELIANCE', 'IRFC', 'IRB', 'MSUMI', 'NMDC', 'ITC', 'BEL', 'ONGC', 'HINDALCO', 'MOTHERSON', 'TATAPOWER', 'MANAPPURAM', 'HDFCBANK', 'GROWW', 'ETERNAL'}
    news_syms = set(top_swings['Symbol']) | set(top_inc['Symbol']) | set(fear_cand['Symbol']) | set(dust_gems['Symbol']) | core_watch
    with ThreadPoolExecutor(max_workers=8) as nex:
        fmap = {nex.submit(fetch_stock_news_catalyst, df.at[i, 'Symbol'], df.at[i, 'Company'], df.at[i, 'Catalyst Impact']): i for i in df[df['Symbol'].isin(news_syms)].index.tolist()}
        for fut in as_completed(fmap):
            try: df.at[fmap[fut], 'Catalyst Impact'] = fut.result()
            except: pass

    fo_df = df[df['FO_Regime'] != "CASH STOCK"].sort_values(by="OI_Total", ascending=False).head(220)
    fo_df[["Symbol", "Company", "Entry Trigger", "Ret_1D", "FO_Regime", "OI_Chg_Pct", "OI_Total", "RSI_14", "Volume Profile", "Machine_Prediction", "52W High Disc %", "Industry"]].to_csv("RAW_FO_DECRYPTOR.csv", index=False)
    df.loc[top_swings.index].sort_values(by=["Sort_Priority"])[["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "Pos Size (₹5k Risk)", "RSI_14", "RS vs Nifty", "F&O Ceiling", "52W High", "52W High Date", "52W Low", "52W Low Date", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value", "Corp Event", "Catalyst Impact"]].to_csv("RAW_SWINGS.csv", index=False)
    df.loc[top_inc.index].sort_values(by=["Opportunity Score"], ascending=[False])[["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Div Yield", "Volume Profile", "Corp Event", "Catalyst Impact"]].to_csv("RAW_INCUBATOR.csv", index=False)

    sniper_rows = []
    for _, r in df.loc[top_swings.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], f"🚀 SWING: {r['Alert Type']}", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], r['RSI_14'], r['R:R Ratio'], r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[top_inc.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], f"💎 COMPOUNDER ({r['Accumulation Status']})", r['Entry Trigger'], round(r['Entry Trigger']*0.96,2), round(r['Entry Trigger']*1.08,2), r['RSI_14'], 2.0, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    for _, r in df.loc[fear_cand.index].iterrows(): sniper_rows.append([r['Symbol'], r['Company'], "⚡ EVENT / 200-EMA FEAR BOUNCE", r['Entry Trigger'], round(r['Entry Trigger']*0.955,2), round(r['Entry Trigger']*1.075,2), r['RSI_14'], 1.67, r['RS vs Nifty'], r['52W High'], r['52W Low'], r['Catalyst Impact'], r['Corp Event']])
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Trigger Price", "Stop Loss", "Target", "RSI_14", "R:R Ratio", "RS vs Nifty", "52W High", "52W Low", "Catalyst / Fear Diagnosis", "Corporate Event"]).to_csv("RAW_SNIPER.csv", index=False)

    fear_rows = []
    for _, r in df.loc[dust_gems.index].iterrows():
        act = "💎 ACCUMULATE (Deep Value)" if r['Disc from 52W High'] <= -0.30 else "🟢 PULLBACK ENTRY"
        fear_rows.append([r['Symbol'], r['Company'], act, r['Entry Trigger'], f"₹{round(r['Entry Trigger']*0.98,2)} - ₹{round(r['Entry Trigger']*1.01,2)}", round(r['Entry Trigger']*0.90,2), round(r['Entry Trigger']*1.15,2), r['RSI_14'], r['Disc from 52W High'], r['Dist from 52W Low'], r['Dust_Gem_Score'], r['PE Ratio'], r['ROE'], r['Promoter Holding'], r['FII/DII'], r['Debt-to-Eq'], r['Corp Event']])
    pd.DataFrame(fear_rows, columns=["Symbol", "Company", "Actionable Verdict", "Live CMP", "Target Buy Zone", "Fear Stop Loss", "Rebound Target (+15%)", "RSI_14", "Disc from 52W High", "Dist from 52W Low", "Dust Gem Score", "PE Ratio", "ROE", "Promoter %", "FII/DII %", "Debt-to-Eq", "Corporate Event"]).to_csv("RAW_FEAR_DIP.csv", index=False)

    # Col Q exports ATR_Pct for Cockpit volatility-adaptive stops/targets
    df.sort_values(by="Promoter Holding", ascending=False)[["Symbol", "Company", "Opportunity Score", "Promoter Holding", "Promoter Delta", "FII/DII", "FII Delta", "Debt-to-Eq", "ROE", "Div Yield", "Industry", "Beta", "Ret_20D", "Disc from 52W High", "RSI_14", "Delivery_Pct", "ATR_Pct"]].to_csv("RAW_PROMOTER.csv", index=False)

    try:
        sec_df = df.groupby('Industry').agg(
            Total_Stocks=('Symbol', 'count'), Uptrend_Count=('Stage', lambda x: (x == 'PHASE 2: MARKUP').sum()),
            Avg_1D_Flow=('Ret_1D', lambda x: round(x.mean() * 100, 2)), Avg_5D_Flow=('Ret_5D', lambda x: round(x.mean() * 100, 2)),
            Avg_Money_Flow=('Ret_20D', lambda x: round(x.mean() * 100, 2)), Avg_50D_Flow=('Ret_50D', lambda x: round(x.mean() * 100, 2)),
            Avg_Deliv=('Delivery_Pct', lambda x: round(x.mean() * 100, 1)), Avg_ROE=('ROE', lambda x: round(x.mean() * 100, 1)),
            Hist_Best_Month=('Best_Month', lambda x: x.mode()[0] if len(x.mode()) > 0 else "N/A"),
            Hist_Worst_Month=('Worst_Month', lambda x: x.mode()[0] if len(x.mode()) > 0 else "N/A")
        ).reset_index()
        sec_df['ISAD (Breadth %)'] = round((sec_df['Uptrend_Count'] / sec_df['Total_Stocks']) * 100, 1)
        sec_df['Sector Status'] = np.where(sec_df['ISAD (Breadth %)'] > 45, "🔥 DOMINANT", np.where(sec_df['ISAD (Breadth %)'] < 20, "⚠️ WASHOUT", "🔄 EMERGING"))

        def get_sm(r):
            if r['Avg_Deliv'] >= 50 and r['Avg_Money_Flow'] > 2.0: return f"💰 INST. ACCUMULATION ({r['Avg_Deliv']}% Deliv)"
            if r['Avg_Money_Flow'] > 3.0: return f"🌊 SECTOR MOMENTUM ({r['Avg_Deliv']}% Deliv)"
            if r['Avg_Money_Flow'] < -3.0: return f"⚠️ DISTRIBUTION ({r['Avg_Deliv']}% Deliv)"
            return f"⚖️ NEUTRAL FLOW ({r['Avg_Deliv']}% Deliv)"
        sec_df['Smart Money Direction'] = sec_df.apply(get_sm, axis=1)

        def get_2y_macro(r):
            if r['ISAD (Breadth %)'] >= 50 and r['Avg_50D_Flow'] > 5 and r['Avg_ROE'] >= 14: return f"🚀 STRUCTURAL LEADER (ROE {r['Avg_ROE']}% • Buy Dips)"
            if r['ISAD (Breadth %)'] >= 35 and r['Avg_50D_Flow'] > 0: return f"🟢 CYCLICAL EXPANSION (ROE {r['Avg_ROE']}% • Hold)"
            if r['ISAD (Breadth %)'] < 20 and r['Avg_ROE'] >= 15: return f"💎 CONTRARIAN TURNAROUND WATCH (ROE {r['Avg_ROE']}%)"
            return f"⚖️ SELECTIVE STOCK-PICKER ZONE (ROE {r['Avg_ROE']}%)"
        sec_df['2Y_Macro_Prediction'] = sec_df.apply(get_2y_macro, axis=1)

        scols = ['Industry', 'Sector Status', 'ISAD (Breadth %)', 'Avg_1D_Flow', 'Avg_5D_Flow', 'Avg_Money_Flow', 'Avg_50D_Flow', 'Hist_Best_Month', 'Hist_Worst_Month', 'Smart Money Direction', '2Y_Macro_Prediction']
        sec_df[scols].sort_values(by=['ISAD (Breadth %)', 'Avg_1D_Flow'], ascending=[False, False]).to_csv("RAW_SECTOR.csv", index=False)
    except: pass

    export_alpha_hunter(df, raw_data)
    export_smart_sip_vault(df, raw_data, fundamentals)

if __name__ == "__main__":
    run_quantum_engine()
