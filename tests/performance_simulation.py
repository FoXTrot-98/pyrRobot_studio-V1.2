"""Optional wall-time/latency probe. Run separately from integration tests."""
import argparse,json,os,socket,sys,time,statistics,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
for key in ('PYROBOT_BUS_PUB','PYROBOT_BUS_SUB'):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));os.environ[key]=f'tcp://127.0.0.1:{sock.getsockname()[1]}'
import rerun as rr
from core.runtime.session import Runtime
from core.runtime.project import ProjectDocument

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=float,default=15)
    parser.add_argument('--output',default='artifacts/performance.json')
    parser.add_argument('--explore',action='store_true')
    parser.add_argument('--targets',type=int,default=3)
    args=parser.parse_args()
    rr.init('performance-probe',spawn=False)
    samples={};latencies={};received={};lock=threading.Lock()
    document=ProjectDocument.model_validate_json((ROOT/'examples/four-wheel/teleoperation.pyrobot.json').read_text())
    with Runtime() as runtime:
        runtime.load_project(document)
        for name,entry in runtime.graph.nodes.items():
            node=entry.node_obj
            if hasattr(node,'process'):
                original=node.process
                def measured(port,payload,original=original,name=name):
                    start=time.perf_counter()
                    try:return original(port,payload)
                    finally:
                        with lock:samples.setdefault(name,[]).append(time.perf_counter()-start)
                node.process=measured
        def collect(message):
            if '/out/' not in message.topic:return
            with lock:
                received[message.topic]=message.payload
                latencies.setdefault(message.topic,[]).append(max(0,(time.time_ns()-message.timestamp.wall_ns)/1e9))
        handle=runtime.bus.subscribe('node/',collect)
        runtime.graph.start()
        if args.explore:
            runtime.graph.update_node_params('nav',{'explore':True,'exploration_targets':args.targets,'enabled':True})
            runtime.graph.update_node_params('drive',{'mode':'autonomous'})
        start=time.monotonic()
        while time.monotonic()-start<args.seconds:time.sleep(.1)
        elapsed=time.monotonic()-start
        runtime.graph.stop();handle.close()
        def summary(values):
            ordered=sorted(values)
            return dict(count=len(values),mean_ms=round(statistics.mean(values)*1000,2),p95_ms=round(ordered[min(len(ordered)-1,int(len(ordered)*.95))]*1000,2),max_ms=round(max(values)*1000,2))
        result={'wall_seconds':elapsed,'simulation_seconds':received.get('node/sim/out/truth',{}).get('time'),
                'processing':{k:summary(v) for k,v in samples.items()},'latency':{k:summary(v) for k,v in latencies.items()},
                'navigation':received.get('node/nav/out/path',{}),'truth':received.get('node/sim/out/truth',{})}
        result['navigation'].pop('points',None)
        output=ROOT/args.output;output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
