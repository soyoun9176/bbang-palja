// Run with: node --test tests/frontend-check.mjs
// Exercises the real browser orchestration with controlled HTTP timing.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const profileSource = readFileSync(new URL('../frontend/profile.js', import.meta.url),'utf8').replace(/\bexport /g,'');
const source = profileSource + '\n' + readFileSync(new URL('../frontend/app.js', import.meta.url), 'utf8')
  .replace(/^import[^\n]+\n/gm, '')
  .replace(/\nboot\(\);\s*$/, '');

function fixture({guest = false, storage = new Map(), admin=false} = {}) {
  const remote = {stock: 3, score: 10, approved: false, modal: false};
  const root = {innerHTML: ''};
  let renderCount = 0;
  const requests = [];
  const routeChanges = [];
  const response = (body, status = 200) => ({ok: status < 400, status, json: async () => body});
  const context = {
    URLSearchParams,
    crypto: {getRandomValues: bytes => webcrypto.getRandomValues(bytes)},
    location: {pathname: admin?'/admin/':'/', hash: '#shop'}, history: {replaceState(...args) {routeChanges.push(args[2]);}},
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
    const user = {id, name: `구매자${id}`, role: 'buyer', score: 0, dice_balance: remote.approved ? 1 : 2, rewards_claimed: 0,
      ...(remote.profileCustomized===undefined?{}:{profile_customized:remote.profileCustomized}),...(remote.avatar?{avatar:remote.avatar}:{}),
      ...(remote.unlockedHairpins?{unlocked_hairpins:remote.unlockedHairpins}:{}),
      ...(remote.badges?{badges:remote.badges}:{}),...(remote.titles?{titles:remote.titles}:{}),...(remote.achievements?{achievements:remote.achievements}:{}),...(Object.hasOwn(remote,'equippedTitle')?{equipped_title:remote.equippedTitle}:{}),...(Object.hasOwn(remote,'equippedBadge')?{equipped_badge:remote.equippedBadge}:{})};
    if (path === '/api/config') return response({demo: false, reward_step: 10});
    if (path === '/api/products') return response({products: [{id: 1, stock: remote.stock}]});
    if (path === '/api/auth/me') return response({user});
    if (path === '/api/orders') return response({orders: [{id: 1, status: remote.approved ? 'approved' : 'pending', quantity: 1}]});
    if (path === '/api/rewards') return response({rewards: []});
    if (path === '/api/event-notices') return response({notices: remote.notices || []});
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
    context, remote, storage, requests, response, root, routeChanges,
    run: script => vm.runInContext(script, context),
    get renders() {return renderCount;},
  };
}

const chosenAvatar={face_shape:'financier',skin:'warm',expression:'wink',glasses:'sunglasses',hairpin:'none'};
test('signup collects nickname and phone while login uses phone and profile omits it',()=>{
  const f=fixture();
  const signup=f.run("buyerAuthForm('register')"),login=f.run("buyerAuthForm('login')");
  assert.match(signup,/이름\(닉네임\)/);
  for(const name of ['name','phone','pin'])assert.match(signup,new RegExp(`name="${name}"`));
  assert.doesNotMatch(login,/name="name"/);
  assert.match(login,/name="phone"/);
  assert.doesNotMatch(f.run("profileEditor({id:1,name:'닉네임',phone:'010-1234-5678'})"),/010-1234-5678|name="phone"/);
});

test('phone formatting accepts only exact 010 digits or canonical dashes',()=>{
  const f=fixture();
  assert.equal(f.run("normalizePhone('01012345678')"),'010-1234-5678');
  assert.equal(f.run("normalizePhone('010-1234-5678')"),'010-1234-5678');
  for(const phone of ['010 1234 5678','010-12345678','0101234567','01112345678','01012345678 ','01012345678\n','010-1234-567a','０１０１２３４５６７８']){
    f.context.badPhone=phone;assert.throws(()=>f.run('normalizePhone(badPhone)'),/전화번호/);
  }
});

test('login sends normalized phone and password without nickname',async()=>{
  const f=fixture({guest:true});f.context.authForm={dataset:{mode:'login'}};
  f.run('closeModal=()=>{}');
  f.context.fetchOverride=(path,options)=>path==='/api/auth/login'?f.response({token:'token-A',user:{id:1,name:'닉네임'}}):f.context.normalFetch(path,options);
  await f.run("signInBuyer(authForm,{phone:'01012345678',pin:'1234'})");
  assert.deepEqual(JSON.parse(f.requests.find(r=>r.path==='/api/auth/login').body),{phone:'010-1234-5678',pin:'1234'});
});

function pickupFixture(){
  const f=fixture();
  f.context.fetchOverride=async(path,options)=>{
    if(path==='/api/auth/me'){
      const base=await (await f.context.normalFetch(path,options)).json();
      return f.response({...base,pickup_defaults:{name:base.user.name,phone:base.user.id===1?'010-1234-5678':'010-9999-8888'}});
    }
    return f.context.normalFetch(path,options);
  };
  return f;
}

test('pickup form defaults to the logged-in nickname and phone and both fields are editable',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  const html=f.run('renderPickup()');
  assert.match(html,/id="preorder-name"[^>]*value="구매자1"/);
  assert.match(html,/id="preorder-phone"[^>]*value="010-1234-5678"/);
  assert.doesNotMatch(html,/readonly|가입한 전화번호의 예약만/);
  assert.doesNotMatch(f.run('profileEditor(state.user)'),/010-1234-5678|name="phone"/);
});

test('edited pickup inputs survive refreshes without changing account defaults',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  f.run("state.reservation={id:1};editPickupField('name','다른 예약자');editPickupField('phone','01055556666')");
  await f.run('refresh()');
  const html=f.run('renderPickup()');
  assert.match(html,/id="preorder-name"[^>]*value="다른 예약자"/);
  assert.match(html,/id="preorder-phone"[^>]*value="01055556666"/);
  assert.equal(f.run('state.reservation'),null);
  assert.equal(f.run('state.user.name'),'구매자1');
  assert.equal(f.run('state.pickupDefaults.phone'),'010-1234-5678');
});

test('pickup lookup submits the edited pair with normalized phone and retains the query',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  const normal=f.context.fetchOverride;
  f.context.fetchOverride=(path,options)=>path.startsWith('/api/preorders/lookup?')?
    f.response({reservation:{id:7,name:'예약한 실명',items:[],total:2800}}):normal(path,options);
  await f.run("lookupPreorder({name:' 예약한 실명 ',phone:'01055556666'})");
  const request=f.requests.find(r=>r.path.startsWith('/api/preorders/lookup?'));
  const query=new URL('http://test'+request.path).searchParams;
  assert.equal(query.get('name'),'예약한 실명');assert.equal(query.get('phone'),'010-5555-6666');
  assert.equal(request.headers.Authorization,'Bearer token-A');
  assert.equal(f.run('state.reservation.id'),7);
  assert.equal(f.run('state.pickupDraft.phone'),'010-5555-6666');
  assert.equal(f.run('state.pickupDefaults.phone'),'010-1234-5678');
});

test('a failed lookup clears the previous reservation and preserves edited inputs',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  f.run('state.reservation={id:7}');
  f.context.fetchOverride=()=>f.response({error:'해당 예약이 없습니다.'},404);
  await assert.rejects(f.run("lookupPreorder({name:'다른 이름',phone:'01055556666'})"),/해당 예약이 없습니다/);
  assert.equal(f.run('state.reservation'),null);
  assert.equal(f.run('state.pickupDraft.name'),'다른 이름');
});

test('a response from an earlier pickup query cannot overwrite a later edit',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  let release;
  f.context.fetchOverride=()=>new Promise(resolve=>{release=resolve;});
  const lookup=f.run("lookupPreorder({name:'첫 예약자',phone:'01055556666'})");
  f.run("editPickupField('name','두번째 예약자')");
  release(f.response({reservation:{id:7,name:'첫 예약자'}}));await lookup;
  assert.equal(f.run('state.reservation'),null);
  assert.equal(f.run('state.pickupDraft.name'),'두번째 예약자');
});

test('switching accounts resets the pickup draft to the new accounts own defaults',async()=>{
  const f=pickupFixture();await f.run('refresh()');
  f.run("editPickupField('name','조회 중인 예약자');editPickupField('phone','01055556666');state.token='token-B'");
  await f.run('refresh()');
  assert.equal(f.run('state.pickupDraft'),null);
  assert.equal(f.run('pickupValues().name'),'구매자2');
  assert.equal(f.run('pickupValues().phone'),'010-9999-8888');
  assert.equal(f.run('state.reservation'),null);
});

test('guest entry is available from login and signup and only asks for a buyer name',()=>{
  const f=fixture({guest:true});
  for(const mode of ['login','register']){
    f.run(`state.authMode='${mode}'`);
    assert.match(f.run('renderBuyerLogin()'),/계정 없이 빵만 구매/);
  }
  f.run("state.route='guest';state.guestName='<구매자>';state.products=[]");
  const html=f.run('renderShop()');
  assert.match(html,/name="guest_name"/);
  assert.match(html,/&lt;구매자&gt;/);
  assert.doesNotMatch(html,/name="phone"|name="pin"|예약한 빵 수령/);
  assert.doesNotMatch(f.run("shell(renderShop())"),/data-route="ranking"/);
});

test('guest checkout keeps its receipt and polls only that order without authenticating an account',async()=>{
  const f=fixture({guest:true}),stored=new Map();
  f.context.localStorage.setItem=(key,value)=>stored.set(key,value);
  f.run("state.route='guest';state.guestName=' 빵손님 ';state.cart={1:1}");
  let receipt;
  const order={id:8,user_id:null,customer_name:'빵손님',items:[],status:'pending',quantity:1,total:2800,dice_quantity:0};
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/guest/orders'){receipt=JSON.parse(options.body).request_id;return f.response({order});}
    if(path==='/api/guest/orders/8'){assert.equal(options.headers.Authorization,`Bearer ${receipt}`);return f.response({order});}
    return f.context.normalFetch(path,options);
  };
  await f.run('checkout({disabled:false})');
  const body=JSON.parse(f.requests.find(r=>r.path==='/api/guest/orders').body);
  assert.equal(body.name,'빵손님');
  assert.equal(body.phone,undefined);assert.equal(body.pin,undefined);
  assert.deepEqual(JSON.parse(stored.get('kambo.guest.orders')),[{id:8,token:receipt}]);
  assert.equal(f.run('state.route'),'guest-orders');
  assert.equal(f.run('state.token'),null);
  assert.equal(f.requests.some(r=>['/api/auth/me','/api/orders','/api/auth/register'].includes(r.path)),false);
  f.run("state.orders[0].status='approved'");
  const html=f.run('renderOrders()');
  assert.match(html,/빵손님 님/);assert.match(html,/구매가 완료/);
  assert.doesNotMatch(html,/이벤트 참여하기|주사위 1개 지급/);
});

test('guest checkout validates name and reuses its request key after a lost response',async()=>{
  const f=fixture({guest:true});
  f.run("state.route='guest';state.cart={1:1};closeModal=()=>{}");
  await f.run('checkout({disabled:false})');
  assert.equal(f.requests.length,0);
  f.run("state.guestName='손님'");
  let attempt=0;
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/guest/orders'){if(++attempt===1)throw new Error('connection lost');return f.response({order:{id:1,user_id:null,customer_name:'손님',quantity:1,total:2800}});}
    if(path==='/api/guest/orders/1')return f.response({order:{id:1,user_id:null,customer_name:'손님',quantity:1,total:2800}});
    return f.context.normalFetch(path,options);
  };
  await f.run('checkout({disabled:false})');await f.run('checkout({disabled:false})');
  const requests=f.requests.filter(r=>r.path==='/api/guest/orders');
  assert.equal(requests.length,2);
  assert.equal(JSON.parse(requests[0].body).request_id,JSON.parse(requests[1].body).request_id);
});

