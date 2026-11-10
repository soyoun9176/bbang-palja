import {initAdmin, renderAdmin, renderStaffLogin, handleAdminClick, handleAdminSubmit} from './admin.js';
import {profileAvatar, profileEditor, profileHairpins, profileBadges, profileTitles, profileTitle, titleStyles, badgePicture, badgeIcons, normalizeAvatar} from './profile.js';

const isAdmin = /^\/admin(?:\/|$)/.test(location.pathname);
const tokenKey = `kambo.${isAdmin ? 'staff' : 'buyer'}.token`;
function loadGuestReceipts(){try{const saved=JSON.parse(localStorage.getItem('kambo.guest.orders')||'[]');return Array.isArray(saved)?saved.filter(r=>Number.isSafeInteger(r.id)&&r.id>0&&typeof r.token==='string'):[];}catch{return [];}}
const state = {isAdmin,token:localStorage.getItem(tokenKey),user:null,config:{},products:[],orders:[],rewards:[],rewardRequests:[],eventNotices:[],leaderboard:null,staffData:null,route:location.hash.slice(1)||(isAdmin?'queue':'shop'),cart:{},reservation:null,pickupDefaults:null,pickupDraft:null,pickupUserId:null,authMode:'login',rolling:false,leveling:false,lastRoll:null,selectedDice:null,guestName:sessionStorage.getItem('kambo.guest.name')||'',guestReceipts:isAdmin?[]:loadGuestReceipts()};
function guestPurchase(){return !isAdmin&&!state.user&&['guest','guest-orders'].includes(state.route);}
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
const staffNav=[['queue','clock','주문'],['events','spark','이벤트'],['sales','edit','수기판매'],['inventory','box','재고관리'],['notes','note','인수인계']];
function navButton([route,img,label]) {
  const active=isAdmin?state.route===route:route==='shop'?['shop','pickup','orders'].includes(state.route):['dice','ranking'].includes(state.route);
  const pending=isAdmin?(route==='queue'?state.staffData?.stats.pending_orders||0:route==='events'?state.staffData?.stats.pending_rewards||0:0):0;
  return `<button class="nav-item ${active?'active':''}" data-action="navigate" data-route="${route}" ${active?'aria-current="page"':''}>${icon(img)}<span>${label}</span>${pending?`<b class="pending-pill">${pending}</b>`:''}</button>`;
}
function shell(content) {
  const eventPage=!isAdmin&&['dice','ranking'].includes(state.route);
  return `<div class="shell ${isAdmin?'admin':eventPage?'event-space':'purchase-space'} ${state.user?'signed-in':''}">
    <header class="app-header"><a href="${isAdmin?'/admin/':'/'}" aria-label="캄보딜라이트 홈">${brand()}</a>
    ${state.user?`<button class="profile-button" data-action="profile" aria-label="${esc(state.user.name)} 계정 관리">${profileAvatar(state.user)}<span class="profile-identity">${esc(state.user.name)}${isAdmin?' · 담당자':''}${profileTitle(state.user)}</span> ${icon('chevron')}</button>`:isAdmin?'<span class="muted">담당자 로그인</span>':guestPurchase()?'<button class="text-button" data-action="guest-exit">로그인</button>':''}</header>
    ${state.user?`<nav class="primary-nav" aria-label="${isAdmin?'담당자 메뉴':'주요 메뉴'}">${(isAdmin?staffNav:buyerNav).map(x=>navButton(x)).join('')}</nav>`:''}
    <main class="main">${content}</main>
    ${!isAdmin&&(state.user&&state.route==='shop'||guestPurchase()&&state.route==='guest')&&cartCount()?`<button class="mobile-cart" data-action="open-cart">선택 수량 ${cartCount()} <strong>${money(cartTotal())}원 · 구매하기 ${icon('arrow')}</strong></button>`:''}
  </div>`;
}
function pageHeading(title,desc='') { return `<div class="page-heading"><div><h1>${title}</h1>${desc?`<p>${desc}</p>`:''}</div></div>`; }
function subnav(items) { return `<nav class="subnav" aria-label="${['dice','ranking'].includes(state.route)?'이벤트 메뉴':'구매 메뉴'}">${items.map(([route,label])=>`<button class="${state.route===route?'active':''}" data-action="navigate" data-route="${route}" ${state.route===route?'aria-current="page"':''}>${label}</button>`).join('')}</nav>`; }
function purchaseHeading() { return guestPurchase()?`${pageHeading('빵 구매','계정 없이 이름만 입력하고 주문하세요.')}${subnav([['guest','현장 구매'],['guest-orders','주문 내역']])}`:`${pageHeading('빵 구매','예약한 빵 수령 또는 현장 구매를 선택해 주세요.')}${subnav([['shop','현장 구매'],['pickup','예약한 빵 수령'],['orders','주문 내역']])}`; }
function prototypeNotice() { return window.KAMBO_CONFIG?.prototype||state.config.demo?'<p class="prototype-note">가안 테스트 · 샘플 데이터입니다.</p>':''; }
function renderEventNotices(notices=[],{manage=false}={}) {
  if(!notices.length)return '';
  return `<section class="event-notice-board" aria-label="이벤트 알림판" aria-live="polite">${notices.slice(0,2).map(n=>`<article class="event-notice ${n.kind==='announcement'?'is-announcement':''}">${profileAvatar(n.author)}<div class="event-notice-copy"><div class="event-notice-author"><strong>${esc(n.author.name)}</strong>${profileTitle(n.author)}${n.kind==='announcement'?'<span class="notice-kind">공지</span>':''}</div><p>${esc(n.content)}</p></div>${manage?`<button type="button" class="icon-button notice-delete" data-action="admin-notice-delete" data-id="${Number(n.id)}" aria-label="${esc(n.content)} 알림 삭제">${icon('x')}</button>`:''}</article>`).join('')}</section>`;
}
function cartCount(){return Object.values(state.cart).reduce((s,v)=>s+v,0);}
function cartTotal(){return state.products.reduce((s,p)=>s+p.price*(state.cart[p.id]||0),0);}
function productImage(product){const name=String(product.image||'salt-bread').replace(/[^a-z-]/g,'');return `/assets/${name}.svg`;}
function productPhoto(product){return `<div class="product-photo ${product.photo?'has-image':''}"><span class="photo-placeholder" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24"><path d="M3 3h18v18H3V3Zm0 14 6-6 4 4 3-3 5 5M8 8h.01"/></svg></span>${product.photo?`<img src="${esc(product.photo)}" alt="${esc(product.name)}" loading="lazy" width="96" height="96">`:''}</div>`;}

