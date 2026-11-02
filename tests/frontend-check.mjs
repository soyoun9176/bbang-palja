// Run with: node --test tests/frontend-check.mjs
// Exercises the real browser orchestration with controlled HTTP timing.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const source = readFileSync(new URL('../frontend/app.js', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/, '')
  .replace(/\nboot\(\);\s*$/, '');

function fixture({guest = false, storage = new Map()} = {}) {
  const remote = {stock: 3, score: 10, approved: false, modal: false};
  const root = {innerHTML: ''};
  let renderCount = 0;
  const requests = [];
  const response = (body, status = 200) => ({ok: status < 400, status, json: async () => body});
  const context = {
    crypto: {getRandomValues: bytes => webcrypto.getRandomValues(bytes)},
    location: {pathname: '/', hash: '#shop'}, history: {replaceState() {}},
    localStorage: {getItem: () => guest ? null : 'token-A', removeItem() {}, setItem() {}},
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    window: {KAMBO_CONFIG: {apiBase: ''}, addEventListener() {}},
    document: {hidden: false, activeElement: {tagName: 'BODY'}, addEventListener() {}, querySelectorAll: () => [], getElementById: () => null, querySelector: selector => selector === '#app' ? root : selector === '.modal' && remote.modal ? {} : null},
    initAdmin() {}, renderAdmin() {}, renderStaffLogin() {}, handleAdminClick() {}, handleAdminSubmit() {},
    setInterval: fn => {context.poll = fn;}, setTimeout: fn => queueMicrotask(fn),
    recordRender: () => renderCount++,
  };
  context.normalFetch = async (path, options = {}) => {
    const token = options.headers?.Authorization;
    const id = token === 'Bearer token-B' ? 2 : 1;
    const user = {id, name: `구매자${id}`, role: 'buyer', score: 0, dice_balance: remote.approved ? 1 : 2, rewards_claimed: 0};
    if (path === '/api/config') return response({demo: false, reward_step: 10});
    if (path === '/api/products') return response({products: [{id: 1, stock: remote.stock}]});
    if (path === '/api/auth/me') return response({user});
    if (path === '/api/orders') return response({orders: [{id: 1, status: remote.approved ? 'approved' : 'pending', quantity: 1}]});
    if (path === '/api/rewards') return response({rewards: []});
    if (path === '/api/leaderboard') return response({leaders: [{name: '다른구매자', score: remote.score}], neighbors: [], me: {rank: 1}, total_participants: 2});
    throw new Error(`Unexpected route: ${path}`);
  };
  context.fetch = async (path, options) => {
    requests.push({path, ...options});
    return context.fetchOverride ? context.fetchOverride(path, options) : context.normalFetch(path, options);
  };
  vm.createContext(context);
  vm.runInContext(source + '\nconst renderPage = render; render = recordRender; toast = () => {}; modal = () => {};', context);
  return {
    context, remote, storage, requests, response, root,
    run: script => vm.runInContext(script, context),
    get renders() {return renderCount;},
  };
}

test('polling renders changed stock and leaderboard, including guest stock', async () => {
  for (const guest of [false, true]) {
    const f = fixture({guest});
    await f.run('refresh()');
    f.remote.stock = 1;
    f.remote.score = 20;
    await f.context.poll();
    assert.equal(f.run('state.products[0].stock'), 1);
    if (!guest) assert.equal(f.run('state.leaderboard.leaders[0].score'), 20);
    assert.equal(f.renders, 1);
  }
});