test('staff guest sale sends only buyer name, items and explicit guest mode',async()=>{
  const f=adminFixture();f.state.route='sales';
  await f.run("handleAdminClick('admin-customer-mode',{dataset:{mode:'guest'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/계정 없이 판매/);
  assert.match(html,/name="name"/);assert.doesNotMatch(html,/name="phone"|name="pin"|name="user_id"/);
  f.context.form={id:'admin-manual-sale',values:new Map([['guest','1'],['name','현장 손님']]),
    querySelector:()=>null,querySelectorAll:()=>[{dataset:{saleProduct:'101'},value:'2'}],reset(){}};
  f.context.respond=async()=>({order:{id:9,user_id:null,dice_quantity:0}});
  await f.run('handleAdminSubmit(form)');
  assert.deepEqual(f.requests[0].body,{guest:true,name:'현장 손님',items:[{product_id:101,quantity:2}],request_id:'request-1'});
  assert.match(f.messages[0],/비회원 수기 판매 #9/);
});

test('staff guest preorder pickup does not ask for an account or PIN',async()=>{
  const f=adminFixture();f.state.route='sales';
  f.context.respond=async()=>({reservation:manualReservation()});
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:'등록사용자',phone:'01012345678'});
  await f.run("handleAdminClick('admin-pickup-mode',{dataset:{mode:'guest'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/계정 없이 수령/);assert.match(html,/name="guest"/);
  assert.doesNotMatch(html,/name="user_id"|name="pin"/);
  f.context.respond=async()=>({reservation:manualReservation({status:'approved'}),order:{id:9,user_id:null,dice_quantity:0}});
  await f.submit({guest:'1'},'admin-manual-preorder-complete');
  assert.deepEqual(f.requests[1].body,{name:'등록사용자',phone:'01012345678',guest:true,request_id:'request-1'});
});

test('event manual grants default to an account and keep the normal fulfillment queue separate',async()=>{
  const f=adminFixture();
  assert.match(f.run('renderAdmin()'),/data-tab="manual">임의 지급/);
  assert.doesNotMatch(f.run('renderAdmin()'),/id="admin-manual-grant"/);
  await f.run("handleAdminClick('admin-event-tab',{dataset:{tab:'manual'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/id="admin-manual-grant"/);
  assert.match(html,/name="user_id"/);
  assert.match(html,/name="reason"[^>]*required/);
  assert.match(html,/data-kind="score"/);
  assert.doesNotMatch(html,/name="name"|name="phone"|name="pin"/);
});

test('guest manual grants request a name and block score and profile gifts in the UI',async()=>{
  const f=adminFixture();f.run("eventTab='manual'");
  await f.run("handleAdminClick('admin-grant-recipient',{dataset:{mode:'guest'}})");
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'score'}})");
  let html=f.run('renderAdmin()');
  assert.match(html,/name="name"/);assert.match(html,/name="guest"/);
  assert.match(html,/data-kind="score"[^>]*disabled/);
  assert.doesNotMatch(html,/name="user_id"|name="points"|name="phone"|name="pin"/);
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'gift'}})");
  html=f.run('renderAdmin()');
  assert.match(html,/<option value="sunglasses"[^>]*disabled/);
});

test('account manual bread grants send quantity and reason and display the audit record',async()=>{
  const f=adminFixture();f.run("eventTab='manual'");
  const grant={id:4,user_id:10,customer_name:'등록사용자',kind:'bread',product_id:101,
    item_name:'플레인 휘낭시에',quantity:2,points:0,reason:'지급 오류 보완',staff_name:'담당자',created_at:'2026-11-07T00:00:00Z'};
  f.context.respond=async()=>{f.state.staffData.manual_grants=[grant];return {grant};};
  await f.submit({user_id:'10',product_id:'101',quantity:'2',reason:'지급 오류 보완'},'admin-manual-grant');
  assert.deepEqual(f.requests[0],{path:'/api/staff/manual-event-grants',method:'POST',body:{
    kind:'bread',reason:'지급 오류 보완',user_id:10,quantity:2,product_id:101,request_id:'request-1'}});
  const html=f.run('renderAdmin()');
  assert.match(html,/임의 지급 기록 · 1건/);
  assert.match(html,/플레인 휘낭시에 × 2개/);
  assert.match(html,/지급 오류 보완/);assert.match(html,/담당자/);
  assert.match(f.messages[0],/임의 지급 #4/);
});

test('guest custom prize grants only send a name and gift details',async()=>{
  const f=adminFixture();f.run("eventTab='manual'");
  await f.run("handleAdminClick('admin-grant-recipient',{dataset:{mode:'guest'}})");
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'gift'}})");
  f.run("grantGift='custom'");
  assert.match(f.run('renderAdmin()'),/name="gift_name"/);
  f.context.respond=async()=>({grant:{id:5}});
  await f.submit({guest:'1',name:'비회원 수령자',gift:'custom',gift_name:'푸딩 무드등',quantity:'1',reason:'현장 보상'},'admin-manual-grant');
  assert.deepEqual(f.requests[0].body,{kind:'gift',reason:'현장 보상',guest:true,name:'비회원 수령자',
    gift:'custom',gift_name:'푸딩 무드등',quantity:1,request_id:'request-1'});
});

test('manual score form submits a score rather than quantity or inventory fields',async()=>{
  const f=adminFixture();f.run("eventTab='manual'");
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'score'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/name="points"/);
  assert.doesNotMatch(html,/name="quantity"|name="product_id"|name="gift"/);
  f.context.respond=async()=>({grant:{id:6}});
  await f.submit({user_id:'10',points:'7',reason:'점수 복구'},'admin-manual-grant');
  assert.deepEqual(f.requests[0].body,{kind:'score',reason:'점수 복구',user_id:10,points:7,request_id:'request-1'});
});

test('recipient and reason drafts survive changing grant kind and gift',async()=>{
  const f=adminFixture();f.run("eventTab='manual'");
  function input(name,value){f.listeners.input({target:{name,value,dataset:{},
    closest:selector=>selector==='#admin-manual-grant'?{}:null}});}
  input('user_id','10');input('reason','오류 보완');input('quantity','2');
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'gift'}})");
  input('gift','custom');
  const html=f.run('renderAdmin()');
  assert.match(html,/<option value="10" selected>/);
  assert.match(html,/name="reason"[^>]*value="오류 보완"/);
  assert.match(html,/name="quantity"[^>]*value="2"/);
  assert.match(html,/name="gift_name"/);
});

function profileForm(f) {
  const error={hidden:true,textContent:''},fields=[{disabled:false},{disabled:false}];
  const form={dataset:{userId:'1'},isConnected:true,querySelectorAll:selector=>selector==='fieldset'?fields:[],
    querySelector:selector=>selector==='.profile-editor-error'?error:null};
  Object.assign(f.context,{profileForm:form,chosenAvatar});
  return {form,error,fields};
}

test('first sign-in offers character choices while returning customized users continue normally',async()=>{
  const f=fixture({guest:true});
  f.remote.profileCustomized=false;
  f.context.opened=[];f.context.authForm={dataset:{mode:'login'}};
  f.run('modal=html=>opened.push(html);closeModal=()=>{};');
  f.context.fetchOverride=(path,options)=>path==='/api/auth/login'
    ?f.response({token:'token-A',user:{id:1,name:'구매자1',profile_customized:f.remote.profileCustomized}})
    :f.context.normalFetch(path,options);
  await f.run("signInBuyer(authForm,{name:'구매자1',phone:'01012345678',pin:'1234'})");
  assert.equal(f.context.opened.length,1);
  assert.match(f.context.opened[0],/나만의 연금술사 만들기/);
  for(const label of ['얼굴 종류','표정','안경','구매한 빵 머리핀','다음에 꾸미기'])assert.match(f.context.opened[0],new RegExp(label));
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,0);
  f.remote.profileCustomized=true;f.context.opened.length=0;
  await f.run("signInBuyer(authForm,{name:'구매자1',phone:'01012345678',pin:'1234'})");
  assert.equal(f.context.opened.length,0);
});

test('profile preview changes do not save or replace the current account appearance',async()=>{
  const f=fixture();await f.run('refresh()');
  const preview={innerHTML:''},original=f.context.document.querySelector;
  f.context.document.querySelector=selector=>selector==='[data-profile-preview]'?preview:original(selector);
  const {form}=profileForm(f);form.values=new Map(Object.entries(chosenAvatar));
  f.context.FormData=function(form){return form.values;};
  const before=f.run('JSON.stringify(state.user)');
  f.run('updateProfilePreview(profileForm)');
  assert.match(preview.innerHTML,/프로필 캐릭터/);
  assert.equal(preview.innerHTML,f.run("profileAvatar({...state.user,avatar:chosenAvatar},{className:'profile-preview-picture'})"));
  assert.equal(f.run('JSON.stringify(state.user)'),before);
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,0);
});

test('failed profile saves retain choices, show an inline error and block duplicate saves',async()=>{
  const f=fixture();await f.run('refresh()');
  const {form,error,fields}=profileForm(f);
  let finish;
  f.context.fetchOverride=(path,options)=>path==='/api/profile'?new Promise(resolve=>finish=()=>resolve(f.response({error:'저장 연결을 확인해 주세요.'},503))):f.context.normalFetch(path,options);
  const first=f.run('saveProfile(profileForm,chosenAvatar)');
  await f.run('saveProfile(profileForm,chosenAvatar)');
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,1);
  assert.ok(fields.every(field=>field.disabled));
  finish();await first;
  assert.equal(error.hidden,false);
  assert.equal(error.textContent,'저장 연결을 확인해 주세요.');
  assert.equal(form.isConnected,true);
  assert.ok(fields.every(field=>!field.disabled));
  assert.equal(f.run('state.user.avatar'),undefined);
});

test('saving a profile persists only appearance and updates the account response',async()=>{
  const f=fixture();await f.run('refresh()');profileForm(f);
  f.run('closeModal=()=>{};');
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/profile'){
      f.remote.avatar=JSON.parse(options.body).avatar;f.remote.profileCustomized=true;
      return f.context.normalFetch('/api/auth/me').then(r=>r.json()).then(user=>f.response(user));
    }
    return f.context.normalFetch(path,options);
  };
  await f.run('saveProfile(profileForm,chosenAvatar)');
  const request=f.requests.find(r=>r.path==='/api/profile');
  assert.equal(request.method,'POST');
  assert.deepEqual(JSON.parse(request.body),{avatar:chosenAvatar});
  assert.equal(f.run('JSON.stringify(state.user.avatar)'),JSON.stringify(chosenAvatar));
  assert.equal(f.run('state.user.profile_customized'),true);
  assert.equal(f.run('profileSaving'),false);
});

test('a delayed profile response cannot replace a different signed-in account',async()=>{
  const f=fixture();await f.run('refresh()');const {form}=profileForm(f);
  let finish;
  f.context.fetchOverride=(path,options)=>path==='/api/profile'?new Promise(resolve=>finish=()=>resolve(f.response({user:{id:1,name:'이전 계정',avatar:chosenAvatar}}))):f.context.normalFetch(path,options);
  const first=f.run('saveProfile(profileForm,chosenAvatar)');
  form.isConnected=false;
  f.run("state.token='token-B';state.user={id:2,name:'새 계정'}");
  finish();await first;
  assert.equal(f.run('state.user.name'),'새 계정');
  assert.equal(f.run('state.user.avatar'),undefined);
  assert.equal(f.run('profileSaving'),false);
});

test('rankings show a portrait for every person, including uncustomized accounts',async()=>{
  const f=fixture();await f.run('refresh()');
  f.context.chosenAvatar=chosenAvatar;
  f.run("state.route='ranking';const people=[{id:1,name:'하나',rank:1,score:9,is_me:true,avatar:chosenAvatar},{id:2,name:'둘',rank:2,score:3},{id:3,name:'셋',rank:3,score:0}];state.leaderboard={leaders:people,neighbors:people,me:people[0],total_participants:3};renderPage()");
  for(const name of ['하나','둘','셋'])assert.equal(f.root.innerHTML.split(`${name}의 프로필 캐릭터`).length-1,1);
  assert.match(f.root.innerHTML,/구매자1 계정 관리/);
  assert.equal((f.root.innerHTML.match(/character-unknown/g)||[]).length,1);
});

