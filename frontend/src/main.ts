declare const Vue: any;
declare const SloiRender: any;

type ThemeId = 'carbon' | 'paper' | 'signal';
type Job = {id:string;source_id:string;name:string;model:string;language:string;status:string;duration:number;size:number;media_type:string;progress:number|null;processed_seconds?:number;planned_seconds?:number;analysis_seconds?:number;elapsed_seconds?:number;speed_x?:number|null;eta_seconds?:number|null;speech_map?:number[];attempt:number;warnings?:string[];error?:{code:string;message:string}};
type Model = {id:string;name:string;installed:boolean;note:string};

const themes: Record<ThemeId, {name:string;description:string;accent:string;presets:string[]}> = {
 carbon:{name:'CARBON',description:'Точный измерительный инструмент',accent:'#c6f36b',presets:['#c6f36b','#6fbcff','#ff925c','#c4a1ff','#f07b87']},
 paper:{name:'PAPER',description:'Типографика, чернила и воздух',accent:'#b74326',presets:['#b74326','#2a4ca6','#287258','#724e9f','#206c7b']},
 signal:{name:'SIGNAL',description:'Кинетическая структура сигнала',accent:'#a798ff',presets:['#a798ff','#81d8ff','#ff9ad4','#d1f476','#ffb272']}
};