test('buyers sign in before seeing purchase or event content', async () => {
  const f = fixture({guest: true});
  await f.run('refresh();');
  f.run('renderPage()');
  assert.match(f.root.innerHTML, /id="buyer-auth"/);
  assert.doesNotMatch(f.root.innerHTML, /class="product-list"|class="dice-stage|class="primary-nav"/);
});

test('purchase and event have separate content and only two main menus', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run('renderPage()');
  assert.match(f.root.innerHTML, /aria-label="현판 빵 목록"/);
  assert.doesNotMatch(f.root.innerHTML, /현재 점수|랜덤 빵 뽑기|주사위 1개 굴리기/);
  const nav = f.root.innerHTML.match(/<nav class="primary-nav"[^>]*>(.*?)<\/nav>/s)[1];
  assert.equal((nav.match(/<button/g) || []).length, 2);
  f.run("state.route='dice'; renderPage()");
  assert.match(f.root.innerHTML, /주사위 1개 굴리기/);
  assert.match(f.root.innerHTML, /현재 점수/);
  assert.doesNotMatch(f.root.innerHTML, /현판 빵 목록|구매 요청하기/);
});

test('reaching ten points opens level-up without claiming bread automatically', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run("state.config.reward_step=10; state.user.score=8; state.route='dice'");
  let prompt='';
  f.context.captureModal = html => {prompt=html;};
  f.run('modal = captureModal');
  f.context.fetchOverride = async (path, options) => {
    if(path==='/api/dice/roll') return f.response({value: 3, score: 11, dice_balance: 1});
    if(path==='/api/auth/me') return f.response({user:{id:1,name:'구매자1',role:'buyer',score:11,dice_balance:1,rewards_claimed:0}});
    return f.context.normalFetch(path, options);
  };
  await f.run('rollDice()');
  assert.match(prompt, /10점 달성/);
  assert.match(prompt, /data-action="claim-reward"/);
  assert.match(prompt, /character-unknown/);
  assert.doesNotMatch(prompt, /alchemist-1\.svg|견습 연금술사/);
  assert.equal(f.requests.filter(r=>r.path==='/api/rewards/claim').length,0);
});

test('a change received during a modal renders after closing it', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.remote.modal = true;
  f.remote.approved = true;
  await f.context.poll();
  assert.equal(f.renders, 0);
  f.remote.modal = false;
  await f.context.poll();
  assert.equal(f.renders, 1);
  assert.equal(f.run('state.orders[0].status'), 'approved');
});

test('request IDs work when crypto.randomUUID is unavailable', () => {
  const f = fixture();
  const first = f.run('requestId()');
  assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(first, f.run('requestId()'));
});

test('checkout retries an uncertain request with the same ID after rendering', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run('state.cart = {1: 2}');
  const identities = [];
  f.context.fetchOverride = async (path, options) => {
    if (path === '/api/orders' && options.method === 'POST') {
      identities.push(JSON.parse(options.body).request_id);
      if (identities.length === 1) throw new TypeError('Simulated lost HTTP response');
      return f.response({order: {id: 9, quantity: 2, total: 5000}});
    }
    return f.context.normalFetch(path, options);
  };
  await f.run('checkout({disabled: false})');
  await f.run('checkout({disabled: false})');
  assert.equal(identities.length, 2);
  assert.equal(identities[0], identities[1]);
  assert.equal(f.run('cartCount()'), 0);
  assert.equal(f.storage.size, 0);
});

test('a delayed response from an older login cannot replace the current user', async () => {
  const f = fixture();
  let release;
  f.context.fetchOverride = (path, options) => {
    if (path === '/api/auth/me' && options.headers.Authorization === 'Bearer token-A') {
      return new Promise(resolve => {release = resolve;});
    }
    return f.context.normalFetch(path, options);
  };
  const older = f.run('refresh()');
  f.run("state.token = 'token-B'");
  await f.run('refresh()');
  release(f.response({user: {id: 1, name: '이전구매자', role: 'buyer'}}));
  await older;
  assert.equal(f.run('state.user.id'), 2);
  assert.equal(f.run('state.token'), 'token-B');
});

