import re, json, time, unicodedata, urllib.parse, urllib.request, sys
from pathlib import Path

API_KEY = sys.argv[2] if len(sys.argv) > 2 else ''
SRC = Path(sys.argv[1] if len(sys.argv)>1 else 'CanaisBR01_limpo.m3u8')
DST = SRC.with_name(SRC.stem + '_COM_CAPAS_LOGOS_CATEGORIAS.m3u8')
if not API_KEY: raise SystemExit('Uso: python enriquecer_iptv.py lista.m3u8 SUA_CHAVE_TMDB')

def get(url, tries=3):
    for n in range(tries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'IPTV-Enricher/1.0'})
            with urllib.request.urlopen(req,timeout=25) as r: return json.load(r)
        except Exception:
            if n==tries-1: return None
            time.sleep(1.5*(n+1))

def norm(s):
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\[[^]]*\]|\([^)]*\)',' ',s); s=re.sub(r'\b(fhd|uhd|hd|sd|4k|h265|hevc)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def clean_movie_title(t):
    year=None
    m=re.search(r'(?:\(|-|\s)(19\d{2}|20\d{2})(?:\)|\s|$)',t)
    if m: year=m.group(1)
    q=re.sub(r'\s*\[[^]]*\]\s*',' ',t)
    q=re.sub(r'\s*[\(\-]?\s*(?:19\d{2}|20\d{2})\s*\)?\s*$','',q).strip(' #-')
    return q,year

genres={28:'Acao',12:'Aventura',16:'Animacao',35:'Comedia',80:'Crime',99:'Documentario',18:'Drama',10751:'Familia',14:'Fantasia',36:'Historia',27:'Terror',10402:'Musica',9648:'Misterio',10749:'Romance',878:'Ficcao Cientifica',10770:'Cinema TV',53:'Suspense',10752:'Guerra',37:'Faroeste'}

def tmdb_movie(title):
    q,year=clean_movie_title(title)
    params={'api_key':API_KEY,'query':q,'language':'pt-BR','include_adult':'false'}
    if year: params['year']=year
    u='https://api.themoviedb.org/3/search/movie?'+urllib.parse.urlencode(params)
    d=get(u)
    if not d or not d.get('results'): return None
    # best candidate: year + normalized title similarity, with first result as fallback
    cand=d['results'][:5]; nq=norm(q)
    def score(x):
        s=0; nt=norm(x.get('title','')); no=norm(x.get('original_title',''))
        if nt==nq or no==nq: s+=100
        if nq in nt or nt in nq: s+=30
        if year and (x.get('release_date') or '').startswith(year): s+=25
        s+=min(float(x.get('popularity') or 0),50)/10
        return s
    x=max(cand,key=score)
    # details required to identify Marvel Studios exactly
    det=get(f"https://api.themoviedb.org/3/movie/{x['id']}?api_key={API_KEY}&language=pt-BR") or x
    poster=det.get('poster_path') or x.get('poster_path')
    logo='https://image.tmdb.org/t/p/w500'+poster if poster else ''
    is_marvel=any(c.get('id')==420 for c in det.get('production_companies',[]))
    gids=[g.get('id') for g in det.get('genres',[])] or x.get('genre_ids',[])
    cat='Producoes | Marvel Studios' if is_marvel else ('Filmes | '+genres.get(gids[0],'Outros'))
    return logo,cat

# IPTV-org: channel metadata + logos
channels=get('https://iptv-org.github.io/api/channels.json') or []
logos=get('https://iptv-org.github.io/api/logos.json') or []
logo_by_id={x.get('channel'):x.get('url') for x in logos if x.get('channel') and x.get('url')}
idx={}
for c in channels:
    if c.get('country')!='BR': continue
    for name in [c.get('name',''),c.get('alt_names','') if isinstance(c.get('alt_names'),str) else '']:
        if name: idx[norm(name)]=c

def channel_meta(title,oldgroup):
    nt=norm(title); c=idx.get(nt)
    if not c:
        best=[]
        for k,v in idx.items():
            if len(k)>=4 and (k in nt or nt in k): best.append((len(k),v))
        if best: c=max(best,key=lambda z:z[0])[1]
    logo=logo_by_id.get(c.get('id')) if c else ''
    cats=(c or {}).get('categories') or []
    mp={'sports':'Esportes','news':'Noticias','kids':'Infantil','movies':'Filmes e Series','documentary':'Documentarios','music':'Musica','religious':'Religiosos','general':'Abertos','entertainment':'Variedades'}
    cat='TV | '+mp.get(cats[0],'Outros Canais') if cats else ('TV | 24 Horas' if oldgroup=='24H' else 'TV | Infantil e Desenhos' if oldgroup=='Desenhos' else 'TV | Outros Canais')
    return logo or '',cat

lines=SRC.read_text(encoding='utf-8',errors='ignore').splitlines(); out=[lines[0] if lines else '#EXTM3U']; i=1; cache={}; total=0
while i<len(lines):
    if not lines[i].startswith('#EXTINF'): i+=1; continue
    inf=lines[i]; url=lines[i+1] if i+1<len(lines) else ''; title=inf.split(',',1)[1] if ',' in inf else ''
    gm=re.search(r'group-title="([^"]*)"',inf); old=gm.group(1) if gm else ''
    if old=='Filmes':
        key=norm(title); meta=cache.get(key)
        if meta is None: meta=tmdb_movie(title); cache[key]=meta; time.sleep(.04)
        logo,cat=meta if meta else ('','Filmes | Nao identificado')
    else: logo,cat=channel_meta(title,old)
    if gm: inf=inf[:gm.start(1)]+cat+inf[gm.end(1):]
    else: inf=inf.replace('#EXTINF:-1',f'#EXTINF:-1 group-title="{cat}"',1)
    if logo:
        if re.search(r'tvg-logo="[^"]*"',inf): inf=re.sub(r'tvg-logo="[^"]*"',f'tvg-logo="{logo}"',inf)
        else: inf=inf.replace('#EXTINF:-1',f'#EXTINF:-1 tvg-logo="{logo}"',1)
    out += [inf,url]; total+=1
    if total%250==0: print(f'{total} itens processados...')
    i+=2
DST.write_text('\n'.join(out)+'\n',encoding='utf-8')
print('PRONTO:',DST)
