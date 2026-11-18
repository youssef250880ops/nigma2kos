# -*- coding: utf-8 -*-
"""
Moteur KingOfSat -> Enigma2 (lamedb + bouquets).

- liste des satellites : <base>/satellites
- chaînes d'une position : <base>/pos-13E, <base>/pos-0.8W ...
Les pages sont mises en cache (par défaut 24 h) et les requêtes sont espacées.
"""
import os, re, time, urllib.request
from urllib.parse import urljoin
from html.parser import HTMLParser

BASE = "https://en.kingofsat.net"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Enigma2Tool/1.0"}
FEC = {"1/2": 1, "2/3": 2, "3/4": 3, "5/6": 4, "7/8": 5, "8/9": 6, "3/5": 7, "4/5": 8, "9/10": 9}
POL = {"H": 0, "V": 1, "L": 2, "R": 3}
MOD = {"QPSK": 1, "8PSK": 2, "16APSK": 3, "32APSK": 4}


# ------------------------------------------------------------ téléchargement
def fetch(url, cache_dir=None, max_age=86400, delay=1.5, force=False):
    path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, re.sub(r"[^A-Za-z0-9.]+", "_", url)[-120:] + ".html")
        if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    time.sleep(delay)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        cs = r.headers.get_content_charset() or "utf-8"
    try:
        html = raw.decode(cs, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


# ------------------------------------------------------------ analyse HTML
class RowParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        top = self.stack[-1] if self.stack else None
        if tag == "tr":
            self.stack.append({"cells": [], "imgs": [], "cur": None})
        elif tag in ("td", "th") and top is not None:
            c = {"text": [], "links": [], "imgs": []}
            top["cells"].append(c)
            top["cur"] = c
        elif tag == "a" and top is not None and top["cur"] is not None and a.get("href"):
            top["cur"]["links"].append(a["href"])
        elif tag == "img" and top is not None:
            src = a.get("src", "")
            top["imgs"].append(src)
            if top["cur"] is not None:
                top["cur"]["imgs"].append(src)
        elif tag == "br" and top is not None and top["cur"] is not None:
            top["cur"]["text"].append(" ")

    def handle_endtag(self, tag):
        if tag == "tr" and self.stack:
            self.rows.append(self.stack.pop())
        elif tag in ("td", "th") and self.stack:
            self.stack[-1]["cur"] = None

    def handle_data(self, d):
        if self.stack and self.stack[-1]["cur"] is not None:
            self.stack[-1]["cur"]["text"].append(d)


def rows_of(html):
    p = RowParser()
    p.feed(html)
    out = []
    for r in p.rows:
        cells = [{"t": " ".join("".join(c["text"]).split()), "links": c["links"], "imgs": c["imgs"]}
                 for c in r["cells"]]
        out.append({"cells": cells, "imgs": r["imgs"]})
    return out


def parse_satellites(html, base=BASE):
    sats, order = {}, []
    for r in rows_of(html):
        c = r["cells"]
        if len(c) < 6:
            continue
        m = None
        for l in c[0]["links"]:
            m = re.search(r"pos-([0-9.]+[EW])\b", l)
            if m:
                break
        if not m:
            continue
        pos = m.group(1)
        if pos not in sats:
            sats[pos] = {"pos": pos, "names": [], "channels": 0, "fta": 0,
                         "url": urljoin(base + "/", [l for l in c[0]["links"] if "pos-" in l][0])}
            order.append(pos)
        s = sats[pos]
        name = re.sub(r"\s*Moving.*$", "", c[1]["t"]).strip()
        if name and name not in s["names"]:
            s["names"].append(name)
        if c[5]["t"].isdigit():
            s["channels"] += int(c[5]["t"])
        if len(c) > 6 and c[6]["t"].isdigit():
            s["fta"] += int(c[6]["t"])
    return [sats[p] for p in order]


def orb_value(label):
    """'13.0°E' -> 130 ; '0.8°W' -> 3592 (convention lamedb)."""
    m = re.match(r"\s*([\d.]+)\s*°?\s*([EW])", label)
    if not m:
        return None
    v = int(round(float(m.group(1)) * 10))
    return v if m.group(2) == "E" or v == 0 else 3600 - v


def parse_pos_page(html, default_pos=None):
    tps, cur = [], None
    for r in rows_of(html):
        c = [x["t"] for x in r["cells"]]
        if not c:
            continue
        # --- ligne de transpondeur
        if len(c) >= 9 and re.match(r"^[\d.]+\s*°\s*[EW]", c[0]):
            m = re.match(r"^(\d+(?:\.\d+)?)\s*([HVLR])", c[2])
            si = next((i for i, x in enumerate(c) if re.match(r"^DVB-S(2X?)?$", x)), None)
            if m and si is not None and si + 3 < len(c):
                fec = c[si + 3].strip()
                cur = {"label": c[0], "orb": orb_value(c[0]), "freq": float(m.group(1)),
                       "pol": m.group(2), "std": c[si], "mod": c[si + 1],
                       "sr": int(re.sub(r"\D", "", c[si + 2]) or 0), "fec": fec,
                       "nid": None, "tsid": None, "channels": []}
                tps.append(cur)
            continue
        # --- ligne "Transport Stream ... NID x - TSID y"
        joined = " ".join(c)
        m = re.search(r"NID\s+(\d+)\s*-\s*TSID\s+(\d+)", joined)
        if m and cur is not None and cur["nid"] is None:
            cur["nid"], cur["tsid"] = int(m.group(1)), int(m.group(2))
            continue
        # --- ligne de chaîne
        if cur is None:
            continue
        if c and c[0] == "":
            c = c[1:]
        sid_i = next((k for k in range(4, min(8, len(c))) if c[k].isdigit()), None)
        if sid_i is None or len(c) < sid_i + 4:
            continue
        imgs = [os.path.basename(i).lower() for i in r["imgs"]]
        name = c[0]
        vpid_t = c[sid_i + 1]
        audio_t = c[sid_i + 2]
        vpid = int(vpid_t.split()[0]) if vpid_t.split() and vpid_t.split()[0].isdigit() else 0
        am = re.match(r"\d+", audio_t)
        apid = int(am.group(0)) if am else 0
        pcr_t = c[sid_i + 4] if len(c) > sid_i + 4 else ""
        pcr = int(pcr_t.split()[0]) if pcr_t.split() and pcr_t.split()[0].isdigit() else vpid
        if "ultrahd.gif" in imgs or "ultrahd8k.gif" in imgs or re.search(r"\b(4K|UHD)\b", name, re.I):
            q = "4K"
        elif "hd.gif" in imgs or re.search(r"\bHD\b", name, re.I):
            q = "HD"
        else:
            q = "SD"
        if not vpid:
            if not apid:
                continue  # données seules
            q = "Radio"
        cur["channels"].append({
            "name": name, "country": c[1], "category": c[2],
            "packages": " ".join(c[3:sid_i - 1]).strip(), "crypt": c[sid_i - 1],
            "sid": int(c[sid_i]), "vpid": vpid, "apid": apid, "pcr": pcr,
            "langs": re.findall(r"\b[a-z]{3}\b", audio_t), "quality": q})
    return tps


# ------------------------------------------------------------ export Enigma2
STYPE = {"4K": 31, "HD": 25, "SD": 1, "Radio": 2}


def safe(s):
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_").lower() or "bq"


def build_lists(sat_tps, quals, fta_only=True, countries=None):
    """sat_tps: {pos_label: [tp,...]} -> (transponders, services)"""
    countries = [x.strip().lower() for x in (countries or []) if x.strip()]
    transponders, services, seen, tp_ids = {}, [], set(), {}
    for pos, tps in sat_tps.items():
        for tp in tps:
            if tp["orb"] is None:
                continue
            nid = tp["nid"] if tp["nid"] is not None else 1
            tsid = tp["tsid"] if tp["tsid"] is not None else 1
            chans = []
            for ch in tp["channels"]:
                if ch["quality"] not in quals:
                    continue
                if fta_only and ch["crypt"].lower() != "clear":
                    continue
                if countries and not any(k in ch["country"].lower() for k in countries):
                    continue
                chans.append(ch)
            if not chans:
                continue
            pol = POL.get(tp["pol"], 0)
            ns = tp["orb"] << 16
            tkey = (tp["freq"], tp["pol"])
            while (ns, tsid, nid) in tp_ids and tp_ids[(ns, tsid, nid)] != tkey:
                ns = (tp["orb"] << 16) | (int(tp["freq"]) & 0x7FFF) | (0x8000 if pol in (1, 3) else 0)
                if (ns, tsid, nid) in tp_ids and tp_ids[(ns, tsid, nid)] != tkey:
                    ns += 1
            tp_ids[(ns, tsid, nid)] = tkey
            s2 = tp["std"].startswith("DVB-S2")
            line = "\ts %d:%d:%d:%d:%d:2:0" % (int(round(tp["freq"] * 1000)), tp["sr"] * 1000, pol,
                                               FEC.get(tp["fec"], 0), tp["orb"])
            if s2:
                line += ":1:%d:0:2" % MOD.get(tp["mod"], 2)
            transponders[(ns, tsid, nid)] = [line]
            for ch in chans:
                key = (ch["sid"], tsid, nid, ns)
                if key in seen:
                    continue
                seen.add(key)
                caps = ["c:00%04x" % ch["vpid"]] if ch["vpid"] else []
                if ch["apid"]:
                    caps.append("c:01%04x" % ch["apid"])
                if ch["pcr"]:
                    caps.append("c:03%04x" % ch["pcr"])
                prov = ch["packages"] or pos
                services.append({
                    "sid": ch["sid"], "tsid": tsid, "onid": nid, "ns": ns, "pos": pos,
                    "stype": STYPE[ch["quality"]], "name": ch["name"], "category": ch["category"] or "Other",
                    "quality": ch["quality"], "head": "%04x:%08x:%04x:%04x:%d:0" % (ch["sid"], ns, tsid, nid, STYPE[ch["quality"]]),
                    "extra": ",".join(["p:" + prov.replace(",", " ")] + caps)})
    return transponders, services


def ref(s):
    return "1:0:%X:%X:%X:%X:%X:0:0:0:" % (s["stype"], s["sid"], s["tsid"], s["onid"], s["ns"])


def write_enigma2(out_dir, transponders, services, per_sat, per_cat, per_quality, log=print):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "lamedb"), "w", encoding="utf-8", newline="\n") as f:
        f.write("eDVB services /4/\ntransponders\n")
        for key, data in transponders.items():
            f.write("%08x:%04x:%04x\n" % key + "\n".join(data) + "\n/\n")
        f.write("end\nservices\n")
        for s in services:
            f.write("%s\n%s\n%s\n" % (s["head"], s["name"], s["extra"]))
        f.write("end\nEditors only!\n")

    tv, radio = [], []

    def bq(fname, title, items, kind):
        if not items:
            return
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write("#NAME %s\n" % title)
            for s in items:
                f.write("#SERVICE %s\n" % ref(s))
        (tv if kind == "tv" else radio).append(fname)

    tvs = [s for s in services if s["quality"] != "Radio"]
    rds = [s for s in services if s["quality"] == "Radio"]
    if per_quality:
        for q in ("4K", "HD", "SD"):
            bq("userbouquet.q_%s.tv" % q.lower(), "Chaînes %s" % q, [s for s in tvs if s["quality"] == q], "tv")
    sats = sorted({s["pos"] for s in services})
    if per_sat:
        for p in sats:
            bq("userbouquet.sat_%s.tv" % safe(p), p, [s for s in tvs if s["pos"] == p], "tv")
            bq("userbouquet.sat_%s.radio" % safe(p), "%s Radio" % p, [s for s in rds if s["pos"] == p], "radio")
    if per_cat:
        cats = sorted({s["category"] for s in tvs})
        for p in sats:
            for c in cats:
                bq("userbouquet.%s_%s.tv" % (safe(p), safe(c)), "%s - %s" % (p, c),
                   [s for s in tvs if s["pos"] == p and s["category"] == c], "tv")
    if not (per_sat or per_cat or per_quality):
        bq("userbouquet.all.tv", "Toutes les chaînes", tvs, "tv")
        bq("userbouquet.all.radio", "Radio", rds, "radio")

    for fname, head, lst in (("bouquets.tv", "Bouquets (TV)", tv), ("bouquets.radio", "Bouquets (Radio)", radio)):
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write("#NAME %s\n" % head)
            for fn in lst:
                f.write('#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "%s" ORDER BY bouquet\n' % fn)
    log("Export : %d chaînes, %d transpondeurs, %d bouquets TV, %d bouquets radio -> %s"
        % (len(services), len(transponders), len(tv), len(radio), out_dir))