test('an expired response from an older login cannot log out the current user', async () => {
  const f = fixture();
  let release;
  f.context.fetchOverride = (path, options) => {
    if (path === '/api/auth/me' && options.headers.Authorization === 'Bearer token-A') {
      return new Promise(resolve => {release = resolve;});
    }
    return f.context.normalFetch(path, options);
  };
  const olderPoll = f.context.poll();
  f.run("state.token = 'token-B'");
  await f.run('refresh()');
  release(f.response({error: '이전 세션이 만료되었습니다.'}, 401));
  await olderPoll;
  assert.equal(f.run('state.token'), 'token-B');
  assert.equal(f.run('state.user.id'), 2);
});

test('event entry defaults to ranking and its action follows dice balance', async () => {
  const f=fixture();
  await f.run('refresh()');
  f.run('renderPage()');
  assert.match(f.root.innerHTML, /data-route="orders"[^>]*>주문 내역/);
  assert.doesNotMatch(f.root.innerHTML, /내 주문/);
  assert.match(f.run('navButton(buyerNav[1])'), /data-route="ranking"/);
  f.run("state.route='ranking'; renderPage()");
  assert.match(f.root.innerHTML, /최고의 연금술사 TOP 3/);
  assert.match(f.root.innerHTML, /data-route="dice"[^>]*>.*주사위 굴리기 · 2개/);
  assert.doesNotMatch(f.root.innerHTML, /purchase-cta/);
  f.run('state.user.dice_balance=0; renderPage()');
  assert.match(f.root.innerHTML, /purchase-cta full" data-action="navigate" data-route="shop"/);
  assert.match(f.root.innerHTML, /빵 구매하고 주사위 얻기/);
  f.run("state.route='dice'; renderPage()");
  assert.match(f.root.innerHTML, /빵 구매하고 주사위 얻기/);
  assert.doesNotMatch(f.root.innerHTML, /data-action="roll-dice"/);
});

test('score milestones wait for a successful bread claim before changing character', async () => {
  const f=fixture();
  await f.run('refresh()');
  f.run("state.route='ranking'; state.user.score=9; renderPage()");
  assert.match(f.root.innerHTML, /1점 더 모으면 랜덤 빵 증정!/);
  assert.equal((f.root.innerHTML.match(/character-unknown/g)||[]).length,6);
  assert.doesNotMatch(f.root.innerHTML,/alchemist-[0-5]\.svg/);
  assert.doesNotMatch(f.root.innerHTML, /data-action="claim-reward"/);
  f.run('state.user.score=10; renderPage()');
  assert.equal(f.run('eventProgress().level'), 0);
  assert.match(f.root.innerHTML, /레벨업하고 빵 받기/);
  assert.match(f.root.innerHTML, /현재 점수 <strong>10점/);
  f.run('state.user.rewards_claimed=1; renderPage()');
  assert.equal(f.run('eventProgress().level'), 1);
  assert.match(f.root.innerHTML,/alchemist-1\.svg/);
  assert.doesNotMatch(f.root.innerHTML,/alchemist-[2-5]\.svg/);
  assert.equal((f.root.innerHTML.match(/character-unknown/g)||[]).length,4);
  assert.match(f.root.innerHTML, /10점 더 모으면 랜덤 빵 증정!/);
  f.run('state.user.score=60; state.user.rewards_claimed=5; renderPage()');
  assert.equal(f.run('eventProgress().level'), 5);
  assert.match(f.root.innerHTML, /빵 보상 받기/);
  assert.doesNotMatch(f.root.innerHTML, /레벨업하고 빵 받기/);
});

test('level-up waits for one server claim and reveals character together with bread', async () => {
  const f=fixture();
  await f.run('refresh()');
  f.run('state.user.score=10');
  let release, prompt='';
  let user={id:1,name:'구매자1',role:'buyer',score:10,dice_balance:1,rewards_claimed:0,level:0};
  f.context.captureModal=html=>{prompt=html;};
  f.run('modal=captureModal');
  f.context.fetchOverride=async (path,options)=>{
    if(path==='/api/rewards/claim')return new Promise(resolve=>{release=()=>{
      user={...user,rewards_claimed:1,level:1};
      resolve(f.response({user,reward:{id:1,product_id:1,product_name:'플레인 휘낭시에',threshold:10}}));
    };});
    if(path==='/api/auth/me')return f.response({user});
    return f.context.normalFetch(path,options);
  };
  const first=f.run('claimReward({disabled:false})');
  await f.run('claimReward({disabled:false})');
  assert.equal(f.requests.filter(r=>r.path==='/api/rewards/claim').length,1);
  assert.equal(f.run('eventProgress().level'),0);
  release();
  await first;
  assert.equal(f.run('eventProgress().level'),1);
  assert.match(prompt,/LEVEL UP!/);
  assert.match(prompt,/Lv. 1 견습 연금술사/);
  assert.match(prompt,/alchemist-1\.svg/);
  assert.doesNotMatch(prompt,/character-unknown/);
  assert.match(prompt,/함께 받은 랜덤 빵/);
  assert.match(prompt,/플레인 휘낭시에/);
});

const adminSource=readFileSync(new URL('../frontend/admin.js',import.meta.url),'utf8').replace(/\bexport /g,'');
function adminFixture() {
  const requests=[],messages=[];
  const listeners={};
  const state={user:{id:1},route:'events',products:[],staffData:{users:[{id:10,name:'등록사용자'}],stats:{milk_stock:2},
    products:[{id:101,name:'플레인 휘낭시에',stock:2,preorder_stock:0,price:2800,dice_per_unit:1},
              {id:112,name:'우유',stock:2,preorder_stock:0,price:2000,dice_per_unit:0}]}};
  const context={document:{addEventListener(type,listener){listeners[type]=listener;},querySelector:()=>null},FormData:class {
    constructor(form){this.values=form.values;}
    get(key){return this.values.get(key)??null;}
    has(key){return this.values.has(key);}
  }};
  let identity=0;
  context.shared={state,esc:String,icon:()=>'',money:String,time:()=>'',requestId:()=>`request-${++identity}`,
    api:async(path,options)=>{requests.push(JSON.parse(JSON.stringify({path,...options})));return context.respond?context.respond(path,options):{};},
    submitButton(){},refresh:async()=>{},render(){},toast:message=>messages.push(message),closeModal(){}};
  vm.createContext(context);
  vm.runInContext(adminSource+'\ninitAdmin(shared);',context);
  return {state,requests,messages,context,listeners,run:script=>vm.runInContext(script,context),
    async submit(fields,id='admin-instagram'){
      context.form={id,values:new Map(Object.entries(fields)),isConnected:true,
        querySelector:()=>null,reset(){}};
      await vm.runInContext('handleAdminSubmit(form)',context);
    }};
}

function manualReservation(overrides={}) {
  return {id:7,name:'등록사용자',phone:'01012345678',status:'reserved',total:7600,dice_quantity:2,
    items:[{product_id:101,name:'플레인 휘낭시에',quantity:2,price:2800},{product_id:112,name:'우유',quantity:1,price:2000}],
    order:null,...overrides};
}

test('manual sales switch between the existing walk-in form and reservation lookup',async()=>{
  const f=adminFixture();f.state.route='sales';
  let html=f.run('renderAdmin()');
  assert.match(html,/현장 구매/);
  assert.match(html,/예약한 빵 수령/);
  assert.match(html,/id="admin-manual-sale"/);
  assert.match(html,/data-sale-product="101"/);
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  html=f.run('renderAdmin()');
  assert.match(html,/id="admin-manual-preorder-lookup"/);
  assert.match(html,/예약자 이름/);
  assert.match(html,/예약 전화번호/);
  assert.doesNotMatch(html,/data-sale-product|id="admin-manual-sale"/);
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'walkin'}})");
  assert.match(f.run('renderAdmin()'),/id="admin-manual-sale"/);
});

