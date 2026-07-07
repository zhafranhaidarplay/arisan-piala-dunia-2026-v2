#!/usr/bin/env python3
"""
Cek skor terbaru Piala Dunia 2026 dari ESPN (API publik, gratis, tanpa key)
lalu update array MATCHES di index.html. Didesain untuk dijalankan oleh
GitHub Actions (lihat .github/workflows/update-scores.yml), tapi juga bisa
dites lokal: python3 scripts/update_scores.py

Kalau ada perubahan, script ini HANYA menulis ulang index.html.
Commit + push dilakukan oleh workflow GitHub Actions, bukan oleh script ini.
"""

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = "."
HTML_PATH = f"{REPO_ROOT}/index.html"

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

WIB = timezone(timedelta(hours=7))
MONTH_ID = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"Mei",6:"Jun",7:"Jul",8:"Agu",
            9:"Sep",10:"Okt",11:"Nov",12:"Des"}

# ESPN displayName (atau variasinya) -> nama Indonesia yang dipakai di MATCHES
TEAM_MAP = {
    "south africa": "Afrika Selatan",
    "algeria": "Aljazair",
    "united states": "Amerika", "usa": "Amerika",
    "saudi arabia": "Arab Saudi",
    "argentina": "Argentina",
    "australia": "Australia",
    "austria": "Austria",
    "netherlands": "Belanda",
    "belgium": "Belgia",
    "bosnia and herzegovina": "Bosnia", "bosnia": "Bosnia",
    "brazil": "Brasil",
    "cape verde": "Cape Verde", "cabo verde": "Cape Verde",
    "czechia": "Ceko", "czech republic": "Ceko",
    "curacao": "Curacao", "curaçao": "Curacao",
    "ecuador": "Ekuador",
    "ghana": "Ghana",
    "haiti": "Haiti",
    "england": "Inggris",
    "iraq": "Irak",
    "iran": "Iran", "ir iran": "Iran",
    "japan": "Jepang",
    "germany": "Jerman",
    "canada": "Kanada",
    "colombia": "Kolombia",
    "south korea": "Korsel", "korea republic": "Korsel",
    "croatia": "Kroasia",
    "morocco": "Maroko",
    "mexico": "Meksiko",
    "egypt": "Mesir",
    "norway": "Norwegia",
    "panama": "Panama",
    "ivory coast": "Pantai Gading", "cote d'ivoire": "Pantai Gading", "côte d'ivoire": "Pantai Gading",
    "paraguay": "Paraguay",
    "portugal": "Portugal",
    "france": "Prancis",
    "qatar": "Qatar",
    "dr congo": "RD Congo", "congo dr": "RD Congo", "democratic republic of the congo": "RD Congo",
    "new zealand": "Selandia Baru",
    "senegal": "Senegal",
    "scotland": "Skotlandia",
    "spain": "Spanyol",
    "sweden": "Swedia",
    "switzerland": "Swiss",
    "tunisia": "Tunisia",
    "turkey": "Turki", "turkiye": "Turki", "türkiye": "Turki",
    "uruguay": "Uruguay",
    "uzbekistan": "Uzbekistan",
    "jordan": "Yordania",
}