test('bread face choices preserve legacy profiles and expose named bread options',()=>{
  const f=fixture();
  for(const [old,value] of [['round','madeleine'],['oval','financier'],['square','pound'],['soboro','madeleine'],['salt','financier'],['toast','pound']]){
    f.context.legacy={face_shape:old};
    assert.equal(f.run('normalizeAvatar(legacy,1).face_shape'),value);
  }
  const editor=f.run("profileEditor({id:1,name:'빵 얼굴',avatar:{face_shape:'pound'}})");
  for(const label of ['마들렌','휘낭시에','파운드케이크','굽기 정도'])assert.match(editor,new RegExp(label));
  assert.doesNotMatch(editor,/동그란 얼굴|갸름한 얼굴|각진 얼굴|피부색|소보로빵|소금빵|식빵/);
});

test('profile editor locks sunglasses until the fifteen-point reward',()=>{
  const f=fixture();
  const html=f.run("profileEditor({id:1,name:'구매자',unlocked_hairpins:['none','bread_101']})");
  for(const label of ['얼굴','표정','꾸미기','방긋','활짝','윙크','깜짝','멋진 선글라스'])assert.match(html,new RegExp(label));
  assert.doesNotMatch(html,/머리 모양|머리색|별 머리핀|꽃 머리핀/);
  assert.doesNotMatch(html.match(/<input[^>]*value="bread_101"[^>]*>/)[0],/disabled/);
  assert.match(html.match(/<input[^>]*value="bread_102"[^>]*>/)[0],/disabled/);
  assert.match(html.match(/<input[^>]*value="sunglasses"[^>]*>/)[0],/disabled/);
  const unlocked=f.run("profileEditor({id:1,name:'구매자',sunglasses_unlocked:true})");
  assert.doesNotMatch(unlocked.match(/<input[^>]*value="sunglasses"[^>]*>/)[0],/disabled/);
  assert.match(html,/아직 잠긴 머리핀 · 10종/);
  f.context.portrait={id:1,name:'구매자',avatar:{...chosenAvatar,hairpin:'bread_101'}};
  assert.match(f.run('profileAvatar(portrait)'),/data-pin-product="101"/);
  assert.match(f.run('profileAvatar(portrait)'),/cool-sunglasses/);
});

test('purchase approval refreshes pins in an open editor without discarding the expression draft',async()=>{
  const f=fixture();await f.run('refresh()');
  const {form}=profileForm(f);form.values=new Map(Object.entries(chosenAvatar));
  f.context.FormData=function(form){return form.values;};
  let replaced='';
  const original=f.context.document.querySelector;
  const updated={querySelector:()=>null};
  const target={dataset:{unlocks:'["none"]'},contains:()=>false,querySelector:()=>null,
    set outerHTML(html){replaced=html;}};
  f.context.document.querySelector=selector=>selector==='#profile-editor'?form:selector==='[data-profile-hairpins]'?(replaced?updated:target):original(selector);
  f.remote.unlockedHairpins=['none','bread_101'];
  await f.run('refresh()');
  assert.match(replaced,/data-expression="wink"/);
  assert.doesNotMatch(replaced.match(/<input[^>]*value="bread_101"[^>]*>/)[0],/disabled/);
  assert.match(replaced.match(/<input[^>]*value="bread_102"[^>]*>/)[0],/disabled/);
  assert.equal(form.values.get('expression'),'wink');
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,0);
});

test('avatar rendering restricts untrusted selections to local options and escapes names',()=>{
  const f=fixture();f.context.untrusted={id:1,name:'<script>bad</script>',avatar:{expression:'https://evil.example',glasses:'<svg onload=bad>'}};
  const svg=f.run('profileAvatar(untrusted)');
  assert.doesNotMatch(svg,/<script>|https:\/\/evil|onload=/);
  assert.match(svg,/&lt;script&gt;bad&lt;\/script&gt;/);
  assert.equal(f.run('normalizeAvatar(untrusted.avatar,1).glasses'),'none');
  assert.equal(f.run('normalizeAvatar(untrusted.avatar,1).expression'),'smile');
});

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
  assert.doesNotMatch(f.root.innerHTML, /class="product-list"|class="inline-dice|class="primary-nav"/);
});

test('purchase and event have separate content and only two main menus', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run('renderPage()');
  assert.match(f.root.innerHTML, /aria-label="현판 빵 목록"/);
  assert.doesNotMatch(f.root.innerHTML, /현재 점수|랜덤 빵 뽑기|선택한 주사위 굴리기/);
  const nav = f.root.innerHTML.match(/<nav class="primary-nav"[^>]*>(.*?)<\/nav>/s)[1];
  assert.equal((nav.match(/<button/g) || []).length, 2);
  f.run("state.route='ranking'; renderPage()");
  assert.match(f.root.innerHTML, /선택한 주사위 굴리기/);
  assert.match(f.root.innerHTML, /현재 점수/);
  assert.match(f.root.innerHTML, /최고의 연금술사 TOP 3/);
  assert.doesNotMatch(f.root.innerHTML, /현판 빵 목록|구매 요청하기/);
  assert.doesNotMatch(f.root.innerHTML, /data-admin-search|admin-pickup-search/);
});

test('crossing the first milestone offers its reward without claiming automatically', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run("state.user.score=3; state.route='ranking'");
  let prompt='';
  f.context.captureModal = html => {prompt=html;};
  f.run('modal = captureModal');
  f.context.fetchOverride = async (path, options) => {
    if(path==='/api/dice/roll') return f.response({result:'score',value:3,score:6,dice_balance:1});
    if(path==='/api/auth/me') return f.response({user:{id:1,name:'구매자1',role:'buyer',score:6,dice_balance:1,rewards_claimed:0}});
    return f.context.normalFetch(path, options);
  };
  await f.run('rollDice()');
  assert.match(prompt, /5점 달성/);
  assert.match(prompt,/오트밀 미니바이트/);
  assert.match(prompt, /data-action="claim-reward"/);
  assert.doesNotMatch(prompt, /data-character-level="1"|견습 연금술사/);
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

test('one event page shows rankings and a direct roll action that follows dice balance', async () => {
  const f=fixture();
  await f.run('refresh()');
  f.run('renderPage()');
  assert.match(f.root.innerHTML, /data-route="orders"[^>]*>주문 내역/);
  assert.doesNotMatch(f.root.innerHTML, /내 주문/);
  assert.match(f.run('navButton(buyerNav[1])'), /data-route="ranking"/);
  f.run("state.route='ranking'; renderPage()");
  assert.match(f.root.innerHTML, /최고의 연금술사 TOP 3/);
  assert.match(f.root.innerHTML, /data-action="roll-dice"[^>]*>.*선택한 주사위 굴리기/);
  assert.match(f.root.innerHTML, /남은 주사위 <strong>2개/);
  assert.equal((f.root.innerHTML.match(/data-action="roll-dice"/g)||[]).length,1);
  assert.doesNotMatch(f.root.innerHTML, /class="subnav"|data-route="dice"/);
  assert.doesNotMatch(f.root.innerHTML, /purchase-cta/);
  f.run('state.user.dice_balance=0; renderPage()');
  assert.match(f.root.innerHTML, /purchase-cta full" data-action="navigate" data-route="shop"/);
  assert.match(f.root.innerHTML, /빵 구매하고 주사위 얻기/);
  assert.doesNotMatch(f.root.innerHTML, /data-action="roll-dice"/);
  assert.match(f.root.innerHTML, /최고의 연금술사 TOP 3/);
});

test('old dice links open the same event page and update the bookmark route',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='dice'; renderPage()");
  assert.equal(f.run('state.route'),'ranking');
  assert.equal(f.routeChanges.at(-1),'#ranking');
  assert.match(f.root.innerHTML,/data-action="roll-dice"/);
  assert.match(f.root.innerHTML,/최고의 연금술사 TOP 3/);
  assert.doesNotMatch(f.root.innerHTML,/class="subnav"|data-route="dice"/);
});

test('rolling stays with the rankings, blocks repeated clicks, and shows the last die result',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='ranking'; state.user.score=1; state.user.dice_balance=1; render=renderPage");
  let release;
  let user={id:1,name:'구매자1',role:'buyer',score:1,dice_balance:1,rewards_claimed:0};
  f.context.fetchOverride=async(path,options)=>{
    if(path==='/api/dice/roll')return new Promise(resolve=>{release=()=>{
      user={...user,score:5,dice_balance:0};resolve(f.response({value:4,score:5,dice_balance:0}));
    };});
    if(path==='/api/auth/me')return f.response({user});
    return f.context.normalFetch(path,options);
  };
  const first=f.run('rollDice()');
  assert.match(f.root.innerHTML,/inline-dice rolling/);
  assert.match(f.root.innerHTML,/data-action="roll-dice" disabled/);
  assert.match(f.root.innerHTML,/최고의 연금술사 TOP 3/);
  await f.run('rollDice()');
  assert.equal(f.requests.filter(r=>r.path==='/api/dice/roll').length,1);
  release();await first;
  assert.equal(f.run('state.route'),'ranking');
  assert.deepEqual(f.routeChanges,[]);
  assert.match(f.root.innerHTML,/결과 4 · \+4점/);
  assert.match(f.root.innerHTML,/현재 점수 <strong>5점/);
  assert.match(f.root.innerHTML,/남은 주사위 <strong>0개/);
  assert.match(f.root.innerHTML,/빵 구매하고 주사위 얻기/);
  assert.match(f.root.innerHTML,/최고의 연금술사 TOP 3/);
  assert.doesNotMatch(f.root.innerHTML,/data-action="roll-dice"/);
});

test('event actions remain available while the leaderboard is loading',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='ranking'; state.leaderboard=null; renderPage()");
  assert.match(f.root.innerHTML,/순위를 불러오는 중/);
  assert.match(f.root.innerHTML,/data-action="roll-dice"/);
  assert.match(f.root.innerHTML,/현재 점수/);
});

