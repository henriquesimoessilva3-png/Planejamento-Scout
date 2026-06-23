#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atualiza datas/horários dos jogos da Liga MX (Apertura) no index.html
a partir da API aberta da ESPN (site.api.espn.com), sem Cloudflare/CORS.

- Só toca no bloco BASE_MX (México). Casa cada jogo por confronto (os dois times).
- Só aplica horários CONFIRMADOS pela ESPN (timeValid). Nunca adiciona/remove jogos.
- A Argentina (BASE_AR) NÃO é mexida: é uma base curada com várias competições
  (apertura/clausura/reserva/segunda/copa/Libertadores) que não alinha 1:1 com o
  feed da ESPN — casar automaticamente pegaria jogos errados. Fica manual.

Uso:  python update_fixtures.py [index.html] [--report]
"""
import sys, re, json, ssl, time, unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import urllib.request, urllib.error

INDEX = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "index.html"
REPORT = "--report" in sys.argv
APERTURA_TYPE = 14277  # ESPN season.type para "Torneo Apertura"

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=25))
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError):  # CA local ausente (macOS)
            ctx = ssl._create_unverified_context()
            return json.load(urllib.request.urlopen(req, timeout=25, context=ctx))
        raise

def espn_apertura():
    base = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard"
    cal = http_json(base).get("leagues", [{}])[0].get("calendar", [])
    seen, out = set(), []
    for cdate in cal:
        ymd = str(cdate)[:10].replace("-", "")
        if not ymd.isdigit():
            continue
        for _ in range(3):
            try:
                day = http_json(f"{base}?dates={ymd}"); break
            except Exception:
                time.sleep(1.5)
        else:
            print(f"  [aviso] falha em {ymd}", file=sys.stderr); continue
        for ev in day.get("events", []):
            if ev["id"] in seen or ev.get("season", {}).get("type") != APERTURA_TYPE:
                continue
            seen.add(ev["id"])
            c = ev["competitions"][0]; cs = c["competitors"]
            try:
                h = next(x for x in cs if x["homeAway"] == "home")["team"]["displayName"]
                a = next(x for x in cs if x["homeAway"] == "away")["team"]["displayName"]
            except StopIteration:
                continue
            ts = int(datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).timestamp())
            out.append({"h": h, "a": a, "ts": ts, "tv": bool(c.get("timeValid", False))})
        time.sleep(0.1)
    return out

def canon(name):
    x = re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower())
    for kw, key in [("necaxa","necaxa"),("xolos","tijuana"),("tijuana","tijuana"),("san luis","san luis"),
                    ("leon","leon"),("juarez","juarez"),("pumas","pumas"),("guadalajara","guadalajara"),
                    ("chivas","guadalajara"),("monterrey","monterrey"),("queretaro","queretaro"),
                    ("cruz azul","cruz azul"),("toluca","toluca"),("tigres","tigres"),("atlante","atlante"),
                    ("santos","santos"),("pachuca","pachuca"),("puebla","puebla"),("atlas","atlas"),("america","america")]:
        if kw in x:
            return key
    return None

MX_TZ = {"tij": "America/Tijuana", "jua": "America/Ciudad_Juarez"}
BR = ZoneInfo("America/Sao_Paulo")

def field(line, name):
    m = re.search(r'%s:"([^"]*)"' % name, line)
    return m.group(1) if m else None

def main():
    s = open(INDEX, encoding="utf-8").read()
    games = espn_apertura()
    print(f"ESPN: {len(games)} jogos da Apertura ({sum(g['tv'] for g in games)} com horário confirmado)")
    idx = {}
    for g in games:
        ch, ca = canon(g["h"]), canon(g["a"])
        if ch and ca:
            idx.setdefault((ch, ca), []).append(g)

    m = re.search(r'const BASE_MX=\[(.*?)\n\];', s, re.DOTALL)
    if not m:
        print("[erro] BASE_MX não encontrado"); sys.exit(1)
    lines = m.group(0).split("\n")
    matched = changed = 0
    diffs = []
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("{m:"):
            continue
        hm, vm, dd, hh = field(ln, "m"), field(ln, "v"), field(ln, "d"), field(ln, "h")
        ch, ca = canon(hm), canon(vm)
        cands = idx.get((ch, ca), [])
        if not cands:
            continue
        cur = int(datetime.fromisoformat(dd + "T12:00:00+00:00").timestamp()) if dd else None
        g = min(cands, key=lambda x: abs(x["ts"] - cur)) if cur else cands[0]
        matched += 1
        if not g["tv"]:               # horário não confirmado pela ESPN -> não mexe
            continue
        tz = ZoneInfo(MX_TZ.get(field(ln, "c"), "America/Mexico_City"))
        dt = datetime.fromtimestamp(g["ts"], tz); db = datetime.fromtimestamp(g["ts"], BR)
        nd, nh = dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
        nhbr = db.strftime("%H:%M") + ("+1" if db.date() > dt.date() else "")
        nl = ln
        if dd != nd: nl = re.sub(r'd:"[^"]*"', 'd:"%s"' % nd, nl, count=1)
        if hh != nh: nl = re.sub(r'h:"[^"]*"', 'h:"%s"' % nh, nl, count=1)
        if field(nl, "hbr") not in (None, nhbr): nl = re.sub(r'hbr:"[^"]*"', 'hbr:"%s"' % nhbr, nl, count=1)
        if nl != ln:
            diffs.append(f"{hm} x {vm}: {dd} {hh} -> {nd} {nh}")
            lines[i] = nl; changed += 1
    s2 = s[:m.start()] + "\n".join(lines) + s[m.end():]

    print(f"Casados: {matched}/153 | atualizados (horário confirmado e diferente): {changed}")
    for d in diffs[:30]:
        print("  ", d)
    if REPORT:
        print(f"\n[REPORT] {changed} mudanças (não gravei).")
    elif changed:
        open(INDEX, "w", encoding="utf-8").write(s2)
        print(f"\nGravado: {changed} jogos atualizados.")
    else:
        print("\nNenhuma mudança — já está atualizado.")

if __name__ == "__main__":
    main()
