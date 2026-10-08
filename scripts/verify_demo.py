"""Actual-process end-to-end verification. Saves real reports and restarts platform."""
import json
import os
import socket
import subprocess
import sys
import time
import shutil
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from services.scenarios import demo_target


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


def launch(module, number):
    log=(ROOT/'outputs'/'verification').joinpath(f'{number}.log')
    log.parent.mkdir(parents=True,exist_ok=True)
    handle=log.open('a',encoding='utf-8')
    env=dict(os.environ,LAB_DATA_DIR=str(ROOT/'outputs'/'verification'/'lab'))
    process=subprocess.Popen([sys.executable,'-m','uvicorn',module,'--app-dir',str(ROOT/'backend'),'--host','127.0.0.1','--port',str(number)],cwd=ROOT,env=env,stdout=handle,stderr=handle)
    base=f'http://127.0.0.1:{number}'
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            if httpx.get(base+'/api/health',timeout=1).status_code==200:return process,handle,base
        except httpx.HTTPError:pass
        if process.poll() is not None:raise RuntimeError(f'Server stopped. Read {log}')
        time.sleep(.1)
    raise RuntimeError(f'Server did not start. Read {log}')


def main():
    processes=[]
    try:
        demo,log,demo_base=launch('examples.campushelp.app:app',port());processes.append((demo,log))
        app_port=port()
        platform,log,base=launch('app:app',app_port);processes.append((platform,log))
        ids=[];results=[]
        with httpx.Client(base_url=base,timeout=10) as client:
            def call(path,body=None):
                r=client.post(path,json=body) if body is not None else client.get(path)
                r.raise_for_status();return r.json()
            for mode in ['weak','hardened']:
                target=call('/api/targets',demo_target(demo_base+'/api/chat',mode))
                questions=call(f"/api/targets/{target['id']}/clarifications")
                assert not any(q['essential'] for q in questions['questions'])
                recommendation=call(f"/api/targets/{target['id']}/recommendation")
                request={'target_id':target['id'],'exploration':50,'mode':'offline','limits':{'requests_per_second':20}}
                estimate=call('/api/estimate',request);assert estimate['can_start']
                run=call('/api/runs',request);ids.append(run['id'])
                call(f"/api/runs/{run['id']}/start",{})
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    run=call(f"/api/runs/{run['id']}")
                    if run['report']:break
                    time.sleep(.1)
                assert run['status']=='completed',run.get('error')
                assert run['report']['counts']['FAIL']==(8 if mode=='weak' else 0)
                results.append({'mode':mode,'run_id':run['id'],'counts':run['report']['counts'],'usage':run['usage'],'recommended_before':recommendation['exploration'],'next_recommended':run['report']['next_run']['exploration']})
                print(json.dumps(results[-1]),flush=True)
            comparison=call(f'/api/compare?first={ids[0]}&second={ids[1]}')
            assert len(comparison['resolved'])==8
        platform.terminate();platform.wait(timeout=5)
        restarted,log,base=launch('app:app',app_port);processes.append((restarted,log))
        for id in ids:
            report=httpx.get(base+f'/api/runs/{id}/report').json()
            assert report['run_id']==id
        summary={'actual_http_execution':True,'history_loaded_after_process_restart':True,'results':results,'comparison':comparison}
        path=ROOT/'outputs'/'verification'/'summary.json';path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        if '--seed-workspace' in sys.argv:
            from database.store import Store
            source=Store(ROOT/'outputs'/'verification'/'lab'/'lab.sqlite3')
            destination=Store(ROOT/'outputs'/'lab'/'lab.sqlite3')
            for id in ids:
                run=source.get('run',id)
                destination.put('target',run['target']['id'],run['target'])
                destination.put('run',id,run)
                for event in source.events(id):
                    event.pop('seq',None)
                    destination.event(id,event)
                shutil.copytree(ROOT/'outputs'/'verification'/'lab'/'reports'/id, ROOT/'outputs'/'lab'/'reports'/id, dirs_exist_ok=True)
            print('Actual verified reports saved in the default outputs/lab workspace.',flush=True)
        print(f'Verified. Summary: {path}',flush=True)
    finally:
        for process,handle in processes:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
            handle.close()


if __name__=='__main__':main()
