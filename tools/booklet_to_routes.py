"""
booklet_to_routes.py - Rebuilds routes.json from the printed 2007 VR timetable booklet (PDF).

Usage:  python tools/booklet_to_routes.py BOOKLET.pdf GTFS_DIR [OUT=routes.json]
  BOOKLET.pdf  the 2007 "Aikataulukirja" PDF (not distributed with this project)
  GTFS_DIR     unzipped Digitraffic GTFS (stops.txt, translations.txt)

Stage 1 reads every timetable's number, title and station rows (km, '.o' arrival rows,
red connection rows) from the booklet's text layer. Stage 2 maps station names to today's
station codes, drops closed stations and bus stops. Stage 3 adds each table's own line
sections (filter_groups), Swedish titles and the corrections described in the README.
Requires pdfplumber.
"""
import sys, os
BOOKLET, GTFS = sys.argv[1], sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "routes.json")
import csv, json, re, collections
import pdfplumber

# ---- stage 1: read the booklet
F=BOOKLET
out=collections.OrderedDict()
with pdfplumber.open(F) as pdf:
    for i,p in enumerate(pdf.pages):
        if p.width<600 or i+1<24 or i+1>106: continue
        ws=p.extract_words(extra_attrs=["fontname","size"], x_tolerance=1.5)
        hr=[l for l in p.lines if abs(l["linewidth"]-0.533)<0.05 and l["x1"]-l["x0"]>100]
        for half,(lo,hi) in (("L",(0,330)),("R",(330,700))):
            num=[w["text"] for w in ws if lo<w["x0"]<hi and w["top"]<40 and round(w["size"],1)==13.5]
            title=" ".join(w["text"] for w in ws if lo<w["x0"]<hi and w["top"]<40 and round(w["size"],1)==9.5)
            if not num: continue
            key=(num[0], title)
            if key in out: continue
            # header rule for this half
            rules=[l["top"] for l in hr if lo<=l["x0"]<hi and l["top"]>60]
            top=min(rules) if rules else 95
            ends=[l["top"] for l in p.lines if abs(l["linewidth"]-1.066)<0.05 and lo<=l["x0"]<hi and l["top"]>top]
            bottom=min(ends) if ends else 460
            base = lo + (25.5 if half=="L" else 375.6-330+330-330)  # left edge of content
            x_left = 25.5 if half=="L" else 375.6
            col_end = x_left + 79.6
            chars=[c for c in p.chars if x_left-1<=c["x0"]<col_end+2 and top<c["top"]<bottom]
            lines=collections.defaultdict(list)
            for c in chars: lines[round(c["top"])].append(c)
            rows=[]
            for t in sorted(lines):
                cs=sorted(lines[t], key=lambda c:c["x0"])
                km="".join(c["text"] for c in cs if c["x0"]<x_left+10 and c["text"].isdigit())
                namecs=[c for c in cs if c["x0"]>=x_left+10 and "Condensed" in c["fontname"] and c["text"]!="."]
                name="".join(c["text"] if True else "" for c in namecs)
                # rebuild spaces
                txt=""; prev=None
                for c in namecs:
                    if prev is not None and c["x0"]-prev["x1"]>1.0: txt+=" "
                    txt+=c["text"]; prev=c
                ital=any("Obl" in c["fontname"] for c in namecs)
                arr=any(c["text"]=="o" and "Condensed" not in c["fontname"] and c["x0"]>col_end-10 for c in cs)
                sym="".join(c["text"] for c in cs if "Condensed" not in c["fontname"] and c["text"] not in ".o")
                if not txt and not km: continue
                rows.append({"km":km,"name":txt.strip(),"conn":ital,"arr":arr,"sym":sym})
            out[key]={"page":i+1,"half":half,"rows":rows}
tables=[{"id":k[0],"title":k[1],**v} for k,v in out.items()]

