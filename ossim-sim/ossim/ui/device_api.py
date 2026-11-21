"""Dashboard API for device and disk scheduling experiments."""
from __future__ import annotations
from typing import Any
from ossim.managers.device import DeviceManager
from ossim.ui.memory_api import valid_stop

def handle(path:str,body:dict[str,Any]):
    if path!='/api/device/run':return 404,{'errors':['unknown endpoint']}
    stop=body.get('stop')
    if stop is not None and not valid_stop(stop):return 422,{'errors':['stop must contain positive integer max_time and/or max_events']}
    dm=DeviceManager();err=dm.configure({k:body[k] for k in ('queue_policy','disk_policy','service_ticks','disk_cylinders','disk_head','scan_direction','seed') if k in body})
    if err:return 422,{'errors':err}
    err=dm.load(body.get('requests'))
    if err:return 422,{'errors':err}
    events=dm.run(stop)
    return 200,{'events':[e.to_dict() for e in events],'snapshot':dm.snapshot(),'metrics':dm.metrics(),'warnings':dm.validate(),'csv':dm.export('csv')}
