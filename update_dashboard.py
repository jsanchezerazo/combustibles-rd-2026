#!/usr/bin/env python3
"""
update_dashboard.py
Actualización diaria del dashboard de subsidios combustibles RD 2026.
Ejecutar a las 8:00 AM hora República Dominicana (UTC-4).

Variables que actualiza CADA DÍA:
  - FECHA_CORTE en el header
  - Fecha en el footer
  - TRACKING_DATA con precio WTI, subsidio proyectado, ejecutado acumulado
  - REGIONAL_DATA: campo 'cur' (precio actual) de los 21 países
  - REGIONAL_UPDATED: fecha de última actualización regional

Los LUNES además:
  - Marca 'changed:true' en países cuyo precio varió vs. semana anterior
  - Resetea 'changed:false' en países sin variación
  (Las narrativas se actualizan manualmente vía conversación con el asistente)

Requiere:
  - GH_TOKEN: Personal Access Token de GitHub (env var)
  - GH_USER: jsanchezerazo (env var o constante)
  - Repo: combustibles-rd-2026
"""

import os
import re
import sys
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
GH_USER  = os.getenv("GH_USER",  "jsanchezerazo")
GH_TOKEN = os.getenv("GH_TOKEN", "")           # ← Personal Access Token
GH_REPO  = "combustibles-rd-2026"
GH_BRANCH= "main"

BUDGET   = 13748   # Presupuesto total RD$M
RD_TZ    = timezone(timedelta(hours=-4))       # UTC-4 (hora RD)

MESES_ES = ["enero","febrero","marzo","abril","mayo","junio","julio",
            "agosto","septiembre","octubre","noviembre","diciembre"]

LITERS_PER_GALLON = 3.785

# ── MAPEO PAÍSES REGIONALES ────────────────────────────────────────────────────
# GlobalPetrolPrices nombre → campo 'pais' en REGIONAL_DATA
REGIONAL_MAP = {
    "Mexico":             "México",
    "Guatemala":          "Guatemala",
    "Belize":             "Belice",
    "Honduras":           "Honduras",
    "El Salvador":        "El Salvador",
    "Nicaragua":          "Nicaragua",
    "Costa Rica":         "Costa Rica",
    "Panama":             "Panamá",
    "Cuba":               "Cuba",
    "Haiti":              "Haití",
    "Dominican Republic": "Rep. Dom.",
    "Colombia":           "Colombia",
    "Venezuela":          "Venezuela",
    "Ecuador":            "Ecuador",
    "Peru":               "Perú",
    "Bolivia":            "Bolivia",
    "Chile":              "Chile",
    "Argentina":          "Argentina",
    "Uruguay":            "Uruguay",
    "Paraguay":           "Paraguay",
    "Brazil":             "Brasil",
}

# Países cuyo precio no es de mercado — se actualizan pero no se marcan 'changed'
SKIP_CHANGED_FLAG = {"Cuba", "Venezuela"}


# ── FUNCIONES AUXILIARES (WTI / TRACKING) ─────────────────────────────────────

def fecha_es(dt: datetime) -> str:
    """Convierte datetime → 'D de mes de YYYY'"""
    return f"{dt.day} de {MESES_ES[dt.month-1]} de {dt.year}"


def get_wti_price() -> float:
    """
    Obtiene el precio más reciente del WTI desde Yahoo Finance (sin API key).
    Si falla, intenta con la EIA API pública.
    Devuelve el precio en USD/bbl.
    """
    # Intento 1: Yahoo Finance informal endpoint
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
        print(f"  Yahoo Finance falló: {e}")

    # Intento 2: EIA API pública (no requiere key para datos semanales)
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
        print(f"  EIA falló: {e}")

    print("  ADVERTENCIA: No se pudo obtener WTI online. Se usará el último valor registrado.")
    return None


def sub_from_wti(wti: float) -> int:
    """Función de subsidio semanal (calibrada con datos ene-mar 2026)."""
    if wti <= 68:  return 44
    if wti >= 160: return 5500
    return round(44 + (1702 - 44) / (105 - 68) * (wti - 68))


