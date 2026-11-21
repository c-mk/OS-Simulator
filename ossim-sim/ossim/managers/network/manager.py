"""Deterministic packet-network simulator with routing, queues, buffers and failures."""
from __future__ import annotations
import csv,io,json,heapq
from pathlib import Path
from ossim.core.events import Event,TICKS_PER_MS
from ossim.managers.base import Manager
QUEUE_POLICIES=('fifo','priority')
DEFAULTS={'queue_policy':'fifo','link_delay_ticks':5,'buffer_capacity':4,'packet_ticks':1,'seed':0}
def _int(v):return isinstance(v,int) and not isinstance(v,bool)
class NetworkManager(Manager):
    name='network'
    def __init__(self):self.config=dict(DEFAULTS);self.topology={'nodes':[],'links':[]};self.packets=[];self.reset()
    def configure(self,config):
        m={**self.config,**config};e=[f"unknown setting {k!r}" for k in config if k not in DEFAULTS]
        if m['queue_policy'] not in QUEUE_POLICIES:e.append(f"queue_policy must be one of {', '.join(QUEUE_POLICIES)}")
        for k in ('link_delay_ticks','packet_ticks','buffer_capacity'):
            if not _int(m[k]) or m[k]<1:e.append(f'{k} must be a positive integer')
        if e:return e
        self.config=m;self.reset();return []
    def load(self,data):
        if isinstance(data,(str,Path)):
            try:data=json.loads(Path(data).read_text())
            except Exception as ex:return [f'cannot load network scenario: {ex}']
        if not isinstance(data,dict):return ['network scenario must be an object']
        nodes,links,packets=data.get('nodes'),data.get('links'),data.get('packets',[])
        if not isinstance(nodes,list) or not nodes or not all(isinstance(n,str) and n for n in nodes):return ['nodes must be a non-empty list of names']
        if len(set(nodes))!=len(nodes):return ['node names must be unique']
        if not isinstance(links,list) or not isinstance(packets,list) or not packets:return ['links must be a list and packets must be a non-empty list']
        ls=[];ps=[];err=[]
        for i,l in enumerate(links,1):
            if not isinstance(l,dict) or l.get('from') not in nodes or l.get('to') not in nodes or l.get('from')==l.get('to'):err.append(f'Link {i}: invalid endpoints');continue
            delay=l.get('delay',self.config['link_delay_ticks']);cap=l.get('capacity',self.config['buffer_capacity'])
            if not _int(delay) or delay<1 or not _int(cap) or cap<1:err.append(f'Link {i}: delay and capacity must be positive integers');continue
            ls.append({'from':l['from'],'to':l['to'],'delay':delay,'capacity':cap,'failed':bool(l.get('failed',False))})
        for i,p in enumerate(packets,1):
            if not isinstance(p,dict) or p.get('source') not in nodes or p.get('destination') not in nodes or p.get('source')==p.get('destination'):err.append(f'Packet {i}: invalid source or destination');continue
            at=p.get('at',0);pr=p.get('priority',0)
            if not _int(at) or at<0 or not _int(pr):err.append(f'Packet {i}: at and priority must be integers');continue
            ps.append({'id':str(p.get('id',f'PKT{i}')),'source':p['source'],'destination':p['destination'],'at':at,'priority':pr})
        if err:return err
        self.topology={'nodes':list(nodes),'links':ls};self.packets=ps;self.reset();return []
    def reset(self):self.clock=0;self.events=[];self.history=[];self.seq=0
    def _emit(self,t,p,typ,prev,new,outcome,cost=0,msg='',severity='info'):
        self.seq+=1;self.events.append(Event(self.seq,t,'','', 'network',typ,p['id'],typ.lower(),prev,new,outcome,cost,severity,msg))
    def _route(self,src,dst):
        g={n:[] for n in self.topology['nodes']}
        for i,l in enumerate(self.topology['links']):
            if not l['failed']:g[l['from']].append((l['to'],l['delay'],i));g[l['to']].append((l['from'],l['delay'],i))
        dist={src:0};prev={};heap=[(0,src)]
        while heap:
            d,u=heapq.heappop(heap)
            if d!=dist[u]:continue
            if u==dst:break
            for v,w,i in g[u]:
                nd=d+w
                if nd<dist.get(v,float('inf')):dist[v]=nd;prev[v]=(u,i);heapq.heappush(heap,(nd,v))
        if dst not in dist:return None
        path=[];cur=dst
        while cur!=src:u,i=prev[cur];path.append((u,cur,i));cur=u
        return list(reversed(path))
    def step(self,event=None):return []
    def run(self,stop=None):
        self.reset();stop=stop or {};link_available={i:0 for i in range(len(self.topology['links']))}
        # Simultaneous packet requests are ordered by selected queue policy.
        ps=sorted(self.packets,key=lambda p:(p['at'],-p['priority'] if self.config['queue_policy']=='priority' else 0,p['id']))
        for p in ps:
            route=self._route(p['source'],p['destination'])
            if route is None:self._emit(p['at'],p,'PACKET_DROP','created','dropped','failed',0,'no route available','warning');self.history.append({**p,'status':'dropped','route':[],'arrival':None});continue
            t=p['at'];path=[p['source']];dropped=False
            for a,b,i in route:
                l=self.topology['links'][i]
                service=l['delay']+self.config['packet_ticks'];available=link_available[i]
                waiting=max(0,(available-t+service-1)//service) if available>t else 0
                if waiting>=l['capacity']:self._emit(t,p,'PACKET_DROP','queued','dropped','failed',0,f'buffer full on {a}-{b}','warning');dropped=True;break
                self._emit(t,p,'PACKET_ENQUEUE','created','queued','ok',0,f'{a} -> {b} ({self.config["queue_policy"]}); queued {waiting}')
                start=max(t,available);t=start+service;link_available[i]=t;path.append(b)
                self._emit(t,p,'PACKET_FORWARD','queued','forwarded','ok',service,f'forwarded {a} -> {b}')
            status='dropped' if dropped else 'delivered'
            if not dropped:self._emit(t,p,'PACKET_DELIVER','forwarded','delivered','ok',0,f'delivered to {p["destination"]}')
            self.history.append({**p,'status':status,'route':path,'arrival':None if dropped else t})
        if stop.get('max_time') is not None:self.events=[e for e in self.events if e.time<=stop['max_time']]
        if stop.get('max_events') is not None:self.events=self.events[:stop['max_events']]
        self.events.sort(key=lambda e:(e.time,e.seq))
        self.clock=max((e.time for e in self.events),default=0);return list(self.events)
    def snapshot(self):return {'clock':self.clock,'config':dict(self.config),'topology':self.topology,'packets':self.history,'failed_links':[[l['from'],l['to']] for l in self.topology['links'] if l['failed']]}
    def metrics(self):
        n=len(self.history);d=sum(p['status']=='delivered' for p in self.history);delays=[p['arrival']-p['at'] for p in self.history if p['arrival'] is not None];v={'packets':(n,'count'),'delivered':(d,'count'),'dropped':(n-d,'count'),'delivery_rate':(round(100*d/n,2) if n else 0,'percent'),'average_delay':(round(sum(delays)/len(delays)/TICKS_PER_MS,3) if delays else 0,'ms'),'total_hops':(sum(max(0,len(p['route'])-1) for p in self.history),'count')}
        return {k:{'value':x,'unit':u} for k,(x,u) in v.items()}
    def validate(self):return (['No network topology loaded'] if not self.topology['nodes'] else [])+(['One or more links are failed; routes avoid them'] if any(l['failed'] for l in self.topology['links']) else [])
    def export(self,fmt='json'):
        if fmt=='json':return json.dumps({'snapshot':self.snapshot(),'metrics':self.metrics(),'events':[e.to_dict() for e in self.events]},indent=2)
        if fmt=='csv':
            b=io.StringIO();w=csv.writer(b);w.writerow(['id','source','destination','at','status','route','arrival'])
            for p in self.history:w.writerow([p['id'],p['source'],p['destination'],p['at'],p['status'],'->'.join(p['route']),p['arrival']])
            return b.getvalue()
        raise ValueError('export format must be json or csv')
