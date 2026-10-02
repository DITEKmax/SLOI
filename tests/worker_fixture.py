import json
import sys
from multiprocessing.shared_memory import SharedMemory

import numpy as np


def emit(data):
    print(json.dumps(data), flush=True)


emit({'kind':'ready','pid':__import__('os').getpid(),'python':sys.version.split()[0]})
for line in sys.stdin:
    data=json.loads(line)
    if data['command']=='load':
        emit({'id':data['id'],'ok':True,'metadata':{'runtime':'test-process-not-asr'}})
    elif data['command']=='recognize':
        shared=data['shared']
        memory=SharedMemory(name=shared['name'],track=False)
        try:
            wave=np.ndarray((shared['samples'],),dtype=np.float32,buffer=memory.buf)
            count=len(shared['slices'])
            values=[float(wave[offset]) for offset,length in shared['slices']]
            del wave
        finally:
            memory.close()
        emit({'id':data['id'],'ok':True,'results':[{'text':f'IPC TEST {value}', 'language':None,'language_origin':None,'warnings':[]} for value in values]})
    elif data['command']=='quit':
        break
