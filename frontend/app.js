import {initAdmin, renderAdmin, renderStaffLogin, handleAdminClick, handleAdminSubmit} from './admin.js';

const isAdmin = /^\/admin(?:\/|$)/.test(location.pathname);
const tokenKey = `kambo.${isAdmin ? 'staff' : 'buyer'}.token`;
const state = {isAdmin,token:localStorage.getItem(tokenKey),user:null,config:{},products:[],orders:[],rewards:[],leaderboard:null,staffData:null,route:location.hash.slice(1)||(isAdmin?'queue':'shop'),cart:{},reservation:null,authMode:'login',rolling:false,leveling:false,lastRoll:null};
const paths={shop:'M3 10h18M5 10v10h14V10M3 10l2-6h14l2 6M9 20v-6h6v6M2 10c0 3 4 3 4 0 0 3 4 3 4 0 0 3 4 3 4 0 0 3 4 3 4 0 0 3 4 3 4 0',bag:'M5 7h14l1 14H4L5 7ZM8 8V6a4 4 0 0 1 8 0v2',dice:'M6 3h12a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3ZM8 8h.01M16 8h.01M12 12h.01M8 16h.01M16 16h.01',trophy:'M8 3h8v7a4 4 0 0 1-8 0V3ZM8 5H4v3a4 4 0 0 0 4 4m8-7h4v3a4 4 0 0 1-4 4M12 14v6M8 21h8',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7v5l3 2',arrow:'M4 12h15m-5-5 5 5-5 5',plus:'M12 5v14M5 12h14',minus:'M5 12h14',x:'m6 6 12 12M18 6 6 18',check:'m5 12 4 4L19 6',info:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 11v6M12 7h.01',bread:'M5 11C-1 4 9 0 12 5c5-6 15 1 7 6v9H5v-9ZM9 11v4m6-4v4',user:'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4 21v-2a8 8 0 0 1 16 0v2',users:'M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM2 21v-2a7 7 0 0 1 14 0v2M17 4a4 4 0 0 1 0 7m2 4a6 6 0 0 1 3 5',shield:'m12 2 8 3v6c0 6-8 11-8 11S4 17 4 11V5l8-3ZM8 11l3 3 5-6',box:'m3 7 9-4 9 4v11l-9 4-9-4V7Zm0 0 9 4 9-4M12 11v11M7 5l9 4',note:'M5 3h14v13l-5 5H5V3Zm9 18v-5h5M8 8h8M8 12h5',calendar:'M4 5h16v16H4V5ZM8 3v4m8-4v4M4 10h16M8 14h2m4 0h2m-8 3h2',spark:'m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z',logout:'M9 3H4v18h5m4-15 6 6-6 6m-5-6h11',chevron:'m9 5 7 7-7 7',heart:'M12 21 3 12C-2 6 6 0 12 6c6-6 14 0 9 6l-9 9Z',search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6',milk:'M9 3h6v4l3 4v10H6V11l3-4V3Zm0 4h6M6 12h12',upload:'M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6',edit:'m15 4 5 5M4 20l5-1L21 7l-5-5L4 14v6Z'};
function icon(name){return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.bread}"/></svg>`}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function money(value){return Number(value||0).toLocaleString('ko-KR');}
function time(value){if(!value)return '';return new Intl.DateTimeFormat('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value));}
function requestId(){if(crypto.randomUUID)return crypto.randomUUID();const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;return [...bytes].map((b,i)=>([4,6,8,10].includes(i)?'-':'')+b.toString(16).padStart(2,'0')).join('');}
function operation(scope,body={}){const key=`kambo.pending.${isAdmin?'staff':'buyer'}.${state.user?.id||'guest'}.${scope}`;const fingerprint=JSON.stringify(body);let saved;try{saved=JSON.parse(sessionStorage.getItem(key));}catch{}if(!saved||saved.fingerprint!==fingerprint){saved={fingerprint,id:requestId()};sessionStorage.setItem(key,JSON.stringify(saved));}return {id:saved.id,done(){sessionStorage.removeItem(key);}};}
async function refreshAfterAction(){try{await refresh();}catch{toast('작업은 완료됐어요. 최신 상태는 잠시 후 다시 연결해요.');}}
async function api(path,{method='GET',body,token=state.token}={}){const headers={};if(token)headers.Authorization=`Bearer ${token}`;if(body!==undefined)headers['Content-Type']='application/json';const r=await fetch(`${(window.KAMBO_CONFIG?.apiBase||'').replace(/\/$/,'')}${path}`,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json().catch(()=>({error:'서버 응답을 확인할 수 없어요.'}));if(!r.ok){const error=new Error(data.error||'요청을 처리하지 못했어요.');error.status=r.status;throw error;}return data;}
function toast(message,type='success'){const node=document.createElement('div');node.className=`toast ${type}`;node.innerHTML=`${icon(type==='error'?'info':'check')}<span>${esc(message)}</span>`;document.querySelector('#toast-root').append(node);setTimeout(()=>node.remove(),4500);}
let previousFocus;
function modal(content,{wide=false}={}){previousFocus=document.activeElement;document.querySelector('#modal-root').innerHTML=`<div class="overlay"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-label="${isAdmin?'담당자 작업':'캄보딜라이트 안내'}" tabindex="-1"><button class="modal-close" data-action="close-modal" aria-label="닫기">${icon('x')}</button>${content}</section></div>`;document.body.style.overflow='hidden';requestAnimationFrame(()=>(document.querySelector('.modal input:not([type=hidden]),.modal textarea,.modal select,.modal [type=submit]')||document.querySelector('.modal'))?.focus());}
function closeModal(){document.querySelector('#modal-root').innerHTML='';document.body.style.overflow='';previousFocus?.focus?.();}
function submitButton(form,busy,label){const button=form.querySelector('[type=submit]');if(!button)return;button.disabled=busy;if(!button.dataset.label)button.dataset.label=button.innerHTML;button.innerHTML=busy?'<span class="spinner"></span> 처리하고 있어요':label||button.dataset.label;}
function brand(){return `<span class="brand"><span class="brand-icon">${icon('bread')}</span><span><strong>캄보딜라이트</strong><small>CAMBODELIGHT</small></span></span>`;}
const buyerNav=[['shop','bag','빵 구매'],['ranking','trophy','이벤트 참여']];
const staffNav=[['queue','clock','주문 확인'],['sales','edit','수기 판매'],['inventory','box','재고'],['events','spark','인스타 이벤트'],['notes','note','인수인계']];
function navButton([route,img,label]) {
  const active=isAdmin?state.route===route:route==='shop'?['shop','pickup','orders'].includes(state.route):['dice','ranking'].includes(state.route);
  const pending=isAdmin&&route==='queue'?(state.staffData?.stats.pending_orders||0):0;
  return `<button class="nav-item ${active?'active':''}" data-action="navigate" data-route="${route}" ${active?'aria-current="page"':''}>${icon(img)}<span>${label}</span>${pending?`<b class="pending-pill">${pending}</b>`:''}</button>`;
}
function shell(content) {
  const eventPage=!isAdmin&&['dice','ranking'].includes(state.route);
  return `<div class="shell ${isAdmin?'admin':eventPage?'event-space':'purchase-space'} ${state.user?'signed-in':''}">
    <header class="app-header"><a href="${isAdmin?'/admin/':'/'}" aria-label="캄보딜라이트 홈">${brand()}</a>
    ${state.user?`<button class="profile-button" data-action="profile">${esc(state.user.name)}${isAdmin?' · 담당자':''} ${icon('chevron')}</button>`:isAdmin?'<span class="muted">담당자 로그인</span>':''}</header>
    ${state.user?`<nav class="primary-nav" aria-label="${isAdmin?'담당자 메뉴':'주요 메뉴'}">${(isAdmin?staffNav:buyerNav).map(x=>navButton(x)).join('')}</nav>`:''}
    <main class="main">${content}</main>
    ${!isAdmin&&state.user&&state.route==='shop'&&cartCount()?`<button class="mobile-cart" data-action="open-cart">선택 수량 ${cartCount()} <strong>${money(cartTotal())}원 · 구매하기 ${icon('arrow')}</strong></button>`:''}
  </div>`;
}
function pageHeading(title,desc='') { return `<div class="page-heading"><div><h1>${title}</h1>${desc?`<p>${desc}</p>`:''}</div></div>`; }
function subnav(items) { return `<nav class="subnav" aria-label="${['dice','ranking'].includes(state.route)?'이벤트 메뉴':'구매 메뉴'}">${items.map(([route,label])=>`<button class="${state.route===route?'active':''}" data-action="navigate" data-route="${route}" ${state.route===route?'aria-current="page"':''}>${label}</button>`).join('')}</nav>`; }
function purchaseHeading() { return `${pageHeading('빵 구매','예약한 빵 수령 또는 현장 구매를 선택해 주세요.')}${subnav([['shop','현장 구매'],['pickup','예약한 빵 수령'],['orders','주문 내역']])}`; }
function eventHeading() { return pageHeading('이벤트 참여','주사위를 굴리고, 최고의 연금술사에 도전해요.'); }
function prototypeNotice() { return window.KAMBO_CONFIG?.prototype||state.config.demo?'<p class="prototype-note">가안 테스트 · 샘플 데이터입니다.</p>':''; }
function cartCount(){return Object.values(state.cart).reduce((s,v)=>s+v,0);}
function cartTotal(){return state.products.reduce((s,p)=>s+p.price*(state.cart[p.id]||0),0);}
function productImage(product){const name=String(product.image||'salt-bread').replace(/[^a-z-]/g,'');return `/assets/${name}.svg`;}
function productPhoto(product){return `<div class="product-photo"><span class="photo-placeholder" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24"><path d="M3 3h18v18H3V3Zm0 14 6-6 4 4 3-3 5 5M8 8h.01"/></svg></span>${product.photo?`<img src="${esc(product.photo)}" alt="${esc(product.name)} 사진" loading="lazy" width="72" height="72">`:''}</div>`;}

function renderBasket() {
  const entries=state.products.filter(p=>state.cart[p.id]);
  return `<section class="basket"><h2>선택한 품목</h2>${entries.length?`<div class="basket-items">${entries.map(p=>`<div class="basket-item"><div><strong>${esc(p.name)} × ${state.cart[p.id]}${p.unit||'개'}</strong><span>${money(p.price*state.cart[p.id])}원</span></div><button class="icon-button" data-action="remove-cart" data-id="${p.id}" aria-label="${esc(p.name)} 선택 취소">${icon('x')}</button></div>`).join('')}</div>`:'<p class="muted">구매할 품목의 수량을 선택해 주세요.</p>'}
  <div class="basket-total"><span>선택 수량 ${cartCount()}</span><strong>${money(cartTotal())}원</strong></div>
  <button class="primary-button full" data-action="checkout" ${!entries.length?'disabled':''}>구매 요청하기</button>
  <p class="form-hint">담당자에게 입금 내역을 보여주고 승인을 받아주세요.</p></section>`;
}
function renderShop() {
  return `${purchaseHeading()}<div class="shop-layout"><section class="product-list" aria-label="현판 빵 목록">${state.products.map(p=>`<article class="product-row ${p.stock<=0?'sold-out':''}" ${p.stock<=0?'aria-disabled="true"':''}>
    ${productPhoto(p)}
    <div class="product-info"><h2>${esc(p.name)}</h2>${p.subtitle?`<span class="menu-concept">${esc(p.subtitle)}</span>`:''}<div class="product-price"><strong>${money(p.price)}원</strong>${p.dice_per_unit===0?'<span class="menu-concept">주사위 미지급</span>':''}${p.stock<=0?'<span class="sold-out-label">품절</span>':''}</div></div>
    <div class="product-count"><button class="quantity-button" data-action="cart-minus" data-id="${p.id}" ${p.stock<=0||!state.cart[p.id]?'disabled':''} aria-label="${esc(p.name)} 수량 줄이기">${icon('minus')}</button><span aria-label="${esc(p.name)} 선택 수량">${state.cart[p.id]||0}</span><button class="quantity-button" data-action="cart-plus" data-id="${p.id}" ${p.stock<=0||(state.cart[p.id]||0)>=p.stock?'disabled':''} aria-label="${esc(p.name)} 수량 늘리기">${icon('plus')}</button></div>
    </article>`).join('')}</section><aside class="desktop-basket">${renderBasket()}</aside></div>`;
}
function authRequired() { return renderBuyerLogin(); }
function orderDice(order){return order.dice_quantity??order.quantity;}
function orderLines(order){return `<div class="order-lines">${order.items.map(i=>`<div class="order-line"><span>${esc(i.name)} <span>× ${i.quantity}</span></span><span>${money(i.price*i.quantity)}원</span></div>`).join('')}</div>`;}
function orderStatus(status){return `<span class="status ${status}">${icon(status==='approved'?'check':status==='cancelled'?'x':'clock')}${{pending:'담당자 확인 중',approved:'수령 완료',cancelled:'취소 완료'}[status]||status}</span>`;}
function renderPickup() {
  return `${purchaseHeading()}<section class="content-card narrow"><h2>예약 내역 조회</h2><form id="preorder-lookup"><div class="field"><label for="preorder-name">예약자 이름</label><input id="preorder-name" name="name" value="${esc(state.user.name)}" readonly required></div><div class="field"><label for="preorder-phone">예약 전화번호</label><input id="preorder-phone" type="tel" name="phone" inputmode="tel" autocomplete="tel" placeholder="01012345678" required maxlength="20"></div><button class="primary-button full" type="submit">예약 조회</button></form>
  ${state.reservation?`<div class="reservation-result"><h3>${esc(state.reservation.name)} 님의 예약</h3>${orderLines(state.reservation)}<div class="basket-total"><span>예약 금액</span><strong>${money(state.reservation.total)}원</strong></div><button class="primary-button full" data-action="claim-preorder" data-id="${state.reservation.id}">담당자에게 수령 요청</button><p class="form-hint">담당자가 예약한 빵을 전달하고 승인하면 완료됩니다.</p></div>`:''}</section>`;
}
function renderOrders() {
  return `${purchaseHeading()}<div class="narrow">${state.orders.length?state.orders.map(o=>`<article class="order-card"><div class="order-top"><strong>${{walkin:'현장 구매',preorder:'예약한 빵 수령',manual:'수기 판매'}[o.type]} #${String(o.id).padStart(3,'0')}</strong>${orderStatus(o.status)}</div>${orderLines(o)}<div class="order-bottom"><span>${time(o.created_at)}</span><strong>${money(o.total)}원</strong></div>
  ${o.status==='pending'?`<p class="callout">${o.type==='preorder'?'담당자에게 예약 내역을 보여주고 빵을 받아주세요.':'담당자에게 주문과 입금 내역을 보여주세요.'} 승인 대기 중입니다.</p>`:o.status==='approved'?`<div class="callout"><span>구매 완료 · ${orderDice(o)?`주사위 ${orderDice(o)}개 지급`:'우유는 주사위 미지급'}</span><button class="text-button" data-action="navigate" data-route="ranking">이벤트 참여하기 ${icon('arrow')}</button></div>`:''}</article>`).join(''):'<div class="empty-state"><h2>주문 내역이 없습니다.</h2><button class="primary-button" data-action="navigate" data-route="shop">현장 구매하기</button></div>'}</div>`;
}
const dieDots={1:[5],2:[1,9],3:[1,5,9],4:[1,3,7,9],5:[1,3,5,7,9],6:[1,3,4,6,7,9]};
function die(value=5){return `<div class="big-dice" aria-label="주사위 ${value}">${Array.from({length:9},(_,i)=>`<i class="${dieDots[value].includes(i+1)?'dot':''}"></i>`).join('')}</div>`;}
const characterTiers = [
  {name:'연금술 수련생'}, {name:'견습 연금술사'}, {name:'원소 연금술사'},
  {name:'황금 연금술사'}, {name:'별빛 현자'}, {name:'전설의 대연금술사'},
];
function eventProgress(user=state.user) {
  const step=state.config.reward_step||10,claimed=user.rewards_claimed||0;
  const level=Math.min(characterTiers.length-1,claimed),target=(claimed+1)*step;
  return {step,claimed,level,target,remaining:Math.max(0,target-user.score),eligible:user.score>=target};
}
function characterPortrait(level,className='',earnedLevel=eventProgress().level) {
  if(level===0||level>earnedLevel)return `<div class="alchemist character-unknown ${className}" role="img" aria-label="아직 얻지 못한 캐릭터">?</div>`;
  return `<img class="alchemist ${className}" src="/assets/alchemist-${level}.svg" alt="${characterTiers[level].name}" width="160" height="160">`;
}
function diceAction() {
  const busy=state.rolling||state.leveling;
  if(!state.user.dice_balance)return `<button class="primary-button purchase-cta full" data-action="navigate" data-route="shop" ${busy?'disabled':''}>${icon('bag')}빵 구매하고 주사위 얻기</button>`;
  return `<button class="primary-button full" data-action="roll-dice" ${busy?'disabled':''}>${icon('dice')}${state.rolling?'굴리는 중…':'주사위 1개 굴리기'}</button>`;
}
function renderDiceControl() {
  const result=state.rolling?'주사위를 굴리고 있어요…':state.lastRoll?`결과 ${state.lastRoll} · +${state.lastRoll}점`:state.user.dice_balance?'나온 숫자만큼 점수가 쌓여요.':'빵 구매 승인 후 주사위가 지급돼요.';
  return `<div class="inline-dice ${state.rolling?'rolling':''}" aria-label="주사위 굴리기" aria-busy="${state.rolling}">
    <div class="dice-control-head"><div class="dice-visual" aria-hidden="true">${die(state.lastRoll||1)}</div><div><p class="dice-balance">남은 주사위 <strong>${state.user.dice_balance}개</strong></p><p class="dice-feedback ${state.lastRoll&&!state.rolling?'has-result':''}" role="status">${result}</p></div></div>
    ${diceAction()}
  </div>`;
}
function renderLevelCard() {
  const {step,level,target,remaining,eligible}=eventProgress();
  const progress=Math.min(step,Math.max(0,state.user.score-target+step));
  return `<section class="level-card content-card event-play" aria-label="내 점수와 주사위">
    <div class="character-summary">${characterPortrait(level)}<div><span class="level-badge">Lv. ${level}</span><h2>${characterTiers[level].name}</h2><p>현재 점수 <strong>${money(state.user.score)}점</strong></p></div></div>
    <p class="level-message" aria-live="polite">${eligible?`${target}점 달성! ${level<5?'레벨업하고 빵을 받아요.':'랜덤 빵을 받아요.'}`:`${remaining}점 더 모으면 ${level<5?'레벨업!':'랜덤 빵 증정!'}`}</p>
    <div class="progress" role="progressbar" aria-label="다음 빵 보상까지" aria-valuemin="0" aria-valuemax="${step}" aria-valuenow="${progress}"><span style="width:${progress/step*100}%"></span></div>
    ${eligible?`<button class="primary-button full level-up-button" data-action="claim-reward" ${state.leveling||state.rolling?'disabled':''}>${icon('spark')}${state.leveling?'빵을 뽑고 있어요…':level<5?'레벨업하고 빵 받기':'빵 보상 받기'}</button>`:''}
    ${renderDiceControl()}
    <details id="event-character-stages" class="character-stages"><summary>캐릭터 성장 단계 <span>10점마다 랜덤 빵</span></summary><ol class="level-milestones" aria-label="10점마다 연금술사 성장">${characterTiers.slice(1).map((tier,i)=>{const stage=i+1;return `<li class="${stage<=level?'unlocked':stage===level+1&&eligible?'ready':'locked'}" ${stage===level?'aria-current="step"':''}>${characterPortrait(stage)}<span>${stage*step}점</span></li>`;}).join('')}</ol>
    <p class="level-caption">10점마다 랜덤 빵 1개 · 캐릭터는 50점까지 성장</p></details>
  </section>`;
}
function renderRewardHistory() {
  return state.rewards.length?`<details id="buyer-reward-history" class="content-card reward-history"><summary>당첨된 빵 · ${state.rewards.length}개</summary>${state.rewards.map(r=>`<div class="reward-item"><strong>${esc(r.product_name)}</strong><span>${r.threshold}점 · 당첨 #${r.id}</span></div>`).join('')}<p class="form-hint">담당자에게 당첨 기록을 보여주고 받아가세요.</p></details>`:'';
}
function renderEvent() {
  const board=state.leaderboard;
  const rankings=board?`<section class="content-card"><h2>최고의 연금술사 TOP 3</h2><p class="form-hint">양일 누적 점수로 최종 1·2·3등을 선정합니다.</p><ol class="leaders">${board.leaders.map(p=>`<li class="${p.is_me?'me':''}"><span class="rank-number">${p.rank}위</span><strong>${esc(p.name)}${p.is_me?' (나)':''}</strong><b>${money(p.score)}점</b></li>`).join('')}</ol></section>
  <section class="content-card ranking-neighbors"><h2>내 주변 순위</h2>${board.neighbors.map(p=>`<div class="rank-row ${p.is_me?'me':''}"><span>${p.rank}위</span><strong>${esc(p.name)}${p.is_me?' (나)':''}</strong><b>${money(p.score)}점</b></div>`).join('')}<p class="form-hint">내 순위 ${board.me?.rank||'-'}위 · 총 ${board.total_participants}명 참여</p></section>`:'<section class="content-card"><h2>점수 순위</h2><p class="form-hint">순위를 불러오는 중입니다.</p></section>';
  return `${eventHeading()}<div class="event-layout"><div class="event-personal">${renderLevelCard()}${renderRewardHistory()}</div><div class="event-rankings">${rankings}</div></div>`;
}
function render() {
  if(!isAdmin&&state.route==='dice'){state.route='ranking';history.replaceState(null,'','#ranking');}
  let content;
  if(isAdmin)content=state.user?renderAdmin():renderStaffLogin();
  else content=state.user?({shop:renderShop,pickup:renderPickup,orders:renderOrders,ranking:renderEvent}[state.route]||renderShop)():renderBuyerLogin();
  const expanded=[...document.querySelectorAll('#app details[open]')].map(node=>node.id).filter(Boolean);
  document.querySelector('#app').innerHTML=shell(prototypeNotice()+content);
  expanded.forEach(id=>{const node=document.getElementById(id);if(node)node.open=true;});
  document.title=`${isAdmin?'담당자':!state.user?'로그인':['dice','ranking'].includes(state.route)?'이벤트 참여':'빵 구매'} · 캄보딜라이트`;
}
let refreshVersion=0;
async function refresh(){const version=++refreshVersion,token=state.token;try{const get=path=>api(path,{token});const jobs=[get('/api/config'),get('/api/products')];if(token)jobs.push(get('/api/auth/me'));const results=await Promise.all(jobs);let extra;if(token){const user=results[2].user;if((isAdmin&&user.role!=='staff')||(!isAdmin&&user.role!=='buyer')){if(state.token===token){localStorage.removeItem(tokenKey);state.token=null;state.user=null;}return;}extra=isAdmin?await get('/api/staff/dashboard'):await Promise.all([get('/api/orders'),get('/api/rewards'),get('/api/leaderboard')]);}if(state.token!==token||version!==refreshVersion)return;state.config=results[0];state.products=results[1].products;if(token){state.user=results[2].user;if(isAdmin)state.staffData=extra;else{state.orders=extra[0].orders;state.rewards=extra[1].rewards;state.leaderboard=extra[2];}}}catch(error){if(token!==state.token||version!==refreshVersion)return;throw error;}}

initAdmin({state,api,icon,esc,money,time,toast,modal,closeModal,render,refresh,requestId,submitButton});

function buyerAuthForm(mode='login') {
  return `<div class="auth-switch"><button class="${mode==='login'?'active':''}" data-action="auth-mode" data-mode="login">로그인</button><button class="${mode==='register'?'active':''}" data-action="auth-mode" data-mode="register">계정 만들기</button></div><form id="buyer-auth" data-mode="${mode}"><div class="field"><label for="auth-name">이름</label><input id="auth-name" name="name" autocomplete="username" maxlength="30" required></div><div class="field"><label for="auth-pin">숫자 4자리 비밀번호</label><input id="auth-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="${mode==='register'?'new-password':'current-password'}" required></div>${mode==='register'?'<p class="form-hint">이미 사용 중인 이름으로는 가입할 수 없습니다.</p>':''}<button type="submit" class="primary-button full">${mode==='register'?'계정 만들기':'로그인'}</button></form>`;
}
function renderBuyerLogin() { return `<section class="login-card content-card"><h1>이름과 비밀번호를 입력해 주세요.</h1><p class="form-hint">처음이라면 계정을 만들어 주세요.</p>${buyerAuthForm(state.authMode)}</section>`; }
function openAuth(mode='login') { modal(`<h2>로그인</h2>${buyerAuthForm(mode)}`); }

async function checkout(button){if(!cartCount())return;if(!state.user){openAuth();return;}const items=Object.entries(state.cart).map(([product_id,quantity])=>({product_id:Number(product_id),quantity}));const op=operation('checkout',items);button.disabled=true;try{const {order}=await api('/api/orders',{method:'POST',body:{items,request_id:op.id}});state.cart={};op.done();if(!state.orders.some(o=>o.id===order.id))state.orders.unshift(order);await refreshAfterAction();state.route='orders';history.replaceState(null,'','#orders');render();modal(`<div class="order-success"><div class="success-icon">${icon('check')}</div><h2>빵 구매 요청을 보냈어요!</h2><p>담당자에게 주문을 보여 주고<br>안내받은 계좌로 입금해 주세요.</p><div class="success-box">주문 #${String(order.id).padStart(3,'0')} · 선택 수량 ${order.quantity}<strong>${money(order.total)}원</strong>${orderDice(order)?`확인 후 주사위 ${orderDice(order)}개가 지급돼요.`:'우유 구매에는 주사위가 지급되지 않아요.'}</div><button class="primary-button full" data-action="close-modal">주문 내역 확인하기 ${icon('arrow')}</button></div>`);}catch(error){if(error.status>=400&&error.status<500)op.done();button.disabled=false;toast(error.message,'error');await refresh().catch(()=>{});render();}}
function openLevelUp() {
  const {level,target,eligible}=eventProgress();
  if(!eligible)return;
  const nextLevel=Math.min(5,level+1);
  modal(`<div class="draw-prompt">${characterPortrait(nextLevel,'level-preview')}<span class="label-kicker">${level<5?'다음 연금술사':'최고 레벨 달성'}</span><h2>${target}점 달성!</h2><p>${level<5?'새 캐릭터로 레벨업하고<br>':''}랜덤 빵 1개를 받아요.</p><button class="primary-button full" data-action="claim-reward">${level<5?'레벨업하고 빵 받기':'빵 보상 받기'}</button></div>`);
}
async function rollDice() {
  if(state.rolling||state.leveling||!state.user?.dice_balance)return;
  const {target}=eventProgress(),before=state.user.score;
  state.rolling=true;render();const op=operation('dice');
  try {
    const [result]=await Promise.all([api('/api/dice/roll',{method:'POST',body:{request_id:op.id}}),new Promise(r=>setTimeout(r,850))]);
    state.lastRoll=result.value;state.user.score=result.score;state.user.dice_balance=result.dice_balance;op.done();state.rolling=false;
    await refreshAfterAction();render();
    if(before<target&&state.user.score>=target)openLevelUp();
  } catch(error) { if(error.status>=400&&error.status<500)op.done();state.rolling=false;render();toast(error.message,'error'); }
}
async function claimReward(button) {
  if(state.leveling||state.rolling)return;
  state.leveling=true;button.disabled=true;const op=operation('reward');
  try {
    const {reward,user}=await api('/api/rewards/claim',{method:'POST',body:{request_id:op.id}});
    state.user=user;op.done();await refreshAfterAction();
    state.leveling=false;render();
    const p=state.products.find(p=>p.id===reward.product_id),level=eventProgress(user).level;
    const upgraded=user.rewards_claimed<=5;
    modal(`<div class="order-success level-up-result"><span class="label-kicker">${upgraded?'LEVEL UP!':'랜덤 빵 당첨'}</span>${characterPortrait(level,'level-preview',level)}<h2>${upgraded?`Lv. ${level} ${characterTiers[level].name}`:'전설의 연금술은 계속!'}</h2><div class="bread-prize">${p?`<img src="${productImage(p)}" alt="" width="76" height="64">`:icon('bread')}<div><span>함께 받은 랜덤 빵</span><strong>${esc(reward.product_name)}</strong>${p?.subtitle?`<small>${esc(p.subtitle)}</small>`:''}</div></div><p>${reward.threshold}점 달성을 축하해요.<br>담당자에게 이 화면을 보여 주고 빵을 받아 가세요.</p><p class="form-hint">당첨 #${reward.id} · 담당자 화면에도 기록됐어요.</p><button class="primary-button full" data-action="close-modal">확인</button></div>`);
  } catch(error) {
    if(error.status>=400&&error.status<500)op.done();
    state.leveling=false;button.disabled=false;toast(error.message,'error');
  }
}
document.addEventListener('error',event=>{if(event.target.matches?.('.product-photo img'))event.target.remove();},true);
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;const action=el.dataset.action;try{
if(action==='navigate'){state.route=el.dataset.route;location.hash=state.route;render();window.scrollTo({top:0,behavior:'instant'});}
else if(action==='login')isAdmin?document.querySelector('#staff-login input')?.focus():openAuth();
else if(action==='auth-mode'){state.authMode=el.dataset.mode;if(document.querySelector('.modal'))openAuth(el.dataset.mode);else render();}
else if(action==='close-modal')closeModal();
else if(action==='profile')modal(`<h2>${esc(state.user.name)}</h2><button class="secondary-button full" data-action="logout">로그아웃</button>`);
else if(action==='logout'){await api('/api/auth/logout',{method:'POST',body:{}});localStorage.removeItem(tokenKey);state.token=null;state.user=null;state.orders=[];state.rewards=[];state.staffData=null;state.reservation=null;closeModal();render();toast('다음에 또 따뜻한 빵으로 만나요.');}
else if(action==='cart-plus'||action==='cart-minus'||action==='remove-cart'){const id=Number(el.dataset.id),p=state.products.find(p=>p.id===id);const quantity=action==='remove-cart'?0:(state.cart[id]||0)+(action==='cart-plus'?1:-1);if(quantity>p.stock){toast('지금 남은 수량만큼 담을 수 있어요.','error');return;}const basketOpen=!!document.querySelector('.modal .basket');if(quantity>0)state.cart[id]=quantity;else delete state.cart[id];render();if(basketOpen)modal(renderBasket());}
else if(action==='open-cart')modal(renderBasket());
else if(action==='checkout')await checkout(el);
else if(action==='claim-preorder'){el.disabled=true;try{const {order}=await api(`/api/preorders/${el.dataset.id}/claim`,{method:'POST',body:{request_id:el.dataset.requestId||(el.dataset.requestId=requestId())}});if(!state.orders.some(o=>o.id===order.id))state.orders.unshift(order);await refreshAfterAction();state.route='orders';location.hash='orders';render();toast(order.status==='approved'?'이미 픽업을 완료한 예약이에요.':'픽업을 요청했어요. 담당자에게 말씀해 주세요.');}catch(error){el.disabled=false;throw error;}}
else if(action==='roll-dice')await rollDice();
else if(action==='claim-reward')await claimReward(el);
else if(action==='retry')location.reload();
else await handleAdminClick(action,el,event);
}catch(error){toast(error.message||'잠시 후 다시 시도해 주세요.','error');}});
document.addEventListener('submit',async event=>{const form=event.target;event.preventDefault();const data=Object.fromEntries(new FormData(form));submitButton(form,true);try{if(form.id==='buyer-auth'){const result=await api(`/api/auth/${form.dataset.mode}`,{method:'POST',body:{name:data.name.trim(),pin:data.pin}});state.token=result.token;state.user=result.user;localStorage.setItem(tokenKey,result.token);await refresh();closeModal();render();toast(`${result.user.name} 님, 반가워요!`);}else if(form.id==='preorder-lookup'){const {reservation}=await api(`/api/preorders/lookup?${new URLSearchParams(data)}`);state.reservation=reservation;render();toast('예약 내역을 찾았어요.');}else await handleAdminSubmit(form,event);}catch(error){if(form.id==='buyer-auth'){const errorNode=document.createElement('p');errorNode.className='error-message';errorNode.setAttribute('role','alert');errorNode.textContent=error.message;form.querySelector('.error-message')?.remove();form.prepend(errorNode);}else toast(error.message,'error');}finally{submitButton(form,false);}});
document.addEventListener('keydown',event=>{if(!document.querySelector('.modal'))return;if(event.key==='Escape')closeModal();if(event.key==='Tab'){const focusables=[...document.querySelectorAll('.modal button:not(:disabled),.modal a[href],.modal input:not([disabled]),.modal select,.modal textarea')].filter(n=>n.offsetParent!==null);const first=focusables[0],last=focusables.at(-1);if(event.shiftKey&&document.activeElement===first){last?.focus();event.preventDefault();}else if(!event.shiftKey&&document.activeElement===last){first?.focus();event.preventDefault();}}});
window.addEventListener('hashchange',()=>{state.route=location.hash.slice(1)||(isAdmin?'queue':'shop');render();});
let polling=false,pendingRender=false;
function snapshot(){return JSON.stringify([state.user,state.products,state.orders,state.staffData,state.leaderboard,state.rewards]);}
function safeToRender(){return !document.querySelector('.modal')&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!state.rolling&&!state.leveling;}
setInterval(async()=>{if(polling||state.rolling||state.leveling||document.hidden)return;polling=true;try{const before=snapshot();const oldOrders=isAdmin?state.staffData?.orders||[]:state.orders;await refresh();const newOrders=isAdmin?state.staffData?.orders||[]:state.orders;if(isAdmin){const fresh=newOrders.filter(o=>o.status==='pending'&&!oldOrders.some(old=>old.id===o.id));if(fresh.length)toast(`${fresh[0].customer_name} 님의 새 주문이 도착했어요.`);}else{const newlyApproved=newOrders.find(o=>o.status==='approved'&&oldOrders.find(old=>old.id===o.id&&old.status==='pending'));if(newlyApproved)toast(`주문이 승인됐어요. ${orderDice(newlyApproved)?`주사위 ${orderDice(newlyApproved)}개가 도착했어요!`:'우유 구매에는 주사위가 지급되지 않아요.'}`);}if(before!==snapshot())pendingRender=true;if(pendingRender&&safeToRender()){render();pendingRender=false;}}catch(error){if(error.status===401){localStorage.removeItem(tokenKey);state.token=null;state.user=null;render();toast('다시 로그인해 주세요.','error');}}finally{polling=false;}},4000);
async function boot(){try{await refresh();render();}catch(error){if(error.status===401){localStorage.removeItem(tokenKey);state.token=null;state.user=null;await refresh();render();}else document.querySelector('#app').innerHTML=`<div class="connection-error">${brand()}<h1>빵집에 연결하고 있어요</h1><p>잠시 후 다시 연결해 주세요.<br>${esc(error.message)}</p><button class="primary-button" data-action="retry">다시 연결하기 ${icon('arrow')}</button></div>`;}}
boot();
