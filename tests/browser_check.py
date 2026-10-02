from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'frontend' / 'dist'
OUT = ROOT / 'validation' / 'screenshots'


def fixture():
    return {'version': '1.0.0-rc1', 'native_available': True,
        'preferences': {'theme': 'carbon', 'accent': '#c6f36b'},
        'defaults': {'model': 'whisper', 'language': 'ru'},
        'models': [{'id': key, 'name': name, 'installed': True, 'note': 'UI fixture: not an inference benchmark'} for key,name in [('gigaam','GigaAM v3'),('qwen','Qwen3 ASR'),('whisper','Whisper RU'),('parakeet','Parakeet v3')]],
        'queue': {'active_id': 'a', 'running': True, 'pause_after_current': False, 'jobs': [
          {'id':'a','source_id':'s1','name':'Лекция 07. Аналитика данных.mp4','model':'qwen','language':'ru','status':'TRANSCRIBING','duration':5538,'size':2_615_125_000,'media_type':'video','progress':68.5,'processed_seconds':3193,'planned_seconds':4662,'elapsed_seconds':277,'speed_x':13.6,'eta_seconds':128,'speech_map':[.15 if i%29<3 else .5+.5*math.sin(i*.4)**2 for i in range(160)],'attempt':1},
          {'id':'b','source_id':'s2','name':'IELTS · Speaking practice.m4a','model':'parakeet','language':'en','status':'WAITING','duration':1433,'size':35_146_532,'media_type':'audio','progress':None,'attempt':0},
          {'id':'c','source_id':'s3','name':'Семинар — базы данных.wav','model':'gigaam','language':'ru','status':'WAITING','duration':2944,'size':91_994_003,'media_type':'audio','progress':None,'attempt':0}]},
        'telemetry':{'gpu_available':True,'gpu_name':'NVIDIA GeForce RTX 3050 Ti Laptop GPU','gpu_utilization_pct':94,'gpu_memory_used_mb':3460,'gpu_memory_total_mb':4096,'cpu_utilization_pct':31,'system_ram_used_mb':8991,'system_ram_total_mb':16384,'gpu_temperature_c':74,'gpu_power_w':51.2,'history':[{'gpu_utilization_pct':85+8*math.sin(i*.4),'gpu_memory_used_mb':3380+80*math.sin(i*.12),'cpu_utilization_pct':28+9*math.sin(i*.45)} for i in range(60)]}}