test('reservation lookup shows original items and completes for the matching buyer',async()=>{
  const f=adminFixture();f.state.route='sales';
  const reservation=manualReservation();
  f.context.respond=async path=>path.endsWith('/lookup')?{reservation}:{
    reservation:{...reservation,status:'approved',order:{id:9,status:'approved',user_id:10}},
    order:{id:9,dice_quantity:2},already_completed:false};
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.submit({name:' 등록사용자 ',phone:'010-1234-5678'},'admin-manual-preorder-lookup');
  assert.deepEqual(f.requests[0],{path:'/api/staff/preorders/lookup',method:'POST',body:{name:'등록사용자',phone:'010-1234-5678'}});
  let html=f.run('renderAdmin()');
  assert.match(html,/플레인 휘낭시에 × 2/);
  assert.match(html,/우유 × 1/);
  assert.match(html,/7600원/);
  assert.match(html,/주사위 2개를 지급/);
  assert.match(html,/name="user_id" value="10"/);
  assert.doesNotMatch(html,/name="pin"|data-sale-product/);
  await f.submit({user_id:'10'},'admin-manual-preorder-complete');
  assert.deepEqual(f.requests[1],{path:'/api/staff/preorders/7/complete',method:'POST',body:{
    name:'등록사용자',phone:'01012345678',user_id:10,request_id:'request-1'}});
  assert.match(f.messages[0],/수령을 완료.*주사위 2개/);
  html=f.run('renderAdmin()');
  assert.match(html,/이미 수령 완료한 예약입니다. 주문 #9/);
  assert.doesNotMatch(html,/id="admin-manual-preorder-complete"/);
});

test('reservation pickup creates a new buyer PIN only when no account exists',async()=>{
  const f=adminFixture();f.state.route='sales';
  const reservation=manualReservation({name:'새예약자',dice_quantity:0,total:2000,
    items:[{product_id:112,name:'우유',quantity:1,price:2000}]});
  f.context.respond=async path=>path.endsWith('/lookup')?{reservation}:{reservation:{...reservation,status:'approved'},
    order:{id:9,dice_quantity:0},already_completed:false};
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.submit({name:'새예약자',phone:reservation.phone},'admin-manual-preorder-lookup');
  const html=f.run('renderAdmin()');
  assert.match(html,/name="pin" type="password"/);
  assert.match(html,/우유는 주사위를 지급하지 않습니다/);
  assert.doesNotMatch(html,/name="user_id"/);
  await f.submit({pin:'2345'},'admin-manual-preorder-complete');
  assert.deepEqual(f.requests[1].body,{name:'새예약자',phone:reservation.phone,pin:'2345',request_id:'request-1'});
  assert.doesNotMatch(f.messages[0],/주사위/);
  assert.doesNotMatch(f.run('renderAdmin()'),/id="admin-manual-preorder-complete"/);
});

test('a queued pickup uses its linked buyer and an approved queue order cannot be completed again',async()=>{
  const f=adminFixture();f.state.route='sales';
  const reservation=manualReservation({name:'연결된구매자',status:'pending',order:{id:9,user_id:21,status:'pending'}});
  f.context.respond=async()=>({reservation});
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.submit({name:reservation.name,phone:reservation.phone},'admin-manual-preorder-lookup');
  let html=f.run('renderAdmin()');
  assert.match(html,/수령 요청 접수됨/);
  assert.match(html,/name="user_id" value="21"/);
  f.state.staffData.orders=[{id:9,reservation_id:7,user_id:21,status:'approved'}];
  html=f.run('renderAdmin()');
  assert.match(html,/이미 수령 완료/);
  assert.doesNotMatch(html,/id="admin-manual-preorder-complete"/);
});

test('editing a reservation lookup or switching sale type ignores an older response',async()=>{
  for(const change of ['input','switch']) {
    const f=adminFixture();f.state.route='sales';
    let release;
    f.context.respond=()=>new Promise(resolve=>{release=()=>resolve({reservation:manualReservation()});});
    await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
    const lookup=f.submit({name:'등록사용자',phone:'01012345678'},'admin-manual-preorder-lookup');
    if(change==='input')f.listeners.input({target:{name:'name',value:'다른예약자',closest:selector=>selector==='#admin-manual-preorder-lookup'?{}:null}});
    else await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'walkin'}})");
    release();await lookup;
    assert.doesNotMatch(f.run('renderAdmin()'),/id="manual-preorder-result"/);
    assert.equal(f.run('manualReservation'),null);
  }
});

