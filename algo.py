"""Prototype pédagogique, uniquement API publique et argent fictif. Python 3.10+."""
import json, math, os, time, threading, queue, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'simulation_v2.json'
FEE = 0.008  # hypothèse fixe prudente par côté, à revalider
SLIP = 0.001  # glissement simulé par côté, non garanti en réel
PAIRS = {'BTC/EUR': 'XBTEUR', 'ETH/EUR': 'ETHEUR'}

def initial():
    return dict(cash=500., positions={}, seen={}, trades=[], peak=500., drawdown=0., last_poll=0.)

def api(endpoint, **params):
    url = 'https://api.kraken.com/0/public/' + endpoint + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'CryptoSimulation/1.0'})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.load(response)
    if data.get('error'):
        raise ValueError('; '.join(data['error']))
    return data['result']

def market(pair):
    result = api('OHLC', pair=pair, interval=5)
    rows = next(v for k, v in result.items() if k != 'last')
    rows = [[float(x) for x in row[:7]] for row in rows[:-1]]
    now = time.time()
    if len(rows) < 55 or not 0 <= now - (rows[-1][0] + 300) < 330:
        raise ValueError('Bougies insuffisantes ou périmées : aucune opération simulée.')
    if any(b[0]-a[0] != 300 for a,b in zip(rows[-55:], rows[-54:])):
        raise ValueError('Historique discontinu : aucune opération simulée.')
    ticker = next(iter(api('Ticker', pair=pair).values()))
    bid, ask = float(ticker['b'][0]), float(ticker['a'][0])
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask)) or ask < bid:
        raise ValueError('Cotation invalide.')
    if any(not all(math.isfinite(v) for v in r) or r[4] <= 0 for r in rows):
        raise ValueError('Bougies invalides.')
    return rows, bid, ask

def signal(rows):
    closes = [r[4] for r in rows]
    short, long = sum(closes[-20:])/20, sum(closes[-50:])/50
    breakout = closes[-1] > max(r[2] for r in rows[-21:-1])
    volume = rows[-1][6] > 1.5 * sum(r[6] for r in rows[-21:-1])/20
    atr = sum(max(rows[i][2]-rows[i][3], abs(rows[i][2]-rows[i-1][4]),
                  abs(rows[i][3]-rows[i-1][4])) for i in range(len(rows)-14,len(rows)))/14
    return short > long and breakout and volume, atr, f'Tendance {"OK" if short > long else "non"} · Cassure {"OK" if breakout else "non"} · Volume {"OK" if volume else "non"}'

def step(s, name, rows, bid, ask, now):
    messages = []
    p = s['positions'].get(name)
    if p:
        reason = ('stop observé' if bid <= p['stop'] else 'objectif observé' if bid >= p['target']
                  else 'durée de 72 h atteinte' if now-p['opened'] >= 72*3600 else '')
        if reason:
            exit_price = bid*(1-SLIP)
            proceeds = p['qty']*exit_price*(1-FEE)
            pnl = proceeds-p['cost']
            s['cash'] += proceeds
            s['trades'].append(dict(asset=name, entry=p['entry'], exit=exit_price,
                                    opened=p['opened'], closed=now, pnl=pnl, reason=reason))
            del s['positions'][name]
            messages.append(f'SORTIE FICTIVE {name} : {pnl:+.2f} € nets · {reason}')
    eligible, atr, details = signal(rows)
    stamp = rows[-1][0]
    if s['seen'].get(name) != stamp:
        s['seen'][name] = stamp
        if eligible and name not in s['positions'] and not messages and s['drawdown'] < .10:
            entry = ask*(1+SLIP)
            # Refuse une entrée trop éloignée de la clôture signal.
            distance = max(2*atr, entry*.02)
            if abs(entry/rows[-1][4]-1) < .01 and distance < entry:
                stop = entry-distance
                loss_per_unit = entry*(1+FEE)-stop*(1-SLIP)*(1-FEE)
                # 2,50 € de risque théorique et au plus 100 € engagés par actif.
                qty = min(2.5/loss_per_unit, min(100.,s['cash'])/(entry*(1+FEE)))
                if qty*entry >= 5:
                    cost = qty*entry*(1+FEE)
                    # Objectif de profit net = deux fois la perte théorique au stop.
                    target = (cost+2*qty*loss_per_unit)/(qty*(1-SLIP)*(1-FEE))
                    s['cash'] -= cost
                    s['positions'][name] = dict(qty=qty, entry=entry, cost=cost, stop=stop,
                                                target=target, opened=now)
                    messages.append(f'ENTRÉE FICTIVE {name} : {entry:.2f} € · stop {stop:.2f} · objectif {target:.2f}')
    return details, messages