def scenario_from_wti(wti: float) -> str:
    if wti <= 80:  return "alivio"
    if wti <= 110: return "base"
    return "escalada"


def js_to_json(s: str) -> str:
    """Convierte notación JavaScript (claves sin comillas) a JSON válido."""
    return re.sub(r'([\{,])\s*([a-zA-Z_]\w*)\s*:', r'\1 "\2":', s)


def get_last_tracking_data(html: str):
    """Extrae el último entry de TRACKING_DATA del HTML."""
    m = re.search(r'const TRACKING_DATA = (\[[\s\S]*?\]);', html)
    if not m:
        return None
    try:
        data = json.loads(js_to_json(m.group(1)))
        return data[-1] if data else None
    except:
        return None


def update_tracking_entry(html: str, new_entry: dict) -> str:
    """
    Reemplaza o agrega un entry en TRACKING_DATA para la fecha dada.
    Si ya existe una entrada para hoy, la actualiza. Si no, la agrega.
    """
    m = re.search(r'(const TRACKING_DATA = )(\[[\s\S]*?\]);', html)
    if not m:
        print("  ERROR: No se encontró TRACKING_DATA en el HTML.")
        return html

    try:
        data = json.loads(js_to_json(m.group(2)))
    except:
        data = []

    today_str = new_entry["date"]
    updated = False
    for i, entry in enumerate(data):
        if entry.get("date") == today_str:
            data[i] = new_entry
            updated = True
            break
    if not updated:
        data.append(new_entry)

    lines = ["[\n"]
    for i, entry in enumerate(data):
        comma = "," if i < len(data) - 1 else ""
        lines.append(
            f'  {{ date:"{entry["date"]}", wti:{entry["wti"]}, '
            f'subWk:{entry["subWk"]}, execCum:{entry["execCum"]}, '
            f'scenario:"{entry["scenario"]}"{" " if comma else " "}}}{comma}\n'
        )
    lines.append("]")
    new_data_str = "".join(lines)

    return html[:m.start(2)] + new_data_str + html[m.end(2):]


def update_dates(html: str, dt: datetime) -> str:
    """Actualiza Corte en header y Fecha en footer."""
    fecha = fecha_es(dt)

    html = re.sub(
        r'(Corte:\s*)\d{1,2} de \w+ de \d{4}',
        lambda m: f"Corte: {fecha}",
        html
    )
    html = re.sub(
        r'(\·\s*)\d{1,2} de \w+ de \d{4}(\s*·\s*Elaborado)',
        lambda m: f"{m.group(1)}{fecha}{m.group(2)}",
        html
    )
    return html


# ── FUNCIONES REGIONALES ───────────────────────────────────────────────────────

def get_regional_prices() -> dict:
    """
    Obtiene precios actuales de gasolina regular (USD/galón) para
    los países de Latinoamérica desde GlobalPetrolPrices.
    Devuelve dict: { pais_name: price_usd_per_gallon }
    """
    url = "https://www.globalpetrolprices.com/gasoline_prices/"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  GlobalPetrolPrices no disponible: {e}")
        return {}

    prices = {}

    # Patrón 1: tabla HTML estándar
    # <a href="/Mexico/gasoline_prices/">Mexico</a></td><td>X.XX</td><td>Y.YYY</td>
    pattern1 = (r'href="/[^"]+/gasoline_prices/"[^>]*>([^<]+)</a>'
                r'</td>(?:\s*<td[^>]*>[^<]*</td>\s*)'
                r'<td[^>]*>([\d.]+)</td>')
    for m in re.finditer(pattern1, raw):
        name = m.group(1).strip()
        if name in REGIONAL_MAP:
            price_liter = float(m.group(2))
            prices[REGIONAL_MAP[name]] = round(price_liter * LITERS_PER_GALLON, 2)

    # Patrón 2: array JS embebido (formato alternativo del sitio)
    # ["Mexico","22.590","1.082","0.000"]
    if not prices:
        pattern2 = r'\["([^"]+)","[\d.]+","([\d.]+)"'
        for m in re.finditer(pattern2, raw):
            name = m.group(1).strip()
            if name in REGIONAL_MAP:
                price_liter = float(m.group(2))
                prices[REGIONAL_MAP[name]] = round(price_liter * LITERS_PER_GALLON, 2)

    if prices:
        found = [k for k in REGIONAL_MAP.values() if k in prices]
        print(f"  Precios regionales obtenidos: {len(found)}/21 países")
    else:
        print("  ADVERTENCIA: No se pudieron parsear precios de GlobalPetrolPrices.")

    return prices


