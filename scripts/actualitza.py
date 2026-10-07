"""Llegeix la web pública de la Federació Catalana de Billar i desa
els partits del C.B. MONFORTE "C" a data/data.json."""
import json, re, sys, os, unicodedata, datetime
import requests
from bs4 import BeautifulSoup

BASE = "https://intranet.fcbillar.cat"
LLIGA, DIVISIO, GRUP = 38, 160, 345          # Lliga Catalana 3 Bandes · 1a Divisió · Grup A
EQUIP = 'MONFORTE "C"'
RANKING_INICIAL = 124                         # rànquing del 27/07/2026
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "data.json")
INICIALS = os.path.join(ROOT, "data", "inicials.json")
DEBUG = os.path.join(ROOT, "data", "debug")

S = requests.Session()
S.headers["User-Agent"] = "MonforteC-app/1.0 (seguiment equip; 2 consultes/setmana)"

def norm(t):
    t = (t or "").replace("“", '"').replace("”", '"').replace("«", '"').replace("»", '"').replace("''", '"')
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()

def get(path, debug_name=None):
    r = S.get(BASE + path, timeout=30)
    r.raise_for_status()
    if debug_name:
        os.makedirs(DEBUG, exist_ok=True)
        with open(os.path.join(DEBUG, debug_name + ".html"), "w", encoding="utf-8") as f:
            f.write(r.text)
    return BeautifulSoup(r.text, "html.parser")

def rows(soup):
    out = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        links = [a.get("href", "") for a in tr.find_all("a")]
        if cells:
            out.append((cells, links))
    return out

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", norm(name).lower()).strip("-")[:60]

def pretty(name):
    return re.sub(r"\s+", " ", name).strip().title()

SCORE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})|(\d{2})/(\d{2})/(\d{4})")
STATUS = {"FINALITZADA", "PENDENT", "TANCADA", "TRES BANDES", "OBERTA", "AJORNADA"}

def find_date(texts):
    for t in texts:
        m = DATE.search(t)
        if m:
            return m.group(1) or f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
    return ""

def team_cells(cells):
    out = []
    for c in cells:
        if " - " in c and not SCORE.match(c):
            out.extend(x.strip() for x in c.split(" - ", 1))
            continue
        n = norm(c)
        if not n or SCORE.match(n) or DATE.search(n) or n.isdigit() or n in STATUS:
            continue
        if re.search(r"[A-Z]{2}", n):
            out.append(c)
    return out

def jornades():
    soup = get(f"/frontend/lligues/jornades/{LLIGA}/{DIVISIO}/{GRUP}", "jornades")
    out, seen = [], set()
    pat = re.compile(rf"/frontend/lligues/encontres/{LLIGA}/{DIVISIO}/{GRUP}/(\d+)")
    for cells, links in rows(soup):
        for l in links:
            m = pat.search(l)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                num = next((re.search(r"\d+", c).group() for c in cells if re.search(r"JORNADA\s*\d+", norm(c))), str(len(out) + 1))
                out.append({"id": m.group(1), "jornada": num, "date": find_date(cells)})
    return out

def encontre(j):
    soup = get(f"/frontend/lligues/encontres/{LLIGA}/{DIVISIO}/{GRUP}/{j['id']}", f"encontres-{j['jornada']}")
    pat = re.compile(r"/frontend/lligues/partides/[\d/]+/(\d+)")
    for cells, links in rows(soup):
        teams = team_cells(cells)
        idx = [i for i, t in enumerate(teams[:2]) if EQUIP in norm(t)]
        if not idx or len(teams) < 2:
            continue
        home = idx[0] == 0
        rival = teams[1] if home else teams[0]
        link = next((l for l in links if pat.search(l)), None)
        return {"venue": "L" if home else "F", "rival": rival, "date": find_date(cells) or j["date"],
                "link": link, "played": bool(link) and any("FINALITZADA" in norm(c) for c in cells)}
    return None

def partides(link, venue, jornada):
    path = link[len(BASE):] if link.startswith(BASE) else link
    soup = get(path, f"partides-{jornada}")
    res = []
    for cells, _ in rows(soup):
        names = []
        for c in cells:
            if SCORE.match(c) or not re.search(r"[A-Za-zÀ-ÿ]{2}", c):
                continue
            if " - " in c and c.count(",") >= 2:
                names.extend(x.strip() for x in c.split(" - ", 1))
            elif "," in c:
                names.append(c)
        scores = [SCORE.match(c) for c in cells if SCORE.match(c)]
        ints = [int(c) for c in cells if c.strip().isdigit()]
        if len(names) < 2 or len(scores) < 2 or not ints:
            continue
        me = 0 if venue == "L" else 1
        sm, car = int(scores[me].group(1)), int(scores[me].group(2))
        pts = (int(scores[-1].group(1)), int(scores[-1].group(2))) if len(scores) >= 3 else None
        r = ""
        if pts:
            mine, theirs = (pts[0], pts[1]) if venue == "L" else (pts[1], pts[0])
            r = "G" if mine > theirs else "P" if mine < theirs else "E"
        res.append({"name": names[me].strip(), "car": car, "ent": ints[0], "sm": sm, "res": r})
    return res

def ranking():
    try:
        soup = get(f"/frontend/rankings/llistat-dades?idranking={RANKING_INICIAL}&idmodalitat=1", "ranking")
    except Exception as e:
        print("Rànquing no disponible:", e); return {}
    out = {}
    for cells, _ in rows(soup):
        name = next((c for c in cells if "," in c), None)
        avg = next((c for c in cells if re.fullmatch(r"\d+[.,]\d{3,}", c.strip())), None)
        if name and avg:
            out[norm(name)] = round(float(avg.replace(",", ".")), 3)
    return out

def main():
    js = jornades()
    if not js:
        sys.exit("No s'han trobat jornades: potser ha canviat la web.")
    calendar, matches, players = [], [], {}
    for j in js:
        e = encontre(j)
        if not e:
            continue
        calendar.append({"jornada": j["jornada"], "date": e["date"], "rival": e["rival"], "venue": e["venue"], "played": e["played"]})
        if not e["played"]:
            continue
        rs = partides(e["link"], e["venue"], j["jornada"])
        if not rs:
            print(f"Jornada {j['jornada']}: sense partides llegibles"); continue
        out = []
        for r in rs:
            pid = slug(r["name"])
            players.setdefault(pid, {"id": pid, "name": pretty(r["name"]), "key": norm(r["name"])})
            out.append({"pid": pid, "car": r["car"], "ent": r["ent"], "sm": r["sm"], "res": r["res"]})
        matches.append({"id": "j" + j["jornada"].zfill(2), "jornada": j["jornada"], "date": e["date"], "rival": e["rival"], "venue": e["venue"], "results": out})
    rk = ranking()
    manual = {}
    if os.path.exists(INICIALS):
        manual = {norm(k): v for k, v in json.load(open(INICIALS, encoding="utf-8")).items()}
    for p in players.values():
        ini = manual.get(p["key"], rk.get(p["key"]))
        p["initial"] = f"{float(ini):.3f}" if ini not in (None, "") else ""
        del p["key"]
    data = {"equip": 'C.B. Monforte "C"', "competicio": "Lliga Catalana Tres Bandes · 1a Divisió · Grup A",
            "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
            "players": sorted(players.values(), key=lambda p: p["name"]),
            "matches": matches, "calendar": calendar}
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(matches)} partits, {len(players)} jugadors, {len(calendar)} jornades al calendari")

if __name__ == "__main__":
    main()