def attach(page, state, calls, errors):
    def bridge(path, options):
        method = options.get('method', 'GET')
        data = json.loads(options.get('body') or '{}')
        calls.append({'path': path, 'method': method, 'data': data})
        body, status = {'ok': True}, 200
        if path == '/api/session': body = {'csrf':'ui-fixture-token'}
        elif path == '/api/state': body = state
        elif path == '/api/preferences': state['preferences'] = data
        elif path == '/api/queue/pause': state['queue']['pause_after_current'] = True
        elif path == '/api/queue/start': state['queue']['pause_after_current'] = False
        elif path == '/api/queue/order':
            active = [j for j in state['queue']['jobs'] if j['status'] != 'WAITING']
            queued = {j['id']:j for j in state['queue']['jobs'] if j['status'] == 'WAITING'}
            state['queue']['jobs'] = active + [queued[i] for i in data['ids']]
        elif path.startswith('/api/jobs/') and method == 'PUT':
            for job in state['queue']['jobs']:
                if job['id'] == path.rsplit('/',1)[-1]: job.update(data)
        elif path.startswith('/api/native/'):
            status, body = 409, {'message':'UI test: native Windows interaction is not executed.'}
        return {'status':status,'body':json.dumps(body,ensure_ascii=False),'headers':{'content-type':'application/json'}}
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.expose_function('_bridge', bridge)
    page.set_content('<!doctype html><html lang="ru" data-theme="carbon"><head><meta charset="utf-8"></head><body><div id="app"></div></body></html>')
    css = re.sub(r'@font-face\s*\{[^}]+\}', '', (DIST/'style.css').read_text())
    page.add_style_tag(content=css)
    page.add_script_tag(content='''window.fetch=async (path,options={})=>{const r=await window._bridge(path,options);return new Response(r.body,{status:r.status,headers:r.headers})};window.WebSocket=class {static OPEN=1;readyState=1;constructor(){this.timer=setInterval(async()=>{const r=await window._bridge('/api/state',{});this.onmessage?.({data:r.body})},800)}close(){clearInterval(this.timer);this.onclose?.()}};''')
    for name in ('vendor/vue.global.js','render.js','app.js'):
        page.add_script_tag(content=(DIST/name).read_text())
    page.wait_for_function("document.querySelector('.progress-number')?.textContent.includes('68.5')")
    page.evaluate("""()=>{const el=document.createElement('div');el.id='fixture-label';el.textContent='ПРОВЕРКА ВЁРСТКИ · ТЕСТОВЫЕ ДАННЫЕ, НЕ GPU-BENCHMARK · РЕЗЕРВНЫЕ ШРИФТЫ';el.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#101217;color:#d7d7db;text-align:center;font:9px Arial;padding:4px;letter-spacing:.6px';document.body.append(el)}""")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'browser':'Chromium','transport':'offline browser fixture; API tested independently in pytest','fonts':'fallback only; Google Font bytes downloaded on Windows install','screens':[], 'errors':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
        state=fixture(); calls=[]; errors=[]
        attach(page,state,calls,errors)
        for theme in ('carbon','paper','signal'):
            if theme != 'carbon':
                if not page.locator('#appearance-panel').count(): page.locator('.appearance-button').click()
                page.locator('.theme-option').filter(has_text=theme.upper()).click()
                page.get_by_label('Закрыть оформление', exact=True).click()
            page.wait_for_timeout(450)
            for width,height in ((1920,1080),(1600,900),(1366,768),(768,1024),(390,844)):
                page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(250)
                overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not overflow, (theme,width,'horizontal overflow')
                assert page.locator('.progress-number').inner_text().replace('\n','').startswith('68.5')
                assert page.get_by_role('progressbar').get_attribute('aria-valuenow') == '68.5'
                filename=f'{theme}-{width}x{height}.png'
                page.screenshot(path=str(OUT/filename),full_page=True)
                report['screens'].append({'theme':theme,'viewport':[width,height],'horizontal_overflow':overflow,'document_height':page.evaluate('document.documentElement.scrollHeight'),'screenshot':filename})
        page.set_viewport_size({'width':1600,'height':900})
        page.get_by_role('button',name='Пауза после текущей').click();page.wait_for_timeout(350)
        assert state['queue']['pause_after_current'] is True
        page.get_by_role('button',name='Продолжить очередь').click();page.wait_for_timeout(350)
        assert state['queue']['pause_after_current'] is False
        page.get_by_label('Выше Семинар — базы данных.wav').click();page.wait_for_timeout(350)
        assert [j['id'] for j in state['queue']['jobs']] == ['a','c','b']
        page.get_by_label('Модель для IELTS · Speaking practice.m4a').select_option('qwen');page.wait_for_timeout(350)
        assert state['queue']['jobs'][2]['model']=='qwen'
        page.locator('.appearance-button').click();page.get_by_label('Свой акцентный цвет').fill('#101010');page.wait_for_timeout(400)
        assert state['preferences']['accent']=='#101010'
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent-ink').trim()")=='#edeff0'
        page.keyboard.press('Escape');assert page.locator('#appearance-panel').count()==0
        page.emulate_media(reduced_motion='reduce')
        assert page.evaluate("getComputedStyle(document.querySelector('.equalizer b')).animationName")=='none'
        report['interaction_checks']=['theme switching preserves queue','custom accent persists','contrast fallback','pause after current','resume queue','reorder waiting','change model per job','Escape closes appearance','reduced motion','real-valued progress binding']
        assert not errors, errors
        report['errors']=errors
        report['status']='passed'
        browser.close()
    (ROOT/'validation'/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