def get_current_regional_cur(html: str, pais: str):
    """Lee el valor actual de 'cur' para un país en REGIONAL_DATA."""
    marker = f'pais:"{pais}"'
    pos = html.find(marker)
    if pos == -1:
        return None
    block = html[pos:pos+400]
    m = re.search(r'cur:([\d.]+|null)', block)
    if not m:
        return None
    val = m.group(1)
    return None if val == "null" else float(val)


def update_regional_cur(html: str, pais: str, new_price: float) -> str:
    """Actualiza el campo 'cur' de un país en REGIONAL_DATA."""
    marker = f'pais:"{pais}"'
    pos = html.find(marker)
    if pos == -1:
        return html
    block = html[pos:pos+400]
    new_block = re.sub(r'(cur:)([\d.]+|null)', rf'\g<1>{new_price}', block, count=1)
    return html[:pos] + new_block + html[pos+400:]


def update_regional_changed(html: str, pais: str, changed: bool) -> str:
    """Actualiza el flag 'changed' de un país en REGIONAL_DATA."""
    marker = f'pais:"{pais}"'
    pos = html.find(marker)
    if pos == -1:
        return html
    block = html[pos:pos+400]
    new_val = 'true' if changed else 'false'
    new_block = re.sub(r'(changed:)(true|false)', rf'\g<1>{new_val}', block, count=1)
    return html[:pos] + new_block + html[pos+400:]


def update_regional_date(html: str, date_str: str) -> str:
    """Actualiza REGIONAL_UPDATED con la fecha actual."""
    return re.sub(
        r'const REGIONAL_UPDATED = "[^"]+";',
        f'const REGIONAL_UPDATED = "{date_str}";',
        html
    )


def apply_regional_updates(html: str, new_prices: dict, is_monday: bool,
                            date_str: str) -> str:
    """
    Aplica actualizaciones de precios regionales al HTML.
    - Siempre: actualiza 'cur' para países con nuevo precio
    - Lunes: resetea 'changed' a false para todos, luego marca true donde cambió
    - Actualiza REGIONAL_UPDATED
    """
    if not new_prices:
        return html

    updated_count = 0
    changed_count = 0

    for gpp_name, pais in REGIONAL_MAP.items():
        if pais not in new_prices:
            continue
        if pais in SKIP_CHANGED_FLAG:
            continue  # Cuba y Venezuela: no actualizar (precios no de mercado)

        new_price = new_prices[pais]
        old_price = get_current_regional_cur(html, pais)

        # Actualizar precio
        html = update_regional_cur(html, pais, new_price)
        updated_count += 1

        # Gestión del flag 'changed' solo los lunes
        if is_monday:
            price_changed = (old_price is not None and
                             abs(new_price - old_price) > 0.01)
            html = update_regional_changed(html, pais, price_changed)
            if price_changed:
                changed_count += 1
                print(f"  ↑ {pais}: ${old_price:.2f} → ${new_price:.2f}")

    # Actualizar fecha
    html = update_regional_date(html, date_str)

    day_type = "lunes" if is_monday else "día regular"
    print(f"  Precios regionales actualizados: {updated_count} países ({day_type})")
    if is_monday and changed_count:
        print(f"  Países con variación marcada: {changed_count}")

    return html


# ── GIT PUSH ───────────────────────────────────────────────────────────────────