def save(s):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, STATE)


def cycle(s, snapshots, now):
    """Travaille sur une copie : un échec ne modifie pas le portefeuille en mémoire."""
    import copy
    s=copy.deepcopy(s)
    warnings=[]
    if s['last_poll'] and now-s['last_poll'] > 120:
        warnings.append('Interruption de surveillance : résultats incomplets sur cette période.')
    equity=lambda: s['cash']+sum(p['qty']*snapshots[n][1]*(1-SLIP)*(1-FEE) for n,p in s['positions'].items())
    value=equity(); s['peak']=max(s['peak'],value)
    s['drawdown']=max(s['drawdown'],1-value/s['peak'])
    cards={}; alerts=[]
    for name,(rows,bid,ask) in snapshots.items():
        seen=s['seen'].get(name)==rows[-1][0]
        eligible,atr,details=signal(rows)
        _,messages=step(s,name,rows,bid,ask,now)
        alerts.extend(messages)
        position=s['positions'].get(name)
        state='ATTENDRE'; reason='Les trois critères ne sont pas réunis.'
        if position:
            state='POSITION EN COURS'; reason='Sortie au stop, à l’objectif ou après 72 h.'
            if any('ENTRÉE' in m for m in messages):
                state='ACHAT SIMULÉ'; reason='Signal confirmé : une position fictive vient d’être ouverte.'
        elif messages:
            state='VENTE SIMULÉE'; reason=messages[-1]
        elif s['drawdown']>=.10:
            state='ENTRÉES SUSPENDUES'; reason='Baisse maximale de 10 % atteinte.'
        elif eligible:
            if seen: reason='Signal de cette bougie déjà évalué. Attente de la suivante.'
            elif abs(ask*(1+SLIP)/rows[-1][4]-1)>=.01: reason='Prix trop éloigné du signal : entrée refusée.'
            elif s['cash']<5*(1+FEE): reason='Liquidités fictives insuffisantes.'
            else: reason='Entrée refusée par les limites de taille ou de risque.'
        cards[name]=dict(rows=rows,bid=bid,ask=ask,details=details,state=state,
                         reason=reason,position=position)
    value=equity(); s['peak']=max(s['peak'],value)
    s['drawdown']=max(s['drawdown'],1-value/s['peak']); s['last_poll']=now
    return s,cards,value,alerts,warnings

