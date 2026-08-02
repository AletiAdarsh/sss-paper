"""Rank all 77 stocks from the user's screener.in quality screen (st3).

Composite score = earnings momentum + sales momentum + ROCE (quality)
                + valuation (inverse P/E) + yield + balance-sheet safety.
Percentile-rank based so single outliers (e.g. loss->profit base effects)
can't dominate; extreme growth values are capped first.

Then splices in local price history (data/ohlcv_fyers) to add a TREND check,
so we don't repeat the "great stock, terrible entry" mistake.

Run:  py screen_rank77.py
"""
import pandas as pd, numpy as np, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
OHLCV = Path(r"C:\Users\adars\sss\data\ohlcv_fyers")

# name, cmp, pe, mcap, div, qtr_profit_var, qtr_sales_var, roce, int_coverage
D = [
("20 Microns",207.50,11.03,732,0.59,14.99,14.80,17.31,6.27),
("ABB",7518.00,104.56,159313,0.52,-25.23,5.78,29.93,108.67),
("Action Const.Eq.",1042.80,28.43,12418,0.19,22.28,20.49,31.70,32.23),
("ADC India",2171.00,52.74,999,1.16,18.98,33.89,31.44,2463.00),
("Aditya AMC",992.55,28.45,28711,2.56,11.68,3.48,32.23,270.60),
("Ador Welding",1554.95,22.61,2706,1.50,890.46,23.19,22.71,75.06),
("Affle 3i",1519.10,47.01,21388,0.00,15.95,20.28,16.84,107.21),
("Ajax Engineering",580.10,29.18,6637,0.00,4.41,0.25,23.86,1087.89),
("Apar Inds.",13672.00,54.88,54926,0.37,3.66,26.74,31.12,4.07),
("Atlanta Electric",1647.00,58.01,12665,0.00,50.42,47.99,45.26,6.40),
("Auto.Corp.of Goa",2319.95,19.57,1413,1.19,26.60,24.80,29.61,749.00),
("Benares Hotels",10200.00,30.12,1326,0.25,8.84,35.51,29.83,141.62),
("Bharat Electron",407.30,49.10,297727,0.59,4.62,11.75,36.53,1197.58),
("Bikaji Foods",639.45,58.01,16033,0.19,31.29,14.15,21.97,32.83),
("BLS Internat.",231.30,13.85,9524,0.86,31.57,17.58,29.34,35.30),
("Bosch",40940.00,57.85,120757,0.66,2.98,13.34,21.54,116.57),
("Canara Robeco",280.65,25.63,5597,1.42,23.98,20.07,40.11,139.73),
("Caplin Point Lab",2536.00,30.06,19277,0.23,19.32,19.45,24.63,923.75),
("Cemindia Project",1622.10,47.38,27866,0.18,113.63,17.42,32.76,4.74),
("Crizac",187.60,14.98,3283,4.26,50.26,15.02,52.34,4104.14),
("Cummins India",5586.15,63.87,154848,1.18,18.00,21.89,39.50,256.25),
("Dodla Dairy",1055.95,25.14,6370,0.48,-2.00,18.12,16.72,64.69),
("Dynamic Cables",421.65,22.42,2043,0.12,37.01,33.22,26.21,11.46),
("eClerx Services",1884.95,25.08,17728,0.03,24.45,23.27,34.81,23.19),
("Eco Recyc.",500.05,41.75,965,0.00,267.79,90.48,29.97,46.03),
("Eicher Motors",7614.75,37.58,209023,1.08,11.58,16.01,30.52,101.06),
("Emcure Pharma",1894.15,37.98,35928,0.16,21.01,16.70,23.97,10.18),
("Endurance Tech.",2705.00,39.33,38049,0.42,17.32,37.88,18.28,23.63),
("Fiem Industries",2326.85,24.06,6124,1.73,26.86,17.49,29.34,123.10),
("Frontier Springs",1384.95,26.69,1636,0.04,42.28,17.78,50.92,294.79),
("Garware Hi Tech",6865.30,47.16,15950,0.17,39.09,8.90,18.02,55.42),
("GE Vernova T&D",4446.00,88.99,113840,0.22,86.32,42.04,76.43,117.16),
("Gillette India",7833.45,39.02,25529,2.28,21.32,3.20,90.62,74.00),
("Godfrey Phillips",2088.40,21.34,32575,1.50,77.36,13.59,32.84,166.24),
("Goel Construct.",460.00,14.37,665,0.00,36.84,29.61,34.23,7.09),
("Goldiam Intl.",346.95,30.62,5224,0.65,61.38,18.14,23.89,71.16),
("HBL Engineering",721.65,23.90,20004,0.27,44.18,27.03,58.45,76.33),
("Hexaware Tech.",551.95,23.03,33725,2.04,7.46,12.63,30.07,18.50),
("Hindustan Copper",495.10,48.37,47877,0.30,133.05,58.06,42.40,271.57),
("Hitachi Energy",32313.75,140.13,144030,0.02,79.71,46.21,29.02,108.60),
("Indrapr. Medical",369.75,18.47,3390,1.21,1.68,9.31,35.83,41.87),
("Inox India",2086.50,72.80,18938,0.10,11.19,24.70,33.48,38.37),
("Intl Gemological",342.95,25.46,14821,0.73,25.22,26.51,30.72,348.36),
("Inventurus Knowl",1863.00,44.33,31981,0.00,39.36,18.47,36.86,13.88),
("Jeena Sikho",564.00,31.53,7011,0.19,78.97,54.79,70.74,24.22),
("KMC Speciality",133.25,46.52,2173,0.00,223.67,34.99,26.04,8.58),
("Kovai Medical",5911.00,26.45,6467,0.25,15.81,15.87,22.19,11.17),
("Krishna Defence",1283.20,50.34,1918,0.10,64.44,42.18,31.07,49.38),
("Kwality Pharma",2651.85,40.49,2752,0.00,74.60,35.81,24.25,9.23),
("Macpower CNC",1329.70,39.27,1330,0.11,10.93,25.35,29.11,29.84),
("Marksans Pharma",241.75,26.21,10955,0.37,63.59,20.84,18.84,24.23),
("MPS",2469.40,23.05,4224,3.37,41.19,20.38,39.27,86.26),
("Netweb Technol.",4323.55,119.62,24619,0.06,65.67,86.59,37.50,22.35),
("Newgen Software",529.05,22.00,7540,1.13,26.35,11.23,25.01,88.81),
("Nippon Life Ind.",1144.50,47.82,73167,1.86,28.84,30.39,43.80,282.71),
("Polycab India",8930.70,46.97,134539,0.53,32.46,39.01,33.21,15.24),
("Power Mech Proj.",2551.30,22.17,8066,0.05,21.59,13.89,21.82,5.82),
("Prec. Wires (I)",361.55,42.97,6609,0.35,85.50,67.19,32.94,3.86),
("Prudent Corp.",2887.75,53.84,11957,0.12,14.24,27.40,37.48,63.72),
("R R Kabel",2428.05,54.45,27463,0.40,30.06,33.65,28.10,9.73),
("Radico Khaitan",4110.45,89.59,55073,0.22,94.92,15.31,24.15,13.69),
("Raghav Product.",1251.70,91.69,5748,0.08,67.55,48.72,30.30,118.00),
("Railtel Corpn.",290.05,25.60,9309,0.97,35.68,27.56,22.78,131.67),
("Rajoo Engineers",56.13,20.68,1003,0.27,3.40,44.67,24.70,26.71),
("Saksoft",170.55,16.52,2261,0.58,19.65,3.74,25.48,21.71),
("Sarda Energy",502.60,16.14,17711,0.29,45.61,1.19,17.39,6.89),
("Schaeffler India",4130.00,51.61,64553,0.85,20.46,18.81,27.90,458.07),
("Swaraj Engines",3580.00,21.29,4350,3.07,11.13,21.54,58.38,723.24),
("Talbros Auto.",405.60,24.07,2504,0.17,18.96,14.91,18.56,10.94),
("Thejo Engg.",1907.90,40.39,2070,0.26,4.07,18.26,19.40,14.20),
("Tips Music",705.35,41.60,9017,1.82,92.94,32.41,122.19,1460.35),
("TPL Plastech",79.22,21.25,618,1.27,18.01,23.75,22.28,8.24),
("Travel Food",1300.10,38.82,17120,0.00,17.45,25.67,42.37,10.32),
("Triveni Turbine",618.55,54.46,19663,0.65,8.52,26.32,35.86,189.00),
("Uni Abex Alloy",4620.00,19.36,912,0.75,75.47,29.53,19.25,80.01),
("Waaree Renewab.",1007.60,21.80,10514,0.10,62.18,131.33,85.38,49.42),
("Wealth First Por",962.35,26.53,1025,2.08,345.22,606.44,34.63,1723.67),
]
SYM = {  # only where a local price file exists / name differs
 "Ador Welding":"ADOR","Affle 3i":"AFFLE","Prec. Wires (I)":"PRECWIRE","Crizac":"CRIZAC",
 "Bharat Electron":"BEL","Hexaware Tech.":"HEXT","eClerx Services":"ECLERX","Dodla Dairy":"DODLA",
 "BLS Internat.":"BLS","Action Const.Eq.":"ACE","Polycab India":"POLYCAB","Eicher Motors":"EICHERMOT",
 "Cummins India":"CUMMINSIND","Bosch":"BOSCHLTD","Godfrey Phillips":"GODFRYPHLP","HBL Engineering":"HBLENGINE",
 "Hindustan Copper":"HINDCOPPER","Railtel Corpn.":"RAILTEL","Marksans Pharma":"MARKSANS",
 "Newgen Software":"NEWGEN","Triveni Turbine":"TRITURBINE","Nippon Life Ind.":"NAM-INDIA",
 "Schaeffler India":"SCHAEFFLER","Radico Khaitan":"RADICO","Caplin Point Lab":"CAPLIPOINT",
 "Emcure Pharma":"EMCURE","Endurance Tech.":"ENDURANCE","Swaraj Engines":"SWARAJENG",
 "Sarda Energy":"SARDAEN","Saksoft":"SAKSOFT","Fiem Industries":"FIEMIND","Goldiam Intl.":"GOLDIAM",
 "Gillette India":"GILLETTE","Bikaji Foods":"BIKAJI","Aditya AMC":"ABSLAMC","Apar Inds.":"APARINDS",
 "Inox India":"INOXINDIA","Travel Food":"TFSC","Netweb Technol.":"NETWEB","R R Kabel":"RRKABEL",
 "Power Mech Proj.":"POWERMECH","Prudent Corp.":"PRUDENT","Kovai Medical":"KOVAI",
 "Intl Gemological":"IGIL","Inventurus Knowl":"IKS","Tips Music":"TIPSMUSIC","Waaree Renewab.":"WAAREERTL",
 "Talbros Auto.":"TALBROAUTO","MPS":"MPSLTD","Canara Robeco":"CANROBECO","GE Vernova T&D":"GVT&D",
 "Hitachi Energy":"POWERINDIA","Marksans":"MARKSANS","Atlanta Electric":"ATALREAL",
}