test('score bar has image bubbles that unlock by score and reveal claim controls only in details', async()=>{
  const f=fixture();await f.run('refresh()');let prompt='';
  f.context.capture=html=>prompt=html;f.run('modal=capture');
  f.run("state.route='ranking';state.user.score=4;renderPage()");
  assert.match(f.root.innerHTML,/1점 더 모으면 레벨업!/);
  assert.match(f.root.innerHTML,/character-unknown/);
  assert.match(f.root.innerHTML,/aria-valuemax="30" aria-valuenow="4"/);
  assert.equal((f.root.innerHTML.match(/data-action="open-milestone"/g)||[]).length,5);
  for(const point of [5,10,15,20,30])assert.match(f.root.innerHTML,new RegExp(`data-threshold="${point}"`));
  assert.doesNotMatch(f.root.innerHTML,/data-action="claim-reward"|milestone-roadmap|10점마다|50점까지/);
  f.run('openMilestone(5)');
  assert.match(prompt,/오트밀 미니바이트/);
  assert.match(prompt,/프로필 배지 · 마법의 씨앗/);
  assert.match(prompt,/1점 더 모으면/);
  assert.match(prompt,/\/assets\/oatmeal.svg/);
  assert.doesNotMatch(prompt,/data-action="claim-reward"/);
  f.run('state.user.score=5;renderPage();openMilestone(5)');
  assert.match(f.root.innerHTML,/milestone-trigger is-achieved [^"]*" data-action="open-milestone" data-threshold="5"/);
  assert.match(prompt,/data-action="claim-reward" data-threshold="5">상품 받기/);
  f.run('openMilestone(15)');
  assert.match(prompt,/멋진 선글라스/);
  assert.match(prompt,/멋쟁이 마법사/);
  assert.doesNotMatch(prompt,/data-action="claim-reward"/);
  f.run('state.user.claimed_milestones=[5];state.user.level=1;renderPage();openMilestone(5)');
  assert.match(f.root.innerHTML,/data-character-level="1"/);
  assert.match(f.root.innerHTML,/is-claimed/);
  assert.doesNotMatch(prompt,/data-action="claim-reward"/);
  f.run('state.user.score=60;state.user.level=5;state.user.claimed_milestones=[5,10,15,20,30];renderPage()');
  assert.match(f.root.innerHTML,/30점 보상까지 모두 받았어요/);
  assert.match(f.root.innerHTML,/aria-valuemax="30" aria-valuenow="30"/);
  assert.match(f.root.innerHTML,/width:100%/);
});

test('claiming an achieved bubble sends that threshold rather than the first unclaimed reward',async()=>{
  const f=fixture();await f.run('refresh()');let prompt='';
  f.context.capture=html=>prompt=html;f.run('modal=capture;state.user.score=20;openMilestone(15)');
  assert.match(prompt,/멋진 선글라스/);
  assert.match(prompt,/data-threshold="15">상품 받기/);
  assert.equal(f.requests.filter(r=>r.path==='/api/rewards/claim').length,0);
  f.context.fetchOverride=(path,options)=>path==='/api/rewards/claim'?f.response({reward:{id:2,threshold:15,kind:'sunglasses',product_name:'멋진 선글라스'},user:{id:1,name:'구매자1',score:20,level:1,claimed_milestones:[15]}}):f.context.normalFetch(path,options);
  await f.run("claimReward({dataset:{threshold:'15'},disabled:false})");
  const request=f.requests.find(r=>r.path==='/api/rewards/claim');
  assert.equal(JSON.parse(request.body).threshold,15);
});

test('level-up waits for one server claim before revealing the reward', async () => {
  const f=fixture();
  await f.run('refresh()');
  f.run('state.user.score=10');
  let release, prompt='';
  let user={id:1,name:'구매자1',role:'buyer',score:10,dice_balance:1,rewards_claimed:0,level:0};
  f.context.captureModal=html=>{prompt=html;};
  f.run('modal=captureModal');
  f.context.fetchOverride=async (path,options)=>{
    if(path==='/api/rewards/claim')return new Promise(resolve=>{release=()=>{
      user={...user,rewards_claimed:1,level:1,claimed_milestones:[5]};
      resolve(f.response({user,reward:{id:1,product_id:null,product_name:'오트밀 미니바이트',kind:'oatmeal',threshold:5}}));
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
  assert.match(prompt,/견습 연금술사/);
  assert.match(prompt,/data-character-level="1"/);
  assert.doesNotMatch(prompt,/character-unknown/);
  assert.match(prompt,/오트밀 미니바이트/);
});

const adminSource=readFileSync(new URL('../frontend/admin.js',import.meta.url),'utf8').replace(/\bexport /g,'');
test('typed dice show quantities and colors without exposing face distributions',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='ranking';state.user.dice=[{kind:'preorder_gold',name:'준비된 마법사의 주사위',color:'gold',quantity:1},{kind:'instagram',name:'인싸 마법사의 주사위',color:'pink',quantity:1}];state.selectedDice='instagram';renderPage()");
  assert.match(f.root.innerHTML,/준비된 마법사의 주사위/);
  assert.match(f.root.innerHTML,/인싸 마법사의 주사위/);
  assert.match(f.root.innerHTML,/data-kind="instagram" aria-pressed="true"/);
  assert.doesNotMatch(f.root.innerHTML,/5천원|2만원|faces|1, 1, 2|6, 9, 11/);
  assert.equal(f.run('selectedDie().kind'),'instagram');
  f.run("state.user.dice=state.user.dice.filter(d=>d.kind!=='instagram')");
  assert.equal(f.run('selectedDie().kind'),'preorder_gold');
});

test('a selected typed die sends only its kind and a retry-safe identifier',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.user.dice=[{kind:'preorder_gold',name:'준비된 마법사의 주사위',color:'gold',quantity:1}];state.selectedDice='preorder_gold'");
  f.context.fetchOverride=(path,options)=>path==='/api/dice/roll'?f.response({result:'score',value:22,score:22,dice_balance:0}):f.context.normalFetch(path,options);
  await f.run('rollDice()');
  const body=JSON.parse(f.requests.find(r=>r.path==='/api/dice/roll').body);
  assert.deepEqual(Object.keys(body).sort(),['kind','request_id']);
  assert.equal(body.kind,'preorder_gold');
  assert.match(f.run("die(22,'gold')"),/<b>22<\/b>/);
});

test('milk dice outcomes show milk instead of a zero-point die or automatic milestone claim',async()=>{
  const f=fixture();await f.run('refresh()');let prompt='';
  f.context.capture=html=>prompt=html;f.run('modal=capture');
  f.context.fetchOverride=(path,options)=>path==='/api/dice/roll'?f.response({id:4,result:'milk',value:0,score:0,dice_balance:1,dice:{color:'pink'},fulfillment:{id:4,status:'awaiting_choice'}}):f.context.normalFetch(path,options);
  await f.run('rollDice()');
  assert.match(prompt,/우유 보상 당첨!/);
  assert.match(prompt,/이벤트 요청 #4/);
  assert.doesNotMatch(prompt,/\+0점|주사위 0/);
  assert.equal(f.requests.filter(r=>r.path==='/api/rewards/claim').length,0);
  assert.match(f.run("die('milk','pink')"),/우유 당첨/);
});

const adminProductPhoto=fixture().run('productPhoto');
const sharedEventNotices=fixture().run('renderEventNotices');
function adminFixture() {
  const requests=[],messages=[];
  const listeners={};
  const nodes=new Map();
  let renderCalls=0;
  const state={user:{id:1},route:'events',products:[],staffData:{users:[{id:10,name:'등록사용자'}],stats:{milk_stock:2},
    products:[{id:101,name:'플레인 휘낭시에',stock:2,preorder_stock:0,price:2800,dice_per_unit:1},
              {id:112,name:'우유',stock:2,preorder_stock:0,price:1000,dice_per_unit:0}]}};
  const context={document:{addEventListener(type,listener){listeners[type]=listener;},querySelector:selector=>nodes.get(selector)||null},FormData:class {
    constructor(form){this.values=form.values;}
    get(key){return this.values.get(key)??null;}
    has(key){return this.values.has(key);}
  }};
  let identity=0;
  context.shared={state,esc:String,icon:()=>'',money:String,time:()=>'',normalizePhone:value=>value,requestId:()=>`request-${++identity}`,
    productPhoto:adminProductPhoto,renderEventNotices:sharedEventNotices,api:async(path,options)=>{requests.push(JSON.parse(JSON.stringify({path,...options})));return context.respond?context.respond(path,options):{};},
    submitButton(){},refresh:async()=>{},render(){renderCalls++;},toast:message=>messages.push(message),closeModal(){}};
  vm.createContext(context);
  vm.runInContext(profileSource+'\n'+adminSource+'\nshared.profileAvatar=profileAvatar;shared.badgePicture=badgePicture;shared.badgeIcons=badgeIcons;shared.profileTitle=profileTitle;shared.titleStyles=titleStyles;initAdmin(shared);',context);
  return {state,requests,messages,context,listeners,nodes,run:script=>vm.runInContext(script,context),
    get renders(){return renderCalls;},
    search(key,value){listeners.input({target:{dataset:{adminSearch:key},value,closest:()=>null}});},
    async lookup(fields){
      context.lookupFields=fields;
      await vm.runInContext('lookupManualPreorder(lookupFields.name,lookupFields.phone)',context);
    },
    async submit(fields,id='admin-instagram'){
      context.form={id,values:new Map(Object.entries(fields)),isConnected:true,
        querySelector:()=>null,reset(){}};
      await vm.runInContext('handleAdminSubmit(form)',context);
    }};
}

function manualReservation(overrides={}) {
  return {id:7,name:'등록사용자',phone:'01012345678',status:'reserved',total:6600,dice_quantity:2,
    items:[{product_id:101,name:'플레인 휘낭시에',quantity:2,price:2800},{product_id:112,name:'우유',quantity:1,price:1000}],
    order:null,...overrides};
}

test('staff navigation follows order, event, manual sale, stock and handover',()=>{
  const f=fixture({admin:true});
  f.run("state.user={id:1,name:'담당',role:'staff'};state.staffData={stats:{pending_rewards:2}};renderPage()");
  const nav=f.root.innerHTML.match(/<nav class="primary-nav"[^>]*>(.*?)<\/nav>/s)[1];
  assert.deepEqual([...nav.matchAll(/data-route="([^"]+)"/g)].map(m=>m[1]),['queue','events','sales','inventory','notes']);
  for(const label of ['주문','이벤트','수기판매','재고관리','인수인계'])assert.match(nav,new RegExp(label));
  assert.match(nav,/data-route="events"[^>]*>.*?pending-pill">2/s);
});

test('event page defaults to physical requests and keeps Instagram in a separate subtab',()=>{
  const f=adminFixture();
  f.state.staffData.reward_requests=[{id:1,user_id:10,customer_name:'등록사용자',status:'pending',product_id:101,product_name:'플레인 휘낭시에',threshold:20,remaining_stock:2},
    {id:2,user_id:10,customer_name:'등록사용자',status:'awaiting_choice',product_name:'우유·두유 선택',roll_id:5}];
  let html=f.run('renderAdmin()');
  assert.match(html,/전달 완료 · 승인/);
  assert.match(html,/이벤트 #1/);
  assert.doesNotMatch(html,/id="admin-instagram"|이벤트 #2/);
  f.run("eventFilter='awaiting_choice'");html=f.run('renderAdmin()');
  assert.match(html,/이벤트 #2/);
  assert.doesNotMatch(html,/전달 완료 · 승인/);
  f.run("eventTab='instagram'");html=f.run('renderAdmin()');
  assert.match(html,/id="admin-instagram"/);
});

test('staff approval and cancellation use fulfillment transitions without extra inventory requests',async()=>{
  const f=adminFixture();let prompt='';
  f.context.shared.modal=html=>prompt=html;
  f.state.staffData.reward_requests=[{id:9,user_id:10,customer_name:'등록사용자',status:'pending',product_name:'두유'}];
  await f.run("handleAdminClick('admin-event-cancel',{dataset:{id:'9'}})");
  assert.equal(f.requests.length,0);
  assert.match(prompt,/확보한 재고 1개를 반환/);
  assert.match(prompt,/취소 후 다시 뽑지 않습니다/);
  await f.run("handleAdminClick('admin-event-transition',{dataset:{id:'9',mode:'cancel'}})");
  await f.run("handleAdminClick('admin-event-transition',{dataset:{id:'9',mode:'approve'}})");
  assert.deepEqual(f.requests.map(r=>r.path),['/api/staff/reward-requests/9/cancel','/api/staff/reward-requests/9/approve']);
});

test('stock on hold includes pending event requests but excludes unselected and cancelled rewards',()=>{
  const f=adminFixture();f.state.route='inventory';
  f.state.staffData.orders=[{status:'pending',items:[{product_id:101,quantity:2}]}];
  f.state.staffData.reward_requests=[{status:'pending',product_id:101},{status:'awaiting_choice',product_id:null},{status:'cancelled',product_id:101}];
  assert.equal(f.run('heldStock(101)'),3);
  assert.match(f.run('renderAdmin()'),/<td>2<\/td><td>0<\/td><td>3<\/td><td><strong>5<\/strong>/);
});

test('beverage selection disables sold-out drinks and always separates cancellation from postponing',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.products=[{id:112,name:'우유',stock:0,beverage_reward_eligible:true},{id:113,name:'두유',stock:1,beverage_reward_eligible:true}]");
  let html=f.run('beverageOptions({id:9})');
  assert.match(html,/data-product="112" disabled/);
  assert.match(html,/data-product="113" >.*두유 선택/s);
  assert.match(html,/data-action="decline-beverage" data-request="9">취소하기/);
  assert.match(html,/data-action="close-modal">나중에 선택하기/);
  f.run('state.products[1].stock=0');html=f.run('beverageOptions({id:9})');
  assert.match(html,/모두 품절/);
  assert.match(html,/data-action="decline-beverage"/);
});

test('beverage choice posts selected product once and refreshes the staff-pending state',async()=>{
  const f=fixture();await f.run('refresh()');let release;
  let row={id:9,status:'awaiting_choice',product_name:'우유·두유 선택'};
  f.run('closeModal=()=>{}');
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/reward-requests/9/choose')return new Promise(resolve=>release=()=>{row={...row,status:'pending',product_id:113,product_name:'두유'};resolve(f.response({request:row}));});
    if(path==='/api/rewards')return f.response({rewards:[],requests:[row]});
    return f.context.normalFetch(path,options);
  };
  const first=f.run("chooseBeverage({dataset:{request:'9',product:'113'}})");
  await f.run("chooseBeverage({dataset:{request:'9',product:'112'}})");
  assert.equal(f.requests.filter(r=>r.path.includes('/choose')).length,1);
  const body=JSON.parse(f.requests.find(r=>r.path.includes('/choose')).body);
  assert.equal(body.product_id,113);
  assert.deepEqual(Object.keys(body).sort(),['product_id','request_id']);
  release();await first;
  assert.equal(f.run('state.rewardRequests[0].status'),'pending');
  assert.match(f.run('renderRewardRequests()'),/담당자 지급 대기/);
});

test('a stock conflict refreshes the drink choices without drawing a new reward',async()=>{
  const f=fixture();await f.run('refresh()');let prompt='';
  f.context.capture=html=>prompt=html;f.run('modal=capture;closeModal=()=>{}');
  f.context.fetchOverride=(path,options)=>{
    if(path.includes('/choose'))return f.response({error:'두유 재고가 부족합니다.'},409);
    if(path==='/api/products')return f.response({products:[{id:112,name:'우유',stock:0,beverage_reward_eligible:true},{id:113,name:'두유',stock:0,beverage_reward_eligible:true}]});
    if(path==='/api/rewards')return f.response({rewards:[],requests:[{id:9,status:'awaiting_choice'}]});
    return f.context.normalFetch(path,options);
  };
  await f.run("chooseBeverage({dataset:{request:'9',product:'113'}})");
  assert.match(prompt,/모두 품절/);
  assert.match(prompt,/decline-beverage/);
  assert.equal(f.requests.filter(r=>r.path==='/api/dice/roll'||r.path==='/api/rewards/claim').length,0);
});

test('preorder status search accepts partial names, formatted phones and combined menu terms',()=>{
  const f=adminFixture();f.state.route='inventory';
  f.state.staffData.reservations=[manualReservation({name:'김이박'}),manualReservation({id:8,name:'박다른',phone:'01098764321',
    items:[{product_id:103,name:'카라멜 휘낭시에',quantity:1,price:3000}],total:3000})];
  for(const query of ['이박','5678','010-1234-5678','플레인 5678','김이박   휘낭시에']){
    f.search('inventory',query);
    const html=f.run('renderAdmin()');
    assert.match(html,/<td><strong>김이박/);
    assert.doesNotMatch(html,/<td><strong>박다른/);
    assert.match(html,/검색 결과 1건 \/ 전체 2건/);
  }
  f.search('inventory','카라멜');
  assert.match(f.run('renderAdmin()'),/<td><strong>박다른/);
  f.search('inventory','.*[');
  assert.match(f.run('renderAdmin()'),/검색 결과가 없습니다/);
  f.search('inventory','');
  assert.match(f.run('renderAdmin()'),/검색 결과 2건 \/ 전체 2건/);
  assert.equal(f.requests.length,0);
});

test('typing a search updates only its results and leaves input focus and composition alone',()=>{
  const f=adminFixture();f.state.staffData.reservations=[manualReservation({name:'김이박'})];
  const results={innerHTML:''};f.nodes.set('#inventory-preorder-results',results);
  const input={dataset:{adminSearch:'inventory'},value:'이박',closest:()=>null};
  f.context.document.activeElement=input;
  f.listeners.input({target:input,isComposing:true});
  assert.match(results.innerHTML,/김이박/);
  assert.equal(f.context.document.activeElement,input);
  assert.equal(input.value,'이박');
  assert.equal(f.renders,0);
  assert.equal(f.requests.length,0);
});

test('pickup search selects a matching reservation and checks its latest status before fulfillment',async()=>{
  const f=adminFixture();f.state.route='sales';
  const r=manualReservation({name:'김이박'});
  f.state.staffData.reservations=[r,manualReservation({id:8,name:'다른예약',phone:'01011112222'})];
  f.context.respond=async()=>({reservation:{...r,status:'approved',order:{id:13,user_id:10,customer_name:'등록사용자',status:'approved'}}});
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  f.search('pickup','5678');
  let html=f.run('renderAdmin()');
  assert.match(html,/김이박 예약 확인/);
  assert.doesNotMatch(html,/다른예약 예약 확인/);
  assert.equal(f.requests.length,0);
  await f.run("handleAdminClick('admin-preorder-select',{dataset:{id:'7'},disabled:false})");
  assert.deepEqual(f.requests,[{path:'/api/staff/preorders/lookup',method:'POST',body:{name:'김이박',phone:'01012345678'}}]);
  html=f.run('renderAdmin()');
  assert.match(html,/이미 수령 완료한 예약입니다. 주문 #13/);
  assert.doesNotMatch(html,/id="admin-manual-preorder-complete"/);
  f.search('pickup','다른예약');
  assert.equal(f.run('manualReservation'),null);
  assert.doesNotMatch(f.run('renderAdmin()'),/id="manual-preorder-result"/);
});

test('searching existing accounts clears an earlier selection and submits only the chosen match',async()=>{
  const f=adminFixture();f.state.route='sales';f.state.staffData.users.push({id:11,name:'여니'});
  const reservation=manualReservation({name:'예약자'});
  f.context.respond=async path=>path.endsWith('/lookup')?{reservation}:{
    reservation:{...reservation,status:'approved',order:{id:9,status:'approved',user_id:11,customer_name:'여니'}},
    order:{id:9,dice_quantity:2},already_completed:false};
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:reservation.name,phone:reservation.phone});
  f.run("manualPickupUser='10'");
  const select={innerHTML:''},count={textContent:''};
  f.nodes.set('#admin-pickup-user',select);f.nodes.set('#pickup-account-count',count);
  f.search('users','여');
  assert.equal(f.run('manualPickupUser'),'');
  assert.match(select.innerHTML,/여니/);
  assert.doesNotMatch(select.innerHTML,/등록사용자|selected/);
  assert.equal(count.textContent,'검색된 계정 1명');
  f.listeners.input({target:{name:'user_id',value:'11',closest:selector=>selector==='#admin-manual-preorder-complete'?{}:null}});
  assert.match(f.run('renderAdmin()'),/<option value="11" selected>여니/);
  await f.submit({user_id:'11'},'admin-manual-preorder-complete');
  assert.equal(f.requests[1].body.user_id,11);
  assert.match(f.run('renderAdmin()'),/수령 계정: 여니/);
});

test('order search includes the reservation name and phone and retains the selected status filter',async()=>{
  const f=adminFixture();f.state.route='queue';
  f.state.staffData.reservations=[manualReservation({name:'예약실명'})];
  f.state.staffData.orders=[{id:1,reservation_id:7,user_id:10,customer_name:'계정별명',type:'preorder',status:'pending',quantity:2,total:5600,
    items:[{name:'플레인 휘낭시에',price:2800,quantity:2}]},{id:2,user_id:11,customer_name:'다른구매자',type:'walkin',status:'approved',quantity:1,total:3000,
    items:[{name:'초코 휘낭시에',price:3000,quantity:1}]}];
  for(const query of ['예약실명','5678','계정별명','플레인']){
    f.search('queue',query);
    assert.match(f.run('queueResults()'),/계정별명/);
    assert.doesNotMatch(f.run('queueResults()'),/다른구매자/);
  }
  await f.run("handleAdminClick('admin-order-filter',{dataset:{filter:'approved'}})");
  assert.match(f.run('queueResults()'),/검색 결과 0건/);
  f.search('queue','초코');
  assert.match(f.run('queueResults()'),/다른구매자/);
  assert.doesNotMatch(f.run('queueResults()'),/계정별명/);
  f.search('inventory','예약실명');f.search('pickup','다른예약');
  assert.equal(f.run('staffSearch.queue'),'초코');
  assert.equal(f.requests.length,0);
});

test('staff order lines show current remaining stock without subtracting the order again',()=>{
  const f=adminFixture();
  f.context.order={id:1,customer_name:'구매자',type:'walkin',status:'pending',quantity:2,total:5600,
    items:[{product_id:101,name:'플레인 휘낭시에',price:2800,quantity:2,remaining_stock:8,unit:'개'}]};
  assert.match(f.run('orderCard(order)'),/× 2<\/b><small[^>]*>\(남은 재고 8개\)/);
  f.context.order.items[0].remaining_stock=0;
  assert.match(f.run('orderCard(order)'),/\(남은 재고 0개\)/);
  f.context.order.type='preorder';
  assert.match(f.run('orderCard(order)'),/\(남은 예판 재고 0개\)/);
  f.context.order.items=[{product_id:108,name:'도넛',price:2000,quantity:1,remaining_stock:3,unit:'세트'}];
  f.context.order.type='manual';
  assert.match(f.run('orderCard(order)'),/\(남은 재고 3세트\)/);
  // A historical product need not be in the active product list.
  f.context.order.items=[{product_id:1,name:'이전 빵',price:2500,quantity:2,remaining_stock:4,unit:'개'}];
  assert.match(f.run('orderCard(order)'),/\(남은 재고 4개\)/);
  delete f.context.order.items[0].remaining_stock;
  assert.doesNotMatch(f.run('orderCard(order)'),/남은 재고/);
  f.context.order.items[0].product_id=101;
  assert.match(f.run('orderCard(order)'),/\(남은 재고 2개\)/);
  f.context.order.type='preorder';
  assert.match(f.run('orderCard(order)'),/\(남은 예판 재고 0개\)/);
});

test('manual sales switch between the existing walk-in form and reservation lookup',async()=>{
  const f=adminFixture();f.state.route='sales';
  let html=f.run('renderAdmin()');
  assert.match(html,/현장 구매/);
  assert.match(html,/예약한 빵 수령/);
  assert.match(html,/id="admin-manual-sale"/);
  assert.match(html,/data-sale-product="101"/);
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  html=f.run('renderAdmin()');
  assert.match(html,/id="admin-pickup-search"/);
  assert.match(html,/예약 검색/);
  assert.match(html,/전화번호 뒷자리/);
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
  await f.lookup({name:' 등록사용자 ',phone:'010-1234-5678'});
  assert.deepEqual(f.requests[0],{path:'/api/staff/preorders/lookup',method:'POST',body:{name:'등록사용자',phone:'010-1234-5678'}});
  let html=f.run('renderAdmin()');
  assert.match(html,/플레인 휘낭시에 × 2/);
  assert.match(html,/우유 × 1/);
  assert.match(html,/6600원/);
  assert.match(html,/주사위 2개를 지급/);
  assert.match(html,/<select id="admin-pickup-user" name="user_id" required/);
  assert.match(html,/<option value="10" selected>등록사용자/);
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
  const reservation=manualReservation({name:'새예약자',dice_quantity:0,total:1000,
    items:[{product_id:112,name:'우유',quantity:1,price:1000}]});
  f.context.respond=async path=>path.endsWith('/lookup')?{reservation}:{reservation:{...reservation,status:'approved'},
    order:{id:9,dice_quantity:0},already_completed:false};
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:'새예약자',phone:reservation.phone});
  assert.match(f.run('renderAdmin()'),/수령할 구매자 계정/);
  await f.run("handleAdminClick('admin-pickup-mode',{dataset:{mode:'new'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/name="pin" type="password"/);
  assert.match(html,/우유·두유는 주사위를 지급하지 않습니다/);
  assert.doesNotMatch(html,/name="user_id"/);
  await f.submit({pin:'2345'},'admin-manual-preorder-complete');
  assert.deepEqual(f.requests[1].body,{name:'새예약자',phone:reservation.phone,pin:'2345',request_id:'request-1'});
  assert.doesNotMatch(f.messages[0],/주사위/);
  assert.doesNotMatch(f.run('renderAdmin()'),/id="admin-manual-preorder-complete"/);
});

test('staff can choose a differently named existing account and retain it across rerenders',async()=>{
  const f=adminFixture();f.state.route='sales';
  const reservation=manualReservation({name:'예약자실명'});
  f.context.respond=async path=>path.endsWith('/lookup')?{reservation}:{
    reservation:{...reservation,status:'approved',order:{id:9,status:'approved',user_id:10,customer_name:'등록사용자'}},
    order:{id:9,dice_quantity:2},already_completed:false};
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:reservation.name,phone:reservation.phone});
  let html=f.run('renderAdmin()');
  assert.match(html,/기존 계정에 추가/);
  assert.match(html,/<option value="10" >등록사용자/);
  assert.doesNotMatch(html,/name="pin"/);
  f.listeners.input({target:{name:'user_id',value:'10',closest:selector=>selector==='#admin-manual-preorder-complete'?{}:null}});
  assert.match(f.run('renderAdmin()'),/<option value="10" selected>등록사용자/);
  await f.submit({user_id:'10'},'admin-manual-preorder-complete');
  assert.deepEqual(f.requests[1].body,{name:'예약자실명',phone:reservation.phone,user_id:10,request_id:'request-1'});
  html=f.run('renderAdmin()');
  assert.match(html,/수령 계정: 등록사용자/);
  assert.doesNotMatch(html,/id="admin-manual-preorder-complete"/);
});

test('a reservation with no registered buyers can still create its first account',async()=>{
  const f=adminFixture();f.state.route='sales';f.state.staffData.users=[];
  const reservation=manualReservation();f.context.respond=async()=>({reservation});
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:reservation.name,phone:reservation.phone});
  const html=f.run('renderAdmin()');
  assert.match(html,/name="pin" type="password"/);
  assert.doesNotMatch(html,/<select[^>]*name="user_id"/);
});

test('a queued pickup uses its linked buyer and an approved queue order cannot be completed again',async()=>{
  const f=adminFixture();f.state.route='sales';
  const reservation=manualReservation({name:'연결된구매자',status:'pending',order:{id:9,user_id:21,customer_name:'실제계정',status:'pending'}});
  f.context.respond=async()=>({reservation});
  await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'preorder'}})");
  await f.lookup({name:reservation.name,phone:reservation.phone});
  let html=f.run('renderAdmin()');
  assert.match(html,/수령 요청 접수됨/);
  assert.match(html,/name="user_id" value="21"/);
  assert.match(html.replace(/<[^>]*>/g,''),/수령 계정:\s*실제계정/);
  assert.doesNotMatch(html,/<select[^>]*name="user_id"|admin-pickup-mode/);
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
    const lookup=f.lookup({name:'등록사용자',phone:'01012345678'});
    if(change==='input')f.search('pickup','다른예약자');
    else await f.run("handleAdminClick('admin-sale-type',{dataset:{type:'walkin'}})");
    release();await lookup;
    assert.doesNotMatch(f.run('renderAdmin()'),/id="manual-preorder-result"/);
    assert.equal(f.run('manualReservation'),null);
  }
});

