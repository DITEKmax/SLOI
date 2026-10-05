"""Offline real-Chromium UI regression suite; synthetic fixtures are visibly labelled.

SLOI_CHROMIUM=/path/to/chromium python tests/browser_check.py
Optional --baseline-dist captures an untouched bundle with the same responsive matrix.
Actual API/upload processing is tested separately by browser_live.py and pytest.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (320, 390, 699, 700, 768, 999, 1000, 1024, 1199, 1200, 1366, 1600, 1920)
THEMES = ('carbon', 'paper', 'signal')


def fixture():
    return {'version': '1.0.0-rc1', 'native_available': True,
      'preferences': {'theme':'carbon','accent':'#c6f36b'}, 'defaults': {'model':'whisper','language':'ru'},
      'models':[{'id':key,'name':name,'installed':True,'note':'Тестовая карточка интерфейса'} for key,name in [('gigaam','GigaAM v3'),('qwen','Qwen3 ASR'),('whisper','Whisper RU'),('parakeet','Parakeet v3')]],
      'queue': {'active_id':'a','running':True,'pause_after_current':False,'jobs':[
        {'id':'a','source_id':'s1','name':'Лекция 07. Аналитика данных.mp4','model':'qwen','language':'ru','status':'TRANSCRIBING','duration':5538,'size':2615125000,'media_type':'video','progress':68.5,'processed_seconds':3193,'planned_seconds':4662,'elapsed_seconds':277,'speed_x':13.6,'eta_seconds':128,'speech_map':[.15 if i%29<3 else .5+.5*math.sin(i*.4)**2 for i in range(160)],'attempt':1,'audio_stream_index':1,'audio_tracks':[{'index':1,'title':'Основная речь','language':'ru','channels':2,'default':True},{'index':2,'title':'Перевод','language':'en','channels':2}]},
        {'id':'b','source_id':'s2','name':'IELTS · Speaking practice.m4a','model':'parakeet','language':'en','status':'WAITING','duration':1433,'size':35146532,'media_type':'audio','progress':None,'attempt':0,'source_upload':True},
        {'id':'c','source_id':'s3','name':'Семинар — базы данных.wav','model':'gigaam','language':'ru','status':'WAITING','duration':2944,'size':91994003,'media_type':'audio','progress':None,'attempt':0,'audio_stream_index':2,'audio_tracks':[{'index':1,'title':'Комментарий','language':'en','channels':2},{'index':2,'title':'Русская речь','language':'ru','channels':1,'default':True}]},
        {'id':'d','source_id':'s4','name':'Управление пассажирским комплексом.mp4','model':'gigaam','language':'ru','status':'COMPLETE','duration':1230,'size':10804003,'media_type':'video','progress':100,'processed_seconds':1100,'planned_seconds':1100,'elapsed_seconds':203,'speed_x':6.1,'attempt':1,'warnings':['В тестовом видео несколько дорожек; выбрана основная речь.']}
      ]},
      'telemetry':{'gpu_available':True,'gpu_name':'NVIDIA GeForce RTX 3050 Ti Laptop GPU','gpu_utilization_pct':94,'gpu_memory_used_mb':3460,'gpu_memory_total_mb':4096,'cpu_utilization_pct':31,'system_ram_used_mb':8991,'system_ram_total_mb':16384,'gpu_temperature_c':74,'gpu_power_w':51.2,'history':[{'gpu_utilization_pct':85+8*math.sin(i*.4),'gpu_memory_used_mb':3380+80*math.sin(i*.12),'cpu_utilization_pct':28+9*math.sin(i*.45)} for i in range(60)]}}


def attach(page, state, calls, errors, dist, controller, label):
    def bridge(path, options):
        method=options.get('method','GET');data=json.loads(options.get('body') or '{}')
        calls.append({'path':path,'method':method,'data':data})
        body,status={'ok':True},200
        if controller.get('offline'): status,body=503,{'message':'Тестовый разрыв соединения.'}
        elif path=='/api/session': body={'csrf':'ui-fixture-token'}
        elif path=='/api/state': body=state
        elif path=='/api/preferences': state['preferences']=data
        elif path=='/api/queue/pause': state['queue']['pause_after_current']=True
        elif path=='/api/queue/start': state['queue'].update(running=True,pause_after_current=False)
        elif path=='/api/queue/cancel':
            for j in state['queue']['jobs']:
                if j['id']==state['queue']['active_id']:j['cancelling']=True
        elif path=='/api/queue/order':
            nonwaiting=[j for j in state['queue']['jobs'] if j['status']!='WAITING'];waiting={j['id']:j for j in state['queue']['jobs'] if j['status']=='WAITING'}
            state['queue']['jobs']=nonwaiting+[waiting[i] for i in data['ids']]
        elif path.startswith('/api/results/') and path.endswith('/text'):
            status=500 if controller.get('preview_fail') else 200
            body={'message':'Тест: текст временно недоступен.'} if status!=200 else {'text':'Пассажирский комплекс включает вокзалы, станции и обслуживание пассажиров.\n\nТест безопасного текста: <script>alert("fixture")</script>.'}
        elif path.startswith('/api/jobs/') and method=='PUT':
            for j in state['queue']['jobs']:
                if j['id']==path.rsplit('/',1)[-1]:j.update(data)
        elif path.startswith('/api/jobs/') and path.endswith('/retry'):
            for j in state['queue']['jobs']:
                if j['id']==path.split('/')[3]:j.update(status='WAITING',error=None,progress=None)
        elif path.startswith('/api/jobs/') and method=='DELETE':state['queue']['jobs'][:]=[j for j in state['queue']['jobs'] if j['id']!=path.rsplit('/',1)[-1]]
        elif path.startswith('/api/native/'):status,body=409,{'message':'Тест: системное окно Windows не выполняется.'}
        return {'status':status,'body':json.dumps(body,ensure_ascii=False),'headers':{'content-type':'application/json'}}
    def upload_bridge(url, file, headers):
        calls.append({'path':url,'method':'UPLOAD','data':file,'headers':headers})
        if controller.get('upload_fail'):return {'status':400,'body':json.dumps({'message':'Тест: повреждённая запись.'})}
        q=parse_qs(urlsplit(url).query);job_id='upload-'+str(len([c for c in calls if c['method']=='UPLOAD']))
        state['queue']['jobs'].append({'id':job_id,'source_id':'src-'+job_id,'name':file['name'],'size':file['size'],'duration':30,'media_type':'video' if file['name'].endswith('.mp4') else 'audio','model':q['model'][0],'language':q['language'][0],'status':'WAITING','progress':None,'attempt':0,'source_upload':True})
        return {'status':200,'body':json.dumps({'job_id':job_id,'source_id':'src-'+job_id})}
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.expose_function('_bridge',bridge);page.expose_function('_uploadBridge',upload_bridge)
    page.set_content('<!doctype html><html lang="ru" data-theme="carbon"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div></body></html>')
    css=re.sub(r'@font-face\s*\{[^}]+\}','',(dist/'style.css').read_text())
    page.add_style_tag(content=css)
    page.add_script_tag(content='''window.fetch=async(path,options={})=>{const r=await window._bridge(path,options);return new Response(r.body,{status:r.status,headers:r.headers})};window.WebSocket=class{static OPEN=1;readyState=1;constructor(){this.timer=setInterval(async()=>{const r=await window._bridge('/api/state',{});if(r.status===200)this.onmessage?.({data:r.body});else this.close()},160)}close(){if(this.readyState===3)return;this.readyState=3;clearInterval(this.timer);this.onclose?.()}};window.XMLHttpRequest=class{constructor(){this.upload={};this.headers={};this.aborted=false}open(method,url){this.method=method;this.url=url}setRequestHeader(k,v){this.headers[k]=v}send(file){let n=0;this.timer=setInterval(async()=>{if(this.aborted)return;n++;this.upload.onprogress?.({lengthComputable:true,loaded:Math.min(n/5,1)*file.size,total:file.size});if(n>=5){clearInterval(this.timer);const r=await window._uploadBridge(this.url,{name:file.name,size:file.size,type:file.type},this.headers);if(this.aborted)return;this.status=r.status;this.responseText=r.body;this.onload?.()}},110)}abort(){this.aborted=true;clearInterval(this.timer);this.onabort?.()}};''')
    for name in ('vendor/vue.global.js','render.js','app.js'):page.add_script_tag(content=(dist/name).read_text())
    page.wait_for_function("document.querySelector('.progress-number')?.textContent.includes('68.5')")
    page.evaluate("label=>{const e=document.createElement('div');e.id='fixture-label';e.textContent=label+' · ТЕСТОВЫЕ ДАННЫЕ · РЕЗЕРВНЫЕ ШРИФТЫ · НЕ ASR/GPU-БЕНЧМАРК';e.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#101217;color:#d7d7db;text-align:center;font:9px Arial;padding:4px;letter-spacing:.4px';document.body.append(e)}",label)


def geometry_check(page, report, name):
    findings=page.evaluate("""()=>{
      const result=[],box=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
      const shown=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0};
      const overlap=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1;
      const checkPairs=(elements,kind)=>{for(let i=0;i<elements.length;i++)for(let j=i+1;j<elements.length;j++)if(shown(elements[i])&&shown(elements[j])&&overlap(box(elements[i]),box(elements[j])))result.push({kind,a:elements[i].className,b:elements[j].className})};
      checkPairs([...document.querySelectorAll('.workflow-bar>div')],'workflow-overlap');
      const hero=document.querySelector('.hero'),telemetry=document.querySelector('.telemetry');if(hero&&telemetry&&overlap(box(hero),box(telemetry)))result.push({kind:'hero-telemetry-overlap'});
      for(const row of document.querySelectorAll('.queue-row')){
        const r=box(row);checkPairs([...row.children],'queue-cell-overlap');
        for(const e of row.querySelectorAll('button,select,.queue-status>span')){if(!shown(e))continue;const b=box(e);if(b.left<r.left-1||b.right>r.right+1||b.top<r.top-1||b.bottom>r.bottom+1)result.push({kind:'queue-control-outside-row',class:e.className,label:e.getAttribute('aria-label')||e.textContent,control:b,row:r});}
      }
      const workflow=document.querySelector('.workflow-bar');if(workflow){const parent=box(workflow);for(const e of workflow.children){const b=box(e);if(b.left<parent.left-1||b.right>parent.right+1)result.push({kind:'workflow-column-outside',class:e.className});}}
      return result;
    }""")
    report.setdefault('geometry_checks',[]).append({'screen':name,'width':page.viewport_size['width'],'height':page.viewport_size['height'],'findings':findings})
    if findings:report.setdefault('geometry_failures',[]).append({'screen':name,'findings':findings})


def capture(page, out, name, report):
    geometry=page.evaluate('''()=>({width:innerWidth,height:innerHeight,document_width:document.documentElement.scrollWidth,document_height:document.documentElement.scrollHeight,overflow:document.documentElement.scrollWidth>innerWidth,offenders:[...document.querySelectorAll('#app *')].filter(e=>{let r=e.getBoundingClientRect();return r.width>0&&(r.right>innerWidth+1||r.left<-1)}).slice(0,12).map(e=>({tag:e.tagName,class:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
    page.screenshot(path=str(out/(name+'.png')),full_page=True)
    geometry.update(screenshot=name+'.png');report['screens'].append(geometry)
    if report.get('check_geometry'):geometry_check(page,report,name)
    if geometry['overflow']:report['layout_failures'].append(geometry)


def themes_matrix(browser, dist, out, report, baseline=False):
    page=browser.new_page(viewport={'width':1366,'height':900},device_scale_factor=1)
    state=fixture();calls=[];errors=[];controller={};attach(page,state,calls,errors,dist,controller,'ДО ИСПРАВЛЕНИЙ' if baseline else 'ПОСЛЕ ИСПРАВЛЕНИЙ')
    for theme in THEMES:
        if theme!='carbon':
            page.locator('.appearance-button').click();page.locator('.theme-option').filter(has_text=theme.upper()).click();page.get_by_label('Закрыть оформление',exact=True).click()
        page.wait_for_timeout(460)
        for width in WIDTHS:
            height=844 if width<700 else 900 if width<1600 else 1080
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(100)
            capture(page,out,f'{theme}-running-{width}',report)
            if not baseline:
                assert page.get_by_role('progressbar',name='Распознано аудио').get_attribute('aria-valuenow')=='68.5'
                assert page.get_by_role('button',name=re.compile(r'^Добавить файлы')).is_visible()
                assert page.get_by_role('button',name=re.compile(r'^Пауза после текущей')).is_visible()
                if width < 700:
                    targets=page.locator('.row-actions button').evaluate_all('(elements)=>elements.map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))')
                    assert all(t['width']>=44 and t['height']>=44 for t in targets),(theme,width,targets)
                    report.setdefault('mobile_hit_targets',[]).append({'theme':theme,'width':width,'minimum_width':min(t['width'] for t in targets),'minimum_height':min(t['height'] for t in targets)})
    if not baseline:
        page.set_viewport_size({'width':1366,'height':600});geometry_check(page,report,'short-desktop-1366x600');capture(page,out,'signal-running-1366x600',report)
        interactions(page,state,calls,errors,controller,out,report)
    assert not errors,errors
    report['errors']+=errors;page.close()


def interactions(page,state,calls,errors,controller,out,report):
    checks=report['interaction_checks']
    page.set_viewport_size({'width':1366,'height':900})
    page.locator('.appearance-button').click();page.locator('.theme-option').filter(has_text='CARBON').click();page.get_by_label('Закрыть оформление',exact=True).click()
    page.get_by_role('button',name=re.compile(r'^Пауза после текущей')).click();page.wait_for_timeout(180);assert state['queue']['pause_after_current']
    page.get_by_role('button',name=re.compile(r'^Продолжить очередь')).click();page.wait_for_timeout(180);assert not state['queue']['pause_after_current'];checks+=['pause after current','resume queue']
    page.get_by_role('button',name='Управление пассажирским комплексом.mp4',exact=True).click()
    assert page.locator('.source-info h1').inner_text()=='Управление пассажирским комплексом.mp4'
    assert page.locator('.active-context').is_visible();assert page.locator('.queue-row.selected').count()==1
    page.get_by_role('button',name='Открыть текст ↗',exact=True).click();page.locator('.transcript-text').wait_for()
    assert '<script>alert' in page.locator('.transcript-text').inner_text()
    assert page.locator('.result-dialog').get_attribute('open') is not None
    capture(page,out,'carbon-result-1366',report)
    page.set_viewport_size({'width':390,'height':844});capture(page,out,'carbon-result-390',report)
    page.keyboard.press('Escape');assert page.locator('.result-dialog').get_attribute('open') is None
    page.wait_for_function("document.activeElement?.textContent.startsWith('Открыть текст')")
    page.set_viewport_size({'width':1366,'height':900});page.get_by_role('button',name='К текущей записи ↗').click();assert 'Лекция 07' in page.locator('.source-info h1').inner_text()
    checks+=['select completed job while processing','return to active job','plain text result preview','modal Escape and focus restoration']
    page.get_by_label('Отменить текущую обработку',exact=True).click();assert page.locator('.confirm-dialog').get_attribute('open') is not None
    capture(page,out,'carbon-cancel-confirm-1366',report)
    page.get_by_role('button',name='Продолжить обработку',exact=True).click();assert not any(c['path']=='/api/queue/cancel' for c in calls)
    page.get_by_label('Отменить текущую обработку',exact=True).click();page.get_by_role('button',name='Остановить запись',exact=True).click();page.wait_for_timeout(180)
    assert state['queue']['jobs'][0]['cancelling'];assert not page.get_by_label('Отменить текущую обработку',exact=True).is_enabled();checks+=['cancel confirmation dismiss','cancel request and cancelling feedback']
    state['queue']['jobs'][0]['cancelling']=False
    page.get_by_label('Выше Семинар — базы данных.wav',exact=True).click();page.wait_for_timeout(180);assert [j['id'] for j in state['queue']['jobs'] if j['status']=='WAITING']==['c','b']
    page.get_by_label('Модель для IELTS · Speaking practice.m4a',exact=True).select_option('qwen');page.wait_for_timeout(180)
    assert next(j for j in state['queue']['jobs'] if j['id']=='b')['model']=='qwen'
    page.get_by_role('button',name='Семинар — базы данных.wav',exact=True).click();page.get_by_label('Аудиодорожка выбранной записи',exact=True).select_option('1');page.wait_for_timeout(180)
    assert next(j for j in state['queue']['jobs'] if j['id']=='c')['audio_stream_index']==1
    capture(page,out,'carbon-track-choice-1366',report);checks+=['waiting reorder','per-job model','audio track selection']
    page.get_by_label('Модель для новых файлов',exact=True).select_option('gigaam');page.wait_for_timeout(460)
    page.wait_for_function("document.querySelector('[aria-label=\"Модель для новых файлов\"]').value==='gigaam' && document.querySelector('[aria-label=\"Основной язык новых файлов\"] option[value=en]').disabled")
    assert page.get_by_label('Основной язык новых файлов',exact=True).locator('option[value=en]').get_attribute('disabled') is not None
    assert state['preferences']['default_model']=='gigaam';checks+=['GigaAM English prevention','new-file preferences persist']
    state['queue']['running']=False;page.wait_for_timeout(180)
    page.get_by_role('button',name=re.compile(r'Применить к ожидающим')).click();page.wait_for_timeout(220)
    assert all(j['model']=='gigaam' and j['language']=='ru' for j in state['queue']['jobs'] if j['status']=='WAITING');checks+=['apply defaults to all stopped waiting jobs']
    # Browser picker uploads small synthetic payloads; XHR transport is explicitly mocked.
    inp=page.get_by_label('Выбрать аудио или видео',exact=True)
    before=len(state['queue']['jobs']);inp.set_input_files([{'name':'Проверка.mp4','mimeType':'video/mp4','buffer':b'fixture-media'}]);page.locator('.upload-panel').wait_for();assert page.get_by_role('button',name=re.compile(r'^Добавить файлы')).is_disabled()
    page.wait_for_timeout(230);capture(page,out,'carbon-upload-1366',report);page.wait_for_function("!document.querySelector('.upload-panel')")
    assert len(state['queue']['jobs'])==before+1
    upload=next(c for c in reversed(calls) if c['method']=='UPLOAD');assert upload['headers']['X-Sloi-Csrf']=='ui-fixture-token';assert upload['headers']['Content-Type']=='application/octet-stream';assert upload['data']['size']==13
    before=len(state['queue']['jobs']);inp.set_input_files([{'name':'Отмена.wav','mimeType':'audio/wav','buffer':b'cancel-fixture'}]);page.locator('.upload-panel').wait_for();page.get_by_role('button',name='Отменить перенос',exact=True).click();page.wait_for_function("!document.querySelector('.upload-panel')");assert len(state['queue']['jobs'])==before
    inp.set_input_files([{'name':'bad.exe','mimeType':'application/octet-stream','buffer':b'unsupported'}]);page.locator('.error-notice').wait_for();assert 'Выберите аудио' in page.locator('.error-notice').inner_text();checks+=['upload progress and busy controls','raw XHR body with CSRF','upload cancellation','unsupported extension rejection']
    controller['upload_fail']=True;inp.set_input_files([{'name':'bad.wav','mimeType':'audio/wav','buffer':b'bad'}]);page.wait_for_function("!document.querySelector('.upload-panel')");page.wait_for_timeout(650);assert 'повреждённая' in page.locator('.error-notice').inner_text();controller['upload_fail']=False;checks+=['upload server error feedback']
    # Track and error states, independent from active processing.
    state['queue']['active_id']=None;state['queue']['running']=False;state['queue']['jobs']=[copy.deepcopy(fixture()['queue']['jobs'][0])]
    for status in ('WAITING','PREPARING','ANALYSING','FAILED','CANCELLED','SOURCE_MISSING','COMPLETE'):
        job=state['queue']['jobs'][0];job['status']=status;job['progress']=100 if status=='COMPLETE' else None;job['error']={'code':'AUDIO_ERROR','message':'Выбранная дорожка повреждена. Проверьте файл и выберите другую дорожку.'} if status=='FAILED' else None
        page.wait_for_timeout(180)
        if status not in ('COMPLETE',):assert page.locator('.progress-number').count()==0
        for width in (390,1366):
            page.set_viewport_size({'width':width,'height':844 if width==390 else 900});capture(page,out,f'carbon-{status.lower()}-{width}',report)
    checks+=['waiting/preparing/VAD/failure/cancel/missing/complete states']
    # Empty state and optional Windows affordances.
    state['queue']['jobs']=[];state['native_available']=False;page.wait_for_timeout(180)
    assert page.get_by_text('Добавить без копирования',exact=True).count()==0
    for width in (320,390,1366):page.set_viewport_size({'width':width,'height':844 if width<700 else 900});capture(page,out,f'carbon-empty-{width}',report)
    assert page.get_by_role('button',name=re.compile(r'^Запустить очередь')).is_disabled();checks+=['empty state start reason','non-Windows native controls hidden']
    controller['offline']=True;page.wait_for_timeout(350);assert page.locator('.connection-notice').is_visible();assert page.get_by_role('button',name=re.compile(r'^Добавить файлы')).is_disabled();capture(page,out,'carbon-offline-1366',report)
    controller['offline']=False;page.get_by_role('button',name='Подключиться ↻',exact=True).click();page.wait_for_function("!document.querySelector('.connection-notice')");checks+=['disconnect disables actions','manual reconnect']
    page.locator('.appearance-button').click();page.get_by_label('Свой акцентный цвет',exact=True).fill('#101010');page.wait_for_timeout(460)
    assert state['preferences']['accent']=='#101010';assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent-ink').trim()")=='#edeff0'
    page.keyboard.press('Escape');assert page.locator('#appearance-panel').count()==0;checks+=['custom accent contrast fallback','Escape closes appearance']
    page.emulate_media(reduced_motion='reduce');assert page.evaluate("getComputedStyle(document.querySelector('.primary-button')).transitionDuration")=='0s';checks+=['CSS reduced motion']
    assert not errors,errors


def main():
    p=argparse.ArgumentParser();p.add_argument('--browser',default=os.environ.get('SLOI_CHROMIUM'));p.add_argument('--output',type=Path,default=ROOT/'validation');p.add_argument('--baseline-dist',type=Path);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    report={'browser':'Chromium','transport':'offline API and XHR fixtures; real application routes tested independently','fonts':'fallback fonts; no downloaded production font assets','screens':[],'errors':[],'layout_failures':[],'interaction_checks':[],'check_geometry':True,'geometry_failures':[]}
    env=dict(os.environ)
    if os.environ.get('SLOI_CHROMIUM_LIBRARY_PATH'):env['LD_LIBRARY_PATH']=os.environ['SLOI_CHROMIUM_LIBRARY_PATH']
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'],env=env)
        report['browser_version']=browser.version
        if args.baseline_dist:
            before={'screens':[],'errors':[],'layout_failures':[],'interaction_checks':[]};out=args.output/'screenshots-before';out.mkdir(exist_ok=True);themes_matrix(browser,args.baseline_dist,out,before,baseline=True)
            (args.output/'browser-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
        out=args.output/'screenshots';out.mkdir(exist_ok=True)
        try:themes_matrix(browser,ROOT/'frontend'/'dist',out,report)
        except BaseException as exc:
            report['errors'].append(type(exc).__name__+': '+str(exc));raise
        finally:
            report['status']='passed' if not report['layout_failures'] and not report.get('geometry_failures') and not report['errors'] else 'failed'
            (args.output/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));browser.close()
    print(json.dumps({'status':report['status'],'screens':len(report['screens']),'layout_failures':report['layout_failures'],'geometry_failures':report.get('geometry_failures'),'interaction_checks':report['interaction_checks']},ensure_ascii=False,indent=2))
    assert not report['layout_failures'],report['layout_failures']
    assert not report.get('geometry_failures'),report.get('geometry_failures')

if __name__=='__main__':main()
