"""HTTP coverage for the device and network manager dashboard endpoints."""
import json
import threading
import urllib.error
import urllib.request
import pytest
from ossim.ui.__main__ import make_server

@pytest.fixture(scope='module')
def base():
    srv=make_server(0);threading.Thread(target=srv.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}';srv.shutdown()

def post(base,path,body):
    req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())

def test_device_and_network_endpoints(base):
    code,d=post(base,'/api/device/run',{'queue_policy':'priority','disk_policy':'sstf','requests':[
        {'id':'disk-a','device':'disk','cylinder':80,'priority':1},
        {'id':'print-a','device':'printer'}, {'id':'key-a','device':'keyboard','failed':True}]})
    assert code==200 and d['metrics']['requests']['value']==3 and d['metrics']['failures']['value']==1
    code,n=post(base,'/api/network/run',{'queue_policy':'fifo','nodes':['A','B','C'],
        'links':[{'from':'A','to':'B','delay':2},{'from':'B','to':'C','delay':2}],
        'packets':[{'id':'pkt-a','source':'A','destination':'C'}]})
    assert code==200 and n['snapshot']['packets'][0]['route']==['A','B','C']
    assert n['metrics']['delivered']['value']==1