test('Instagram certification grants one special die without milk controls',()=>{
  const f=adminFixture();f.run("eventTab='instagram'");const html=f.run('renderAdmin()');
  assert.match(html,/<option value="10"[^>]*>등록사용자/);
  assert.match(html,/인싸 마법사의 주사위 1개 지급/);
  assert.doesNotMatch(html,/<input[^>]*name="(?:dice|milk_quantity|name|pin)"/);
});

test('Instagram submits only the registered user and request identifier',async()=>{
  const f=adminFixture();await f.submit({user_id:'10'});
  assert.deepEqual(f.requests[0],{path:'/api/staff/instagram',method:'POST',body:{user_id:10,request_id:'request-1'}});
  assert.equal(f.messages[0],'인스타 이벤트를 인증하고 전용 주사위 1개를 지급했어요.');
});

test('milk uses the product inventory table and normal stock adjustment',()=>{
  const f=adminFixture();
  f.state.route='inventory';
  const html=f.run('renderAdmin()');
  assert.match(html,/<td><strong>우유<\/strong><\/td><td>2<\/td>/);
  assert.match(html,/data-product="112"/);
  assert.doesNotMatch(html,/inventory-milk|우유 재고 수정/);
});

test('inventory offers a collapsed preorder status table with plain menu text and live status',()=>{
  const f=adminFixture();f.state.route='inventory';
  f.state.staffData.reservations=[manualReservation(),manualReservation({id:8,name:'수령요청자',status:'pending'}),
    manualReservation({id:9,name:'완료예약자',status:'approved'})];
  let html=f.run('renderAdmin()');
  assert.match(html,/<details id="inventory-preorders" class="preorder-status-panel">/);
  assert.match(html,/<summary class="secondary-button">.*예판 수령 현황/);
  assert.match(html,/<th>이름<\/th><th>전화번호<\/th><th>메뉴<\/th><th>수령 상태<\/th>/);
  assert.match(html,/010-1234-5678/);
  assert.match(html,/<td class="preorder-menu">플레인 휘낭시에 2개, 우유 1개<\/td>/);
  assert.match(html,/수령 대기/);
  assert.match(html,/수령 요청 접수/);
  assert.match(html,/수령 완료/);
  f.state.staffData.reservations[0].status='approved';
  html=f.run('renderAdmin()');
  assert.doesNotMatch(html,/수령 대기/);
  f.state.staffData.reservations=[];
  assert.match(f.run('renderAdmin()'),/등록된 예판이 없습니다/);
});

