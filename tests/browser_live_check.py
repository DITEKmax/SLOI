"""Real FastAPI/browser smoke using browser_live.py's explicit synthetic ASR double.

Run with SLOI_CHROMIUM and optional SLOI_CHROMIUM_LIBRARY_PATH set.
No ASR model downloads, GPU benchmark, or real recognition-quality claims.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser();p.add_argument('--browser',default=os.environ.get('SLOI_CHROMIUM'));p.add_argument('--port',type=int,default=8765);args=p.parse_args()
 out=ROOT/'validation';screens=out/'screenshots-live';screens.mkdir(parents=True,exist_ok=True)
 qa=ROOT.parent/'qa'/('live-browser-'+str(time.time_ns()));url=f'http://127.0.0.1:{args.port}'
 report={'transport':'real HTTP/session/CSRF/WebSocket/upload/results API','asr':'explicit TestModels double with synthetic audio; not a recognition benchmark','checks':[],'errors':[],'screens':[]}
 log=(out/'browser-live-server.log').open('w')
 server=subprocess.Popen([sys.executable,str(ROOT/'tests'/'browser_live.py'),'--root',str(qa),'--port',str(args.port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 def screenshot(page,name):
  page.screenshot(path=str(screens/(name+'.png')),full_page=True);report['screens'].append(name+'.png');assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')
 try:
  for _ in range(80):
   try:
    with urlopen(url+'/health',timeout=.3) as r:
     if r.status==200:break
   except Exception:
    if server.poll() is not None:raise RuntimeError('QA server exited; see browser-live-server.log')
    time.sleep(.1)
  else:raise RuntimeError('QA server did not become ready')
  env=dict(os.environ)
  if os.environ.get('SLOI_CHROMIUM_LIBRARY_PATH'):env['LD_LIBRARY_PATH']=os.environ['SLOI_CHROMIUM_LIBRARY_PATH']
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'],env=env)
   context=browser.new_context(viewport={'width':1366,'height':900},accept_downloads=True)
   page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)));page.goto(url)
   page.wait_for_function("() => document.querySelector('.connection i.online')")
   assert page.get_by_text('Добавить без копирования',exact=True).count()==0
   assert page.get_by_role('button',name='Запустить очередь ↗',exact=True).is_disabled()
   screenshot(page,'live-empty');report['checks']+=['local session and WebSocket connected','non-Windows optional native controls hidden','empty queue start disabled']
   audio=qa/'fixtures'/'Лекция — браузерный тест.wav';cancel_audio=qa/'fixtures'/'Отмена — браузерный тест.wav'
   inp=page.get_by_label('Выбрать аудио или видео',exact=True);inp.set_input_files(str(audio))
   page.locator('.queue-row').wait_for();page.wait_for_function("() => !document.querySelector('.upload-panel')")
   state=context.request.get(url+'/api/state').json();assert len(state['queue']['jobs'])==1 and state['queue']['jobs'][0]['status']=='WAITING';assert state['queue']['jobs'][0]['source_upload']
   page.get_by_label('Модель для новых файлов',exact=True).select_option('qwen');page.get_by_role('button',name='Применить к ожидающим (1)',exact=True).click()
   page.wait_for_function("() => document.querySelector('.queue-choice select')?.value==='qwen'");screenshot(page,'live-waiting');report['checks']+=['raw browser file upload registered real queue job','apply defaults updates real job']
   page.get_by_role('button',name='Запустить очередь ↗',exact=True).click()
   page.wait_for_function("() => document.querySelector('.queue-row.active')")
   screenshot(page,'live-processing');page.get_by_role('button',name='Пауза после текущей Ⅱ',exact=True).click()
   page.wait_for_function("() => document.querySelector('.queue-row.done')",timeout=15000);state=context.request.get(url+'/api/state').json();assert state['queue']['jobs'][0]['status']=='COMPLETE';assert not state['queue']['running'];screenshot(page,'live-complete')
   report['checks']+=['real queue stages and completion','pause after current stops subsequent execution']
   page.get_by_role('button',name='Открыть текст ↗',exact=True).click();page.locator('.transcript-text').wait_for();assert page.locator('.transcript-text').inner_text();screenshot(page,'live-result-preview')
   with page.expect_download() as d:page.locator('.result-dialog').get_by_role('button',name='Скачать Markdown ↓',exact=True).click()
   downloaded=d.value;md=out/'live-synthetic-result.md';downloaded.save_as(str(md));assert md.stat().st_size>100
   page.keyboard.press('Escape');report['checks']+=['real saved text preview','Markdown download from result API']
   inp.set_input_files(str(cancel_audio));page.wait_for_function("() => document.querySelectorAll('.queue-row').length===2 && !document.querySelector('.upload-panel')")
   page.get_by_role('button',name='Запустить очередь ↗',exact=True).click();page.wait_for_function("() => document.querySelector('.queue-row.active')")
   page.get_by_label('Отменить текущую обработку',exact=True).click();screenshot(page,'live-cancel-confirm');page.get_by_role('button',name='Остановить запись',exact=True).click()
   page.wait_for_function("() => [...document.querySelectorAll('.queue-status')].some(e=>e.textContent.includes('Отменено'))",timeout=15000)
   state=context.request.get(url+'/api/state').json();assert state['queue']['jobs'][1]['status']=='CANCELLED';report['checks']+=['real cancellation reaches CANCELLED']
   inp.set_input_files(str(audio));page.wait_for_function("() => document.querySelectorAll('.queue-row').length===3 && !document.querySelector('.upload-panel')")
   page.get_by_role('button',name='Запустить очередь ↗',exact=True).click();page.wait_for_function("() => document.querySelector('.queue-row.active')");page.close()
   for _ in range(100):
    state=context.request.get(url+'/api/state').json()
    if state['queue']['jobs'][2]['status']=='COMPLETE':break
    time.sleep(.1)
   else:raise AssertionError('Queue failed to complete after browser tab was closed')
   page=context.new_page();page.goto(url);page.wait_for_function("() => document.querySelectorAll('.queue-row.done').length===2")
   screenshot(page,'live-reopened-complete');report['checks']+=['queue continues after closing tab','reopened SPA restores completed jobs']
   assert not report['errors'],report['errors'];browser.close();report['status']='passed'
 except BaseException as e:
  report['status']='failed';report['errors'].append(type(e).__name__+': '+str(e));raise
 finally:
  server.terminate()
  try:server.wait(timeout=5)
  except subprocess.TimeoutExpired:server.kill();server.wait()
  log.close();(out/'browser-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