test('Instagram certification selects a registered user and defaults both benefits on',()=>{
  const f=adminFixture();
  const html=f.run('renderAdmin()');
  assert.match(html,/등록 사용자/);
  assert.match(html,/<option value="10"[^>]*>등록사용자/);
  assert.match(html,/type="checkbox" name="dice" value="1" checked/);
  assert.match(html,/type="checkbox" name="milk_quantity" value="1" checked/);
  assert.match(html,/인스타 이벤트 인증 완료/);
  assert.doesNotMatch(html,/<select[^>]*name="(?:dice|milk_quantity)"/);
  assert.doesNotMatch(html,/<input[^>]*name="(?:name|pin)"/);
});

test('Instagram checkbox combinations submit explicit zeros for unchecked benefits',async()=>{
  for(const milk of [false,true])for(const dice of [false,true]) {
    const f=adminFixture();
    await f.submit({user_id:'10',...(milk?{milk_quantity:'1'}:{}),...(dice?{dice:'1'}:{})});
    assert.equal(f.requests.length,1);
    assert.deepEqual(f.requests[0],{path:'/api/staff/instagram',method:'POST',body:{
      user_id:10,milk_quantity:milk?1:0,dice:dice?1:0,request_id:'request-1'}});
    assert.equal(f.messages[0],'인스타 이벤트 인증과 선택한 지급 내역을 기록했어요.');
  }
});

