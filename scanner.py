import warnings
import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

def run_quantum_engine():
    print("1. Loading Master Universe...")
    # Reads the Universe_List directly from your GitHub repo
    try:
        univ = pd.read_csv("Universe_List.csv")
    except Exception:
        # Fallback list if Universe_List.csv isn't uploaded yet
        univ = pd.DataFrame({
            'Symbol': ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'BHARTIARTL', 'ITC', 'HFCL', 'IRB'],
            'Company': ['Reliance Ind', 'TCS Ltd', 'HDFC Bank', 'Infosys', 'ICICI Bank', 'SBI', 'Airtel', 'ITC Ltd', 'HFCL Ltd', 'IRB Infra']
        })
    
    univ['Symbol'] = univ['Symbol'].astype(str).str.strip()
    univ['YF_Ticker'] = univ['Symbol'] + '.NS'
    tickers = univ['YF_Ticker'].tolist()
    
    print(f"2. Downloading 5-Year Data for {len(tickers)} stocks...")
    raw_data = yf.download(tickers, period="5y", interval="1d", progress=False)
    
    results = []
    
    def process(row):
        symbol, ticker = row['Symbol'], row['YF_Ticker']
        try:
            c = raw_data['Close'][ticker].dropna()
            if len(c) < 200: return None
            
            h = raw_data['High'][ticker].reindex(c.index).ffill()
            l = raw_data['Low'][ticker].reindex(c.index).ffill()
            v = raw_data['Volume'][ticker].reindex(c.index).ffill()
            
            cur_close = c.iloc[-1]
            vol_30d = v.iloc[-30:].mean()
            if (vol_30d * cur_close) < 10000000: return None  # > 1 Cr ADTV floor
            
            # 52W High / Low & Dates
            w_52h = h.iloc[-252:]
            w_52l = l.iloc[-252:]
            h_52w = w_52h.max()
            h_52w_date = w_52h.idxmax().strftime('%d-%b-%Y')
            l_52w = w_52l.min()
            l_52w_date = w_52l.idxmin().strftime('%d-%b-%Y')
            
            # ATH & Date
            ath_val = h.max()
            ath_date = h.idxmax().strftime('%d-%b-%Y')
            dist_to_ath = round(((ath_val - cur_close) / cur_close) * 100, 1)
            dist_from_52w_low = round(((cur_close - l_52w) / l_52w) * 100, 1)

            # Technicals
            ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
            slope_200 = ema200 - c.ewm(span=200, adjust=False).mean().iloc[-20]
            
            dsr = v.iloc[-1] / vol_30d if vol_30d > 0 else 1
            is_vdu = dsr <= 0.50
            fall_3d = (cur_close - c.iloc[-4]) / c.iloc[-4]
            wick_pct = (cur_close - l.iloc[-1]) / (h.iloc[-1] - l.iloc[-1]) if (h.iloc[-1] - l.iloc[-1]) > 0 else 0
            
            alert_type = "Standard"
            if fall_3d <= -0.05 and dsr >= 2.0 and wick_pct > 0.5: alert_type = "🔥 DEAD BOTTOM"
            elif is_vdu and cur_close > ema50: alert_type = "⚡ VCP + VDU"
            elif dsr >= 5.0 and cur_close < 250: alert_type = "🚀 5x VOL AWAKENING"
            
            nbt_stage = "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4"

            # Risk/Reward Targets
            sl_price = round(l.iloc[-10:].min() * 0.99, 2)
            risk = cur_close - sl_price
            target_7 = round(cur_close * 1.07, 2)
            rr_ratio = round((target_7 - cur_close) / risk, 2) if risk > 0 else 0
            fo_ceiling = round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2)

            trading_verdict = f"🎯 BUY ENTRY: ₹{round(cur_close, 2)}" if (rr_ratio >= 1.5 and alert_type != "Standard") else "⏳ WAIT"

            # Fundamental Proxy
            fund_score, insider_pct, inst_pct, roe, debt_eq = 0, 0, 0, 0, 0
            accum_status = "NEUTRAL"
            if alert_type != "Standard" or dist_from_52w_low < 30:
                try:
                    info = yf.Ticker(ticker).info
                    insider_pct = round((info.get('heldPercentInsiders', 0) or 0) * 100, 2)
                    inst_pct = round((info.get('heldPercentInstitutions', 0) or 0) * 100, 2)
                    roe = round((info.get('returnOnEquity', 0) or 0) * 100, 2)
                    debt_eq = round((info.get('debtToEquity', 0) or 0), 2)
                    if insider_pct >= 50: fund_score += 30
                    if inst_pct >= 15: fund_score += 20
                    if roe > 15: fund_score += 20
                    if debt_eq < 50: fund_score += 30
                    if fund_score >= 70 and is_vdu and dist_from_52w_low < 30: accum_status = "💎 SILENT ACCUMULATION"
                    elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"
                except Exception: pass

            return {
                'Symbol': symbol, 'Company': row.get('Company', symbol),
                'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 'Entry Trigger': round(cur_close, 2),
                'Stop Loss': sl_price, 'Target 7%': target_7, 'F&O Ceiling / Max Pain': fo_ceiling,
                '52W High': round(h_52w, 2), '52W High Date': h_52w_date,
                '52W Low': round(l_52w, 2), '52W Low Date': l_52w_date,
                'ATH': round(ath_val, 2), 'ATH Date': ath_date, 'Dist to ATH (%)': f"{dist_to_ath}%",
                'R:R Ratio': rr_ratio, 'Opportunity Score': fund_score, 'Stage': nbt_stage,
                '🕵️ Accumulation Status': accum_status, 'Promoter Holding (%)': f"{insider_pct}%",
                'FII/DII (%)': f"{inst_pct}%", 'Dist from 52W Low (%)': f"{dist_from_52w_low}%",
                'Debt-to-Equity': debt_eq, 'ROE (%)': f"{roe}%", 'Volume Profile': "VDU" if is_vdu else "Normal"
            }
        except Exception: return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process, row): row for _, row in univ.iterrows()}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return

    print("3. Exporting CSV files directly to repository...")
    
    # Save Momentum Swings
    sw_cols = ["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "F&O Ceiling / Max Pain", "52W High", "52W High Date", "52W Low", "52W Low Date", "ATH", "ATH Date", "Dist to ATH (%)"]
    sw_df = df[sw_cols].sort_values(by="Trading Verdict", ascending=False)
    sw_df.to_csv("swings_output.csv", index=False)

    # Save 10x Incubator
    inc_cols = ["Symbol", "Company", "🕵️ Accumulation Status", "Opportunity Score", "Promoter Holding (%)", "FII/DII (%)", "Dist from 52W Low (%)", "Dist to ATH (%)", "52W Low Date", "ATH Date", "Debt-to-Equity", "ROE (%)", "Volume Profile"]
    inc_df = df[df['🕵️ Accumulation Status'] != "NEUTRAL"][inc_cols].sort_values(by="Opportunity Score", ascending=False)
    inc_df.to_csv("incubator_output.csv", index=False)

    # Save Sniper Watchlist
    top_swings = sw_df[sw_df['Trading Verdict'].str.contains("BUY")].head(15)
    top_inc = inc_df.head(15)
    sniper_rows = []
    for _, r in top_swings.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "MOMENTUM SWING", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], 2.0, r['52W High'], r['52W Low']])
    for _, r in top_inc.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "10X MULTIBAGGER", "Stage-2 Breakout", "50 EMA Floor", "+100% Ride", 5.0, "Near 52W Low", r['Dist from 52W Low (%)']])
    
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Weekly Anchor Buy", "Stop Loss", "Target 7%", "R:R Ratio", "52W High", "52W Low"]).to_csv("sniper_output.csv", index=False)
    print("Done!")

if __name__ == "__main__":
    run_quantum_engine()