test('milk purchase and mixed order messages use bread dice rather than total quantity',async()=>{
  const f=fixture();
  await f.run('refresh()');
  f.run("state.route='orders'; state.orders=[{id:1,type:'walkin',status:'approved',quantity:3,dice_quantity:2,total:6600,items:[{name:'빵',quantity:2,price:2800},{name:'우유',quantity:1,price:1000}]}]; renderPage()");
  assert.match(f.root.innerHTML,/구매 완료 · 주사위 2개 지급/);
  assert.doesNotMatch(f.root.innerHTML,/주사위 3개 지급/);
  f.run('state.orders[0].dice_quantity=0; renderPage()');
  assert.match(f.root.innerHTML,/음료는 주사위 미지급/);
  f.run("state.route='shop'; state.products=[{id:112,name:'우유',price:1000,stock:2,dice_per_unit:0}]; state.cart={112:2}; renderPage()");
  assert.match(f.root.innerHTML,/주사위 미지급/);
  let prompt='';
  f.context.captureModal=html=>{prompt=html;};f.run('modal=captureModal');
  f.context.fetchOverride=async(path,options)=>{
    if(path==='/api/orders'&&options.method==='POST')return f.response({order:{id:9,quantity:2,dice_quantity:0,total:2000}});
    return f.context.normalFetch(path,options);
  };
  await f.run('checkout({disabled:false})');
  assert.match(prompt,/음료 구매에는 주사위가 지급되지 않아요/);
  assert.doesNotMatch(prompt,/주사위 2개/);
});

const testBadges=[
  {id:'score_5',name:'마법의 씨앗',description:'5점 보상을 받으면 이 배지를 얻을 수 있어요.',icon:'spark',owned:true,earned_at:'2026-11-07T00:00:00Z'},
  {id:'score_10',name:'빛나는 연금술',description:'10점 보상을 받으면 이 배지를 얻을 수 있어요.',icon:'flask',owned:false,earned_at:null},
];
test('equipped badges overlay the upper left of profile pictures but not face or hairpin swatches',()=>{
  const f=fixture();f.context.badgeUser={id:1,name:'참가자',equipped_badge:testBadges[0]};
  assert.match(f.run('profileAvatar(badgeUser)'),/data-badge-position="top-left"/);
  assert.match(f.run('profileAvatar(badgeUser)'),/data-badge-id="score_5"/);
  assert.match(f.run('profileAvatar(badgeUser,{full:true})'),/profile-badged-avatar badge-full/);
  assert.doesNotMatch(f.run('profileAvatar(badgeUser,{breadOnly:true})'),/profile-badge-overlay/);
  assert.doesNotMatch(f.run('profileAvatar(badgeUser,{pinOnly:true})'),/profile-badge-overlay/);
  f.context.badgeUser.equipped_badge=null;
  assert.doesNotMatch(f.run('profileAvatar(badgeUser)'),/profile-badge-overlay/);
});
test('profile badge tab offers only owned badges as radios and locked badges as question buttons',()=>{
  const f=fixture();f.context.badgeUser={id:1,name:'참가자',badges:testBadges,equipped_badge:testBadges[0]};
  const html=f.run('profileEditor(badgeUser)');
  assert.match(html,/data-tab="badges"/);
  assert.match(html,/name="badge_id" value="score_5" checked/);
  assert.match(html,/name="badge_id" value=""/);
  assert.doesNotMatch(html,/name="badge_id" value="score_10"/);
  assert.match(html,/data-action="badge-info" data-badge="score_10"/);
  assert.match(html,/class="badge-unknown"[^>]*>\?<\/i>/);
});
test('locked badge clicks reveal the earning hint without replacing the profile form or sending requests',async()=>{
  const f=fixture();await f.run('refresh()');
  const info={hidden:true,innerHTML:'',scrollIntoView(){}},original=f.context.document.querySelector;
  f.context.document.querySelector=selector=>selector==='[data-badge-info]'?info:original(selector);
  f.context.badgeList=testBadges;f.run('state.user.badges=badgeList');
  const before=f.requests.length;
  f.run("showBadgeInfo('score_10')");
  assert.equal(info.hidden,false);assert.match(info.innerHTML,/10점 보상을 받으면 이 배지를 얻을 수 있어요/);
  assert.equal(f.requests.length,before);
  assert.equal(f.run('state.user.equipped_badge'),undefined);
});
test('badge selection previews without saving or replacing the equipped account badge',async()=>{
  const f=fixture();f.remote.badges=testBadges;f.remote.equippedBadge=null;await f.run('refresh()');
  const {form}=profileForm(f),preview={innerHTML:''},original=f.context.document.querySelector;
  form.values=new Map([...Object.entries(chosenAvatar),['badge_id','score_5']]);
  f.context.FormData=class{constructor(form){this.values=form.values;}[Symbol.iterator](){return this.values.entries();}};
  f.context.document.querySelector=selector=>selector==='[data-profile-preview]'?preview:original(selector);
  f.run('updateProfilePreview(profileForm)');
  assert.match(preview.innerHTML,/profile-badge-overlay/);assert.match(preview.innerHTML,/data-badge-id="score_5"/);
  assert.equal(f.run('state.user.equipped_badge'),null);
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,0);
});
test('saving or removing the profile badge uses the existing profile transaction',async()=>{
  const f=fixture();f.remote.badges=testBadges;f.remote.equippedBadge=null;await f.run('refresh()');profileForm(f);
  f.context.fetchOverride=async(path,options)=>{
    if(path==='/api/profile'){
      const body=JSON.parse(options.body);f.remote.avatar=body.avatar;
      f.remote.equippedBadge=testBadges.find(b=>b.id===body.badge_id)||null;
      return f.response(await (await f.context.normalFetch('/api/auth/me')).json());
    }
    return f.context.normalFetch(path,options);
  };
  await f.run("saveProfile(profileForm,{...chosenAvatar,badge_id:'score_5'})");
  assert.deepEqual(JSON.parse(f.requests.find(r=>r.path==='/api/profile').body),{avatar:chosenAvatar,badge_id:'score_5'});
  assert.equal(f.run('state.user.equipped_badge.id'),'score_5');
  await f.run("saveProfile(profileForm,{...chosenAvatar,badge_id:''})");
  const requests=f.requests.filter(r=>r.path==='/api/profile');
  assert.equal(JSON.parse(requests[1].body).badge_id,null);
  assert.equal(f.run('state.user.equipped_badge'),null);
});
test('new badge ownership updates the open picker without discarding the current selection',async()=>{
  const f=fixture();f.remote.badges=testBadges;await f.run('refresh()');
  const {form}=profileForm(f),preview={innerHTML:''},target={dataset:{badges:JSON.stringify(testBadges)},outerHTML:''};
  form.values=new Map([...Object.entries(chosenAvatar),['badge_id','score_5']]);
  f.context.FormData=class{constructor(form){this.values=form.values;}[Symbol.iterator](){return this.values.entries();}};
  const original=f.context.document.querySelector;
  f.context.document.querySelector=selector=>selector==='#profile-editor'?form:selector==='[data-profile-badges]'?target:selector==='[data-profile-preview]'?preview:original(selector);
  f.context.updatedBadges=testBadges.map(b=>({...b,owned:true}));
  f.run('state.user.badges=updatedBadges;syncProfileBadges()');
  assert.match(target.outerHTML,/name="badge_id" value="score_5" checked/);
  assert.match(target.outerHTML,/name="badge_id" value="score_10"/);
  assert.equal(f.requests.filter(r=>r.path==='/api/profile').length,0);
});
test('staff badge mode shows owned badges, catalog creation and a separate grant endpoint',async()=>{
  const f=adminFixture();f.state.staffData.badges=testBadges;
  f.state.staffData.users[0].badges=testBadges;
  f.run("eventTab='manual';grantDraft.user_id='10'");
  await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'badge'}})");
  const html=f.run('renderAdmin()');
  assert.match(html,/id="admin-badge-create"/);assert.match(html,/배지 추가·보유 현황/);
  assert.match(html,/<option value="score_5"[^>]*disabled/);
  assert.match(html,/name="badge_id"/);assert.doesNotMatch(html,/name="quantity"/);
  f.context.respond=async()=>({grant:{id:9}});
  await f.submit({user_id:'10',badge_id:'score_10',reason:'이벤트 조건 확인'},'admin-manual-grant');
  assert.deepEqual(f.requests[0],{path:'/api/staff/badge-grants',method:'POST',body:{
    user_id:10,badge_id:'score_10',reason:'이벤트 조건 확인',request_id:'request-1'}});
  await f.run("handleAdminClick('admin-grant-recipient',{dataset:{mode:'guest'}})");
  assert.match(f.run('renderAdmin()'),/data-kind="badge"[^>]*disabled/);
});
test('staff can create a badge with a visible acquisition hint and a local icon',async()=>{
  const f=adminFixture();f.context.respond=async()=>({badge:{id:'custom_1'}});
  await f.submit({name:'특별상',description:'이벤트를 완료하면 이 배지를 얻을 수 있어요.',icon:'trophy'},'admin-badge-create');
  assert.deepEqual(f.requests[0],{path:'/api/staff/badges',method:'POST',body:{
    name:'특별상',description:'이벤트를 완료하면 이 배지를 얻을 수 있어요.',icon:'trophy',request_id:'request-1'}});
});

