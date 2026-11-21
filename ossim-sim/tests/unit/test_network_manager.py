from ossim.managers.network import NetworkManager
from ossim.ui.network_api import handle

SCENARIO={'nodes':['A','B','C','D'],'links':[{'from':'A','to':'B','delay':2},{'from':'B','to':'C','delay':2},{'from':'A','to':'D','delay':1},{'from':'D','to':'C','delay':1}],'packets':[{'id':'p1','source':'A','destination':'C'},{'id':'p2','source':'B','destination':'D'}]}
def test_routing_queue_metrics_and_failure():
    nm=NetworkManager();assert nm.load(SCENARIO)==[];events=nm.run()
    assert [p['status'] for p in nm.history]==['delivered','delivered']
    assert nm.history[0]['route']==['A','D','C']
    assert nm.metrics()['delivered']['value']==2
    broken={**SCENARIO,'links':[dict(l,failed=True) if l['from']=='A' and l['to']=='D' else l for l in SCENARIO['links']]}
    nm.load(broken);nm.run();assert nm.history[0]['route']==['A','B','C']

def test_network_api_drop_when_no_route_and_validation():
    body={'nodes':['A','B'],'links':[{'from':'A','to':'B','failed':True}],'packets':[{'source':'A','destination':'B'}]}
    code,out=handle('/api/network/run',body);assert code==200 and out['metrics']['dropped']['value']==1
    assert out['events'][0]['event_type']=='PACKET_DROP'
    assert handle('/api/network/run',{'nodes':['A'],'links':[],'packets':[]})[0]==422

def test_shared_link_buffer_overflow_drops_excess_packet():
    nm=NetworkManager();assert nm.configure({'buffer_capacity':1,'packet_ticks':2})==[]
    scenario={'nodes':['A','B'],'links':[{'from':'A','to':'B','delay':5,'capacity':1}],
              'packets':[{'id':'first','source':'A','destination':'B','at':0},
                         {'id':'second','source':'A','destination':'B','at':0}]}
    assert nm.load(scenario)==[];nm.run()
    assert [p['status'] for p in nm.history]==['delivered','dropped']
    assert any(e.event_type=='PACKET_DROP' and 'buffer full' in e.message for e in nm.events)