function renderBasket() {
  const entries=state.products.filter(p=>state.cart[p.id]);
  return `<section class="basket"><h2>선택한 품목</h2>${entries.length?`<div class="basket-items">${entries.map(p=>`<div class="basket-item"><div><strong>${esc(p.name)} × ${state.cart[p.id]}${p.unit||'개'}</strong><span>${money(p.price*state.cart[p.id])}원</span></div><button class="icon-button" data-action="remove-cart" data-id="${p.id}" aria-label="${esc(p.name)} 선택 취소">${icon('x')}</button></div>`).join('')}</div>`:'<p class="muted">구매할 품목의 수량을 선택해 주세요.</p>'}
  <div class="basket-total"><span>선택 수량 ${cartCount()}</span><strong>${money(cartTotal())}원</strong></div>
  <button class="primary-button full" data-action="checkout" ${!entries.length?'disabled':''}>구매 요청하기</button>
  <p class="form-hint">담당자에게 입금 내역을 보여주고 승인을 받아주세요.</p></section>`;
}
function renderShop() {
  return `${purchaseHeading()}${guestPurchase()?`<section class="content-card guest-name-card"><div class="field"><label for="guest-name">구매자 이름</label><input id="guest-name" name="guest_name" autocomplete="name" maxlength="30" placeholder="담당자에게 알려줄 이름" value="${esc(state.guestName)}" required></div><p class="form-hint">비회원 구매에는 이벤트 주사위가 지급되지 않아요.</p></section>`:''}<div class="shop-layout"><section class="product-list" aria-label="현판 빵 목록">${state.products.map(p=>`<article class="product-row ${p.stock<=0?'sold-out':''}" ${p.stock<=0?'aria-disabled="true"':''}>
    ${productPhoto(p)}
    <div class="product-info"><h2>${esc(p.name)}</h2>${p.subtitle?`<span class="menu-concept">${esc(p.subtitle)}</span>`:''}<div class="product-price"><strong>${money(p.price)}원</strong>${p.dice_per_unit===0?'<span class="menu-concept">주사위 미지급</span>':''}${p.stock<=0?'<span class="sold-out-label">품절</span>':''}</div></div>
    <div class="product-count"><button class="quantity-button" data-action="cart-minus" data-id="${p.id}" ${p.stock<=0||!state.cart[p.id]?'disabled':''} aria-label="${esc(p.name)} 수량 줄이기">${icon('minus')}</button><span aria-label="${esc(p.name)} 선택 수량">${state.cart[p.id]||0}</span><button class="quantity-button" data-action="cart-plus" data-id="${p.id}" ${p.stock<=0||(state.cart[p.id]||0)>=p.stock?'disabled':''} aria-label="${esc(p.name)} 수량 늘리기">${icon('plus')}</button></div>
    </article>`).join('')}</section><aside class="desktop-basket">${renderBasket()}</aside></div>`;
}
function authRequired() { return renderBuyerLogin(); }
function orderDice(order){return order.user_id===null?0:order.dice_quantity??order.quantity;}
function orderLines(order){return `<div class="order-lines">${order.items.map(i=>`<div class="order-line"><span>${esc(i.name)} <span>× ${i.quantity}</span></span><span>${money(i.price*i.quantity)}원</span></div>`).join('')}</div>`;}
function orderStatus(status){return `<span class="status ${status}">${icon(status==='approved'?'check':status==='cancelled'?'x':'clock')}${{pending:'담당자 확인 중',approved:'수령 완료',cancelled:'취소 완료'}[status]||status}</span>`;}
let pickupLookupVersion=0;
function pickupValues(){return state.pickupDraft||state.pickupDefaults||{name:state.user?.name||'',phone:''};}
function clearPickupResult(){state.reservation=null;document.querySelector('.reservation-result')?.remove();}
function resetPickup(){pickupLookupVersion++;state.pickupUserId=null;state.pickupDefaults=null;state.pickupDraft=null;clearPickupResult();}
function editPickupField(name,value){
  if(!['name','phone'].includes(name))return;
  state.pickupDraft={...pickupValues(),[name]:value};pickupLookupVersion++;clearPickupResult();
}
async function lookupPreorder(data){
  const version=++pickupLookupVersion,token=state.token,userId=state.user?.id;
  clearPickupResult();
  const query={name:data.name.trim(),phone:normalizePhone(data.phone)};
  state.pickupDraft=query;
  try{
    const {reservation}=await api(`/api/preorders/lookup?${new URLSearchParams(query)}`,{token});
    if(version!==pickupLookupVersion||token!==state.token||userId!==state.user?.id)return;
    state.reservation=reservation;render();toast('예약 내역을 찾았어요.');
  }catch(error){if(version===pickupLookupVersion&&token===state.token&&userId===state.user?.id)throw error;}
}
function renderPickup() {
  const values=pickupValues();
  return `${purchaseHeading()}<section class="content-card narrow"><h2>예약 내역 조회</h2><form id="preorder-lookup"><div class="field"><label for="preorder-name">예약자 이름</label><input id="preorder-name" name="name" value="${esc(values.name)}" placeholder="예약할 때 사용한 이름" required maxlength="30"></div><div class="field"><label for="preorder-phone">예약자 전화번호</label><input id="preorder-phone" name="phone" type="tel" inputmode="tel" value="${esc(values.phone)}" placeholder="010-1234-5678" minlength="11" maxlength="13" pattern="010(?:[0-9]{8}|-[0-9]{4}-[0-9]{4})" data-phone-input required></div><p class="form-hint">예약할 때 사용한 이름과 전화번호로 조회해 주세요.</p><button class="primary-button full" type="submit">예약 조회</button></form>
  ${state.reservation?`<div class="reservation-result"><h3>${esc(state.reservation.name)} 님의 예약</h3>${orderLines(state.reservation)}<div class="basket-total"><span>예약 금액</span><strong>${money(state.reservation.total)}원</strong></div><button class="primary-button full" data-action="claim-preorder" data-id="${state.reservation.id}">담당자에게 수령 요청</button><p class="form-hint">담당자가 예약한 빵을 전달하고 승인하면 완료됩니다.</p></div>`:''}</section>`;
}
function renderOrders() {
  return `${purchaseHeading()}<div class="narrow">${guestPurchase()?'<p class="form-hint">이 기기에서 접수한 비회원 주문입니다. 담당자에게 주문 번호와 이름을 보여주세요.</p>':''}${state.orders.length?state.orders.map(o=>`<article class="order-card"><div class="order-top"><strong>${{walkin:'현장 구매',preorder:'예약한 빵 수령',manual:'수기 판매'}[o.type]} #${String(o.id).padStart(3,'0')}</strong>${orderStatus(o.status)}</div>${guestPurchase()?`<p class="guest-order-name">${esc(o.customer_name)} 님</p>`:''}${orderLines(o)}<div class="order-bottom"><span>${time(o.created_at)}</span><strong>${money(o.total)}원</strong></div>
  ${o.status==='pending'?`<p class="callout">${o.type==='preorder'?'담당자에게 예약 내역을 보여주고 빵을 받아주세요.':'담당자에게 주문과 입금 내역을 보여주세요.'} 승인 대기 중입니다.</p>`:o.status==='approved'?guestPurchase()?'<p class="callout">구매가 완료됐어요. 감사합니다!</p>':`<div class="callout"><span>구매 완료 · ${orderDice(o)?`주사위 ${orderDice(o)}개 지급`:'음료는 주사위 미지급'}</span><button class="text-button" data-action="navigate" data-route="ranking">이벤트 참여하기 ${icon('arrow')}</button></div>`:''}</article>`).join(''):`<div class="empty-state"><h2>주문 내역이 없습니다.</h2><button class="primary-button" data-action="navigate" data-route="${guestPurchase()?'guest':'shop'}">현장 구매하기</button></div>`}</div>`;
}
const dieDots={1:[5],2:[1,9],3:[1,5,9],4:[1,3,7,9],5:[1,3,5,7,9],6:[1,3,4,6,7,9]};
function die(value=1,color='plain'){
  const milk=value==='milk',dots=dieDots[value];
  return `<div class="big-dice die-${esc(color)} ${dots?'':'die-symbol'}" aria-label="${milk?'우유 당첨':`주사위 ${value}`}">${milk?icon('milk'):dots?Array.from({length:9},(_,i)=>`<i class="${dots.includes(i+1)?'dot':''}"></i>`).join(''):`<b>${esc(value)}</b>`}</div>`;
}
const characterTiers = [
  {name:'연금술 수련생'}, {name:'견습 연금술사'}, {name:'원소 연금술사'},
  {name:'황금 연금술사'}, {name:'별빛 현자'}, {name:'전설의 대연금술사'},
];
const milestonePreview=[
  {threshold:5,kind:'oatmeal',name:'오트밀 미니바이트',extra:'프로필 배지 · 마법의 씨앗'},
  {threshold:10,kind:'milk',name:'우유 또는 두유',extra:'프로필 배지 · 빛나는 연금술'},
  {threshold:15,kind:'sunglasses',name:'멋진 선글라스',extra:'칭호 「멋쟁이 마법사」'},
  {threshold:20,kind:'bread',name:'랜덤 빵 1개',extra:''},
  {threshold:30,kind:'bread',name:'랜덤 빵 1개',extra:'칭호 「대현자 연금술사」 · 담당자에게 커스텀 칭호 요청 가능'},
];
function eventProgress(user=state.user) {
  const milestones=state.config.milestones||milestonePreview,claimed=user.claimed_milestones||[];
  const next=milestones.find(m=>!claimed.includes(m.threshold)),index=next?milestones.indexOf(next):milestones.length;
  const previous=index?milestones[index-1].threshold:0,target=next?.threshold??null;
  return {milestones,claimed,level:Math.min(5,user.level??claimed.length),next,target,
    step:next?target-previous:1,previous,remaining:next?Math.max(0,target-user.score):0,eligible:!!next&&user.score>=target};
}
function characterPortrait(level,className='',earnedLevel=eventProgress().level) {
  if(level===0||level>earnedLevel)return `<div class="alchemist character-unknown ${className}" role="img" aria-label="아직 얻지 못한 캐릭터">?</div>`;
  return profileAvatar(state.user,{className:`alchemist ${className}`,full:true,level,label:characterTiers[level].name});
}
function ownedDice(){return state.user.dice|| (state.user.dice_balance?[{kind:'walkin',name:'현장 구매 주사위',color:'plain',quantity:state.user.dice_balance}]:[]);}
function selectedDie(){const dice=ownedDice();return dice.find(d=>d.kind===state.selectedDice)||dice[0];}
const dieColors={plain:'일반',rainbow:'무지개',silver:'은색',gold:'금색',pink:'인스타'};
function diceAction() {
  const busy=state.rolling||state.leveling,chosen=selectedDie();
  if(!chosen)return `<button class="primary-button purchase-cta full" data-action="navigate" data-route="shop" ${busy?'disabled':''}>${icon('bag')}빵 구매하고 주사위 얻기</button>`;
  return `<button class="primary-button full" data-action="roll-dice" ${busy?'disabled':''}>${icon('dice')}${state.rolling?'굴리는 중…':'선택한 주사위 굴리기'}</button>`;
}
function renderDiceControl() {
  const last=state.lastRoll,chosen=selectedDie(),busy=state.rolling||state.leveling;
  const result=state.rolling?'주사위를 굴리고 있어요…':last?.result==='milk'?'음료 보상 당첨! 우유 또는 두유를 선택해 주세요.':last?`결과 ${last.value} · +${last.value}점`:chosen?'사용할 주사위를 고르고 굴려요.':'빵 구매 승인 후 주사위가 지급돼요.';
  return `<div class="inline-dice ${state.rolling?'rolling':''}" aria-label="주사위 굴리기" aria-busy="${state.rolling}">
    <div class="dice-control-head"><div class="dice-visual" aria-hidden="true">${die(last?.result==='milk'?'milk':last?.value||1,last?.dice?.color||chosen?.color||'plain')}</div><div><p class="dice-balance">남은 주사위 <strong>${state.user.dice_balance}개</strong></p><p class="dice-feedback ${last&&!state.rolling?'has-result':''}" role="status">${esc(result)}</p></div></div>
    ${ownedDice().length?`<div class="dice-picker" role="group" aria-label="사용할 주사위">${ownedDice().map(d=>`<button class="dice-choice die-${esc(d.color)} ${d.kind===chosen?.kind?'selected':''}" data-action="select-dice" data-kind="${esc(d.kind)}" aria-pressed="${d.kind===chosen?.kind}" ${busy?'disabled':''}><span class="dice-color-mark" aria-hidden="true"></span><span><strong>${esc(d.name)}</strong><small>${d.kind.startsWith('preorder_')?`${dieColors[d.color]} · `:''}${d.quantity}개</small></span>${d.kind===chosen?.kind?icon('check'):''}</button>`).join('')}</div>`:''}
    ${diceAction()}
  </div>`;
}
function milestoneImage(milestone){return `/assets/${({oatmeal:'oatmeal',milk:'milk',sunglasses:'sunglasses',bread:'reward-bread'})[milestone.kind]||'reward-bread'}.svg`;}
function renderMilestoneTrack(){
  const {milestones,claimed}=eventProgress(),maximum=Math.max(...milestones.map(m=>Number(m.threshold))),score=Math.min(maximum,Math.max(0,state.user.score));
  return `<section class="magic-level-track" aria-label="마법 레벨업"><div class="level-track-heading"><h3>마법 레벨업</h3><span>${score} / ${maximum}점</span></div><div class="milestone-track"><div class="milestone-track-bar" role="progressbar" aria-label="마법 레벨업 점수" aria-valuemin="0" aria-valuemax="${maximum}" aria-valuenow="${score}"><span style="width:${score/maximum*100}%"></span></div><span class="milestone-zero" aria-hidden="true">0</span><ol class="milestone-stops" aria-label="점수별 보상">${milestones.map(m=>{const received=claimed.includes(m.threshold),achieved=received||state.user.score>=m.threshold;return `<li style="left:${Number(m.threshold)/maximum*100}%"><button class="milestone-trigger ${achieved?'is-achieved':'is-locked'} ${received?'is-claimed':''}" data-action="open-milestone" data-threshold="${m.threshold}" aria-label="${m.threshold}점 보상: ${esc(m.name)} · ${received?'받기 완료':achieved?'달성':'미달성'}"><span class="milestone-bubble"><img src="${milestoneImage(m)}" alt="" width="32" height="32">${received?`<span class="milestone-received" aria-hidden="true">${icon('check')}</span>`:''}</span><span class="milestone-dot" aria-hidden="true"></span><span class="milestone-point">${m.threshold}점</span></button></li>`;}).join('')}</ol></div><p class="milestone-track-hint">말풍선을 눌러 보상을 확인해요.</p></section>`;
}
function openMilestone(threshold){
  if(state.rolling||state.leveling)return;
  const {milestones,claimed}=eventProgress(),m=milestones.find(m=>m.threshold===Number(threshold));if(!m)return;
  const received=claimed.includes(m.threshold),achieved=state.user.score>=m.threshold;
  const record=state.rewards.find(r=>r.threshold===m.threshold&&r.kind!=='legacy_bread'),request=record?.fulfillment;
  const status=received?(request?rewardStatus(request.status):'보상 받기 완료'):achieved?`${m.threshold}점 달성!`:`${m.threshold-state.user.score}점 더 모으면 받을 수 있어요.`;
  modal(`<div class="draw-prompt milestone-detail ${achieved||received?'is-achieved':'is-locked'}"><span class="label-kicker">${m.threshold}점 보상</span><img class="milestone-detail-image" src="${milestoneImage(m)}" alt="${esc(m.name)}" width="112" height="112"><h2>${esc(m.name)}</h2><p class="milestone-detail-status">${esc(status)}</p>${m.extra?`<p class="form-hint">${esc(m.extra)}</p>`:''}${!received&&achieved?`<button class="primary-button full" data-action="claim-reward" data-threshold="${m.threshold}">상품 받기</button>`:''}${request?.status==='awaiting_choice'?`<button class="primary-button full" data-action="open-beverage-choice" data-request="${request.id}">우유·두유 선택하기</button>`:''}${received&&request?.status==='pending'?'<p class="form-hint">담당자에게 이벤트 요청을 보여주고 물품을 받아주세요.</p>':''}</div>`);
}
function renderLevelCard() {
  const {level,target,next,remaining,eligible}=eventProgress();
  return `<section class="level-card content-card event-play" aria-label="내 점수와 주사위">
    <div class="character-summary">${characterPortrait(level)}<div><span class="level-badge">Lv. ${level}</span><h2>${characterTiers[level].name}</h2><p>현재 점수 <strong>${money(state.user.score)}점</strong></p></div></div>
    <p class="level-message" aria-live="polite">${!next?'30점 보상까지 모두 받았어요! 더 높은 순위에 도전해요.':eligible?`${target}점 달성! 말풍선을 눌러 보상을 받아요.`:`${remaining}점 더 모으면 레벨업!`}</p>
    ${renderMilestoneTrack()}
    ${renderDiceControl()}
  </section>`;
}
const rewardStatus = status => ({awaiting_choice:'음료 선택 필요',pending:'담당자 지급 대기',approved:'수령 완료',cancelled:'지급 취소'}[status]||status);
function beverageOptions(request){
  const drinks=state.products.filter(p=>p.beverage_reward_eligible),empty=!drinks.some(p=>p.stock>0);
  return `<div class="beverage-options">${drinks.map(p=>`<button class="secondary-button full" data-action="choose-beverage" data-request="${request.id}" data-product="${p.id}" ${p.stock<=0?'disabled':''}>${icon('milk')}${esc(p.name)} ${p.stock<=0?'품절':'선택'}</button>`).join('')}</div>${empty?'<p class="form-hint">우유와 두유가 모두 품절이에요.</p>':''}<p class="form-hint">취소하면 이번 음료 보상은 받지 않는 것으로 처리돼요.</p><div class="button-row"><button class="secondary-button" data-action="decline-beverage" data-request="${request.id}">취소하기</button><button class="text-button" data-action="close-modal">나중에 선택하기</button></div>`;
}
function openBeverageChoice(request){
  if(!request)return;
  request=state.rewardRequests.find(r=>r.id===request.id)||request;
  if(request.status&&request.status!=='awaiting_choice')return;
  modal(`<div class="draw-prompt"><div class="draw-icon">${icon('milk')}</div><h2>우유 보상 당첨!</h2><p>우유 또는 두유 중 1개를 선택해 주세요.<br>선택 후 담당자에게 요청을 보여주세요.</p>${beverageOptions(request)}<p class="form-hint">이벤트 요청 #${request.id}</p></div>`);
}
function renderRewardRequests(){
  const active=state.rewardRequests.filter(r=>['awaiting_choice','pending'].includes(r.status));
  return active.length?`<section class="content-card buyer-reward-requests"><h2>이벤트 물품 수령</h2>${active.map(r=>`<article class="buyer-reward-request"><div><strong>${esc(r.product_name)}${r.status==='pending'?' × 1':''}</strong><span class="status pending">${rewardStatus(r.status)}</span></div><p class="form-hint">이벤트 #${r.id} · ${r.roll_id?'주사위 당첨':`${r.threshold}점 보상`}</p>${r.status==='awaiting_choice'?`<button class="secondary-button full" data-action="open-beverage-choice" data-request="${r.id}" ${state.rolling||state.leveling?'disabled':''}>우유·두유 선택하기</button>`:'<p class="form-hint">담당자에게 이 요청을 보여주고 물품을 받아주세요.</p>'}</article>`).join('')}</section>`:'';
}
async function chooseBeverage(button,decline=false){
  if(state.rolling||state.leveling)return;
  const id=Number(button.dataset.request),body=decline?{}:{product_id:Number(button.dataset.product)};
  const op=operation(`beverage-${id}`,body);state.leveling=true;button.disabled=true;
  try{
    const result=await api(`/api/reward-requests/${id}/${decline?'decline':'choose'}`,{method:'POST',body:{...body,request_id:op.id}});
    op.done();
    state.rewardRequests=[result.request,...state.rewardRequests.filter(r=>r.id!==id)];
    state.rewards=state.rewards.map(r=>r.fulfillment?.id===id?{...r,fulfillment:{...r.fulfillment,...result.request}}:r);
    await refreshAfterAction();state.leveling=false;closeModal();render();
    toast(decline?'이번 음료 보상은 받지 않는 것으로 처리했어요.':'음료를 확보하고 담당자에게 지급을 요청했어요.');
  }catch(error){
    if(error.status>=400&&error.status<500)op.done();state.leveling=false;
    await refresh().catch(()=>{});render();
    const current=state.rewardRequests.find(r=>r.id===id);if(current?.status==='awaiting_choice')openBeverageChoice(current);else closeModal();
    toast(error.message,'error');
  }
}
function renderRewardHistory() {
  return state.rewards.length?`<details id="buyer-reward-history" class="content-card reward-history"><summary>이벤트 보상 기록 · ${state.rewards.length}건</summary>${state.rewards.map(r=>`<div class="reward-item"><strong>${esc(r.product_name)}</strong><span>${r.kind==='dice_milk'?'주사위 당첨':r.kind==='legacy_bread'?`이전 이벤트 ${r.threshold}점`:`${r.threshold}점`} · ${r.fulfillment?rewardStatus(r.fulfillment.status):r.kind==='sunglasses'?'자동 지급':'이전 지급 기록'}</span></div>`).join('')}</details>`:'';
}
function renderAchievements(){
  const achievements=state.user?.achievements||[];
  return `<section class="content-card achievements"><div class="section-heading"><h2>도전과제</h2><span>${achievements.filter(a=>a.completed).length}/${achievements.length} 달성</span></div><p class="form-hint">구매를 모아 배지와 반짝이는 칭호를 얻어요.</p><div class="achievement-list">${achievements.map(a=>`<button type="button" class="achievement-card ${a.completed?'is-completed':''}" data-action="achievement-detail" data-achievement="${esc(a.id)}">${badgePicture({id:a.badge_id,name:a.name})}<span class="achievement-copy"><strong>${esc(a.name)}${a.completed?`<i>${icon('check')} 달성</i>`:''}</strong><small>${esc(a.description)}</small><span class="achievement-progress"><span style="width:${Math.min(100,Math.max(0,a.current/a.target*100))}%"></span></span><small class="achievement-count">${money(a.current)} / ${money(a.target)}${esc(a.unit)}</small></span>${icon('chevron')}</button>`).join('')}</div></section>`;
}
function openAchievement(id){
  const a=state.user?.achievements?.find(a=>a.id===id);if(!a)return;
  modal(`<div class="achievement-detail">${badgePicture({id:a.badge_id,name:a.name},{decorative:false})}<h2>${esc(a.name)}</h2><p>${esc(a.description)}</p><div class="achievement-rewards"><span>달성 보상</span><strong>프로필 배지</strong>${profileTitle({equipped_title:{name:a.title,style:a.style||'magic'}})}</div>${a.items?`<ul class="achievement-items">${a.items.map(item=>`<li class="${item.quantity>=(a.id==='focus'?5:1)?'is-done':''}"><span>${esc(item.name)}</span><b>${money(item.quantity)}${a.id==='focus'?' / 5':''}개</b></li>`).join('')}</ul>`:''}${a.dates?.length?`<p class="form-hint">달성일 · ${a.dates.map(esc).join(', ')}</p>`:''}<p class="form-hint">${a.completed?'배지와 칭호를 획득했어요.':'구매 승인 후 자동으로 지급돼요.'}</p>${a.completed?'<button type="button" class="primary-button full" data-action="profile-rewards">프로필에서 칭호 고르기</button>':''}</div>`);
}
function renderEvent() {
  const board=state.leaderboard;
  const rankings=board?`<section class="content-card"><h2>최고의 연금술사 TOP 3</h2><p class="form-hint">양일 누적 점수로 최종 1·2·3등을 선정합니다.</p><ol class="leaders">${board.leaders.map(p=>`<li class="${p.is_me?'me':''}"><span class="rank-number">${p.rank}위</span><strong class="profile-name">${profileAvatar(p)}<span class="profile-identity">${esc(p.name)}${p.is_me?' (나)':''}${profileTitle(p)}</span></strong><b>${money(p.score)}점</b></li>`).join('')}</ol><p class="form-hint">내 순위 ${board.me?.rank||'-'}위 · 총 ${board.total_participants}명 참여</p></section>`:'<section class="content-card"><h2>점수 순위</h2><p class="form-hint">순위를 불러오는 중입니다.</p></section>';
  return `${renderEventNotices(state.eventNotices)}<div class="event-layout"><div class="event-personal">${renderRewardRequests()}${renderLevelCard()}${renderRewardHistory()}</div><div class="event-rankings">${rankings}${renderAchievements()}</div></div>`;
}
function render() {
  const previousTrackWidth=document.querySelector('.milestone-track-bar > span')?.style.width;
  if(!isAdmin&&state.route==='dice'){state.route='ranking';history.replaceState(null,'','#ranking');}
  let content;
  if(isAdmin)content=state.user?renderAdmin():renderStaffLogin();
  else content=state.user?({shop:renderShop,pickup:renderPickup,orders:renderOrders,ranking:renderEvent}[state.route]||renderShop)():guestPurchase()?(state.route==='guest-orders'?renderOrders():renderShop()):renderBuyerLogin();
  const expanded=[...document.querySelectorAll('#app details[open]')].map(node=>node.id).filter(Boolean);
  document.querySelector('#app').innerHTML=shell((!isAdmin&&state.user&&state.route==='ranking'?'':prototypeNotice())+content);
  const trackFill=document.querySelector('.milestone-track-bar > span');
  if(previousTrackWidth&&trackFill?.animate&&previousTrackWidth!==trackFill.style.width&&!window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches){
    trackFill.animate([{width:previousTrackWidth},{width:trackFill.style.width}],{duration:650,easing:'ease-out'});
  }
  expanded.forEach(id=>{const node=document.getElementById(id);if(node)node.open=true;});
  document.title=`${isAdmin?'담당자':guestPurchase()?'비회원 빵 구매':!state.user?'로그인':['dice','ranking'].includes(state.route)?'이벤트 참여':'빵 구매'} · 캄보딜라이트`;
}
let refreshVersion=0;
async function refresh(){
  const version=++refreshVersion,token=state.token,guest=guestPurchase();
  try{
    const get=path=>api(path,{token}),jobs=[get('/api/config'),get('/api/products')];
    if(token)jobs.push(get('/api/auth/me'));
    const results=await Promise.all(jobs);let extra,guestResults;
    if(token){
      const user=results[2].user;
      if((isAdmin&&user.role!=='staff')||(!isAdmin&&user.role!=='buyer')){if(state.token===token){localStorage.removeItem(tokenKey);state.token=null;state.user=null;resetPickup();}return;}
      extra=isAdmin?await get('/api/staff/dashboard'):await Promise.all([get('/api/orders'),get('/api/rewards'),get('/api/leaderboard'),get('/api/event-notices')]);
    }else if(guest){
      guestResults=await Promise.all(state.guestReceipts.map(async receipt=>{
        try{return {receipt,order:(await api(`/api/guest/orders/${receipt.id}`,{token:receipt.token})).order};}
        catch(error){if(error.status===404)return {receipt,missing:true};throw error;}
      }));
    }
    if(state.token!==token||version!==refreshVersion||guest!==guestPurchase())return;
    state.config=results[0];state.products=results[1].products;state.eventNotices=token&&!isAdmin?extra[3].notices:[];
    if(token){state.user=results[2].user;if(isAdmin)state.staffData=extra;else{if(state.pickupUserId!==state.user.id){resetPickup();state.pickupUserId=state.user.id;}state.pickupDefaults=results[2].pickup_defaults||{name:state.user.name,phone:''};state.orders=extra[0].orders;state.rewards=extra[1].rewards;state.rewardRequests=extra[1].requests||[];state.leaderboard=extra[2];}syncProfileHairpins();syncProfileBadges();syncProfileTitles();}
    else if(guestResults){state.orders=guestResults.filter(r=>r.order).map(r=>r.order).sort((a,b)=>b.id-a.id);if(guestResults.some(r=>r.missing)){state.guestReceipts=guestResults.filter(r=>!r.missing).map(r=>r.receipt);localStorage.setItem('kambo.guest.orders',JSON.stringify(state.guestReceipts));}}
  }catch(error){if(token!==state.token||version!==refreshVersion)return;throw error;}
}