const testTitles=[
 {id:'elements',name:'원소 수집가',description:'휘낭시에 4종 모두 구매',style:'magic',owned:true},
 {id:'vvip',name:'캄딜 VVIP',description:'빵 11종 모두 구매',style:'gold',owned:false},
 {id:'fast',name:'⚡ 우사인볼트 연금술사',description:'선착순 구매',style:'lightning',owned:true},
];
const testAchievements=[
 {id:'elements',name:'원소 수집가',description:'휘낭시에 4종을 모두 구매해요.',current:2,target:4,unit:'종',completed:false,badge_id:'ach_elements',title:'원소 수집가',items:[{name:'플레인 휘낭시에',quantity:2},{name:'초코 휘낭시에',quantity:0}]},
 {id:'all_breads',name:'캄딜 VVIP',description:'빵 메뉴 11종을 모두 구매해요.',current:11,target:11,unit:'종',completed:true,badge_id:'ach_vvip',title:'캄딜 VVIP',style:'gold'},
];
test('event replaces nearby ranks with private achievement progress and retains top three',async()=>{
 const f=fixture();f.remote.achievements=testAchievements;await f.run('refresh()');
 f.run("state.route='ranking';renderPage()");
 assert.doesNotMatch(f.root.innerHTML,/내 주변 순위|ranking-neighbors/);
 assert.match(f.root.innerHTML,/최고의 연금술사 TOP 3/);
 assert.match(f.root.innerHTML,/도전과제/);assert.match(f.root.innerHTML,/1\/2 달성/);
 assert.match(f.root.innerHTML,/width:50%/);assert.match(f.root.innerHTML,/2 \/ 4종/);
 assert.match(f.root.innerHTML,/achievement-card is-completed/);
});
test('achievement details describe rewards and purchase quantities without claim requests',async()=>{
 const f=fixture();f.remote.achievements=testAchievements;await f.run('refresh()');let html='';
 f.context.capture=content=>html=content;f.run('modal=capture');
 const before=f.requests.length;f.run("openAchievement('elements')");
 assert.match(html,/플레인 휘낭시에/);assert.match(html,/2개/);assert.match(html,/구매 승인 후 자동으로 지급/);
 assert.doesNotMatch(html,/data-action="profile-rewards"/);
 f.run("openAchievement('all_breads')");assert.match(html,/title-gold/);assert.match(html,/프로필에서 칭호 고르기/);
 assert.equal(f.requests.length,before);
});
test('generated badge artwork uses four bundled assets while unknown ids keep safe local drawings',()=>{
 const f=fixture();
 for(const [id,file] of [['ach_elements','elements'],['ach_vvip','vvip'],['ach_focus','focus'],['ach_fast','fast']]){
  const html=f.run(`badgePicture({id:'${id}',name:'배지'})`);assert.match(html,new RegExp(`/assets/badges/${file}-v1.webp`));
  assert.ok(readFileSync(new URL(`../frontend/assets/badges/${file}-v1.webp`,import.meta.url)).length>1000);
 }
 f.context.evilBadge={id:'https://evil.test/badge',icon:'x',name:'<script>bad</script>'};
 assert.doesNotMatch(f.run('badgePicture(evilBadge)'),/<img|<script>|src="https/);
});
test('titles use safe styles and escaped text beside nickname in the header and rankings',async()=>{
 const f=fixture();f.remote.equippedTitle=testTitles[2];await f.run('refresh()');
 f.run("state.route='ranking';state.leaderboard.leaders[0].equipped_title=state.user.equipped_title;renderPage()");
 assert.equal((f.root.innerHTML.match(/title-lightning/g)||[]).length,2);
 assert.match(f.root.innerHTML,/⚡ 우사인볼트 연금술사/);
 f.context.untrustedTitle={equipped_title:{name:'<img src=x onerror=alert(1)>',style:'evil" onload="x'}};
 const html=f.run('profileTitle(untrustedTitle)');assert.match(html,/title-magic/);
 assert.doesNotMatch(html,/<img|class="[^"]*evil/);assert.match(html,/&lt;img/);
});
test('title picker offers owned titles and none while locked titles reveal earning instructions',async()=>{
 const f=fixture();f.remote.titles=testTitles;f.remote.equippedTitle=testTitles[0];await f.run('refresh()');
 const html=f.run('profileEditor(state.user)');
 assert.match(html,/data-tab="titles"/);assert.match(html,/name="title_id" value="elements" checked/);
 assert.match(html,/name="title_id" value=""/);assert.doesNotMatch(html,/name="title_id" value="vvip"/);
 assert.match(html,/data-action="title-info" data-title="vvip"/);
 const panel={hidden:true,innerHTML:'',scrollIntoView(){}};const original=f.context.document.querySelector;
 f.context.document.querySelector=s=>s==='[data-title-info]'?panel:original(s);
 const before=f.requests.length;f.run("showTitleInfo('vvip')");
 assert.match(panel.innerHTML,/빵 11종 모두 구매/);assert.equal(panel.hidden,false);assert.equal(f.requests.length,before);
});
test('title preview changes locally and save sends title and badge in the same transaction',async()=>{
 const f=fixture();f.remote.titles=testTitles;f.remote.equippedTitle=null;f.remote.badges=testBadges;await f.run('refresh()');
 const {form}=profileForm(f),preview={innerHTML:''},titlePreview={innerHTML:''},original=f.context.document.querySelector;
 form.values=new Map([...Object.entries(chosenAvatar),['title_id','fast'],['badge_id','score_5']]);
 f.context.FormData=class{constructor(form){this.values=form.values;}[Symbol.iterator](){return this.values.entries();}};
 f.context.document.querySelector=s=>s==='[data-profile-preview]'?preview:s==='[data-profile-title-preview]'?titlePreview:original(s);
 f.run('updateProfilePreview(profileForm)');assert.match(titlePreview.innerHTML,/title-lightning/);
 assert.equal(f.run('state.user.equipped_title'),null);
 f.context.fetchOverride=async(path,options)=>{
  if(path==='/api/profile'){const body=JSON.parse(options.body);f.remote.equippedTitle=testTitles.find(t=>t.id===body.title_id)||null;return f.response(await(await f.context.normalFetch('/api/auth/me')).json());}
  return f.context.normalFetch(path,options);
 };
 await f.run("saveProfile(profileForm,{...chosenAvatar,badge_id:'score_5',title_id:'fast'})");
 assert.deepEqual(JSON.parse(f.requests.find(r=>r.path==='/api/profile').body),{avatar:chosenAvatar,badge_id:'score_5',title_id:'fast'});
 await f.run("saveProfile(profileForm,{...chosenAvatar,title_id:''})");
 assert.equal(JSON.parse(f.requests.filter(r=>r.path==='/api/profile')[1].body).title_id,null);
});
test('live title ownership refresh retains the current choice and draft avatar',async()=>{
 const f=fixture();f.remote.titles=testTitles;await f.run('refresh()');const {form}=profileForm(f);
 const preview={innerHTML:''},titlePreview={innerHTML:''},target={dataset:{titles:JSON.stringify(testTitles)},outerHTML:'',querySelector:()=>null};
 form.values=new Map([...Object.entries(chosenAvatar),['title_id','elements']]);
 f.context.FormData=class{constructor(form){this.values=form.values;}[Symbol.iterator](){return this.values.entries();}};
 const original=f.context.document.querySelector;
 f.context.document.querySelector=s=>s==='#profile-editor'?form:s==='[data-profile-titles]'?target:s==='[data-profile-preview]'?preview:s==='[data-profile-title-preview]'?titlePreview:original(s);
 f.context.newTitles=testTitles.map(t=>({...t,owned:true}));f.run('state.user.titles=newTitles;syncProfileTitles()');
 assert.match(target.outerHTML,/name="title_id" value="elements" checked/);assert.match(target.outerHTML,/name="title_id" value="vvip"/);
 assert.equal(form.values.get('expression'),'wink');assert.match(titlePreview.innerHTML,/원소 수집가/);
});
test('staff title controls track ownership and custom creation and forbid guest grants',async()=>{
 const f=adminFixture();f.state.staffData.titles=testTitles;f.state.staffData.users[0].titles=testTitles;
 f.run("eventTab='manual';grantDraft.user_id='10'");await f.run("handleAdminClick('admin-grant-kind',{dataset:{kind:'title'}})");
 let html=f.run('renderAdmin()');assert.match(html,/칭호 추가·보유 현황/);assert.match(html,/id="admin-title-create"/);
 assert.match(html,/<option value="elements"[^>]*disabled/);assert.doesNotMatch(html,/name="quantity"/);
 f.context.respond=async()=>({grant:{id:8}});
 await f.submit({user_id:'10',title_id:'vvip',reason:'조건 확인'},'admin-manual-grant');
 assert.deepEqual(f.requests[0],{path:'/api/staff/title-grants',method:'POST',body:{user_id:10,title_id:'vvip',reason:'조건 확인',request_id:'request-1'}});
 await f.run("handleAdminClick('admin-grant-recipient',{dataset:{mode:'guest'}})");
 html=f.run('renderAdmin()');assert.match(html,/data-kind="title"[^>]*disabled/);
});
test('staff custom title creation sends only the validated name hint and style',async()=>{
 const f=adminFixture();f.context.respond=async()=>({title:{id:'custom_1'}});
 await f.submit({name:'캄딜 대마법사',description:'담당자 확인',style:'gold'},'admin-title-create');
 assert.deepEqual(f.requests[0],{path:'/api/staff/titles',method:'POST',body:{name:'캄딜 대마법사',description:'담당자 확인',style:'gold',request_id:'request-1'}});
});

