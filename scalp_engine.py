"""Isolated synthetic long/short experiment; public spot proxy, NO real orders."""
import copy, json, math, os, threading, time, urllib.request, urllib.parse
from pathlib import Path

CONFIG = dict(initial=200., leverage=20., margin=20., fee=.0005, slip=.0002,
              maintenance=.005, liquidation_fee=.005, funding_8h=.0001,
              stop_fraction=.003, target_fraction=.006, max_hold=900, poll=5)
PAIRS={'BTC/EUR':'XBTEUR','ETH/EUR':'ETHEUR'}
FILE=Path(os.environ.get('SCALP_DATA_DIR',str(Path(__file__).resolve().parent)))/'simulation_rapide_200.json'
LOCK=threading.Lock()
VIEW={'updated':0,'error':'Premier relevé en attente.','equity':200.,'markets':{},'config':CONFIG}
STOP=threading.Event()

def initial():
    return dict(version=1,cash=200.,position=None,trades=[],seen={},peak=200.,drawdown=0.,
                last_poll=0.,gaps=0,cooldown_until=0.,events=[])

def save(s):
    FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=FILE.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(s,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,FILE)

def load():
    if not FILE.exists():return initial()
    s=json.loads(FILE.read_text(encoding='utf-8'))
    if not isinstance(s,dict) or not initial().keys()<=s.keys() or s['version']!=1:
        raise ValueError('Sauvegarde rapide incompatible : arrêt sans remise à zéro.')
    if not math.isfinite(s['cash']) or s['cash']<0:raise ValueError('Solde rapide invalide.')
    return s

def api(endpoint,**params):
    req=urllib.request.Request('https://api.kraken.com/0/public/'+endpoint+'?'+urllib.parse.urlencode(params),headers={'User-Agent':'CryptoLabSynthetic/1'})
    with urllib.request.urlopen(req,timeout=8) as response:d=json.load(response)
    if d.get('error'):raise ValueError('; '.join(d['error']))
    return d['result']

def check_rows(rows,now):
    if len(rows)<22:raise ValueError(f'Bougies insuffisantes : {len(rows)}/22.')
    for r in rows:
        if len(r)!=7 or not all(math.isfinite(x) for x in r):raise ValueError('Bougie invalide : format ou nombre non fini.')
        # VWAP (index 5) is not an OHLC price and is unused by the strategy.
        # Allow a zero VWAP only when volume is zero; retain all OHLC checks.
        stamp,op,hi,lo,cl,vwap,volume=r
        if min(op,hi,lo,cl)<=0 or hi<max(op,lo,cl) or lo>min(op,cl):
            raise ValueError(f'Prix OHLC invalide à {stamp:g} : O={op}, H={hi}, L={lo}, C={cl}.')
        if volume<0 or vwap<0 or (volume>0 and vwap==0):
            raise ValueError(f'Volume/VWAP invalide à {stamp:g} : volume={volume}, VWAP={vwap}.')
    age=now-(rows[-1][0]+60)
    if not 0<=age<75:raise ValueError(f'Bougies 1 min périmées : âge après clôture {age:.0f} s (limite 75 s).')
    if any(b[0]-a[0]!=60 for a,b in zip(rows[-22:-1],rows[-21:])):raise ValueError('Bougies discontinues.')