test('milk uses the product inventory table and normal stock adjustment',()=>{
  const f=adminFixture();
  f.state.route='inventory';
  const html=f.run('renderAdmin()');
  assert.match(html,/<td><strong>우유<\/strong><\/td><td>2<\/td>/);
  assert.match(html,/data-product="112"/);
  assert.doesNotMatch(html,/inventory-milk|우유 재고 수정/);
});

test('milk purchase and mixed order messages use bread dice rather than total quantity',async()=>{
  const f=fixture();
  await f.run('refresh()');
  f.run("state.route='orders'; state.orders=[{id:1,type:'walkin',status:'approved',quantity:3,dice_quantity:2,total:7600,items:[{name:'빵',quantity:2,price:2800},{name:'우유',quantity:1,price:2000}]}]; renderPage()");
  assert.match(f.root.innerHTML,/구매 완료 · 주사위 2개 지급/);
  assert.doesNotMatch(f.root.innerHTML,/주사위 3개 지급/);
  f.run('state.orders[0].dice_quantity=0; renderPage()');
  assert.match(f.root.innerHTML,/우유는 주사위 미지급/);
  f.run("state.route='shop'; state.products=[{id:112,name:'우유',price:2000,stock:2,dice_per_unit:0}]; state.cart={112:2}; renderPage()");
  assert.match(f.root.innerHTML,/주사위 미지급/);
  let prompt='';
  f.context.captureModal=html=>{prompt=html;};f.run('modal=captureModal');
  f.context.fetchOverride=async(path,options)=>{
    if(path==='/api/orders'&&options.method==='POST')return f.response({order:{id:9,quantity:2,dice_quantity:0,total:4000}});
    return f.context.normalFetch(path,options);
  };
  await f.run('checkout({disabled:false})');
  assert.match(prompt,/우유 구매에는 주사위가 지급되지 않아요/);
  assert.doesNotMatch(prompt,/주사위 2개/);
});