Vue.createApp({render:SloiRender,setup(){
 const {ref,reactive,computed,onMounted,onBeforeUnmount,watch,nextTick} = Vue;
 const state = reactive({version:'1.0.0-rc1',queue:{jobs:[] as Job[],active_id:null as string|null,running:false,pause_after_current:false},telemetry:{} as Record<string,any>,models:[] as Model[],native_available:false});
 const connected = ref(false),appearance = ref(false),error = ref(''),info = ref(''),busyNative = ref(false),dropHover=ref(false),dragJob=ref('');
 const selectedId=ref('');
 const theme = ref('carbon' as ThemeId),accent=ref(themes.carbon.accent),defaultModel=ref('whisper'),defaultLanguage=ref('auto'),fieldCanvas=ref(null as HTMLCanvasElement|null);
 let csrf='',socket:WebSocket|null=null,retryTimer:number|undefined,pollTimer:number|undefined,saveTimer:number|undefined,stopped=false,initialized=false,field:SignalField|null=null;
 const allJobs=computed(()=>state.queue.jobs),active=computed(()=>state.queue.jobs.find((j:Job)=>j.id===state.queue.active_id));
 const selected=computed(()=>active.value || state.queue.jobs.find((j:Job)=>j.id===selectedId.value) || [...state.queue.jobs].reverse().find((j:Job)=>j.status==='COMPLETE') || state.queue.jobs[0] || null);
 const waiting=computed(()=>state.queue.jobs.filter((j:Job)=>j.status==='WAITING'));
 const completed=computed(()=>state.queue.jobs.filter((j:Job)=>j.status==='COMPLETE'));
 const percentage=computed(()=>selected.value && ['TRANSCRIBING','FINALIZING','COMPLETE'].includes(selected.value.status) ? selected.value.progress : null);
 const anyInstalled=computed(()=>state.models.some((m:Model)=>m.installed));
 const waitingInstalled=computed(()=>waiting.value.every((j:Job)=>state.models.find((m:Model)=>m.id===j.model)?.installed));
 const themeList=Object.entries(themes).map(([id,t])=>({id,...t}));
 const presets=computed(()=>themes[theme.value as ThemeId].presets);
 const totalDuration=computed(()=>state.queue.jobs.reduce((a:number,j:Job)=>a+(j.duration||0),0));
 const progressCaption=computed(()=>selected.value?.status==='COMPLETE'?'РАСШИФРОВКА ГОТОВА':selected.value?.status==='ANALYSING'?'АНАЛИЗ РЕЧИ':selected.value?.status==='LOADING_MODEL'?'ЗАГРУЗКА МОДЕЛИ':'РАСПОЗНАНО');
 const statusText=(status?:string)=>({WAITING:'В ОЧЕРЕДИ',PREPARING:'ПОДГОТОВКА',ANALYSING:'АНАЛИЗ АУДИО',LOADING_MODEL:'ЗАГРУЗКА МОДЕЛИ',TRANSCRIBING:'РАСПОЗНАВАНИЕ',FINALIZING:'СОХРАНЕНИЕ',COMPLETE:'ГОТОВО',FAILED:'ОШИБКА',CANCELLED:'ОТМЕНЕНО',INTERRUPTED:'ПРЕРВАНО',SOURCE_MISSING:'ИСХОДНИК НЕДОСТУПЕН'} as Record<string,string>)[status||'']||'ГОТОВ К РАБОТЕ';
 const time=(value?:number|null)=>{if(value==null||!Number.isFinite(value))return '—:—';const s=Math.max(0,Math.floor(value));return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0')};
 const metric=(value?:number|null,d=1)=>value==null||!Number.isFinite(value)?'—':value.toFixed(d);
 const gb=(value?:number|null,d=2)=>metric(value==null?null:value/1024,d);
 const ratio=(a?:number,b?:number)=>a!=null&&b?Math.max(0,Math.min(100,a/b*100)):0;
 const size=(bytes:number)=>bytes>=1024**3?(bytes/1024**3).toFixed(2)+' GB':(bytes/1024**2).toFixed(1)+' MB';
 const languageText=(lang:string)=>lang==='ru'?'RU / основной':lang==='en'?'EN / основной':'AUTO / язык';
 const modelName=(id:string)=>state.models.find((m:Model)=>m.id===id)?.name||id;
 const spark=(key:string,max:number,w=300,h=35)=>{const hist=state.telemetry.history||[];if(!hist.some((r:any)=>r[key]!=null))return '';let down=false;return hist.map((r:any,i:number)=>{if(r[key]==null){down=false;return ''}const x=i/Math.max(1,hist.length-1)*w,y=h-2-Math.min(1,Math.max(0,r[key]/max))*(h-4);const a=(down?'L':'M')+x.toFixed(1)+' '+y.toFixed(1);down=true;return a}).join(' ')};
 function applyTheme(){document.documentElement.dataset.theme=theme.value;document.documentElement.style.setProperty('--accent',accent.value);const rgb=accent.value.match(/\w\w/g)?.map((v:string)=>parseInt(v,16))||[190,240,90];const lum=rgb.map((v:number)=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});const l=.2126*lum[0]+.7152*lum[1]+.0722*lum[2];document.documentElement.style.setProperty('--on-accent',l>.179?'#10120f':'#ffffff');const bg=theme.value==='paper'?.857:theme.value==='signal'?.0075:.0076;const contrast=(Math.max(l,bg)+.05)/(Math.min(l,bg)+.05);document.documentElement.style.setProperty('--accent-ink',contrast<4.5?(theme.value==='paper'?'#242824':'#edeff0'):accent.value)}
 async function api(path:string,method='GET',data?:unknown){const result=await fetch(path,{method,headers:{...(data!==undefined?{'Content-Type':'application/json'}:{}),...(method==='GET'?{}:{'X-Sloi-Csrf':csrf})},body:data===undefined?undefined:JSON.stringify(data)});if(!result.ok){let detail:any={};try{detail=await result.json()}catch{};throw new Error(detail.message||'Ошибка запроса '+result.status)}return result.headers.get('content-type')?.includes('application/json')?await result.json():null}
 function accept(data:any){state.version=data.version;state.queue=data.queue;state.telemetry=data.telemetry;state.models=data.models;state.native_available=data.native_available;connected.value=true;if(!initialized){initialized=true;theme.value=data.preferences.theme;accent.value=data.preferences.accent;defaultModel.value=data.defaults.model;defaultLanguage.value=data.defaults.language;applyTheme()}}
 async function refresh(){try{accept(await api('/api/state'))}catch(e){connected.value=false}}
 async function execute(work:()=>Promise<any>){try{error.value='';await work();await refresh()}catch(e){error.value=e instanceof Error?e.message:String(e)}}
 function connect(){if(stopped)return;socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.onmessage=e=>{try{accept(JSON.parse(e.data))}catch{error.value='Некорректные данные от backend.'}};socket.onclose=()=>{connected.value=false;if(!stopped)retryTimer=window.setTimeout(bootstrap,1800)};socket.onerror=()=>socket?.close()}
 async function bootstrap(){try{const session=await api('/api/session');csrf=session.csrf;await refresh();connect()}catch{connected.value=false;if(!stopped)retryTimer=window.setTimeout(bootstrap,2200)}}
 function persistTheme(){applyTheme();window.clearTimeout(saveTimer);saveTimer=window.setTimeout(()=>execute(()=>api('/api/preferences','PUT',{theme:theme.value,accent:accent.value})),250)}
 function chooseTheme(id:ThemeId){theme.value=id;accent.value=themes[id].accent;persistTheme()}
 function setAccent(value:string){if(/^#[0-9a-f]{6}$/i.test(value)){accent.value=value;persistTheme()}}
 async function addSources(sources:any[]){if(!sources.length)return;const lang=defaultModel.value==='gigaam'&&defaultLanguage.value==='en'?'ru':defaultLanguage.value;await api('/api/jobs','POST',{source_ids:sources.map(s=>s.id),model:defaultModel.value,language:lang})}
 async function nativeFiles(mode:string){if(busyNative.value)return;await execute(async()=>{busyNative.value=true;info.value=mode==='drop'?'Перетащите файлы в открывшееся Windows-окно. Приложение не создаёт копии исходников.':'Выберите файлы в системном окне Windows. Исходники не копируются.';try{const data=await api('/api/native/'+mode,'POST');await addSources(data.sources);info.value=data.errors?.length?data.errors.map((e:any)=>e.name+': '+e.message).join(' · '):data.sources?.length?'Добавлено записей: '+data.sources.length:''}finally{busyNative.value=false}})}
 function onDragOver(event:DragEvent){if(dragJob.value)return;if(event.dataTransfer?.types.includes('Files'))dropHover.value=true}
 function onDragLeave(event:DragEvent){if(!event.relatedTarget)dropHover.value=false}
 async function onDrop(event:DragEvent){dropHover.value=false;if(dragJob.value)return;const files=Array.from(event.dataTransfer?.files||[]);if(!files.length)return;await execute(async()=>{const data=await api('/api/files/drop','POST',{files:files.map(f=>({name:f.name,size:f.size,last_modified:f.lastModified}))});await addSources(data.sources);if(data.missing?.length){info.value='Браузер скрывает путь новых файлов. Подтвердите их в системном окне — содержимое передаваться не будет.';await nativeFiles('picker')}})}
 const changeModel=(job:Job,model:string)=>execute(()=>api('/api/jobs/'+job.id,'PUT',{model,language:model==='gigaam'&&job.language==='en'?'ru':job.language}));
 const changeLanguage=(job:Job,language:string)=>execute(()=>api('/api/jobs/'+job.id,'PUT',{model:job.model,language}));
 const removeJob=(job:Job)=>execute(()=>api('/api/jobs/'+job.id,'DELETE'));
 const retryJob=(job:Job)=>execute(()=>api('/api/jobs/'+job.id+'/retry','POST'));
 const queueAction=(action:string)=>execute(()=>api('/api/queue/'+action,'POST'));
 function cancelCurrent(){if(window.confirm('Остановить текущую расшифровку? Частичный текст будет удалён. Следующая задача продолжит очередь.'))queueAction('cancel')}
 async function moveJob(job:Job,direction:number){const ids=waiting.value.map((j:Job)=>j.id),i=ids.indexOf(job.id),j=i+direction;if(i<0||j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j],ids[i]];await execute(()=>api('/api/queue/order','PUT',{ids}))}
 function rowDragStart(event:DragEvent,job:Job){if(job.status!=='WAITING'){event.preventDefault();return}dragJob.value=job.id;event.dataTransfer?.setData('text/plain',job.id);if(event.dataTransfer)event.dataTransfer.effectAllowed='move'}
 async function rowDrop(job:Job){const ids=waiting.value.map((j:Job)=>j.id);const from=ids.indexOf(dragJob.value),to=ids.indexOf(job.id);dragJob.value='';if(from<0||to<0||from===to)return;ids.splice(to,0,ids.splice(from,1)[0]);await execute(()=>api('/api/queue/order','PUT',{ids}))}
 function selectJob(job:Job){selectedId.value=job.id}
 function download(job:Job){const a=document.createElement('a');a.href='/api/results/'+job.id+'/download';a.click()}
 function downloadAll(){const a=document.createElement('a');a.href='/api/results.zip';a.click()}
 const reveal=(job:Job)=>execute(()=>api('/api/results/'+job.id+'/reveal','POST'));
 const copyText=(job:Job)=>execute(async()=>{const data=await api('/api/results/'+job.id+'/text');await navigator.clipboard.writeText(data.text);info.value='Текст скопирован без метаданных.'});
 const locate=(job:Job)=>execute(async()=>{busyNative.value=true;try{const data=await api('/api/native/picker','POST');if(data.sources.length!==1){info.value='Для замены исходника выберите один файл.';return}await api('/api/jobs/'+job.id+'/relocate','POST',{source_id:data.sources[0].id});await api('/api/jobs/'+job.id+'/retry','POST')}finally{busyNative.value=false}});
 watch(defaultModel,(id:string)=>{if(id==='gigaam'&&defaultLanguage.value==='en')defaultLanguage.value='ru'});
 onMounted(async()=>{applyTheme();await nextTick();if(fieldCanvas.value)field=new SignalField(fieldCanvas.value,()=>({theme:theme.value,accent:accent.value,progress:percentage.value,active:!!active.value,map:selected.value?.speech_map||[],gpu:state.telemetry.gpu_utilization_pct}));bootstrap();pollTimer=window.setInterval(()=>{if(!socket||socket.readyState!==WebSocket.OPEN)refresh()},6000)});
 onBeforeUnmount(()=>{stopped=true;window.clearTimeout(retryTimer);window.clearTimeout(saveTimer);window.clearInterval(pollTimer);socket?.close();field?.destroy()});
 return {selectJob,theme,accent,themeList,presets,appearance,connected,error,info,busyNative,dropHover,dragJob,fieldCanvas,defaultModel,defaultLanguage,allJobs,active,selected,waiting,completed,percentage,progressCaption,anyInstalled,waitingInstalled,totalDuration,...Vue.toRefs(state),statusText,time,metric,gb,ratio,size,languageText,modelName,spark,chooseTheme,setAccent,nativeFiles,onDragOver,onDragLeave,onDrop,changeModel,changeLanguage,removeJob,retryJob,queueAction,cancelCurrent,moveJob,rowDragStart,rowDrop,download,downloadAll,reveal,copyText,locate};
}}).mount('#app');
