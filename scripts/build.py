"""Spirka nightly data build (format 2).

Reads the official Sofia GTFS static feed (unzipped) and writes the data folder:

    <data_dir>/v1/index.json         stop list, lines, calendar  (loaded on every visit)
    <data_dir>/v1/stops/<id>.json    one small timetable per stop (loaded only for saved stops)
    <data_dir>/v1.prev/              last night's copy, for rollback

Usage:  python3 build2.py <gtfs_dir> <data_dir> [days=9] [-v]
Runs on Python 3.6+. The window starts yesterday (night trips belong to the previous service day).
If the city's file looks broken, nothing is replaced and the exit code is 1.
"""
import csv, json, sys, os, time, shutil, datetime, collections

args = [a for a in sys.argv[1:] if not a.startswith('-')]
GTFS, OUT = args[0], args[1]
NDAYS = int(args[2]) if len(args) > 2 else 9
VERBOSE = '-v' in sys.argv
FORMAT_DIR = 'v1'

def rd(name):
    return csv.DictReader(open(os.path.join(GTFS, name), encoding='utf-8-sig'))

def mins(t):
    h, m, _ = t.split(':')
    return int(h) * 60 + int(m)

# ---- calendar window (Sofia dates) ----
os.environ['TZ'] = 'Europe/Sofia'; time.tzset()
d0 = datetime.date.fromtimestamp(time.time()) - datetime.timedelta(1)
dates = [(d0 + datetime.timedelta(i)).strftime('%Y%m%d') for i in range(NDAYS)]
active = collections.defaultdict(set); DATESET = set(dates)
for r in rd('calendar_dates.txt'):
    if r['date'] in DATESET:
        if r['exception_type'] == '1':
            active[r['date']].add(r['service_id'])
used_services = set().union(*[active[d] for d in dates]) if dates else set()

# Patterns: dates with the same set of running services share one timetable.
pidx, days = {}, {}
for dt in dates:
    key = frozenset(active[dt])
    if key not in pidx:
        pidx[key] = len(pidx)
    days[dt] = pidx[key]
patterns = sorted(pidx, key=pidx.get)
svc_patterns = collections.defaultdict(list)       # service -> pattern numbers it belongs to
for key, p in pidx.items():
    for s in key:
        svc_patterns[s].append(p)

# ---- names, lines, trips ----
en = {}
for r in rd('translations.txt'):
    if r['table_name'] == 'stops' and r['field_name'] == 'stop_name' and r['language'] == 'en':
        en[r['field_value']] = r['translation']
routes = {r['route_id']: [r['route_short_name'], int(r['route_type']), r['route_color'] or '444444', r['route_text_color'] or 'FFFFFF']
          for r in rd('routes.txt')}
trips = {}
hs_bg = {}                        # destination as shown in English -> its Bulgarian original (for the page's Bulgarian mode)
for r in rd('trips.txt'):
    h = r['trip_headsign']; e = en.get(h, h)
    trips[r['trip_id']] = (r['route_id'], r['service_id'], e)
    if e != h: hs_bg[e] = h

# ---- stop times: every line serving a stop (any date), departures for the window ----
serves = collections.defaultdict(set)
trip_stops = collections.defaultdict(list)
dep = collections.defaultdict(lambda: collections.defaultdict(list))   # stop -> (route, headsign, pattern) -> [minutes]
for r in rd('stop_times.txt'):
    t = trips.get(r['trip_id'])
    if not t:
        continue
    rid, svc, hs = t
    s = r['stop_id']
    serves[s].add(rid)
    if routes[rid][1] == 1:                                  # metro: keep each trip's stop order (see 'directions')
        trip_stops[r['trip_id']].append((int(r['stop_sequence']), s))
    if svc in used_services:
        m = mins(r['departure_time'] or r['arrival_time'])
        for p in svc_patterns[svc]:
            dep[s][(rid, hs, p)].append(m)

# ---- metro directions ----
# A few metro trains end early (e.g. at Konstantin Velichkov). Each such destination is filed under the main
# destination it shares a direction with, so the page can show them in one row, and each main direction gets
# an 'inbound' mark at every station: does it head towards the centre (Serdica / NDK) from here?
CENTRE = {'СЕРДИКА', 'СЕРДИКА II', 'НАЦИОНАЛЕН ДВОРЕЦ НА КУЛТУРАТА', 'НАЦИОНАЛЕН ДВОРЕЦ НА КУЛТУРАТА II'}
stop_name = {r['stop_id']: r['stop_name'].upper() for r in rd('stops.txt')}
main_of, seq_of = {}, {}          # (route, headsign) -> main headsign;  (route, main headsign) -> stop order
by_route = collections.defaultdict(lambda: collections.defaultdict(list))
for tid, st in trip_stops.items():
    rid, svc, hs = trips[tid]
    by_route[rid][hs].append([x for _, x in sorted(st)])
