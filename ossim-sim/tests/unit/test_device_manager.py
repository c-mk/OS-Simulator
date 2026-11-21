from ossim.managers.device import DeviceManager
from ossim.ui.device_api import handle

def test_device_types_disk_policies_metrics_and_failure():
    dm=DeviceManager();assert dm.configure({'disk_policy':'sstf','disk_head':50})==[]
    assert dm.load([{'id':'d1','device':'disk','cylinder':90},{'id':'d2','device':'disk','cylinder':55},{'id':'p1','device':'printer'},{'id':'k1','device':'keyboard','failed':True}])==[]
    ev=dm.run();assert any(e.event_type=='DEVICE_FAILURE' for e in ev)
    assert len(dm.snapshot()['requests'])==4
    assert dm.metrics()['requests']['value']==4
    assert dm.metrics()['disk_head_movement']['value']==40

def test_device_api_validation_and_csv():
    code,out=handle('/api/device/run',{'requests':[{'device':'disk','cylinder':60}]})
    assert code==200 and 'disk' in out['snapshot']['devices'] and out['csv'].startswith('id,pid')
    assert handle('/api/device/run',{'requests':[{'device':'phone'}]})[0]==422