test('staff schedule builds date columns and sorted time rows from server data only',()=>{
 const f=adminFixture();f.state.route='notes';
 f.state.staffData.schedule=[{id:1,event_date:'2099-01-02',time:'10:00-11:00',name:'담당 C',role:''},
  {id:2,event_date:'2099-01-01',time:'10:00-11:00',name:'담당 A, 담당 B',role:'판매'},
  {id:3,event_date:'2099-01-01',time:'오픈',name:'준비 담당',role:''}];
 const html=f.run('renderAdmin()');
 assert.match(html,/aria-label="날짜별 담당 시간표"/);
 assert.ok(html.indexOf('title="2099-01-01"')<html.indexOf('title="2099-01-02"'));
 assert.ok(html.indexOf('<th scope="row">오픈')<html.indexOf('<th scope="row">10:00-11:00'));
 assert.match(html,/담당 A, 담당 B/);assert.match(html,/담당 C/);
 assert.match(html,/<small class="muted">판매/);assert.match(html,/<span class="muted">—/);
 assert.doesNotMatch(html,/오늘의 담당 시간표|담당 팀/);
});
test('staff schedule keeps legacy common rows and shows an empty state with no roster',()=>{
 const f=adminFixture();f.state.route='notes';
 assert.match(f.run('renderAdmin()'),/등록된 시간표가 없어요/);
 f.state.staffData.schedule=[{id:1,name:'공통 담당',time:'오픈',role:'준비'}];
 let html=f.run('renderAdmin()');assert.match(html,/aria-label="공통 담당 시간표"/);
 assert.match(html,/공통 담당/);assert.doesNotMatch(html,/날짜별 담당 시간표/);
 f.state.staffData.schedule.push({id:2,name:'날짜 담당',time:'오픈',role:'',event_date:'2099-01-01'});
 html=f.run('renderAdmin()');assert.match(html,/날짜별 담당 시간표/);assert.match(html,/공통 시간표/);
});
test('schedule labels format Korean weekdays without embedding a particular event date',()=>{
 const f=adminFixture();
 assert.equal(f.run("scheduleDateLabel('2099-01-01')"),'1/1(목)');
 assert.equal(f.run("scheduleDateLabel('invalid')"),'invalid');
 assert.equal(f.run("scheduleDateLabel('2099-02-30')"),'2099-02-30');
});

test('manual sale image cards retain product labels, prices, stock constraints and quantity hooks',()=>{
 const f=adminFixture();f.state.route='sales';
 f.state.staffData.products=[{id:101,name:'플레인 휘낭시에',price:2800,stock:3,photo:'/assets/products/plain-financier-v1.webp'},
  {id:102,name:'초코 휘낭시에',price:3000,stock:0,photo:'/assets/products/chocolate-financier-v1.webp'}];
 const html=f.run('renderAdmin()');
 assert.match(html,/class="content-card manual-sale-panel"/);assert.match(html,/class="manual-product-grid" aria-label="수기판매 메뉴"/);
 assert.match(html,/src="\/assets\/products\/plain-financier-v1.webp"/);assert.match(html,/src="\/assets\/products\/chocolate-financier-v1.webp"/);
 assert.match(html,/id="admin-sale-qty-101"[^>]*max="3"[^>]*data-sale-product="101" data-price="2800"/);
 assert.match(html,/id="admin-sale-qty-102"[^>]*max="0"[^>]*disabled/);
 assert.match(html,/재고 3개/);assert.match(html,/품절/);
 assert.equal((html.match(/data-sale-product=/g)||[]).length,2);
 assert.match(html,/data-sale-total/);assert.match(html,/type="submit">판매 완료/);
});
test('buyer product illustrations keep sold out controls and omit inventory numbers',async()=>{
 const f=fixture();await f.run('refresh()');
 f.context.products=[{id:101,name:'플레인 휘낭시에',price:2800,stock:2,photo:'/assets/products/plain-financier-v1.webp'},
  {id:102,name:'초코 휘낭시에',price:3000,stock:0,photo:'/assets/products/chocolate-financier-v1.webp'}];
 f.run("state.products=products;state.route='shop';renderPage()");
 assert.match(f.root.innerHTML,/src="\/assets\/products\/plain-financier-v1.webp" alt="플레인 휘낭시에"/);
 assert.match(f.root.innerHTML,/product-row sold-out/);assert.match(f.root.innerHTML,/data-action="cart-plus" data-id="102" disabled/);
 assert.doesNotMatch(f.root.innerHTML,/재고 2|남은 수량 2/);
 assert.match(f.run("productPhoto({id:112,name:'우유'})"),/photo-placeholder/);
});


const testNotices=[
  {id:3,kind:'achievement',content:'원소 수집가 도전과제를 달성했습니다!',author:{id:10,name:'별빵',equipped_title:{name:'원소 수집가',style:'magic'}}},
  {id:2,kind:'announcement',content:'오늘 이벤트는 오후 6시에 마감됩니다.',author:{name:'관리자'}},
];
test('event board hides at zero, shows one or two, and replaces the prototype notice only on event page',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='ranking';window.KAMBO_CONFIG.prototype=true;renderPage()");
  assert.doesNotMatch(f.root.innerHTML,/event-notice-board|가안 테스트/);
  f.context.notices=testNotices;
  for(const count of [1,2]){
    f.run(`state.eventNotices=notices.slice(0,${count});renderPage()`);
    assert.equal((f.root.innerHTML.match(/<article class="event-notice /g)||[]).length,count);
    assert.ok(f.root.innerHTML.indexOf('event-notice-board')<f.root.innerHTML.indexOf('<h1>이벤트 참여'));
    assert.match(f.root.innerHTML,/별빵/);assert.match(f.root.innerHTML,/profile-avatar/);assert.match(f.root.innerHTML,/title-magic/);
    assert.doesNotMatch(f.root.innerHTML,/가안 테스트/);
  }
  f.run("state.route='shop';renderPage()");
  assert.match(f.root.innerHTML,/가안 테스트/);assert.doesNotMatch(f.root.innerHTML,/event-notice-board/);
});
test('shared board escapes author, title and content and has no buyer management controls',()=>{
  const f=fixture();f.context.badNotices=[{id:1,kind:'announcement',content:'<script>alert(1)</script>',author:{name:'<img src=x>',equipped_title:{name:'<b>칭호</b>',style:'gold'}}}];
  const html=f.run('renderEventNotices(badNotices)');
  assert.doesNotMatch(html,/<script>|<img src=x>|<b>칭호|admin-notice-delete/);
  assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img src=x&gt;/);assert.match(html,/공지/);
});
test('polling updates shared notices without disturbing an open editor and removes the board at zero',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run("state.route='ranking'");f.context.document.activeElement={tagName:'TEXTAREA'};
  f.remote.notices=testNotices;await f.context.poll();
  assert.equal(f.renders,0);assert.equal(f.run('state.eventNotices.length'),2);
  f.context.document.activeElement={tagName:'BODY'};await f.context.poll();assert.equal(f.renders,1);
  f.remote.notices=[];await f.context.poll();assert.equal(f.renders,2);
  assert.equal(f.run('renderEventNotices(state.eventNotices)'), '');
});
test('admin notices have a separate panel with a short announcement form and delete controls',()=>{
  const f=adminFixture();f.run("eventTab='notices'");
  let html=f.run('renderAdmin()');assert.match(html,/data-tab="notices"/);assert.match(html,/id="admin-notice-create"/);
  assert.match(html,/maxlength="160"/);assert.match(html,/공용 관리자 프로필/);assert.match(html,/표시 중인 알림이 없습니다/);
  f.state.staffData.event_notices=testNotices;html=f.run('renderAdmin()');
  assert.equal((html.match(/data-action="admin-notice-delete"/g)||[]).length,2);
  assert.match(html,/별빵/);assert.match(html,/관리자/);assert.doesNotMatch(html,/name="author"|name="user_id"/);
});
test('admin announcement submits content and request id, and deletion calls staff endpoint',async()=>{
  const f=adminFixture();await f.submit({content:'오늘 행사 안내'},'admin-notice-create');
  assert.equal(f.requests[0].path,'/api/staff/event-notices');
  assert.deepEqual(f.requests[0].body,{content:'오늘 행사 안내',request_id:'request-1'});
  f.context.deleteButton={dataset:{id:'3'},disabled:false};
  await f.run("handleAdminClick('admin-notice-delete',deleteButton)");
  assert.deepEqual(f.requests[1],{path:'/api/staff/event-notices/3/delete',method:'POST',body:{}});
});

test('declining a drink sends the cancellation request once and removes buyer waiting UI',async()=>{
  const f=fixture();await f.run('refresh()');let release;
  let row={id:9,status:'awaiting_choice',product_name:'우유·두유 선택',threshold:10};
  f.run('closeModal=()=>{}');f.context.waiting=row;
  f.run('state.rewardRequests=[waiting];state.rewards=[{id:2,threshold:10,kind:"milk",fulfillment:waiting}]');
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/reward-requests/9/decline')return new Promise(resolve=>release=()=>{row={...row,status:'cancelled'};resolve(f.response({request:row}));});
    if(path==='/api/rewards')return f.response({rewards:[{id:2,threshold:10,kind:'milk',fulfillment:row}],requests:[row]});
    return f.context.normalFetch(path,options);
  };
  const first=f.run("chooseBeverage({dataset:{request:'9'}},true)");
  await f.run("chooseBeverage({dataset:{request:'9'}},true)");
  const requests=f.requests.filter(r=>r.path.includes('/decline'));
  assert.equal(requests.length,1);assert.deepEqual(Object.keys(JSON.parse(requests[0].body)),['request_id']);
  release();await first;
  assert.equal(f.run('state.rewardRequests[0].status'),'cancelled');
  assert.equal(f.run('state.rewards[0].fulfillment.status'),'cancelled');
  assert.equal(f.run('renderRewardRequests()'),'');
  assert.match(f.run('renderRewardHistory()'),/지급 취소/);
});

test('successful cancellation updates the milestone record even when the following refresh fails',async()=>{
  const f=fixture();await f.run('refresh()');
  f.run('closeModal=()=>{};state.rewards=[{id:2,threshold:10,kind:"milk",fulfillment:{id:9,status:"awaiting_choice"}}]');
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/reward-requests/9/decline')return f.response({request:{id:9,status:'cancelled',product_name:'우유·두유 선택'}});
    if(path==='/api/config')throw new Error('offline after cancellation');
    return f.context.normalFetch(path,options);
  };
  await f.run("chooseBeverage({dataset:{request:'9'}},true)");
  assert.equal(f.run('state.rewardRequests[0].status'),'cancelled');
  assert.equal(f.run('state.rewards[0].fulfillment.status'),'cancelled');
  assert.equal(f.run('renderRewardRequests()'),'');
  assert.match(f.run('renderRewardHistory()'),/지급 취소/);
  assert.equal(f.run('state.leveling'),false);
});

test('failed cancellation keeps its retry id and the request available instead of pretending success',async()=>{
  const f=fixture();await f.run('refresh()');let prompt='',attempts=0;
  let row={id:9,status:'awaiting_choice',product_name:'우유·두유 선택'};
  f.context.capture=html=>prompt=html;f.run('modal=capture;closeModal=()=>{}');
  f.context.fetchOverride=(path,options)=>{
    if(path==='/api/reward-requests/9/decline'){
      if(++attempts===1)return f.response({error:'일시적인 연결 오류'},503);
      row={...row,status:'cancelled'};return f.response({request:row});
    }
    if(path==='/api/rewards')return f.response({rewards:[],requests:[row]});
    return f.context.normalFetch(path,options);
  };
  await f.run("chooseBeverage({dataset:{request:'9'}},true)");
  assert.equal(f.run('state.rewardRequests[0].status'),'awaiting_choice');
  assert.match(prompt,/data-action="decline-beverage" data-request="9">취소하기/);
  await f.run("chooseBeverage({dataset:{request:'9'}},true)");
  const posts=f.requests.filter(r=>r.path.endsWith('/decline'));
  assert.equal(JSON.parse(posts[0].body).request_id,JSON.parse(posts[1].body).request_id);
  assert.equal(f.run('state.rewardRequests[0].status'),'cancelled');
});