# ---- stage 2: map to station codes
stops=list(csv.DictReader(open(os.path.join(GTFS,"stops.txt"),encoding="utf-8-sig")))
names={s["stop_name"]:s["stop_id"] for s in stops if s["location_type"]=="1"}
FIX={"ulu":"Oulu","oensuu":"Joensuu","ajaani":"Kajaani","ontiomäki":"Kontiomäki","elsinki":"Helsinki","asila":"Pasila","olari":"Kolari"}
TITLE_FIX={("6",0):"Helsinki - Kemi - Kolari",("6",1):"Kolari - Kemi - Helsinki",
           ("14A",0):"Joensuu - Kajaani - Kontiomäki - Oulu",("14A",1):"Oulu - Kontiomäki - Kajaani - Joensuu"}
SKIP={"7C","8A","9A"}   # 7C extraction failed / no service; 8A, 9A are other-period variants of 8 and 9
def clean(n):
    n=re.sub(r"(\s+\d{1,2}(\s+\d{2})?)+$","",n).strip()
    n=re.sub(r"\s+\d+$","",n).strip()
    return FIX.get(n,n)
def match(n):
    if n in names: return names[n]
    c=[k for k in names if len(n)>=4 and k.endswith(n) and len(k)-len(n)<=1]
    return names[c[0]] if len(c)==1 else None
routes=[]; seen=collections.Counter(); dropped=collections.defaultdict(list)
for t in tables:
    if t["id"] in SKIP: continue
    k=seen[t["id"]]; seen[t["id"]]+=1
    title=TITLE_FIX.get((t["id"],k), t["title"]).replace("-"," - ").replace("  "," ")
    title=re.sub(r"\s*-\s*"," - ",title)
    rows=[]
    for r in t["rows"]:
        n=clean(r["name"])
        if not n or re.search(r"\b(las|ras|th)$",n): continue
        code=match(n)
        if not code: dropped[t["id"]].append(n); continue
        rows.append({"code":code,"km":int(r["km"]) if r["km"].isdigit() else None,"arr":bool(r["arr"]),"conn":bool(r["conn"])})
    # same station twice in a row (arrival + departure) where the mark was not a text 'o'
    for a,b in zip(rows,rows[1:]):
        if a["code"]==b["code"] and not a["conn"] and not b["conn"] and not a["arr"] and not b["arr"]:
            a["arr"]=True
    # drop connection rows pointing at the table's own main stations and collapse leftovers
    main=[r["code"] for r in rows if not r["conn"]]
    rows=[r for r in rows if not (r["conn"] and r["code"] in main)]
    routes.append({"id":t["id"],"title_fi":title,"rows":rows})
raw=routes

# ---- stage 3: filters, Swedish titles, corrections
stops=list(csv.DictReader(open(os.path.join(GTFS,"stops.txt"),encoding="utf-8-sig")))
code={s["stop_name"]:s["stop_id"] for s in stops if s["location_type"]=="1"}
name_of={v:k for k,v in code.items()}
tr={r["field_value"]:r["translation"] for r in csv.DictReader(open(os.path.join(GTFS,"translations.txt"),encoding="utf-8-sig"))}
SV_FALLBACK={"Turku":"Åbo","Tampere":"Tammerfors","Oulu":"Uleåborg","Helsinki":"Helsingfors","Hämeenlinna":"Tavastehus",
 "Vaasa":"Vasa","Pori":"Björneborg","Hanko":"Hangö","Karjaa":"Karis","Kokkola":"Karleby","Lahti":"Lahtis",
 "Lappeenranta":"Villmanstrand","Savonlinna":"Nyslott","Mikkeli":"S:t Michel","Kajaani":"Kajana","Iisalmi":"Idensalmi",
 "Tornio":"Torneå","Haaparanta":"Haparanda","Toijala":"Toijala","Riihimäki":"Riihimäki","Seinäjoki":"Seinäjoki",
 "Kouvola":"Kouvola","Kotka":"Kotka","Kemi":"Kemi","Kolari":"Kolari","Rovaniemi":"Rovaniemi","Kemijärvi":"Kemijärvi",
 "Jyväskylä":"Jyväskylä","Pieksämäki":"Pieksämäki","Kuopio":"Kuopio","Joensuu":"Joensuu","Imatra":"Imatra",
 "Haapamäki":"Haapamäki","Ylivieska":"Ylivieska","Parikkala":"Parikkala","Kontiomäki":"Kontiomäki"}
def sv(title):
    return " - ".join(tr.get(p) or SV_FALLBACK.get(p, p) for p in title.split(" - "))
