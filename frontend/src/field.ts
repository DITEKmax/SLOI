type FieldState = {theme:ThemeId;accent:string;progress:number|null;active:boolean;map:number[];gpu:number|null};

class SignalField {
 private canvas:HTMLCanvasElement;
 private context:CanvasRenderingContext2D|null;
 private state:()=>FieldState;
 private observer:ResizeObserver;
 private width=1;
 private height=1;
 private frame=0;
 private timer:number|undefined;
 private reduced=matchMedia('(prefers-reduced-motion: reduce)');
 private dead=false;
 private force=true;
 private lastSignature='';
 private xs=new Float32Array(53);
 private ys=new Float32Array(53);

 constructor(canvas:HTMLCanvasElement,state:()=>FieldState){
  this.canvas=canvas;this.context=canvas.getContext('2d',{alpha:true});this.state=state;
  this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(canvas);
  document.addEventListener('visibilitychange',this.visibilityChanged);
  this.reduced.addEventListener('change',this.motionChanged);
  this.resize();this.schedule(0);
 }

 private resize(){
  const rect=this.canvas.getBoundingClientRect(),width=Math.max(1,rect.width),height=Math.max(1,rect.height);
  const dpr=Math.min(devicePixelRatio,1.5),pixelsW=Math.round(width*dpr),pixelsH=Math.round(height*dpr);
  if(this.canvas.width===pixelsW&&this.canvas.height===pixelsH&&this.width===width&&this.height===height)return;
  this.width=width;this.height=height;this.canvas.width=pixelsW;this.canvas.height=pixelsH;
  this.context?.setTransform(dpr,0,0,dpr,0,0);this.refresh();
 }

 // State changes can request an immediate static redraw without enabling motion.
 refresh(){this.force=true;if(!this.dead&&!document.hidden)this.schedule(0)}

 private visibilityChanged=()=>{
  this.stopScheduled();
  if(!document.hidden){this.force=true;this.schedule(0)}
 };
 private motionChanged=()=>{this.stopScheduled();this.lastSignature='';this.refresh()};
 private stopScheduled(){window.clearTimeout(this.timer);this.timer=undefined;if(this.frame)cancelAnimationFrame(this.frame);this.frame=0}
 private schedule(delay:number){
  if(this.dead||document.hidden||!this.context)return;
  if(this.frame)return;
  window.clearTimeout(this.timer);
  this.timer=window.setTimeout(()=>{this.timer=undefined;this.frame=requestAnimationFrame(this.tick)},delay);
 }
 private tick=(now:number)=>{
  this.frame=0;
  if(this.dead||document.hidden||!this.context)return;
  const snapshot=this.state();
  if(this.reduced.matches){
   // No animation under reduced motion: redraw only when visible data changes.
   const signature=[snapshot.theme,snapshot.accent,snapshot.progress,snapshot.active,this.width,this.height,snapshot.map.join(',')].join('|');
   if(this.force||signature!==this.lastSignature){this.draw(0,snapshot);this.lastSignature=signature}
  }else this.draw(now/1000,snapshot);
  this.force=false;
  // Idle visuals use eight frames per second; active processing retains 30 fps.
  // Hidden pages schedule nothing, and reduced motion needs only a light fallback check.
  this.schedule(this.reduced.matches?500:snapshot.active?1000/30:125);
 };

 private draw(time:number,{theme,accent,progress,active,map}:FieldState){
  const ctx=this.context;if(!ctx)return;
  const w=this.width,h=this.height;ctx.clearRect(0,0,w,h);
  const paper=theme==='paper',signal=theme==='signal';
  const phase=active?time*.28:time*.045;
  const fraction=progress==null?.38:Math.max(0,Math.min(1,progress/100));
  const rows=paper?19:signal?30:26,cols=signal?53:48;
  const tint=paper?'#817e72':signal?'#a5a0ba':'#758078',left=w*.04,right=w*.97;
  ctx.lineCap=paper?'butt':'round';
  for(let row=0;row<rows;row++){
   const rowFrac=row/(rows-1);ctx.beginPath();
   for(let col=0;col<cols;col++){
    const t=col/(cols-1),data=map.length?map[Math.min(map.length-1,Math.floor(t*map.length))]:.52;
    const envelope=Math.pow(Math.sin(t*Math.PI),.75);
    const warp=Math.sin(t*6.3+rowFrac*3+phase)*Math.sin(rowFrac*Math.PI),fold=Math.cos(t*4.8-rowFrac*4.2+phase*.4);
    const x=left+(right-left)*t+Math.sin(rowFrac*3.3+t*4+phase*.2)*w*.025;
    const y=h*.5+(rowFrac-.5)*h*.49+envelope*(warp*h*.145+fold*h*.06)*(0.65+data*.35);
    this.xs[col]=x;this.ys[col]=y;
    if(col===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
   }
   ctx.strokeStyle=tint;ctx.globalAlpha=paper?.19:signal?.12:.19;ctx.lineWidth=paper?.55:.65;ctx.stroke();
   for(let col=0;col<cols;col++){
    const t=col/(cols-1),processed=t<fraction;
    ctx.fillStyle=processed?accent:tint;ctx.globalAlpha=processed?.9:.5;
    if(paper)ctx.fillRect(this.xs[col],this.ys[col],2.3,1);
    else{const radius=signal?1.05+Math.pow(Math.sin(t*Math.PI),.75)*1.05:.95;ctx.beginPath();ctx.arc(this.xs[col],this.ys[col],radius,0,Math.PI*2);ctx.fill()}
   }
  }
  if(signal){
   ctx.globalAlpha=.1;ctx.strokeStyle=accent;ctx.lineWidth=1;
   for(let i=0;i<3;i++){ctx.beginPath();ctx.ellipse(w*.5,h*.53,w*(.24+i*.06),h*(.26+i*.01),-.23,0,Math.PI*2);ctx.stroke()}
  }
  ctx.globalAlpha=1;
  if(active&&progress!==null){
   const x=left+(right-left)*fraction;ctx.strokeStyle=accent;ctx.globalAlpha=.3;ctx.setLineDash([2,6]);ctx.beginPath();ctx.moveTo(x,h*.18);ctx.lineTo(x,h*.83);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;ctx.fillStyle=accent;ctx.fillRect(x-2,h*.83,4,4);
  }
 }

 destroy(){this.dead=true;this.stopScheduled();this.observer.disconnect();document.removeEventListener('visibilitychange',this.visibilityChanged);this.reduced.removeEventListener('change',this.motionChanged)}
}
