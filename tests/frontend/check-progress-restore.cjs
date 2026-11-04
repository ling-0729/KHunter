const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
function fixture(file) {
  const elements = new Map();
  const timers = new Map();
  const requests = [];
  let next = 0;
  const context = vm.createContext({
    console: {log(){}, warn(){}, error(...args){throw new Error(args.join(' '));}},
    document: {addEventListener(){}, getElementById(id) {
      if (!elements.has(id)) elements.set(id,{style:{display:'block'},textContent:''});
      return elements.get(id);
    }},
    setInterval(fn){timers.set(++next,fn); return next;},
    clearInterval(id){timers.delete(id);},
    fetch: async (url, options) => {
      assert(!options?.method || options.method === 'GET');
      requests.push(url);
      return {json: async()=>({success:true,data:context.response})};
    }
  });
  vm.runInContext(fs.readFileSync(file,'utf8'),context);
  context.renderInitTaskLog = () => {};
  return {context,elements,timers,requests};
}
(async()=>{
  const init=fixture('web/static/js/init_simple.js');
  vm.runInContext(`updateInitProgressDisplay = data => { lastProgress = data.progress; };
    showInitCompletionStep = () => { rendered = 'completed'; };
    showInitError = () => { rendered = 'failed'; };`,init.context);
  init.context.response={status:'running',running:true,progress:42,currentTask:'K线数据'};
  await init.context.restoreInitProgress();
  assert.equal(init.elements.get('init-step1').style.display,'none');
  assert.equal(init.elements.get('init-step2').style.display,'block');
  assert.equal(init.context.lastProgress,42);
  assert.equal(init.timers.size,1);
  await init.context.restoreInitProgress();
  assert.equal(init.timers.size,1,'re-entering must not duplicate polling');
  init.context.response={status:'completed',running:false,progress:100};
  await init.context.getInitProgress();
  assert.equal(init.context.rendered,'completed');
  assert.equal(init.timers.size,0);
  init.context.response={status:'paused',running:false,paused:true,progress:50};
  await init.context.restoreInitProgress();
  assert.equal(init.timers.size,1,'paused tasks remain visible');
  init.context.response={status:'failed',running:false};
  await init.context.getInitProgress();
  assert.equal(init.context.rendered,'failed');
  assert.equal(init.timers.size,0);
  const update=fixture('web/static/js/data_update.js');
  vm.runInContext(`updateProgressUI = data => { lastStage = data.currentStage; };
    showUpdateCompleted = () => { rendered = 'completed'; };`,update.context);
  update.context.response={status:'running',running:true,currentStage:'K线增量'};
  await update.context.restoreUpdateProgress();
  assert.equal(update.elements.get('update-progress-state').style.display,'block');
  assert.equal(update.context.lastStage,'K线增量');
  assert.equal(update.timers.size,1);
  await update.context.getUpdateProgress();
  assert(update.requests.length>=2,'polling works without taskId after reload');
  update.context.response={status:'completed',running:false};
  await update.context.getUpdateProgress();
  assert.equal(update.timers.size,0);
  assert.equal(update.context.rendered,'completed');
  console.log('PASS: refresh recovery, running/paused/completed/failed states, single timer, update without taskId; all requests read-only.');
})().catch(error=>{console.error(error);process.exitCode=1});
