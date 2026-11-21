"""Dashboard API for packet-network experiments."""
from __future__ import annotations
from typing import Any
from ossim.managers.network import NetworkManager
from ossim.ui.memory_api import valid_stop

def handle(path:str,body:dict[str,Any]):
    if path!='/api/network/run':return 404,{'errors':['unknown endpoint']}
    stop=body.get('stop')
    if stop is not None and not valid_stop(stop):return 422,{'errors':['stop must contain positive integer max_time and/or max_events']}
    nm=NetworkManager();err=nm.configure({k:body[k] for k in ('queue_policy','link_delay_ticks','buffer_capacity','packet_ticks','seed') if k in body})
    if err:return 422,{'errors':err}
    scenario={k:body[k] for k in ('nodes','links','packets') if k in body}
    err=nm.load(scenario)
    if err:return 422,{'errors':err}
    events=nm.run(stop)
    return 200,{'events':[e.to_dict() for e in events],'snapshot':nm.snapshot(),'metrics':nm.metrics(),'warnings':nm.validate(),'csv':nm.export('csv')}