# Each table's own line sections (station names). A train belongs to the table when it calls,
# in table direction, at >= 2 stations of at least one group.
G={
 "1":  [["Kirkkonummi","Karjaa","Salo","Kupittaa","Turku","Turku satama"]],
 "2":  [["Karjaa","Dragsvik","Tammisaari","Skogby","Lappohja","Santala","Hanko-Pohjoinen","Hanko"]],
 "3":  [["Riihimäki","Hämeenlinna","Toijala","Tampere"]],
 "4":  [["Tampere","Nokia","Karkku","Sastamala","Vammala","Kokemäki","Harjavalta","Pori"]],
 "5":  [["Seinäjoki","Vaasa"]],
 "6":  [["Kemi","Ylitornio","Pello","Kolari"]],
 "7":  [["Lapua","Kauhava","Pännäinen","Kokkola","Kannus","Ylivieska","Oulainen","Vihanti","Ruukki","Oulu","Kemi","Tervola","Muurola","Rovaniemi","Misi","Kemijärvi"]],
 "7A": [["Rovaniemi","Misi","Kemijärvi"]],
 "8":  [["Turku satama","Turku","Loimaa","Humppila"]],
 "9":  [["Jyväskylä","Hankasalmi","Pieksämäki","Varkaus","Heinävesi","Vihtari","Viinijärvi","Joensuu"]],
 "10": [["Orivesi","Jämsä","Jyväskylä","Hankasalmi"]],
 "11": [["Juupajoki","Vilppula","Haapamäki","Pihlajavesi","Myllymäki","Eläinpuisto-Zoo","Ähtäri","Tuuri","Alavus"]],
 "12": [["Kouvola","Myllykoski","Inkeroinen","Tavastila","Kymi","Kyminlinna","Paimenportti","Kotka","Kotkan satama"]],
 "12A":[["Riihimäki","Hikiä","Oitti","Mommila","Lappila","Järvelä","Herrala","Lahti"],
        ["Kouvola","Myllykoski","Inkeroinen","Tavastila","Kymi","Kyminlinna","Paimenportti","Kotka","Kotkan satama"]],
 "13": [["Mäntyharju","Mikkeli","Suonenjoki","Kuopio","Siilinjärvi","Lapinlahti","Iisalmi","Sukeva","Kajaani","Kontiomäki","Paltamo","Vaala","Utajärvi","Muhos"]],
 "14": [["Lappeenranta","Joutseno","Imatra","Simpele","Parikkala","Kesälahti","Kitee","Joensuu","Lieksa","Nurmes"]],
 "14A":[["Joensuu","Eno","Uimaharju","Vuonislahti","Lieksa","Kylänlahti","Höljäkkä","Kohtavaara","Nurmes"]],
 "15": [["Lahti","Riihimäki"]],
 "16": [["Turku satama","Turku","Loimaa","Humppila"],["Riihimäki","Lahti"]],
 "17": [["Seinäjoki","Vaasa"],["Alavus","Tuuri","Ähtäri","Myllymäki","Pihlajavesi","Haapamäki","Keuruu","Petäjävesi","Jyväskylä"],
        ["Pieksämäki","Varkaus","Heinävesi","Vihtari","Viinijärvi","Joensuu"]],
 "18": [["Iisalmi","Runni","Kiuruvesi","Pyhäsalmi","Haapajärvi","Nivala","Ylivieska"]],
 "19": [["Parikkala","Punkaharju","Lusto","Retretti","Kerimäki","Savonlinna"]],
 "30": [["Kemi","Tornio-Itäinen","Tornio","Haaparanta pohjoinen"]],
}
def reverse_route(r, title):
    """Reverse a one-direction table: km from the other end, arrival/departure pairs keep
    'arrival first', feeder rows become onward-connection rows (.o) and vice versa."""
    rows=list(reversed(r["rows"]))
    total=max(x["km"] for x in rows if not x["conn"] and x["km"] is not None)
    out=[]
    for x in rows:
        y=dict(x)
        if not x["conn"] and x["km"] is not None:
            y["km"]=total-x["km"]
        if x["conn"]:
            y["arr"]=not x["arr"]
        out.append(y)
    # restore "arrival row, connections, departure row" order for split stations
    main=[i for i,x in enumerate(out) if not x["conn"]]
    for a,b in zip(main,main[1:]):
        if out[a]["code"]==out[b]["code"]:
            out[a]["arr"],out[b]["arr"]=True,False
        elif out[a]["arr"] and not (a>0 and out[a-1]["code"]==out[a]["code"]):
            out[a]["arr"]=False
    out[main[-1]]["arr"]=True
    out[main[0]]["arr"]=False
    return {"id":r["id"],"title_fi":title,"rows":out}