df = pd.DataFrame(D, columns=["stock","cmp","pe","mcap","div","pvar","svar","roce","intcov"])

# --- cap outliers so base-effect blowups don't hijack the ranking ---
df["pvar_c"] = df["pvar"].clip(upper=100)
df["svar_c"] = df["svar"].clip(upper=80)

pr = lambda s, asc=True: s.rank(ascending=asc, pct=True) * 10
df["s_prof"]  = pr(df["pvar_c"])
df["s_sales"] = pr(df["svar_c"])
df["s_roce"]  = pr(df["roce"])
df["s_val"]   = pr(df["pe"], asc=False)          # cheaper = better
df["s_div"]   = pr(df["div"])
df["s_safe"]  = pr(df["intcov"].clip(upper=300))

df["SCORE"] = (0.28*df["s_prof"] + 0.22*df["s_sales"] + 0.20*df["s_roce"]
             + 0.22*df["s_val"]  + 0.03*df["s_div"] + 0.05*df["s_safe"])
df["PEG"] = (df["pe"] / df["pvar_c"].clip(lower=1)).round(2)


def trend(stock):
    """Local price check: distance from 200DMA and 52w high, 3m return."""
    sym = SYM.get(stock)
    if not sym: return None
    f = OHLCV / f"{sym}.csv"
    if not f.exists(): return None
    d = pd.read_csv(f, parse_dates=["date"]).sort_values("date")
    if len(d) < 210: return None
    c = d["close"]; last = c.iloc[-1]
    return {"vs200": last/c.rolling(200).mean().iloc[-1]*100-100,
            "from_hi": last/c.iloc[-250:].max()*100-100,
            "r3m": last/c.iloc[-64]*100-100 if len(c) > 64 else np.nan}

t = df["stock"].apply(lambda s: trend(s) or {})
df["vs200"]   = [x.get("vs200", np.nan) for x in t]
df["from_hi"] = [x.get("from_hi", np.nan) for x in t]
df["r3m"]     = [x.get("r3m", np.nan) for x in t]

df = df.sort_values("SCORE", ascending=False).reset_index(drop=True)
df.index += 1
pd.set_option("display.width", 260)
pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
cols = ["stock","cmp","pe","mcap","pvar","svar","roce","div","PEG","vs200","from_hi","r3m","SCORE"]
print("ALL 77 RANKED (fundamental composite; vs200/from_hi/r3m = trend where local data exists)\n")
print(df[cols].head(25).to_string())
print("\n... BOTTOM 8 ...")
print(df[cols].tail(8).to_string())
df.to_csv(r"C:\Users\adars\sss\data\screen77_ranked.csv", index=False)
print("\nsaved -> data/screen77_ranked.csv")