# Jendela tanggal ronde knockout (dipakai untuk menentukan label 'group' di
# MATCHES). Diisi otomatis dari field "calendar" milik respons ESPN sendiri,
# supaya tidak hardcode tanggal.
ROUND_LABEL = {
    "round of 32": "RO16",
    "rd of 16": "R16",
    "round of 16": "R16",
    "quarterfinals": "QF",
    "quarterfinal": "QF",
    "semifinals": "SF",
    "semifinal": "SF",
    "3rd-place match": "3RD",
    "third place": "3RD",
    "final": "FINAL",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()


def espn_name_to_id(name):
    key = norm(name)
    if key in TEAM_MAP:
        return TEAM_MAP[key]
    print(f"  PERINGATAN: nama tim ESPN tidak dikenali: '{name}' (lewati)")
    return None


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "arisan-piala-dunia-bot"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_calendar_windows(sample):
    """Ambil jendela tanggal tiap ronde dari field calendar di respons ESPN."""
    windows = []
    try:
        entries = sample["leagues"][0]["calendar"][0]["entries"]
    except Exception:
        return windows
    for e in entries:
        label = norm(e.get("label", ""))
        start = e.get("startDate")
        end = e.get("endDate")
        if not start or not end:
            continue
        try:
            sd = datetime.fromisoformat(start.replace("Z", "+00:00"))
            ed = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except Exception:
            continue
        windows.append((label, sd, ed))
    return windows


def round_for_date(dt_utc, windows):
    for label, sd, ed in windows:
        if sd <= dt_utc <= ed:
            return ROUND_LABEL.get(label)
    return None


def fetch_events(days_back=3, days_fwd=1):
    today = datetime.now(timezone.utc).date()
    all_events = []
    calendar_windows = []
    for delta in range(-days_back, days_fwd + 1):
        d = today + timedelta(days=delta)
        url = f"{ESPN_BASE}?dates={d.strftime('%Y%m%d')}"
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"  Gagal fetch ESPN untuk {d}: {e}")
            continue
        if not calendar_windows:
            calendar_windows = get_calendar_windows(data)
        for ev in data.get("events", []):
            all_events.append(ev)
    # dedupe by event id
    seen = set()
    uniq = []
    for ev in all_events:
        if ev["id"] in seen:
            continue
        seen.add(ev["id"])
        uniq.append(ev)
    return uniq, calendar_windows