def fix_19(r, forward):
    rows=[x for x in r["rows"] if not x["conn"]]
    sl={"code":code["Savonlinna"],"km":59 if forward else 0,"arr":forward,"conn":False}
    if forward:
        rows=[x for x in rows if x["code"] in (code["Parikkala"],code["Punkaharju"],code["Lusto"],code["Retretti"],code["Kerimäki"])]+[sl]
        title="Parikkala - Savonlinna"
    else:
        rows=[sl]+[x for x in rows if x["code"] in (code["Parikkala"],code["Punkaharju"],code["Lusto"],code["Retretti"],code["Kerimäki"])]
        for x in rows[1:]:
            x["km"]=59-([y for y in raw if y["id"]=="19"][0]["rows"][[z["code"] for z in [y for y in raw if y["id"]=="19"][0]["rows"]].index(x["code"])]["km"] or 0)
        title="Savonlinna - Parikkala"
    for x in rows: x["arr"]=False
    rows[-1]["arr"]=True
    return {"id":"19","title_fi":title,"rows":rows}

# add missing reverse directions (printed in the lower half of the same booklet page)
ids=[r["id"] for r in raw]
extra=[]
for r in raw:
    if ids.count(r["id"])==1 and r["id"] in ("1","30"):
        pass
raw2=[]
for r in raw:
    if r["id"]=="19":
        raw2.append(fix_19(r, r["title_fi"].startswith("Parikkala")))
        continue
    raw2.append(r)
    if r["id"]=="1":
        raw2.append(reverse_route(r,"Turku - Helsinki"))
raw=raw2

missing=set()
out=[]
for r in raw:
    rows=r["rows"]
    if r["id"]=="30":   # booklet: Tornio by bus; today the railway runs Oulu - Kemi - Tornio - Haaparanta
        rows=[x for x in rows if not x["conn"] or True]
        rows=rows+[{"code":code["Tornio-Itäinen"],"km":130,"arr":False,"conn":False},
                   {"code":code["Tornio"],"km":132,"arr":False,"conn":False},
                   {"code":code["Haaparanta pohjoinen"],"km":135,"arr":True,"conn":False}]
        r["title_fi"]="Oulu - Kemi - Tornio - Haaparanta"
        r["rows"]=rows
    groups=[]
    rowcodes={x["code"] for x in r["rows"] if not x["conn"]}
    for g in G[r["id"]]:
        cs=[code[n] for n in g if n in code and code[n] in rowcodes]
        missing|={n for n in g if n not in code}
        groups.append(cs)
    out.append({"table_id":r["id"],"title_fi":r["title_fi"],"title_sv":sv(r["title_fi"]),
                "filter_groups":groups, "include_commuter": True,
                "rows":[{"station":x["code"],"km":x["km"],"arrival":x["arr"],"connection":x["conn"]} for x in rows]})
print("filter names not in feed:", sorted(missing))
# table 30 return direction
t30=[o for o in out if o["table_id"]=="30"][0]
rev=reverse_route({"id":"30","rows":[{"code":x["station"],"km":x["km"],"arr":x["arrival"],"conn":x["connection"]} for x in t30["rows"]]},
                  "Haaparanta - Tornio - Kemi - Oulu")
out.insert(out.index(t30)+1,{"table_id":"30","title_fi":rev["title_fi"],"title_sv":sv(rev["title_fi"]),
    "filter_groups":t30["filter_groups"],"include_commuter":True,
    "rows":[{"station":x["code"],"km":x["km"],"arrival":x["arr"],"connection":x["conn"]} for x in rev["rows"]]})
json.dump(out,open(OUT,"w"),ensure_ascii=False,indent=1)
for o in out: print(o["table_id"], "|", o["title_fi"], "|", o["title_sv"])
