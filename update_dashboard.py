#!/usr/bin/env python3
import os, re, sys, json, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

GH_USER  = os.getenv("GH_USER",  "jsanchezerazo")
GH_TOKEN = os.getenv("GH_TOKEN", "")
GH_REPO  = "combustibles-rd-2026"
GH_BRANCH= "main"
BUDGET   = 13748
RD_TZ    = timezone(timedelta(hours=-4))
MESES_ES = ["enero","febrero","marzo","abril","mayo","junio","julio",
            "agosto","septiembre","octubre","noviembre","diciembre"]

def fecha_es(dt):
    return f"{dt.day} de {MESES_ES[dt.month-1]} de {dt.year}"

def get_wti_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=2d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        price = next(p for p in reversed(closes) if p is not None)
        print(f"  WTI (Yahoo Finance): ${price:.2f}")
        return round(price, 2)
    except Exception as e:
        print(f"  Yahoo Finance fallo: {e}")
    try:
        url = ("https://api.eia.gov/v2/petroleum/pri/spt/data/"
               "?frequency=weekly&data[0]=value&facets[series][]=RWTC"
               "&sort[0][column]=period&sort[0][direction]=desc&length=1")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        price = float(data["response"]["data"][0]["value"])
        print(f"  WTI (EIA): ${price:.2f}")
        return round(price, 2)
    except Exception as e:
        print(f"  EIA fallo: {e}")
    print("  ADVERTENCIA: No se pudo obtener WTI. Usando ultimo valor.")
    return None

def sub_from_wti(wti):
    if wti <= 68:  return 44
    if wti >= 160: return 5500
    return round(44 + (1702 - 44) / (105 - 68) * (wti - 68))

def scenario_from_wti(wti):
    if wti <= 80:  return "alivio"
    if wti <= 110: return "base"
    return "escalada"

def get_last_tracking_data(html):
    m = re.search(r'const TRACKING_DATA = ([\s\S]*?);', html)
    if not m: return None
    try:
        txt = m.group(1).strip()
        txt = re.sub(r'\bdate:', '"date":', txt)
        txt = re.sub(r'\bwti:', '"wti":', txt)
        txt = re.sub(r'\bsubWk:', '"subWk":', txt)
        txt = re.sub(r'\bexecCum:', '"execCum":', txt)
        txt = re.sub(r'\bscenario:', '"scenario":', txt)
        data = json.loads(txt)
        return data[-1] if data else None
    except: return None

def update_tracking_entry(html, new_entry):
    m = re.search(r'(const TRACKING_DATA = )([\s\S]*?);', html)
    if not m:
        print("  ERROR: No se encontro TRACKING_DATA")
        return html
    try:
        txt = m.group(2).strip()
        txt = re.sub(r'\bdate:', '"date":', txt)
        txt = re.sub(r'\bwti:', '"wti":', txt)
        txt = re.sub(r'\bsubWk:', '"subWk":', txt)
        txt = re.sub(r'\bexecCum:', '"execCum":', txt)
        txt = re.sub(r'\bscenario:', '"scenario":', txt)
        data = json.loads(txt)
    except: data = []
    today_str = new_entry["date"]
    updated = False
    for i, entry in enumerate(data):
        if entry.get("date") == today_str:
            data[i] = new_entry; updated = True; break
    if not updated: data.append(new_entry)
    lines = ["[\n"]
    for i, entry in enumerate(data):
        comma = "," if i < len(data) - 1 else ""
        lines.append(f'  {{ date:"{entry["date"]}", wti:{entry["wti"]}, subWk:{entry["subWk"]}, execCum:{entry["execCum"]}, scenario:"{entry["scenario"]}" }}{comma}\n')
    lines.append("]")
    return html[:m.start(2)] + "".join(lines) + html[m.end(2):]

def update_dates(html, dt):
    fecha = fecha_es(dt)
    html = re.sub(r'(Corte:\s*)\d{1,2} de \w+ de \d{4}', f"Corte: {fecha}", html)
    return html

def main():
    now_rd = datetime.now(RD_TZ)
    today_str = now_rd.strftime("%Y-%m-%d")
    print(f"\n=== Actualizacion dashboard combustibles RD ===")
    print(f"  Fecha/hora RD: {now_rd.strftime('%Y-%m-%d %H:%M')} (UTC-4)")
    html_path = Path(__file__).parent / "index.html"
    if not html_path.exists():
        print(f"  ERROR: No se encontro {html_path}"); sys.exit(1)
    html = html_path.read_text(encoding="utf-8")
    wti = get_wti_price()
    if wti is None:
        last = get_last_tracking_data(html)
        wti = last["wti"] if last else 105
        print(f"  Usando ultimo WTI: ${wti}")
    sub_wk = sub_from_wti(wti)
    scenario = scenario_from_wti(wti)
    last = get_last_tracking_data(html)
    exec_cum = last["execCum"] if last else 5583
    print(f"  WTI: ${wti} | Subsidio: RD${sub_wk:,}M/sem | Escenario: {scenario}")
    new_entry = {"date": today_str, "wti": wti, "subWk": sub_wk, "execCum": exec_cum, "scenario": scenario}
    html = update_dates(html, now_rd)
    html = update_tracking_entry(html, new_entry)
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML actualizado correctamente")
    print(f"\n=== Actualizacion completada ===\n")

if __name__ == "__main__":
    main()