initAdmin({state,api,icon,esc,money,time,toast,modal,closeModal,render,refresh,requestId,submitButton,profileAvatar,profileTitle,titleStyles,badgePicture,badgeIcons,productPhoto,normalizePhone,renderEventNotices});

function normalizePhone(value){
  if(typeof value!=='string'||/[^0-9-]/.test(value)||!/^(?:010[0-9]{8}|010-[0-9]{4}-[0-9]{4})$/.test(value))throw new Error('전화번호는 01012345678 또는 010-1234-5678 형식으로 입력해 주세요. 숫자와 정해진 위치의 대시만 사용할 수 있어요.');
  const digits=value.replaceAll('-','');return `${digits.slice(0,3)}-${digits.slice(3,7)}-${digits.slice(7)}`;
}
function buyerAuthForm(mode='login') {
  return `<div class="auth-switch"><button class="${mode==='login'?'active':''}" data-action="auth-mode" data-mode="login">로그인</button><button class="${mode==='register'?'active':''}" data-action="auth-mode" data-mode="register">계정 만들기</button></div><form id="buyer-auth" data-mode="${mode}">${mode==='register'?'<div class="field"><label for="auth-name">이름(닉네임)</label><input id="auth-name" name="name" autocomplete="nickname" maxlength="30" required></div>':''}<div class="field"><label for="auth-phone">전화번호</label><input id="auth-phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="010-1234-5678" minlength="11" maxlength="13" pattern="010(?:[0-9]{8}|-[0-9]{4}-[0-9]{4})" title="01012345678 또는 010-1234-5678" data-phone-input required></div><div class="field"><label for="auth-pin">숫자 4자리 비밀번호</label><input id="auth-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" autocomplete="${mode==='register'?'new-password':'current-password'}" required></div>${mode==='register'?'<p class="form-hint">전화번호당 계정 하나를 만들 수 있어요. 화면에는 닉네임만 보여요.</p>':''}<button type="submit" class="primary-button full">${mode==='register'?'계정 만들기':'로그인'}</button></form>`;
}
function guestEntry(){return `<div class="guest-entry"><button class="secondary-button full" data-action="guest-start">계정 없이 빵만 구매</button>${state.guestReceipts.length?'<button class="text-button full" data-action="guest-orders">비회원 주문 내역</button>':''}</div>`;}
function renderBuyerLogin() { return `<section class="login-card content-card"><h1>전화번호와 비밀번호를 입력해 주세요.</h1><p class="form-hint">처음이라면 계정을 만들어 주세요.</p>${buyerAuthForm(state.authMode)}${guestEntry()}</section>`; }
let profileSaving=false;
function openProfile(onboarding=false,tab='face') {
  if(!state.user||profileSaving)return;
  if(state.rolling||state.leveling){toast('진행 중인 이벤트가 끝나면 꾸밀 수 있어요.');return;}
  modal(profileEditor(state.user,{onboarding}));
  if(tab!=='face')selectProfileTab(document.querySelector('.profile-editor'),tab);
}
function selectProfileTab(editor,tab){
  editor.querySelectorAll('[data-action="profile-tab"]').forEach(button=>{const selected=button.dataset.tab===tab;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});
  editor.querySelectorAll('[data-profile-panel]').forEach(panel=>panel.hidden=panel.dataset.profilePanel!==tab);
}
function selectedProfileBadge(data){
  const id=Object.hasOwn(data,'badge_id')?data.badge_id:state.user.equipped_badge?.id;
  return state.user.badges?.find(b=>b.id===id&&b.owned)||null;
}
function selectedProfileTitle(data){
  const id=Object.hasOwn(data,'title_id')?data.title_id:state.user.equipped_title?.id;
  return state.user.titles?.find(t=>t.id===id&&t.owned)||null;
}
function updateProfilePreview(form) {
  const preview=document.querySelector('[data-profile-preview]');
  if(preview&&Number(form.dataset.userId)===state.user?.id){
    const data=Object.fromEntries(new FormData(form)),avatar=normalizeAvatar(data,state.user.id);
    preview.innerHTML=profileAvatar({...state.user,avatar,equipped_badge:selectedProfileBadge(data)},{className:'profile-preview-picture'});
    const titlePreview=document.querySelector('[data-profile-title-preview]');
    if(titlePreview)titlePreview.innerHTML=profileTitle({equipped_title:selectedProfileTitle(data)});
    form.querySelectorAll('.profile-choice-picture').forEach(picture=>{
      const input=picture.closest('.profile-choice').querySelector('input');
      picture.outerHTML=profileAvatar({...state.user,equipped_badge:null,avatar:{...avatar,[input.name]:input.value}},{className:'profile-choice-picture',decorative:true,breadOnly:['face_shape','expression'].includes(input.name),pinOnly:input.name==='hairpin'});
    });
  }
}
function syncProfileHairpins() {
  const form=document.querySelector('#profile-editor'),target=document.querySelector('[data-profile-hairpins]');
  if(!form||!target||profileSaving||Number(form.dataset.userId)!==state.user?.id)return;
  const owned=JSON.stringify([...new Set(['none',...(state.user.unlocked_hairpins||[])])]);
  if(target.dataset.unlocks===owned)return;
  const draft=normalizeAvatar(Object.fromEntries(new FormData(form)),state.user.id);
  const focused=target.contains(document.activeElement)?document.activeElement.value:null;
  const expanded=!!target.querySelector('details[open]');
  target.outerHTML=profileHairpins(state.user,draft);
  const updated=document.querySelector('[data-profile-hairpins]');
  if(expanded&&updated.querySelector('details'))updated.querySelector('details').open=true;
  if(focused)updated.querySelector(`input[value="${focused}"]`)?.focus({preventScroll:true});
}
function syncProfileBadges(){
  const form=document.querySelector('#profile-editor'),target=document.querySelector('[data-profile-badges]');
  if(!form||!target||profileSaving||Number(form.dataset.userId)!==state.user?.id)return;
  if(target.dataset.badges===JSON.stringify(state.user.badges||[]))return;
  const draft=Object.fromEntries(new FormData(form));
  target.outerHTML=profileBadges(state.user,draft.badge_id??state.user.equipped_badge?.id??'');
  updateProfilePreview(form);
}
function showBadgeInfo(id){
  if(profileSaving)return;
  const badge=state.user?.badges?.find(b=>b.id===id),target=document.querySelector('[data-badge-info]');
  if(!badge||!target)return;
  target.innerHTML=`<strong>${esc(badge.name)}</strong><p>${esc(badge.description)}</p>`;
  target.hidden=false;target.scrollIntoView?.({block:'nearest'});
}
function syncProfileTitles(){
  const form=document.querySelector('#profile-editor'),target=document.querySelector('[data-profile-titles]');
  if(!form||!target||profileSaving||Number(form.dataset.userId)!==state.user?.id)return;
  if(target.dataset.titles===JSON.stringify(state.user.titles||[]))return;
  const draft=Object.fromEntries(new FormData(form));
  const expanded=!!target.querySelector('details[open]');
  target.outerHTML=profileTitles(state.user,draft.title_id??state.user.equipped_title?.id??'');
  if(expanded){const details=document.querySelector('[data-profile-titles] details');if(details)details.open=true;}
  updateProfilePreview(form);
}
function showTitleInfo(id){
  if(profileSaving)return;
  const title=state.user?.titles?.find(t=>t.id===id),target=document.querySelector('[data-title-info]');
  if(!title||!target)return;
  target.innerHTML=`<strong>${esc(title.name)}</strong><p>${esc(title.description)}</p>`;
  target.hidden=false;target.scrollIntoView?.({block:'nearest'});
}
async function signInBuyer(form,data) {
  const result=await api(`/api/auth/${form.dataset.mode}`,{method:'POST',body:{...(form.dataset.mode==='register'?{name:data.name.trim()}:{}),phone:normalizePhone(data.phone),pin:data.pin}});
  resetPickup();state.token=result.token;state.user=result.user;state.lastRoll=null;state.selectedDice=null;localStorage.setItem(tokenKey,result.token);
  await refresh();closeModal();render();
  if(state.user.profile_customized===false)openProfile(true);
  else toast(`${result.user.name} 님, 반가워요!`);
}
async function saveProfile(form,data) {
  if(profileSaving||Number(form.dataset.userId)!==state.user?.id)return;
  const userId=state.user.id,token=state.token;
  const avatar=normalizeAvatar(data,userId);
  profileSaving=true;submitButton(form,true);
  form.querySelectorAll('fieldset').forEach(node=>node.disabled=true);
  document.querySelectorAll('.profile-editor-footer,.modal-close').forEach(node=>node.disabled=true);
  const errorNode=form.querySelector('.profile-editor-error');
  if(errorNode)errorNode.hidden=true;
  try {
    const result=await api('/api/profile',{method:'POST',body:{avatar,...(Object.hasOwn(data,'badge_id')?{badge_id:data.badge_id||null}:{}),...(Object.hasOwn(data,'title_id')?{title_id:data.title_id||null}:{})},token});
    if(state.token!==token||state.user?.id!==userId)return;
    state.user=result.user;
    if(state.leaderboard){
      for(const key of ['leaders','neighbors'])state.leaderboard[key]=state.leaderboard[key].map(p=>p.id===userId?{...p,avatar:result.user.avatar,equipped_badge:result.user.equipped_badge||null,equipped_title:result.user.equipped_title||null}:p);
      if(state.leaderboard.me?.id===userId)state.leaderboard.me={...state.leaderboard.me,avatar:result.user.avatar,equipped_badge:result.user.equipped_badge||null,equipped_title:result.user.equipped_title||null};
    }
    await refreshAfterAction();
    if(state.token!==token||state.user?.id!==userId)return;
    closeModal();render();toast('내 연금술사를 저장했어요.');
  } catch(error) {
    if(state.token===token&&state.user?.id===userId&&form.isConnected&&errorNode){
      errorNode.textContent=error.message||'캐릭터를 저장하지 못했어요. 다시 시도해 주세요.';
      errorNode.hidden=false;
    }
  } finally {
    profileSaving=false;
    if(form.isConnected){
      form.querySelectorAll('fieldset').forEach(node=>node.disabled=false);
      document.querySelectorAll('.profile-editor-footer,.modal-close').forEach(node=>node.disabled=false);
      submitButton(form,false);
    }
  }
}
function openAuth(mode='login') { modal(`<h2>로그인</h2>${buyerAuthForm(mode)}${guestEntry()}`); }

