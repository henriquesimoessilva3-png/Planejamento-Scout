#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza datas/horários da Primera argentina (BASE_AR apertura/clausura) com
DUPLA CONFIRMAÇÃO: só corrige quando Promiedos E ESPN concordam na data (±1 dia).
Foco em jogos FUTUROS (data >= hoje). Nunca adiciona/remove jogos.
Uso: python update_ar_dual.py [index.html] [--report]
"""
import sys, re, json, ssl, time, unicodedata
from datetime import date, datetime, timezone, timedelta
import urllib.request, urllib.error

ARG = timezone(timedelta(hours=-3))  # Argentina UTC-3 (sem horário de verão)
def hhmin(s):
    try: h, m = s.split(":"); return int(h) * 60 + int(m)
    except: return None

INDEX = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "index.html"
REPORT = "--report" in sys.argv
WINDOW = 10
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TODAY = date.today()

def _open(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=25)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            r = urllib.request.urlopen(req, timeout=25, context=ssl._create_unverified_context())
        else:
            raise
    data = r.read().decode("utf-8", "ignore")
    return data if raw else json.loads(data)

def strip(x):
    return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower())

def canon(n):
    x = " " + strip(n) + " "
    if "rivadavia" in x: return "indriv"
    if "justicia" in x: return "defjusticia"
    if "boca" in x: return "boca"
    if "river" in x: return "river"
    if "racing" in x and "cordoba" not in x and "cba" not in x: return "racing"
    if "independiente" in x: return "independiente"
    if "san lorenzo" in x: return "sanlorenzo"
    if "estudiantes" in x and ("rio cuarto" in x or " rc " in x): return "estudiantesrc"
    if "estudiantes" in x: return "estudianteslp"
    if "gimnasia" in x and ("mendoza" in x or "mza" in x): return "gimnasiamza"
    if "gimnasia" in x: return "gimnasialp"
    if "velez" in x: return "velez"
    if "huracan" in x: return "huracan"
    if "lanus" in x: return "lanus"
    if "banfield" in x: return "banfield"
    if "argentinos" in x: return "argentinos"
    if "platense" in x: return "platense"
    if "barracas" in x: return "barracas"
    if ("central cordoba" in x) or ("cent" in x and "cordoba" in x): return "centralcba"
    if "talleres" in x: return "talleres"
    if "belgrano" in x and "def" not in x: return "belgrano"
    if "instituto" in x: return "instituto"
    if "newell" in x: return "newells"
    if "rosario" in x and "central" in x: return "rosariocentral"
    if "godoy" in x: return "godoy"
    if "colon" in x: return "colon"
    if "union" in x: return "union"
    if "sarmiento" in x: return "sarmiento"
    if "tucuman" in x and "san martin" not in x: return "atltucuman"
    if "riestra" in x: return "riestra"
    if "aldosivi" in x: return "aldosivi"
    if "tigre" in x and "tucuman" not in x: return "tigre"
    if "san martin" in x and ("san juan" in x or " sj " in x): return "sanmartinsj"
    if "madryn" in x: return "madryn"
    return None

def dparse(s):
    y, mo, da = s.split("-"); return date(int(y), int(mo), int(da))

def fetch_promiedos():
    html = _open("https://www.promiedos.com.ar/league/liga-profesional/hc", raw=True)
    rids = sorted(set(re.findall(r"\d{1,3}_\d{1,3}_\d{1,3}_\d{1,3}", html)))
    by = {}
    for rid in rids:
        try: d = _open(f"https://api.promiedos.com.ar/league/games/hc/{rid}")
        except Exception: continue
        for g in d.get("games", []):
            t = g.get("teams", [])
            st = g.get("start_time", "")
            if len(t) < 2 or len(st) < 16: continue
            iso = f"{st[6:10]}-{st[3:5]}-{st[0:2]}"; hh = st[11:16]
            ch, ca = canon(t[0]["name"]), canon(t[1]["name"])
            if ch and ca: by.setdefault((ch, ca), []).append((iso, hh))
        time.sleep(0.04)
    return by

def fetch_espn():
    base = "https://site.api.espn.com/apis/site/v2/sports/soccer/arg.1/scoreboard"
    cal = _open(base).get("leagues", [{}])[0].get("calendar", [])
    by = {}
    for c in cal:
        d10 = str(c)[:10]
        if d10 < TODAY.isoformat(): continue          # só futuro
        ymd = d10.replace("-", "")
        try: day = _open(f"{base}?dates={ymd}")
        except Exception: continue
        for ev in day.get("events", []):
            cs = ev["competitions"][0]["competitors"]
            try:
                h = next(x for x in cs if x["homeAway"] == "home")["team"]["displayName"]
                a = next(x for x in cs if x["homeAway"] == "away")["team"]["displayName"]
            except StopIteration: continue
            ch, ca = canon(h), canon(a)
            if not (ch and ca): continue
            dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ARG)
            tv = bool(ev["competitions"][0].get("timeValid", False))
            by.setdefault((ch, ca), []).append((dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), tv))
        time.sleep(0.06)
    return by

def nearest(cands, ref, keyfn=lambda c: c):
    if not cands: return None
    best = min(cands, key=lambda c: abs((dparse(keyfn(c)) - ref).days))
    return best if abs((dparse(keyfn(best)) - ref).days) <= WINDOW else None

def field(line, name):
    m = re.search(r'%s:"([^"]*)"' % name, line)
    return m.group(1) if m else None

def main():
    s = open(INDEX, encoding="utf-8").read()
    print("Buscando Promiedos (hc) ..."); prom = fetch_promiedos()
    print(f"  Promiedos: {sum(len(v) for v in prom.values())} jogos")
    print("Buscando ESPN (arg.1, futuro) ..."); espn = fetch_espn()
    print(f"  ESPN: {sum(len(v) for v in espn.values())} jogos futuros")

    m = re.search(r'const BASE_AR=\[(.*?)\n\];', s, re.DOTALL)
    lines = m.group(0).split("\n")
    considered = matched = confirmed = changed = 0
    diffs = []; skipped = []
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("{m:"): continue
        cp = field(ln, "cp")
        if cp not in ("apertura", "clausura"): continue
        hm, vm, dd, hh = field(ln, "m"), field(ln, "v"), field(ln, "d"), field(ln, "h")
        if not dd or dparse(dd) < TODAY: continue        # só jogos futuros
        considered += 1
        ch, ca = canon(hm), canon(vm)
        if not (ch and ca): skipped.append(f"{hm} x {vm} [sem canon]"); continue
        ref = dparse(dd)
        pm = nearest(prom.get((ch, ca), []), ref, keyfn=lambda c: c[0])
        em = nearest(espn.get((ch, ca), []), ref, keyfn=lambda c: c[0])
        if not pm or not em:
            skipped.append(f"{hm} x {vm} [{ 'sem promiedos' if not pm else 'sem espn'}]"); continue
        matched += 1
        if abs((dparse(pm[0]) - dparse(em[0])).days) > 1:   # fontes DISCORDAM na data -> não mexe
            skipped.append(f"{hm} x {vm} [discordam data: prom {pm[0]} / espn {em[0]}]"); continue
        confirmed += 1
        nd = pm[0]
        # hora: só troca se Promiedos e ESPN concordam (±60min) e ESPN marca confirmado; senão mantém a do usuário
        pmin, emin = hhmin(pm[1]), hhmin(em[1])
        nh = pm[1] if (em[2] and pmin is not None and emin is not None and abs(pmin - emin) <= 60) else hh
        nl = ln
        if dd != nd: nl = re.sub(r'd:"[^"]*"', 'd:"%s"' % nd, nl, count=1)
        if nh and hh != nh: nl = re.sub(r'h:"[^"]*"', 'h:"%s"' % nh, nl, count=1)
        if nl != ln:
            tag = "data+hora" if nh != hh else "data"
            diffs.append(f"[{cp}] {hm} x {vm}: {dd} {hh} -> {nd} {nh}  ({tag} ✓)")
            lines[i] = nl; changed += 1
    s2 = s[:m.start()] + "\n".join(lines) + s[m.end():]

    print(f"\nJogos futuros considerados: {considered}")
    print(f"  com match nas 2 fontes: {matched} | confirmados (datas concordam): {confirmed} | a alterar: {changed}")
    for d in diffs[:30]: print("  ", d)
    if skipped:
        print(f"\n--- não alterados ({len(skipped)}) — amostra ---")
        for x in sorted(set(skipped))[:15]: print("  ", x)
    if REPORT:
        print(f"\n[REPORT] {changed} mudanças (não gravei).")
    elif changed:
        open(INDEX, "w", encoding="utf-8").write(s2); print(f"\nGravado: {changed} jogos.")
    else:
        print("\nSem mudanças.")

if __name__ == "__main__":
    main()
