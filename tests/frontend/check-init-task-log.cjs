const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes=new Map();
function element(){return {style:{},children:[],textContent:'',appendChild(child){this.children.push(child)},replaceChildren(){this.children=[]}}}
const saved=new Map();
const c=vm.createContext({console,Date,localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},document:{getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},createElement:element}});
vm.runInContext(fs.readFileSync('web/static/js/init_task_log.js','utf8'),c);
const cases=[
 ["✓ [交易日历] 完成: {'added': 38, 'updated': 0, 'total': 38}",'success'],
 ["✓ [个股资金流向] 完成: {'added': 0, 'failed': 37, 'coverage': {'expected': 37, 'actual': 0}}",'failed'],
 ["✓ [个股基本面] 完成: {'added': 5, 'failed': 2}",'partial'],
 ["⏭ [个股基本面] 跳过 ✓：数据源无权限 ✗",'skipped'],
 ["✓ [个股资金流向] 完成: {'failed': 0, 'coverage': {'expected': 37, 'actual': 20}}",'partial'],
 ["✗ [个股公告事件] 失败: <img src=x onerror=alert(1)>",'failed']
];
for(const [text,status] of cases)assert.equal(c.classifyInitResult(text),status,text);
const data={status:'running',running:true,currentTask:'初始化个股基本面...',logs:['✓ 初始化任务 INIT_20261104_232228 已启动','✓ 数据初始化完成',...cases.slice(0,2).map(x=>x[0]),'⟳ [个股基本面] 开始初始化']};
c.renderInitTaskLog(data);
assert(nodes.get('init-task-log-summary').textContent.includes('失败 1'));
assert.equal(nodes.get('init-step-log-rows').children[2].children[1].textContent,'失败');
assert.equal(nodes.get('init-step-log-rows').children[3].children[1].textContent,'执行中');
assert(nodes.get('init-task-raw-logs').textContent.includes("'failed': 37"));
const snapshot=saved.get('khunter.initLogSnapshot');assert(snapshot.includes('INIT_20261104_232228'));
c.renderInitTaskLog({status:'completed',running:false,logs:[]});
assert(nodes.get('init-status-text').textContent.includes('部分步骤未成功'));
c.renderInitTaskLog({status:'running',running:true,logs:['✓ 初始化任务 INIT_20261105_123456 已启动']});
assert(!nodes.get('init-task-raw-logs').textContent.includes("'failed': 37"),'new task must clear old results');
console.log('PASS: success/partial/failure/skipped, coverage gaps, false completion warning, rendering, refresh snapshot, task isolation.');