def git_push(html_path: str, commit_msg: str):
    """Clona o actualiza el repo, aplica cambios y hace push."""
    if not GH_TOKEN:
        print("  ADVERTENCIA: GH_TOKEN no configurado. Saltando push a GitHub.")
        return False

    work_dir = Path("/tmp/combustibles-rd-push")
    repo_url  = f"https://{GH_USER}:{GH_TOKEN}@github.com/{GH_USER}/{GH_REPO}.git"

    try:
        if work_dir.exists():
            subprocess.run(["git", "-C", str(work_dir), "pull", "--rebase"], check=True)
        else:
            subprocess.run(["git", "clone", repo_url, str(work_dir)], check=True)

        import shutil
        shutil.copy(html_path, work_dir / "index.html")

        subprocess.run(["git", "-C", str(work_dir), "config", "user.email", "bot@micm-rd.gob.do"], check=True)
        subprocess.run(["git", "-C", str(work_dir), "config", "user.name",  "MICM Dashboard Bot"], check=True)
        subprocess.run(["git", "-C", str(work_dir), "add", "index.html"], check=True)

        result = subprocess.run(["git", "-C", str(work_dir), "diff", "--cached", "--quiet"])
        if result.returncode == 0:
            print("  Sin cambios en index.html — nada que commitear.")
            return True

        subprocess.run(["git", "-C", str(work_dir), "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "-C", str(work_dir), "push", "origin", GH_BRANCH], check=True)
        print(f"  ✓ Push exitoso → https://{GH_USER}.github.io/{GH_REPO}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"  ERROR git: {e}")
        return False


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    now_rd    = datetime.now(RD_TZ)
    today_str = now_rd.strftime("%Y-%m-%d")
    is_monday = now_rd.weekday() == 0   # 0 = lunes

    print(f"\n=== Actualización dashboard combustibles RD ===")
    print(f"  Fecha/hora RD: {now_rd.strftime('%Y-%m-%d %H:%M')} (UTC-4)")
    if is_monday:
        print(f"  *** LUNES: se actualizarán flags 'changed' en datos regionales ***")

    script_dir = Path(__file__).parent
    html_path  = script_dir / "index.html"

    if not html_path.exists():
        print(f"  ERROR: No se encontró {html_path}")
        sys.exit(1)

    html = html_path.read_text(encoding="utf-8")

    # ── 1. WTI ──────────────────────────────────────────────────────────────────
    print("\n[1/3] Precio WTI...")
    wti = get_wti_price()
    if wti is None:
        last = get_last_tracking_data(html)
        wti  = last["wti"] if last else 105
        print(f"  Usando último WTI registrado: ${wti}")

    sub_wk   = sub_from_wti(wti)
    scenario = scenario_from_wti(wti)
    last     = get_last_tracking_data(html)
    exec_cum = last["execCum"] if last else 5583

    print(f"  WTI       : ${wti}/bbl")
    print(f"  Subsidio  : RD${sub_wk:,}M/semana")
    print(f"  Ejecutado : RD${exec_cum:,}M  |  Restante: RD${BUDGET-exec_cum:,}M")
    print(f"  Escenario : {scenario}")

    new_entry = {
        "date":     today_str,
        "wti":      wti,
        "subWk":    sub_wk,
        "execCum":  exec_cum,
        "scenario": scenario
    }

    html = update_dates(html, now_rd)
    html = update_tracking_entry(html, new_entry)

    # ── 2. Precios regionales ───────────────────────────────────────────────────
    print("\n[2/3] Precios regionales (GlobalPetrolPrices)...")
    regional_prices = get_regional_prices()
    date_label = f"{now_rd.day:02d} {MESES_ES[now_rd.month-1][:3]} {now_rd.year}"
    html = apply_regional_updates(html, regional_prices, is_monday, date_label)

    # ── 3. Guardar y push ───────────────────────────────────────────────────────
    print("\n[3/3] Guardando y publicando...")
    html_path.write_text(html, encoding="utf-8")
    print(f"  ✓ HTML actualizado: {html_path}")

    regional_note = f" · {len(regional_prices)} precios regionales" if regional_prices else ""
    monday_note   = " · flags regionales actualizados" if is_monday else ""
    commit_msg = (f"[auto] {today_str} · WTI ${wti} · "
                  f"Subsidio RD${sub_wk:,}M · {scenario}"
                  f"{regional_note}{monday_note}")
    git_push(str(html_path), commit_msg)

    print(f"\n=== Actualización completada ✓ ===\n")


if __name__ == "__main__":
    main()