async function checkout(button){
  if(!cartCount())return;
  const guest=guestPurchase(),name=state.guestName.trim();
  if(!state.user&&!guest){openAuth();return;}
  if(guest&&!name){closeModal();toast('구매자 이름을 입력해 주세요.','error');document.querySelector('#guest-name')?.focus();return;}
  const items=Object.entries(state.cart).map(([product_id,quantity])=>({product_id:Number(product_id),quantity}));
  const body=guest?{name,items}:{items},op=operation(guest?'guest-checkout':'checkout',guest?body:items);
  button.disabled=true;
  try{
    const {order}=await api(guest?'/api/guest/orders':'/api/orders',{method:'POST',body:{...body,request_id:op.id},...(guest?{token:null}:{})});
    if(guest){state.guestReceipts=[...state.guestReceipts.filter(r=>r.id!==order.id),{id:order.id,token:op.id}];localStorage.setItem('kambo.guest.orders',JSON.stringify(state.guestReceipts));}
    state.cart={};op.done();if(!state.orders.some(o=>o.id===order.id))state.orders.unshift(order);
    await refreshAfterAction();state.route=guest?'guest-orders':'orders';history.replaceState(null,'',`#${state.route}`);render();
    modal(`<div class="order-success"><div class="success-icon">${icon('check')}</div><h2>빵 구매 요청을 보냈어요!</h2><p>담당자에게 주문을 보여 주고<br>안내받은 계좌로 입금해 주세요.</p><div class="success-box">주문 #${String(order.id).padStart(3,'0')}${guest?` · ${esc(order.customer_name)}`:''} · 선택 수량 ${order.quantity}<strong>${money(order.total)}원</strong>${guest?'':orderDice(order)?`확인 후 주사위 ${orderDice(order)}개가 지급돼요.`:'음료 구매에는 주사위가 지급되지 않아요.'}</div><button class="primary-button full" data-action="close-modal">주문 내역 확인하기 ${icon('arrow')}</button></div>`);
  }catch(error){if(error.status>=400&&error.status<500)op.done();button.disabled=false;toast(error.message,'error');await refresh().catch(()=>{});render();}
}
function openLevelUp() {
  const {target,eligible}=eventProgress();
  if(eligible)openMilestone(target);
}
async function rollDice() {
  if(state.rolling||state.leveling||!state.user?.dice_balance)return;
  const chosen=selectedDie();if(!chosen)return;
  const {target}=eventProgress(),before=state.user.score,kind=chosen.kind;
  state.selectedDice=kind;state.rolling=true;render();const op=operation('dice',{kind});
  try {
    const [result]=await Promise.all([api('/api/dice/roll',{method:'POST',body:{kind,request_id:op.id}}),new Promise(r=>setTimeout(r,850))]);
    state.lastRoll=result;state.user=result.user||{...state.user,score:result.score,dice_balance:result.dice_balance};op.done();state.rolling=false;
    await refreshAfterAction();render();
    if(result.result==='milk')openBeverageChoice(result.fulfillment);
    else if(target!==null&&before<target&&state.user.score>=target)openLevelUp();
  } catch(error) { if(error.status>=400&&error.status<500)op.done();state.rolling=false;await refresh().catch(()=>{});render();toast(error.message,'error'); }
}
async function claimReward(button) {
  if(state.leveling||state.rolling)return;
  const threshold=Number(button.dataset?.threshold??eventProgress().target);
  const m=eventProgress().milestones.find(m=>m.threshold===threshold);
  if(!m||state.user.score<threshold||eventProgress().claimed.includes(threshold))return;
  state.leveling=true;button.disabled=true;const op=operation(`reward-${threshold}`,{threshold});
  try {
    const {reward,user}=await api('/api/rewards/claim',{method:'POST',body:{threshold,request_id:op.id}});
    state.user=user;op.done();await refreshAfterAction();state.leveling=false;render();
    if(reward.kind==='milk'&&reward.fulfillment){openBeverageChoice(reward.fulfillment);return;}
    const p=state.products.find(p=>p.id===reward.product_id),level=eventProgress(user).level;
    modal(`<div class="order-success level-up-result"><span class="label-kicker">LEVEL UP!</span>${characterPortrait(level,'level-preview',level)}<h2>${esc(reward.product_name)}${reward.kind==='sunglasses'?' 해제!':' 당첨!'}</h2><div class="bread-prize">${p?`<img src="${productImage(p)}" alt="" width="76" height="64">`:icon(reward.kind==='milk'?'milk':'spark')}<strong>${esc(reward.product_name)}</strong></div><p>${reward.threshold}점 달성을 축하해요.<br>${reward.kind==='sunglasses'?'계정 관리 → 꾸미기에서 착용할 수 있어요.':'물품을 확보했어요. 담당자에게 요청을 보여주고 받아 가세요.'}</p><p class="form-hint">${reward.fulfillment?`이벤트 요청 #${reward.fulfillment.id} · 담당자 지급 대기`:`점수 보상 #${reward.id} · 자동 지급됐어요.`}</p><button class="primary-button full" data-action="close-modal">확인</button></div>`);
  } catch(error) {
    if(error.status>=400&&error.status<500)op.done();state.leveling=false;button.disabled=false;toast(error.message,'error');
  }
}
document.addEventListener('input',event=>{if(event.target.closest?.('#preorder-lookup'))editPickupField(event.target.name,event.target.value);if(event.target.matches?.('[data-phone-input]'))event.target.setCustomValidity('');if(event.target.id==='guest-name'){state.guestName=event.target.value;sessionStorage.setItem('kambo.guest.name',state.guestName);}});
document.addEventListener('focusout',event=>{const input=event.target;if(!input.matches?.('[data-phone-input]')||!input.value)return;try{input.value=normalizePhone(input.value);if(input.closest?.('#preorder-lookup'))state.pickupDraft={...pickupValues(),phone:input.value};input.setCustomValidity('');}catch(error){input.setCustomValidity(error.message);}});
document.addEventListener('error',event=>{if(event.target.matches?.('.product-photo img'))event.target.remove();},true);
document.addEventListener('change',event=>{const form=event.target.closest?.('#profile-editor');if(form)updateProfilePreview(form);});
document.addEventListener('click',async event=>{const el=event.target.closest('[data-action]');if(!el)return;const action=el.dataset.action;try{
if(action==='navigate'){state.route=el.dataset.route;location.hash=state.route;render();window.scrollTo({top:0,behavior:'instant'});}
else if(action==='guest-start'||action==='guest-orders'){closeModal();state.route=action==='guest-start'?'guest':'guest-orders';location.hash=state.route;await refreshAfterAction();render();window.scrollTo({top:0,behavior:'instant'});}
else if(action==='guest-exit'){state.route='shop';location.hash='shop';state.orders=[];render();}
else if(action==='login')isAdmin?document.querySelector('#staff-login input')?.focus():openAuth();
else if(action==='auth-mode'){state.authMode=el.dataset.mode;if(document.querySelector('.modal'))openAuth(el.dataset.mode);else render();}
else if(action==='close-modal'){if(!profileSaving)closeModal();}
else if(action==='profile')openProfile();
else if(action==='profile-rewards')openProfile(false,'titles');
else if(action==='achievement-detail')openAchievement(el.dataset.achievement);
else if(action==='badge-info')showBadgeInfo(el.dataset.badge);
else if(action==='title-info')showTitleInfo(el.dataset.title);
else if(action==='profile-tab'){
  selectProfileTab(el.closest('.profile-editor'),el.dataset.tab);
}
else if(action==='logout'){if(profileSaving)return;await api('/api/auth/logout',{method:'POST',body:{}});localStorage.removeItem(tokenKey);state.token=null;state.user=null;resetPickup();state.orders=[];state.rewards=[];state.rewardRequests=[];state.staffData=null;state.reservation=null;state.lastRoll=null;state.selectedDice=null;closeModal();render();toast('다음에 또 따뜻한 빵으로 만나요.');}
else if(action==='cart-plus'||action==='cart-minus'||action==='remove-cart'){const id=Number(el.dataset.id),p=state.products.find(p=>p.id===id);const quantity=action==='remove-cart'?0:(state.cart[id]||0)+(action==='cart-plus'?1:-1);if(quantity>p.stock){toast('지금 남은 수량만큼 담을 수 있어요.','error');return;}const basketOpen=!!document.querySelector('.modal .basket');if(quantity>0)state.cart[id]=quantity;else delete state.cart[id];render();if(basketOpen)modal(renderBasket());}
else if(action==='open-cart')modal(renderBasket());
else if(action==='checkout')await checkout(el);
else if(action==='claim-preorder'){el.disabled=true;try{const {order}=await api(`/api/preorders/${el.dataset.id}/claim`,{method:'POST',body:{request_id:el.dataset.requestId||(el.dataset.requestId=requestId())}});if(!state.orders.some(o=>o.id===order.id))state.orders.unshift(order);await refreshAfterAction();state.route='orders';location.hash='orders';render();toast(order.status==='approved'?'이미 픽업을 완료한 예약이에요.':'픽업을 요청했어요. 담당자에게 말씀해 주세요.');}catch(error){el.disabled=false;throw error;}}
else if(action==='select-dice'){if(!state.rolling&&!state.leveling){state.selectedDice=el.dataset.kind;state.lastRoll=null;render();}}
else if(action==='roll-dice')await rollDice();
else if(action==='open-milestone')openMilestone(Number(el.dataset.threshold));
else if(action==='claim-reward')await claimReward(el);
else if(action==='open-beverage-choice'){if(!state.rolling&&!state.leveling)openBeverageChoice(state.rewardRequests.find(r=>r.id===Number(el.dataset.request)&&r.status==='awaiting_choice'));}
else if(action==='choose-beverage')await chooseBeverage(el);
else if(action==='decline-beverage')await chooseBeverage(el,true);
else if(action==='retry')location.reload();
else await handleAdminClick(action,el,event);
}catch(error){toast(error.message||'잠시 후 다시 시도해 주세요.','error');}});
document.addEventListener('submit',async event=>{const form=event.target;event.preventDefault();const data=Object.fromEntries(new FormData(form));submitButton(form,true);try{if(form.id==='buyer-auth'){await signInBuyer(form,data);}else if(form.id==='profile-editor'){await saveProfile(form,data);}else if(form.id==='preorder-lookup'){await lookupPreorder(data);}else await handleAdminSubmit(form,event);}catch(error){if(form.id==='buyer-auth'){const errorNode=document.createElement('p');errorNode.className='error-message';errorNode.setAttribute('role','alert');errorNode.textContent=error.message;form.querySelector('.error-message')?.remove();form.prepend(errorNode);}else toast(error.message,'error');}finally{submitButton(form,false);}});
document.addEventListener('keydown',event=>{if(!document.querySelector('.modal'))return;if(event.key==='Escape'&&!profileSaving)closeModal();if(event.key==='Tab'){const focusables=[...document.querySelectorAll('.modal button:not(:disabled),.modal a[href],.modal input:not([disabled]),.modal select,.modal textarea')].filter(n=>n.offsetParent!==null);const first=focusables[0],last=focusables.at(-1);if(event.shiftKey&&document.activeElement===first){last?.focus();event.preventDefault();}else if(!event.shiftKey&&document.activeElement===last){first?.focus();event.preventDefault();}}});
window.addEventListener('hashchange',()=>{state.route=location.hash.slice(1)||(isAdmin?'queue':'shop');render();});
let polling=false,pendingRender=false;
function snapshot(){return JSON.stringify([state.user,state.products,state.orders,state.staffData,state.leaderboard,state.rewards,state.rewardRequests,state.eventNotices]);}
function safeToRender(){return !document.querySelector('.modal')&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!state.rolling&&!state.leveling;}
setInterval(async()=>{if(polling||state.rolling||state.leveling||document.hidden)return;polling=true;try{const before=snapshot();const oldOrders=isAdmin?state.staffData?.orders||[]:state.orders,oldRewards=state.staffData?.reward_requests||[];await refresh();const newOrders=isAdmin?state.staffData?.orders||[]:state.orders;if(isAdmin){const freshRewards=(state.staffData?.reward_requests||[]).filter(r=>r.status==='pending'&&!oldRewards.some(old=>old.id===r.id&&old.status==='pending'));if(freshRewards.length)toast(`${freshRewards[0].customer_name} 님의 이벤트 지급 요청이 도착했어요.`);const fresh=newOrders.filter(o=>o.status==='pending'&&!oldOrders.some(old=>old.id===o.id));if(fresh.length)toast(`${fresh[0].customer_name} 님의 새 주문이 도착했어요.`);}else{const newlyApproved=newOrders.find(o=>o.status==='approved'&&oldOrders.find(old=>old.id===o.id&&old.status==='pending'));if(newlyApproved)toast(newlyApproved.user_id===null?'주문이 승인됐어요. 빵을 받아주세요.':`주문이 승인됐어요. ${orderDice(newlyApproved)?`주사위 ${orderDice(newlyApproved)}개가 도착했어요!`:'음료 구매에는 주사위가 지급되지 않아요.'}`);}if(before!==snapshot())pendingRender=true;if(pendingRender&&safeToRender()){render();pendingRender=false;}}catch(error){if(error.status===401){localStorage.removeItem(tokenKey);state.token=null;state.user=null;resetPickup();render();toast('다시 로그인해 주세요.','error');}}finally{polling=false;}},4000);
async function boot(){try{await refresh();render();}catch(error){if(error.status===401){localStorage.removeItem(tokenKey);state.token=null;state.user=null;resetPickup();await refresh();render();}else document.querySelector('#app').innerHTML=`<div class="connection-error">${brand()}<h1>빵집에 연결하고 있어요</h1><p>잠시 후 다시 연결해 주세요.<br>${esc(error.message)}</p><button class="primary-button" data-action="retry">다시 연결하기 ${icon('arrow')}</button></div>`;}}
boot();
