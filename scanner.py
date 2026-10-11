import warnings
import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

def run_quantum_engine():
    print("1. Loading Master Universe...")
    try:
        univ = pd.read_csv("Universe_List.csv")
    except Exception:
        univ = pd.DataFrame({'Symbol': ['RELIANCE'], 'Company': ['Reliance Ind'], 'Industry': ['Oil & Gas']})
    
    if 'Company' not in univ.columns and 'Company Name' in univ.columns:
        univ.rename(columns={'Company Name': 'Company'}, inplace=True)
    
    univ['Symbol'] = univ['Symbol'].astype(str).str.strip()
    univ['YF_Ticker'] = univ['Symbol'] + '.NS'
    tickers = univ['YF_Ticker'].tolist()
    
    print(f"2. Downloading Data for {len(tickers)} stocks... (Wait ~4 mins for Full Fundamentals)")
    raw_data = yf.download(tickers, period="5y", interval="1d", progress=False)
    
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
            if len(c) < 200: return None
            
            h = raw_data['High'][ticker].reindex(c.index).ffill()
            l = raw_data['Low'][ticker].reindex(c.index).ffill()
            v = raw_data['Volume'][ticker].reindex(c.index).ffill()
            
            cur_close = c.iloc[-1]
            vol_30d = v.iloc[-30:].mean()
            if (vol_30d * cur_close) < 10000000: return None 
            
            w_52h = h.iloc[-252:]
            w_52l = l.iloc[-252:]
            h_52w = w_52h.max()
            l_52w = w_52l.min()
            
            dist_from_52w_low = round(((cur_close - l_52w) / l_52w), 4)

            ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
            ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
            slope_200 = ema200 - c.ewm(span=200, adjust=False).mean().iloc[-20]
            
            dsr = v.iloc[-1] / vol_30d if vol_30d > 0 else 1
            is_vdu = dsr <= 0.50
            fall_3d = (cur_close - c.iloc[-4]) / c.iloc[-4]
            wick_pct = (cur_close - l.iloc[-1]) / (h.iloc[-1] - l.iloc[-1]) if (h.iloc[-1] - l.iloc[-1]) > 0 else 0
            
            try:
                delta = c.diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs.iloc[-1]))
            except: rsi = 50

            alert_type = "Standard"
            if rsi > 80: alert_type = "🚨 OVERBOUGHT (Caution)"
            elif cur_close < ema200 and slope_200 < 0: alert_type = "📉 DOWNTREND (Avoid)"
            elif fall_3d <= -0.05 and dsr >= 2.0 and wick_pct > 0.5: alert_type = "🔥 DEAD BOTTOM"
            elif is_vdu and cur_close > ema50: alert_type = "⚡ VCP + VDU"
            elif dsr >= 5.0 and cur_close < 250: alert_type = "🚀 5x VOL AWAKENING"
            elif cur_close > ema50 and cur_close < (ema50 * 1.05): alert_type = "🛡️ PULLBACK SUPPORT"
            
            nbt_stage = "PHASE 2: MARKUP" if (cur_close > ema200 and slope_200 > 0) else "PHASE 1/4"

            sl_price = round(l.iloc[-10:].min() * 0.99, 2)
            risk = cur_close - sl_price
            target_7 = round(cur_close * 1.07, 2)
            rr_ratio = round((target_7 - cur_close) / risk, 2) if risk > 0 else 0
            fo_ceiling = round(np.ceil(cur_close / 50.0) * 50.0, 2) if cur_close > 200 else round(np.ceil(cur_close / 10.0) * 10.0, 2)

            if rr_ratio >= 2.0 and alert_type in ["⚡ VCP + VDU", "🚀 5x VOL AWAKENING", "🔥 DEAD BOTTOM"]:
                trading_verdict = f"🎯 STRONG BUY: ₹{round(cur_close, 2)}"
            elif rr_ratio >= 1.5 and alert_type not in ["Standard", "📉 DOWNTREND (Avoid)", "🚨 OVERBOUGHT (Caution)"]:
                trading_verdict = f"🟢 ACCUMULATE: ₹{round(cur_close, 2)}"
            elif alert_type == "🚨 OVERBOUGHT (Caution)":
                trading_verdict = "⚠️ TRIM / AVOID"
            elif alert_type == "📉 DOWNTREND (Avoid)":
                trading_verdict = "⛔ STRICT SKIP"
            else:
                trading_verdict = "⏳ WAIT"

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
            
            # Export Raw Numbers (Empty Strings if missing) to stop Sheets from guessing
            insider_val = round(raw_in, 4) if raw_in is not None else ""
            inst_val = round(raw_inst, 4) if raw_inst is not None else ""
            roe_val = round(raw_roe, 4) if raw_roe is not None else ""
            debt_val = round(raw_debt, 2) if raw_debt is not None else ""
            growth_val = round(raw_growth, 4) if raw_growth is not None else ""
            q_growth_val = round(raw_q_growth, 4) if raw_q_growth is not None else ""
            pe_val = round(raw_pe, 2) if raw_pe is not None else ""
            bv_val = round(raw_bv, 2) if raw_bv is not None else ""
            
            if raw_in is not None and raw_in >= 0.50: fund_score += 30
            if raw_inst is not None and raw_inst >= 0.15: fund_score += 20
            if raw_roe is not None and raw_roe > 0.15: fund_score += 20
            if raw_debt is not None and raw_debt < 50: fund_score += 30
            
            if fund_score >= 70 and is_vdu and dist_from_52w_low < 0.30: accum_status = "💎 SILENT ACCUMULATION"
            elif fund_score >= 70: accum_status = "🟢 STRONG HOLDINGS"

            return {
                'Symbol': symbol, 'Company': row.get('Company', symbol), 'Industry': row.get('Industry', 'Unknown'),
                'Trading Verdict': trading_verdict, 'Alert Type': alert_type, 'Entry Trigger': round(cur_close, 2),
                'Stop Loss': sl_price, 'Target 7%': target_7, 'F&O Ceiling': fo_ceiling,
                '52W High': round(h_52w, 2), '52W Low': round(l_52w, 2),
                'R:R Ratio': rr_ratio, 'Opportunity Score': fund_score, 'Stage': nbt_stage,
                'Accumulation Status': accum_status, 'Promoter Holding': insider_val,
                'FII/DII': inst_val, 'Dist from 52W Low': dist_from_52w_low,
                'Debt-to-Eq': debt_val, 'Growth': growth_val, 'ROE': roe_val, 'PE Ratio': pe_val, 'Book Value': bv_val, 
                'QoQ Growth': q_growth_val, 'Volume Profile': "VDU" if is_vdu else "Normal"
            }
        except Exception: return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process, row): row for _, row in univ.iterrows()}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)

    df = pd.DataFrame(results)
    if df.empty: return
    
    # 1. Swings Output
    sw_cols = ["Symbol", "Company", "Trading Verdict", "Alert Type", "Entry Trigger", "Stop Loss", "Target 7%", "F&O Ceiling", "52W High", "52W Low", "Debt-to-Eq", "Growth", "PE Ratio", "Book Value"]
    sw_df = df[sw_cols].sort_values(by="Trading Verdict", ascending=False)
    sw_df.to_csv("swings_output.csv", index=False)

    # 2. Incubator Output
    inc_cols = ["Symbol", "Company", "Accumulation Status", "Opportunity Score", "Promoter Holding", "FII/DII", "Dist from 52W Low", "Debt-to-Eq", "ROE", "QoQ Growth", "Volume Profile"]
    inc_df = df[df['Accumulation Status'] != "NEUTRAL"][inc_cols].sort_values(by="Opportunity Score", ascending=False)
    inc_df.to_csv("incubator_output.csv", index=False)

    # 3. Sniper Output
    top_swings = sw_df[sw_df['Trading Verdict'].str.contains("BUY")].head(15)
    top_inc = inc_df.head(15)
    sniper_rows = []
    for _, r in top_swings.iterrows():
        sniper_rows.append([r['Symbol'], r['Company'], "MOMENTUM SWING", r['Entry Trigger'], r['Stop Loss'], r['Target 7%'], 2.0, r['52W High'], r['52W Low']])
    for _, r in top_inc.iterrows():
        matched_row = df[df['Symbol'] == r['Symbol']].iloc[0]
        sniper_rows.append([r['Symbol'], r['Company'], "10X MULTIBAGGER", matched_row['Entry Trigger'], matched_row['Stop Loss'], round(matched_row['Entry Trigger']*2, 2), 5.0, matched_row['52W High'], matched_row['52W Low']])
    pd.DataFrame(sniper_rows, columns=["Symbol", "Company", "Watchlist Type", "Trigger Price", "Stop Loss", "Target", "R:R Ratio", "52W High", "52W Low"]).to_csv("sniper_output.csv", index=False)
    
    # 4. Promoter Output
    promoter_cols = ["Symbol", "Company", "Opportunity Score", "Promoter Holding", "FII/DII", "Debt-to-Eq", "ROE"]
    df[promoter_cols].sort_values(by="Promoter Holding", ascending=False).to_csv("promoter_output.csv", index=False)

    # 5. Sector Output
    df['RS_20D'] = 0.0
    df['RS_50D'] = 0.0
    for idx, row in df.iterrows():
        try:
            ticker = row['Symbol'] + '.NS'
            c = raw_data['Close'][ticker].dropna()
            if len(c) > 50:
                df.at[idx, 'RS_20D'] = round(((c.iloc[-1] / c.iloc[-20]) - 1) * 100, 2)
                df.at[idx, 'RS_50D'] = round(((c.iloc[-1] / c.iloc[-50]) - 1) * 100, 2)
        except Exception: pass

    sector_df = df.groupby('Industry').agg(
        Total_Stocks=('Symbol', 'count'), Uptrend_Count=('Stage', lambda x: (x == 'PHASE 2: MARKUP').sum()),
        Avg_Money_Flow=('RS_20D', 'mean'), Avg_50D_Flow=('RS_50D', 'mean')
    ).reset_index()
    sector_df['ISAD (Breadth %)'] = round((sector_df['Uptrend_Count'] / sector_df['Total_Stocks']) * 100, 1)
    sector_df['Sector Status'] = np.where(sector_df['ISAD (Breadth %)'] > 40, "🔥 DOMINANT", np.where(sector_df['ISAD (Breadth %)'] < 15, "⚠️ WASHOUT", "🔄 EMERGING"))
    
    def get_cycle(industry):
        i = str(industry).lower()
        if any(x in i for x in ['bank', 'financial', 'real estate', 'auto']): return "Interest Rate Cut Cycle (Boom)"
        if any(x in i for x in ['capital goods', 'infrastructure', 'defense', 'power']): return "Govt Capex Cycle (Pre-Election Boom)"
        if any(x in i for x in ['fmcg', 'consumer', 'fertilizer', 'agri']): return "Rural / Monsoon Cycle (Defensive)"
        if any(x in i for x in ['it ', 'technology', 'pharma']): return "Global Tech / Export Cycle (USD Dependent)"
        return "Idiosyncratic / Stock Specific"
        
    sector_df['2-Year Macro Prediction'] = sector_df['Industry'].apply(get_cycle)
    final_sector_cols = ['Industry', 'Sector Status', 'ISAD (Breadth %)', 'Avg_Money_Flow', 'Avg_50D_Flow', '2-Year Macro Prediction']
    sector_df[final_sector_cols].sort_values(by='ISAD (Breadth %)', ascending=False).to_csv("sector_output.csv", index=False)

if __name__ == "__main__":
    run_quantum_engine()
