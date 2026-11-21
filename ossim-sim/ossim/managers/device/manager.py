"""Deterministic device and disk scheduling manager."""
from __future__ import annotations
import csv, io, json
from pathlib import Path
from ossim.core.events import Event, TICKS_PER_MS
from ossim.managers.base import Manager
DEVICE_TYPES=("disk","printer","keyboard")
QUEUE_POLICIES=("fcfs","priority")
DISK_POLICIES=("fcfs","sstf","scan")
DEFAULTS={"queue_policy":"fcfs","disk_policy":"sstf","service_ticks":{"disk":20,"printer":50,"keyboard":2},"disk_cylinders":200,"disk_head":50,"scan_direction":"up","seed":0}
def _int(v): return isinstance(v,int) and not isinstance(v,bool)
class DeviceManager(Manager):
    name="device"
    def __init__(self): self.config=json.loads(json.dumps(DEFAULTS)); self.requests=[]; self.reset()
    def configure(self,config):
        m={**self.config,**config}; e=[f"unknown setting {k!r}" for k in config if k not in DEFAULTS]
        if m['queue_policy'] not in QUEUE_POLICIES:e.append(f"queue_policy must be one of {', '.join(QUEUE_POLICIES)}")
        if m['disk_policy'] not in DISK_POLICIES:e.append(f"disk_policy must be one of {', '.join(DISK_POLICIES)}")
        if not _int(m['disk_cylinders']) or m['disk_cylinders']<2:e.append('disk_cylinders must be an integer of at least 2')
        if not _int(m['disk_head']) or not 0<=m['disk_head']<m['disk_cylinders']:e.append('disk_head must be within the disk')
        if m['scan_direction'] not in ('up','down'):e.append('scan_direction must be up or down')
        s=m['service_ticks']
        if not isinstance(s,dict) or set(s)-set(DEVICE_TYPES) or any(not _int(v) or v<1 for v in s.values()):e.append('service_ticks must map device types to positive integer ticks')
        if e:return e
        m['service_ticks']={**DEFAULTS['service_ticks'],**s}; self.config=m; self.reset(); return []
    def load(self,data):
        if isinstance(data,(str,Path)):
            try:data=json.loads(Path(data).read_text())
            except Exception as ex:return [f'cannot load requests: {ex}']
        if not isinstance(data,list) or not data:return ['requests must be a non-empty list']
        out=[]; errors=[]
        for i,r in enumerate(data,1):
            if not isinstance(r,dict):errors.append(f'Request {i} must be an object');continue
            typ=r.get('device'); at=r.get('at',0); pr=r.get('priority',0); cy=r.get('cylinder',self.config['disk_head'])
            if typ not in DEVICE_TYPES:errors.append(f"Request {i}: device must be one of {', '.join(DEVICE_TYPES)}");continue
            if not _int(at) or at<0 or not _int(pr) or not _int(cy) or not 0<=cy<self.config['disk_cylinders']:errors.append(f'Request {i}: at, priority and cylinder must be valid integers');continue
            out.append({'id':str(r.get('id',f'D{i}')),'pid':str(r.get('pid',f'P{i}')),'device':typ,'at':at,'priority':pr,'cylinder':cy,'failed':bool(r.get('failed',False))})
        if errors:return errors
        self.requests=out;self.reset();return []
    def reset(self):self.clock=0;self.events=[];self.history=[];self.seq=0;self.head=self.config['disk_head']
    def _emit(self,t,r,typ,prev,new,outcome,cost=0,msg='',severity='info'):
        self.seq+=1;self.events.append(Event(self.seq,t,'','', 'device',typ,r['id'],typ.lower(),prev,new,outcome,cost,severity,msg))
    def step(self,event=None):
        if event is not None:return []
        if not self.requests:return []
        if not self.events:self.run({'max_events':1})
        return self.events[:1]
    def run(self,stop=None):
        self.reset(); stop=stop or {}; scheduled=[]
        for dev in DEVICE_TYPES:
            q=[dict(r) for r in self.requests if r['device']==dev]
            if dev=='disk':
                head=self.head; direction=self.config['scan_direction']; ordered=[]
                while q:
                    eligible=[r for r in q if r['at']<=min(x['at'] for x in q)]
                    if self.config['queue_policy']=='priority':r=min(eligible,key=lambda x:(-x['priority'],x['at'],x['id']))
                    elif self.config['disk_policy']=='fcfs':r=min(eligible,key=lambda x:(x['at'],x['id']))
                    elif self.config['disk_policy']=='sstf':r=min(eligible,key=lambda x:(abs(x['cylinder']-head),x['at'],x['id']))
                    else:
                        same=[x for x in eligible if (x['cylinder']>=head if direction=='up' else x['cylinder']<=head)]
                        if not same:direction='down' if direction=='up' else 'up';continue
                        r=min(same,key=lambda x:(x['cylinder'] if direction=='up' else -x['cylinder'],x['at'],x['id']))
                    q.remove(r);r['seek']=abs(r['cylinder']-head);head=r['cylinder'];ordered.append(r)
                self.head=head;scheduled.extend(ordered)
            else:
                q.sort(key=lambda x:(x['at'],-x['priority'] if self.config['queue_policy']=='priority' else 0,x['id']));scheduled.extend(q)
        available={d:0 for d in DEVICE_TYPES}
        for r in sorted(scheduled,key=lambda x:(x['at'],x['device'],x['id'])):
            d=r['device'];start=max(r['at'],available[d]);cost=self.config['service_ticks'][d]+(r.get('seek',0) if d=='disk' else 0);end=start+cost;available[d]=end
            self._emit(start,r,'DEVICE_START','queued','active','ok',0,f"{d} request for {r['pid']}")
            outcome='failed' if r['failed'] else 'ok';typ='DEVICE_FAILURE' if r['failed'] else 'DEVICE_COMPLETE'
            self._emit(end,r,typ,'active','failed' if r['failed'] else 'complete',outcome,cost,f"{d} service {'failed' if r['failed'] else 'completed'}",'warning' if r['failed'] else 'info')
            self.history.append({**r,'start':start,'end':end,'service_ticks':cost,'outcome':outcome})
        if stop.get('max_time') is not None:self.events=[e for e in self.events if e.time<=stop['max_time']]
        if stop.get('max_events') is not None:self.events=self.events[:stop['max_events']]
        self.events.sort(key=lambda e:(e.time,e.seq))
        self.clock=max((e.time for e in self.events),default=0);return list(self.events)
    def snapshot(self):return {'clock':self.clock,'config':self.config,'devices':list(DEVICE_TYPES),'requests':self.history,'disk_head':self.head,'queues':{d:[r['id'] for r in self.requests if r['device']==d and r['id'] not in {h['id'] for h in self.history}] for d in DEVICE_TYPES}}
    def metrics(self):
        n=len(self.history);ok=sum(h['outcome']=='ok' for h in self.history);total=sum(h['service_ticks'] for h in self.history); vals={'requests':(n,'count'),'completed':(ok,'count'),'failures':(n-ok,'count'),'average_service_time':(round(total/n/TICKS_PER_MS,3) if n else 0,'ms'),'disk_head_movement':(sum(h.get('seek',0) for h in self.history),'cylinders')}
        return {k:{'value':v,'unit':u} for k,(v,u) in vals.items()}
    def validate(self):return ([] if self.requests else ['No device requests loaded'])
    def export(self,fmt='json'):
        if fmt=='json':return json.dumps({'snapshot':self.snapshot(),'metrics':self.metrics(),'events':[e.to_dict() for e in self.events]},indent=2)
        if fmt=='csv':
            b=io.StringIO();w=csv.DictWriter(b,fieldnames=['id','pid','device','at','start','end','service_ticks','cylinder','seek','outcome'],extrasaction='ignore');w.writeheader();w.writerows(self.history);return b.getvalue()
        raise ValueError('export format must be json or csv')