def run():
    import tkinter as tk
    from tkinter import ttk, messagebox
    from concurrent.futures import ThreadPoolExecutor
    import csv
    BG='#0b1020'; PANEL='#151d31'; MUTED='#98a6bd'; WHITE='#eef3ff'; GREEN='#59e3b2'; RED='#ff8198'; BLUE='#8bb7ff'
    root=tk.Tk(); root.title('Crypto Lab — simulation V2'); root.geometry('1100x850'); root.minsize(960,760); root.configure(bg=BG)
    style=ttk.Style(root); style.theme_use('clam')
    style.configure('Treeview', background=PANEL,foreground=WHITE,fieldbackground=PANEL,rowheight=28,borderwidth=0)
    style.configure('Treeview.Heading',background='#243049',foreground=WHITE,font=('Segoe UI',10,'bold'))
    def label(parent,text,size=10,color=WHITE,bg=PANEL,bold=False):
        return tk.Label(parent,text=text,font=('Segoe UI',size,'bold' if bold else 'normal'),fg=color,bg=bg,anchor='w')
    head=tk.Frame(root,bg=BG); head.pack(fill='x',padx=24,pady=(20,8))
    label(head,'CRYPTO LAB',24,bg=BG,bold=True).pack(side='left')
    label(head,'  V2  /  100 % FICTIF',11,GREEN,BG,True).pack(side='left',padx=16)
    label(root,'Cours toutes les 30 s  •  Signaux sur bougies de 5 min clôturées  •  Stratégie expérimentale',10,MUTED,BG).pack(anchor='w',padx=24)
    status=label(root,'Connexion à Kraken…',11,BLUE,BG); status.pack(fill='x',padx=24,pady=10)
    metrics=tk.Frame(root,bg=BG); metrics.pack(fill='x',padx=24)
    values=[]
    for title in ['VALEUR NETTE','RÉSULTAT NET','BAISSE MAX.','TRADES CLOS']:
        f=tk.Frame(metrics,bg=PANEL); f.pack(side='left',expand=True,fill='both',padx=(0,8),ipadx=10,ipady=8)
        label(f,title,9,MUTED).pack(anchor='w',padx=10)
        v=label(f,'—',20,bold=True);v.pack(anchor='w',padx=10);values.append(v)
    grid=tk.Frame(root,bg=BG);grid.pack(fill='x',padx=24,pady=14)
    widgets={}
    for n in PAIRS:
        f=tk.Frame(grid,bg=PANEL,padx=16,pady=12);f.pack(side='left',expand=True,fill='both',padx=(0,8))
        label(f,n,16,bold=True).pack(anchor='w')
        price=label(f,'—',24,bold=True);price.pack(anchor='w')
        action=label(f,'CONNEXION…',12,BLUE,bold=True);action.pack(anchor='w',pady=(8,4))
        why=label(f,'En attente de données publiques.',10,MUTED);why.configure(wraplength=440);why.pack(fill='x')
        chart=tk.Canvas(f,height=75,bg=PANEL,highlightthickness=0);chart.pack(fill='x',pady=6)
        label(f,'Clôtures des 40 dernières bougies de 5 min',8,MUTED).pack(anchor='w')
        criteria=label(f,'Tendance —  •  Cassure —  •  Volume —',9,MUTED);criteria.pack(anchor='w',pady=5)
        levels=label(f,'Aucune position fictive ouverte.',11);levels.configure(justify='left');levels.pack(anchor='w')
        widgets[n]=(price,action,why,chart,criteria,levels)
    bar=tk.Frame(root,bg=BG);bar.pack(fill='x',padx=24,pady=(0,8))
    label(bar,'HISTORIQUE DES SORTIES FICTIVES',10,MUTED,BG,True).pack(side='left')
    columns=('actif','entree','sortie','net','motif')
    table=ttk.Treeview(root,columns=columns,show='headings',height=4)
    for key,title,width in zip(columns,['Actif','Entrée (€)','Sortie (€)','Gain / perte net (€)','Motif'],[90,120,120,150,280]):
        table.heading(key,text=title);table.column(key,width=width,anchor='w')
    table.pack(fill='x',padx=24)
    notice=label(root,'Les alertes apparaissent ici. Aucun ordre réel ne peut être envoyé.',10,MUTED,BG)
    notice.configure(wraplength=1040,justify='left');notice.pack(fill='x',padx=24,pady=8)
    label(root,'Frais supposés : 0,8 % par côté + 0,1 % de glissement. Un signal n’est pas une garantie de gain.\nPC connecté et sans veille. Stops vérifiés aux contrôles seulement. Alertes sur PC ; téléphone non connecté.',9,MUTED,BG).pack(anchor='w',padx=24,pady=(0,8))
    try:
        s=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else initial()
        if not isinstance(s,dict) or not initial().keys()<=s.keys(): raise ValueError('Sauvegarde incompatible')
    except Exception as exc:
        messagebox.showerror('Sauvegarde',str(exc));root.destroy();return
    events=queue.Queue();stop_event=threading.Event();wake=threading.Event()
    next_at=0;busy=False;paused=False;last_ok=0;last_cards={}
    def export():
        path=ROOT/('historique_'+time.strftime('%Y%m%d_%H%M%S')+'.csv')
        try:
            with path.open('w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=['asset','entry','exit','opened','closed','pnl','reason'],delimiter=';')
                writer.writeheader();writer.writerows(s['trades'])
            messagebox.showinfo('Export',f'Historique enregistré :\n{path}')
        except OSError as exc: messagebox.showerror('Export',str(exc))
    tk.Button(bar,text='Exporter en CSV',command=export,bg=PANEL,fg=WHITE,relief='flat',padx=12).pack(side='right')
    def worker():
        while not stop_event.is_set():
            started=time.time()
            events.put(('busy',None))
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures={n:pool.submit(market,p) for n,p in PAIRS.items()}
                    snapshots={n:f.result() for n,f in futures.items()}
                if time.time()-started>25: raise ValueError('Collecte trop lente : cycle abandonné.')
                events.put(('data',snapshots))
            except Exception as exc: events.put(('error',str(exc)))
            stop_event.wait(max(1,30-(time.time()-started)))
    def draw(canvas,rows):
        canvas.delete('all');w=max(canvas.winfo_width(),360);h=70
        ys=[r[4] for r in rows[-40:]];lo=min(ys);span=max(ys)-lo
        pts=[]
        for i,y in enumerate(ys):pts.extend((4+i*(w-8)/(len(ys)-1),h-5-(y-lo)/(span or 1)*(h-12)))
        canvas.create_line(*pts,fill=GREEN if ys[-1]>=ys[0] else RED,width=2)
        canvas.create_text(w-4,5,text=f'{max(ys):.2f}',anchor='ne',fill=MUTED,font=('Segoe UI',8))
        canvas.create_text(w-4,h,text=f'{lo:.2f}',anchor='se',fill=MUTED,font=('Segoe UI',8))
    def show(cards,equity):
        for v,t in zip(values,[f'{equity:.2f} €',f'{equity-500:+.2f} €',f"{s['drawdown']:.1%}",str(len(s['trades']))]):v.configure(text=t)
        values[1].configure(fg=GREEN if equity>=500 else RED)
        for n,c in cards.items():
            price,action,why,chart,criteria,levels=widgets[n]
            price.configure(text=f"{c['ask']:,.2f} €".replace(',',' '))
            action.configure(text=c['state'],fg=GREEN if c['position'] else BLUE)
            why.configure(text=c['reason']);criteria.configure(text=c['details']);draw(chart,c['rows'])
            p=c['position']
            if p:
                net=p['qty']*c['bid']*(1-SLIP)*(1-FEE)-p['cost']
                levels.configure(text=f"Entrée {p['entry']:.2f} €   ·   Engagé {p['cost']:.2f} €\nStop {p['stop']:.2f} €   ·   Objectif {p['target']:.2f} €\nRésultat net estimé : {net:+.2f} €")
            else: levels.configure(text='Aucune position fictive ouverte.\nLes niveaux apparaîtront lors d’un achat simulé.\n')
        table.delete(*table.get_children())
        for t in reversed(s['trades'][-30:]):
            table.insert('','end',values=(t['asset'],f"{t['entry']:.2f}",f"{t['exit']:.2f}",f"{t['pnl']:+.2f}",t['reason']))
    def refresh():
        nonlocal s,next_at,busy,last_ok,last_cards,paused
        while not events.empty():
            kind,data=events.get()
            if kind=='busy': busy=True
            elif kind=='error':
                busy=False;paused=True;next_at=time.time()+30
                status.configure(text='HORS CONNEXION — aucune opération simulée',fg=RED)
                notice.configure(text=data,fg=RED)
                for ws in widgets.values():ws[1].configure(text='DONNÉES PÉRIMÉES',fg=RED)
            else:
                try:
                    candidate,cards,equity,alerts,warnings=cycle(s,data,time.time())
                    save(candidate);s=candidate
                except Exception as exc:
                    paused=True;busy=False
                    status.configure(text='SIMULATION SUSPENDUE — erreur de calcul ou de sauvegarde',fg=RED)
                    notice.configure(text=str(exc),fg=RED)
                    for ws in widgets.values():ws[1].configure(text='SIMULATION SUSPENDUE',fg=RED)
                    continue
                last_ok=time.time();next_at=last_ok+30;busy=False;paused=False;last_cards=cards
                show(cards,equity)
                if alerts or warnings:
                    notice.configure(text=time.strftime('%H:%M:%S')+' — '+' | '.join(alerts+warnings),fg=GREEN if alerts else RED)
                    if alerts:root.bell()
        if not paused:
            clock='Actualisation…' if busy else f'Prochain contrôle dans {max(0,int(next_at-time.time()))} s'
            status.configure(text=(f"Derniers cours : {time.strftime('%H:%M:%S',time.localtime(last_ok))}  •  " if last_ok else '')+clock,fg=BLUE)
        root.after(250,refresh)
    threading.Thread(target=worker,daemon=True).start()
    def close():stop_event.set();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);refresh();root.mainloop()

if __name__=='__main__':run()