def parse_finished(events, calendar_windows):
    """Kembalikan list dict siap pakai untuk match yang sudah selesai (FT)."""
    out = []
    for ev in events:
        comp = ev["competitions"][0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed"):
            continue
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")
        home_id = espn_name_to_id(home["team"]["displayName"])
        away_id = espn_name_to_id(away["team"]["displayName"])
        if not home_id or not away_id:
            continue
        try:
            hs = int(home["score"])
            as_ = int(away["score"])
        except Exception:
            continue

        pen = None
        # Deteksi adu penalti: skor imbang tapi salah satu ditandai winner.
        home_win_flag = str(home.get("winner", "")).lower() == "true"
        away_win_flag = str(away.get("winner", "")).lower() == "true"
        if hs == as_ and (home_win_flag or away_win_flag):
            hp = home.get("shootoutScore") or home.get("seriesScore")
            ap = away.get("shootoutScore") or away.get("seriesScore")
            if hp is not None and ap is not None:
                try:
                    pen = {"h": int(hp), "a": int(ap)}
                except Exception:
                    pen = None
            if pen is None:
                print(f"  CATATAN: {home['team']['displayName']} vs {away['team']['displayName']} "
                      f"selesai adu penalti tapi skor penalti tidak terbaca dari API — "
                      f"perlu dicek/dilengkapi manual.")

        dt_utc = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        dt_wib = dt_utc.astimezone(WIB)
        date_str = f"{dt_wib.day:02d} {MONTH_ID[dt_wib.month]}"
        time_str = f"{dt_wib.hour:02d}:{dt_wib.minute:02d}"

        round_label = round_for_date(dt_utc, calendar_windows)

        out.append({
            "home": home_id, "away": away_id,
            "hs": hs, "as": as_, "pen": pen,
            "date": date_str, "time": time_str,
            "round": round_label,
        })
    return out


def load_html():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()


def save_html(content):
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def find_matches_block(content):
    m = re.search(r"const MATCHES = \[(.*?)\n\];", content, re.S)
    if not m:
        raise RuntimeError("Tidak menemukan array MATCHES di index.html")
    return m


def existing_pair_entries(block_text):
    """Cari semua entry {..} dan kembalikan list (home, away, done, raw_text)."""
    entries = []
    for em in re.finditer(r"\{[^{}]*\}", block_text):
        raw = em.group(0)
        hm = re.search(r'home:"([^"]+)"', raw)
        am = re.search(r'away:"([^"]+)"', raw)
        dm = re.search(r"done:(true|false)", raw)
        if not hm or not am:
            continue
        entries.append((hm.group(1), am.group(1), dm.group(1) == "true" if dm else False, raw))
    return entries


def build_new_entry_text(m):
    pen_txt = f", pen:{{h:{m['pen']['h']},a:{m['pen']['a']}}}" if m["pen"] else ""
    group = m["round"] or "R16"
    return (f'{{ date:"{m["date"]}", time:"{m["time"]}", group:"{group}", '
            f'home:"{m["home"]}", away:"{m["away"]}", hs:{m["hs"]}, as:{m["as"]}, done:true{pen_txt} }}')


def update_html(finished):
    content = load_html()
    block_match = find_matches_block(content)
    block_text = block_match.group(1)
    entries = existing_pair_entries(block_text)

    changed = False
    new_block_text = block_text
    to_append = []

    for m in finished:
        pair_found = None
        for (h, a, done, raw) in entries:
            if (h == m["home"] and a == m["away"]) or (h == m["away"] and a == m["home"]):
                pair_found = (h, a, done, raw)
                break

        if pair_found is None:
            to_append.append(m)
            continue

        h, a, done, raw = pair_found
        if done:
            continue  # sudah tercatat final, tidak perlu apa-apa

        # entry placeholder (done:false) -> update di tempat
        is_swapped = (h == m["away"] and a == m["home"])
        hs, as_ = (m["as"], m["hs"]) if is_swapped else (m["hs"], m["as"])
        pen = m["pen"]
        if pen and is_swapped:
            pen = {"h": pen["a"], "a": pen["h"]}
        pen_txt = f", pen:{{h:{pen['h']},a:{pen['a']}}}" if pen else ""

        new_raw = raw
        new_raw = re.sub(r"hs:\s*(null|-?\d+)", f"hs:{hs}", new_raw)
        new_raw = re.sub(r"as:\s*(null|-?\d+)", f"as:{as_}", new_raw)
        new_raw = re.sub(r"done:\s*(true|false)", "done:true", new_raw)
        if pen_txt and "pen:" not in new_raw:
            new_raw = new_raw.rstrip()
            new_raw = re.sub(r"\}\s*$", f"{pen_txt} }}", new_raw)

        new_block_text = new_block_text.replace(raw, new_raw, 1)
        changed = True
        print(f"  Update: {h} vs {a} -> {hs}:{as_}{' (pen)' if pen else ''}")

    if to_append:
        additions = ",\n  ".join(build_new_entry_text(m) for m in to_append)
        new_block_text = new_block_text.rstrip()
        if not new_block_text.endswith(","):
            new_block_text += ","
        new_block_text += "\n  " + additions
        changed = True
        for m in to_append:
            print(f"  Tambah baru: {m['home']} vs {m['away']} -> {m['hs']}:{m['as']} "
                  f"({m['round'] or '?'})")

    if not changed:
        return False

    new_content = content[:block_match.start(1)] + new_block_text + content[block_match.end(1):]
    save_html(new_content)
    return True


def main():
    now = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    print(f"===== Cek skor: {now} =====")
    events, windows = fetch_events()
    print(f"Ambil {len(events)} pertandingan dari ESPN (rentang -3/+1 hari).")
    finished = parse_finished(events, windows)
    print(f"{len(finished)} pertandingan selesai (FT) ditemukan dalam rentang ini.")
    changed = update_html(finished)
    if changed:
        print("HTML diperbarui.")
        sys.exit(0)
    else:
        print("Tidak ada perubahan.")
        sys.exit(0)


if __name__ == "__main__":
    main()