for rid, hss in by_route.items():
    mains = sorted(hss, key=lambda h: -len(hss[h]))[:2]
    for m in mains:
        seq_of[(rid, m)] = max(hss[m], key=len)
        main_of[(rid, m)] = m
    for hs, seqs in hss.items():
        if hs in mains:
            continue
        first, last = seqs[0][0], seqs[0][-1]
        for m in mains:
            L = seq_of[(rid, m)]
            if first in L and last in L and L.index(first) < L.index(last):
                main_of[(rid, hs)] = m
                break

def inbound(rid, main, sid):
    L = seq_of.get((rid, main))
    if not L or sid not in L:
        return 0
    return int(any(stop_name.get(x) in CENTRE for x in L[L.index(sid) + 1:]))

# ---- stop list ----
# Each stop: [id, code, name, English name, lat, lon, lines, towards]
# 'towards' = the two most common destinations of the vehicles leaving this stop in the coming days,
# so people can tell apart two stops with the same name on opposite sides of a road.
def towards(stop_id, stop_name_en, stop_name):
    count = collections.Counter()
    for (rid, hs, p), ms in dep.get(stop_id, {}).items():
        if hs and hs.upper() not in (stop_name_en.upper(), stop_name.upper()):   # trips ending here go nowhere from here
            count[hs] += len(ms)
    return [h for h, _ in count.most_common(2)]

stops = []
for r in rd('stops.txt'):
    if r['location_type'] not in ('', '0'):
        continue
    rs = sorted(serves.get(r['stop_id'], ()))
    if rs:
        name_en = en.get(r['stop_name'], '')
        stops.append([r['stop_id'], r['stop_code'], r['stop_name'], name_en,
                      round(float(r['stop_lat']), 5), round(float(r['stop_lon']), 5), rs,
                      towards(r['stop_id'], name_en, r['stop_name'])])

# ---- sanity checks: if the city's file looks broken tonight, keep yesterday's data ----
codes = {s[1] for s in stops}
problems = []
if len(stops) < 2500: problems.append('only %d stops' % len(stops))
for c in ('0944', '1308', '2327'):
    if c not in codes: problems.append('stop %s missing' % c)
if not active[dates[1]]: problems.append('no service on %s' % dates[1])
if problems:
    print('NOT PUBLISHED: ' + '; '.join(problems)); sys.exit(1)

# ---- write a fresh folder, then swap it in ----
def dump(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))

live_dir = os.path.join(OUT, FORMAT_DIR)
new_dir, prev_dir = live_dir + '.new', live_dir + '.prev'
shutil.rmtree(new_dir, ignore_errors=True)
os.makedirs(os.path.join(new_dir, 'stops'))

dump(os.path.join(new_dir, 'index.json'), {
    'format': 2, 'built': dates[1], 'from': dates[0], 'to': dates[-1],
    'patterns': len(patterns), 'days': days, 'routes': routes, 'stops': stops, 'hb': hs_bg})

nfiles, nbytes = 0, 0
for s in stops:
    sid = s[0]
    rows = collections.defaultdict(lambda: [[] for _ in patterns])        # (route, headsign) -> per pattern
    for (rid, hs, p), ms in dep.get(sid, {}).items():
        rows[(rid, hs)][p] = ms
    out = []
    for (rid, hs), per in sorted(rows.items()):
        enc = []
        for ms in per:                                   # sorted, de-duplicated, stored as differences
            ms = sorted(set(ms))
            enc.append([ms[0]] + [b - a for a, b in zip(ms, ms[1:])] if ms else [])
        if routes[rid][1] == 1 and (rid, hs) in main_of:    # metro: + main destination, + 1 if it heads to the centre
            m = main_of[(rid, hs)]
            out.append([rid, hs, enc, m, inbound(rid, m, sid)])
        else:
            out.append([rid, hs, enc])
    path = os.path.join(new_dir, 'stops', sid + '.json')
    dump(path, {'id': sid, 'r': out})
    nfiles += 1; nbytes += os.path.getsize(path)

shutil.rmtree(prev_dir, ignore_errors=True)
if os.path.isdir(live_dir):
    os.rename(live_dir, prev_dir)
os.rename(new_dir, live_dir)

if VERBOSE:
    print('ok %s -> %s, %d patterns, %d stops, %d stop files, %d KB total'
          % (dates[0], dates[-1], len(patterns), len(stops), nfiles, nbytes // 1024))