class Feed:
    def __init__(self):self.cache={};self.bucket=None
    def read(self):
        start=time.time();bucket=int(start//60)
        if bucket!=self.bucket or not self.cache or any(not 0<=start-(r[-1][0]+60)<75 for r in self.cache.values()):
            fresh={}
            for n,pair in PAIRS.items():
                d=api('OHLC',pair=pair,interval=1)
                rows=next(v for k,v in d.items() if k!='last')
                fresh[n]=[[float(x) for x in r[:7]] for r in rows[:-1]][-60:]
            for name, rows in fresh.items():
                try:check_rows(rows,time.time())
                except ValueError as exc:raise ValueError(name+' : '+str(exc)) from exc
            self.cache=fresh;self.bucket=bucket
        # One ticker request for both markets; keys are explicit internal Kraken names.
        ticks=api('Ticker',pair=','.join(PAIRS.values()))
        keys={'BTC/EUR':'XXBTZEUR','ETH/EUR':'XETHZEUR'}
        now=time.time()
        if now-start>10:raise ValueError('Collecte trop lente : pas de simulation sur cours décalés.')
        out={}
        for n,key in keys.items():
            rows=self.cache[n];check_rows(rows,now)
            t=ticks.get(key) or ticks.get(PAIRS[n])
            if not t:raise ValueError('Cotation manquante : '+n)
            bid,ask=float(t['b'][0]),float(t['a'][0])
            if not all(math.isfinite(v) and v>0 for v in (bid,ask)) or ask<bid:raise ValueError('Cotation invalide.')
            out[n]=dict(rows=rows,bid=bid,ask=ask,mark=(bid+ask)/2)
        return out

def signal(rows):
    closes=[r[4] for r in rows]
    fast=sum(closes[-6:])/6;slow=sum(closes[-20:])/20
    vol=rows[-1][6]>1.2*sum(r[6] for r in rows[-11:-1])/10
    up=closes[-1]>max(r[2] for r in rows[-11:-1])
    down=closes[-1]<min(r[3] for r in rows[-11:-1])
    side='LONG' if fast>slow and up and vol else 'SHORT' if fast<slow and down and vol else None
    return side,dict(trend='hausse' if fast>slow else 'baisse' if fast<slow else 'neutre',breakout=up or down,volume=vol)

def funding(p,now):return p['notional']*CONFIG['funding_8h']*max(0,now-p['opened'])/28800

def liquidation(p,now):
    q=p['qty'];e=p['entry'];m=p['margin'];f=funding(p,now)
    rate=CONFIG['maintenance']+CONFIG['liquidation_fee']
    return (q*e-m+f)/(q*(1-rate)) if p['side']=='LONG' else (m+q*e-f)/(q*(1+rate))

def valuation(p,quote,now,liquidated=False):
    sign=1 if p['side']=='LONG' else -1
    reference=quote['bid'] if sign==1 else quote['ask']
    exit_price=reference*(1-sign*CONFIG['slip'])
    gross=sign*p['qty']*(exit_price-p['entry'])
    exit_fee=p['qty']*exit_price*CONFIG['fee'];fin=funding(p,now)
    penalty=p['qty']*exit_price*CONFIG['liquidation_fee'] if liquidated else 0.
    raw=p['margin']+gross-exit_fee-fin-penalty
    returned=max(0.,raw)  # synthetic isolated margin with a zero floor, not a broker promise
    return dict(exit=exit_price,gross=gross,entry_fee=p['entry_fee'],exit_fee=exit_fee,
                funding=fin,liquidation_fee=penalty,returned=returned,
                floor_adjustment=max(0.,-raw),net=returned-p['margin']-p['entry_fee'])

def step(original,quotes,now):
    s=copy.deepcopy(original);events=[];markets={}
    p=s['position'];equity=s['cash']
    if p:equity+=valuation(p,quotes[p['asset']],now)['returned']
    s['peak']=max(s['peak'],equity);s['drawdown']=max(s['drawdown'],1-equity/s['peak'])
    if s['last_poll'] and now-s['last_poll']>20:
        s['gaps']+=1;events.append('Interruption : passages intermédiaires au stop non reconstruits.')
    if p:
        q=quotes[p['asset']];sign=1 if p['side']=='LONG' else -1
        close_quote=q['bid'] if sign==1 else q['ask']
        liq=liquidation(p,now)
        hit_liq=q['mark']<=liq if sign==1 else q['mark']>=liq
        reason=('liquidation simulée' if hit_liq else 'stop' if sign*(close_quote-p['stop'])<=0
                else 'objectif' if sign*(close_quote-p['target'])>=0 else '15 minutes' if now-p['opened']>=CONFIG['max_hold'] else '')
        if reason:
            v=valuation(p,q,now,hit_liq)
            trade={**p,**v,'closed':now,'reason':reason,'gaps_during_trade':s['gaps']-p['gaps_at_open']}
            s['cash']+=v['returned'];s['trades'].append(trade);s['position']=None
            s['cooldown_until']=now+60
            events.append(f"SORTIE {p['side']} {p['asset']} : {v['net']:+.2f} € nets ({reason})")
    for name,q in quotes.items():
        side,criteria=signal(q['rows']);stamp=q['rows'][-1][0]
        fresh=s['seen'].get(name)!=stamp;s['seen'][name]=stamp
        action='ATTENDRE';why='Critères non réunis.'
        if s['drawdown']>=.10:why='Nouvelles entrées suspendues : baisse maximale ≥ 10 %.'
        elif s['position']:why='Une position est déjà ouverte.'
        elif now<s['cooldown_until']:why='Pause de 60 secondes après une sortie.'
        elif not fresh:why='Bougie déjà évaluée ; attente de la prochaine clôture.'
        elif side:
            sign=1 if side=='LONG' else -1
            ref=q['ask'] if sign==1 else q['bid'];entry=ref*(1+sign*CONFIG['slip'])
            margin=CONFIG['margin'];notional=margin*CONFIG['leverage'];qty=notional/entry;fee=notional*CONFIG['fee']
            if (q['ask']-q['bid'])/q['mark']>.001:why='Écart achat/vente trop large.'
            elif abs(entry/q['rows'][-1][4]-1)>.003:why='Prix trop éloigné de la clôture du signal.'
            elif s['cash']<margin+fee:why='Solde insuffisant pour marge et frais.'
            else:
                s['cash']-=margin+fee
                s['position']=dict(asset=name,side=side,entry=entry,qty=qty,margin=margin,notional=notional,
                    entry_fee=fee,opened=now,stop=entry*(1-sign*CONFIG['stop_fraction']),
                    target=entry*(1+sign*CONFIG['target_fraction']),gaps_at_open=s['gaps'])
                action='ENTRÉE '+side+' SIMULÉE';why='Tendance, cassure et volume réunis.'
                events.append(action+' '+name)
        markets[name]=dict(bid=q['bid'],ask=q['ask'],mark=q['mark'],criteria=criteria,action=action,reason=why)
    p=s['position'];equity=s['cash'];position=None
    if p:
        v=valuation(p,quotes[p['asset']],now);equity+=v['returned']
        position={**p,**v,'leverage':p['notional']/p['margin'],'liquidation_estimate':liquidation(p,now),'remaining_seconds':max(0,CONFIG['max_hold']-(now-p['opened']))}
        markets[p['asset']]['action']='POSITION '+p['side']
        markets[p['asset']]['reason']='Sortie au stop, à l’objectif, à la liquidation ou après 15 min.'
    s['peak']=max(s['peak'],equity);s['drawdown']=max(s['drawdown'],1-equity/s['peak']);s['last_poll']=now
    s['events']=(s['events']+[{'time':now,'text':e} for e in events])[-40:]
    public=dict(updated=now,error='',equity=equity,cash=s['cash'],net=equity-200.,drawdown=s['drawdown'],
                position=position,markets=markets,trades=s['trades'][-100:],trade_count=len(s['trades']),
                events=s['events'],gaps=s['gaps'],config=CONFIG)
    return s,public

def snapshot():
    with LOCK:d=copy.deepcopy(VIEW)
    d['stale']=bool(d['error']) or time.time()-d['updated']>20
    return d

def loop():
    global VIEW
    try:s=load()
    except Exception as exc:
        with LOCK:VIEW['error']=str(exc)
        return
    feed=Feed()
    while not STOP.is_set():
        started=time.monotonic()
        try:
            quotes=feed.read();candidate,data=step(s,quotes,time.time());save(candidate);s=candidate
            with LOCK:VIEW=data
        except Exception as exc:
            with LOCK:VIEW={**VIEW,'error':str(exc)}
        STOP.wait(max(1,CONFIG['poll']-(time.monotonic()-started)))
