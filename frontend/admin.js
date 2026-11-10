let helpers;
let orderFilter = 'pending';
let eventFilter = 'pending';
let eventTab = 'requests';
let grantRecipientMode = 'account';
let grantKind = 'bread';
let grantGift = 'oatmeal';
let grantDraft = {};
let inventoryBucket = 'all';
let customerMode = 'existing';
let manualSaleType = 'walkin';
let manualReservation = null;
let manualLookupVersion = 0;
let manualPickupMode = 'existing';
let manualPickupUser = '';
let inputListenerAdded = false;
const pendingRequests = new Map();
const staffSearch = {inventory:'',pickup:'',queue:'',users:'',events:''};

export function initAdmin(shared) {
  helpers = shared;
  if (!inputListenerAdded) {
    document.addEventListener('input', event => {
      if(event.target.closest?.('#admin-manual-grant')){
        if(['user_id','name','product_id','quantity','points','reason','gift_name','badge_id','title_id'].includes(event.target.name))grantDraft[event.target.name]=event.target.value;
        if(event.target.name==='user_id'&&['badge','title'].includes(grantKind)){
          const buyer=list('users').find(u=>u.id===Number(event.target.value));
          if(buyer?.badges?.some(b=>b.id===grantDraft.badge_id&&b.owned))grantDraft.badge_id='';
          if(buyer?.titles?.some(t=>t.id===grantDraft.title_id&&t.owned))grantDraft.title_id='';
          helpers.render();return;
        }
        if(event.target.name==='gift'){grantGift=event.target.value;helpers.render();return;}
      }
      const search = event.target.dataset?.adminSearch;
      if (Object.hasOwn(staffSearch,search)) { updateStaffSearch(search,event.target.value); return; }
      if(event.target.name==='user_id'){
        const preview=event.target.closest('form')?.querySelector('[data-selected-profile]');
        if(preview)preview.innerHTML=event.target.value?buyerIdentity(Number(event.target.value)):'';
      }
      if (event.target.name==='user_id' && event.target.closest('#admin-manual-preorder-complete')) {
        manualPickupUser = event.target.value;
        return;
      }
      const form = event.target.closest('#admin-manual-sale');
      if (!form) return;
      const total = [...form.querySelectorAll('[data-sale-product]')].reduce((sum, input) => sum + Math.max(0, Number(input.value) || 0) * Number(input.dataset.price), 0);
      const target = form.querySelector('[data-sale-total]');
      if (target) target.textContent = helpers.money(total);
    });
    inputListenerAdded = true;
  }
}

const data = () => helpers.state.staffData || {};
const list = key => data()[key] || [];
const productList = () => data().products || helpers.state.products || [];
const escape = value => helpers.esc(String(value ?? ''));
const i = name => helpers.icon(name);
const number = value => Number(value || 0).toLocaleString('ko-KR');
const won = value => `${helpers.money(Number(value || 0))}원`;
const stamp = value => escape(helpers.time(value));
const typeLabel = type => ({ walkin: '현장 구매', preorder: '예약 수령', manual: '수기 판매' }[type] || type);
const statusLabel = status => ({ pending: '확인 대기', approved: '승인 완료', cancelled: '취소 완료' }[status] || status);
const bucketLabel = bucket => ({ stock: '현판·이벤트', preorder_stock: '예판', reward_stock: '이전 이벤트(통합 전)', milk: '이전 우유(통합 전)', event_supply: '이벤트 물품' }[bucket] || bucket);
const pendingOrders = () => list('orders').filter(order => order.status === 'pending');
const preorderLabel = status => ({reserved:'수령 대기',pending:'수령 요청 접수',approved:'수령 완료'}[status]||status);
const phoneLabel = phone => String(phone).replace(/^(\d{3})(\d{3,4})(\d{4})$/,'$1-$2-$3');
const preorderMenu = r => r.items.map(item=>`${item.name} ${item.quantity}${productList().find(p=>p.id===item.product_id)?.unit||'개'}`).join(', ');
function buyerIdentity(id,name='') {
  if(id===null)return `<span class="profile-name"><span>${escape(name)}</span><small class="muted">비회원</small></span>`;
  const user=list('users').find(u=>u.id===id)||{id,name};
  return `<span class="profile-name">${helpers.profileAvatar?.(user)||''}<span class="profile-identity">${escape(name||user.name)}${helpers.profileTitle?.(user)||''}</span></span>`;
}

function matchesSearch(query,...fields) {
  const normalize=value=>String(value??'').normalize('NFKC').toLowerCase().replace(/[\s-]+/g,'');
  const text=fields.map(normalize).join(' ');
  return String(query).trim().split(/\s+/).filter(Boolean).every(term=>text.includes(normalize(term)));
}
function matchingPreorders(query) {
  return list('reservations').filter(r=>matchesSearch(query,r.name,r.phone,preorderMenu(r),preorderLabel(r.status)));
}
function searchField(key,id,label,placeholder) {
  return `<div class="field admin-search"><label for="${id}">${label}</label><input id="${id}" type="search" data-admin-search="${key}" value="${escape(staffSearch[key])}" placeholder="${placeholder}" autocomplete="off"></div>`;
}
function updateStaffSearch(key,value) {
  staffSearch[key]=value;
  if (key==='pickup') {
    manualReservation=null;manualLookupVersion++;
    document.querySelector('#manual-preorder-result')?.remove();
  }
  if (key==='users') {
    manualPickupUser='';
    const select=document.querySelector('#admin-pickup-user');
    if(select)select.innerHTML=buyerOptions('','수령 계정 선택',value);
    const preview=document.querySelector('#admin-manual-preorder-complete [data-selected-profile]');
    if(preview)preview.innerHTML='';
    const count=document.querySelector('#pickup-account-count');
    if(count)count.textContent=`검색된 계정 ${list('users').filter(u=>matchesSearch(value,u.name,u.phone)).length}명`;
    return;
  }
  const views={inventory:['#inventory-preorder-results',preorderStatusResults],pickup:['#manual-preorder-matches',manualPreorderMatches],queue:['#admin-queue-results',queueResults],events:['#admin-event-results',eventResults]};
  const [selector,view]=views[key],target=document.querySelector(selector);
  if(target)target.innerHTML=view();
}

function heading(title, description, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1>${description ? `<p>${description}</p>` : ''}</div>${actions ? `<div class="admin-actions">${actions}</div>` : ''}</div>`;
}

function empty(title, description, icon = 'box') {
  return `<div class="empty-state admin-empty">${i(icon)}<h2>${title}</h2><p>${description}</p></div>`;
}





function orderStockNote(order, item) {
  const product = productList().find(p => p.id === item.product_id);
  const stock = item.remaining_stock ?? product?.[order.type === 'preorder' ? 'preorder_stock' : 'stock'];
  if (!Number.isInteger(stock) || stock < 0) return '';
  const label = order.type === 'preorder' ? '남은 예판 재고' : '남은 재고';
  return `<small class="order-stock-note">(${label} ${number(stock)}${escape(item.unit || product?.unit || '개')})</small>`;
}

function orderCard(order) {
  const pending = order.status === 'pending';
  return `<article class="pending-order"><div class="pending-title"><h3>${buyerIdentity(order.user_id,order.customer_name)}<small>#${order.id} · ${typeLabel(order.type)}</small></h3><span class="status ${escape(order.status)}">${i(pending ? 'clock' : order.status === 'approved' ? 'check' : 'x')}${statusLabel(order.status)}</span></div><div class="order-lines">${(order.items || []).map(item => `<div class="order-line"><span>${escape(item.name)} <b>× ${item.quantity}</b>${orderStockNote(order, item)}</span><span>${won(item.price * item.quantity)}</span></div>`).join('')}</div><div class="order-bottom"><span>${stamp(order.created_at)} 접수 · 총 ${order.quantity}개</span><strong>${won(order.total)}</strong></div>${pending ? `<div class="order-controls"><button class="secondary-button" data-action="admin-cancel" data-id="${order.id}">${i('x')}취소</button><button class="primary-button" data-action="admin-approve" data-id="${order.id}">${i('check')}${order.type === 'preorder' ? '품목 전달 완료 · 승인' : '입금 · 전달 확인 후 승인'}</button></div>` : ''}</article>`;
}

function queueResults() {
  const filtered=list('orders').filter(order=>{
    const reservation=list('reservations').find(r=>r.id===order.reservation_id);
    return (orderFilter==='all'||order.status===orderFilter)&&matchesSearch(staffSearch.queue,order.customer_name,reservation?.name,reservation?.phone,(order.items||[]).map(item=>item.name).join(' '),`#${order.id}`);
  });
  return `<p class="search-count" role="status">검색 결과 ${filtered.length}건</p><div class="order-queue">${filtered.length?filtered.map(orderCard).join(''):empty('해당 주문이 없습니다.','이름·전화번호·메뉴 또는 주문 상태를 확인해 주세요.','bag')}</div>`;
}
function queuePage() {
  return `${heading('주문','이름·주문·입금 내역을 확인한 뒤 승인해 주세요.',`<button class="secondary-button" data-action="admin-refresh">새로고침</button>`)}
  ${help('주문 확인 방법','현판은 입금과 빵 전달을 확인한 뒤 승인합니다. 예판은 예약한 빵을 전달한 뒤 승인합니다. 품목 옆 괄호는 접수된 주문을 반영한 현재 남은 재고이며, 예판은 별도 예판 재고를 표시합니다. 현장 구매는 빵 개수만큼, 예약 수령은 예약 금액 등급의 전용 주사위 1개를 지급합니다. 비회원 또는 음료만 구매하면 주사위가 지급되지 않습니다. 대기 주문을 취소하면 확보한 재고가 돌아옵니다.')}
  <div class="admin-subtabs">${[['pending','승인 대기'],['approved','승인 완료'],['cancelled','취소']].map(([key,label])=>`<button class="tab-chip ${orderFilter===key?'active':''}" data-action="admin-order-filter" data-filter="${key}">${label} ${list('orders').filter(o=>o.status===key).length}</button>`).join('')}</div>
  ${searchField('queue','admin-queue-search','주문 검색','이름 · 예약 전화번호 · 메뉴 검색')}<div id="admin-queue-results">${queueResults()}</div>`;
}

function heldStock(productId) {
  const rewards=list('reward_requests').filter(r=>r.status==='pending'&&r.product_id===productId).length;
  return rewards + pendingOrders().reduce((sum, order) => sum + (order.items || []).filter(item => item.product_id === productId).reduce((count, item) => count + item.quantity, 0), 0);
}

function preorderStatusResults() {
  const reservations=matchingPreorders(staffSearch.inventory);
  return `<p class="search-count" role="status">검색 결과 ${reservations.length}건 / 전체 ${list('reservations').length}건</p>${reservations.length?`<div class="table-wrap"><table><thead><tr><th>이름</th><th>전화번호</th><th>메뉴</th><th>수령 상태</th></tr></thead><tbody>${reservations.map(r=>`<tr><td><strong>${escape(r.name)}</strong></td><td>${escape(phoneLabel(r.phone))}</td><td class="preorder-menu">${escape(preorderMenu(r))}</td><td><span class="status ${r.status==='approved'?'approved':'pending'}">${escape(preorderLabel(r.status))}</span></td></tr>`).join('')}</tbody></table></div>`:`<p class="form-hint">${list('reservations').length?'검색 결과가 없습니다.':'등록된 예판이 없습니다.'}</p>`}`;
}
function preorderStatusPanel() {
  return `<details id="inventory-preorders" class="preorder-status-panel"><summary class="secondary-button">${i('chevron')}예판 수령 현황 <span>${list('reservations').length}건</span></summary><div class="preorder-status-content">${searchField('inventory','admin-preorder-status-search','예판 검색','이름 · 전화번호 뒷자리 · 메뉴 검색')}<div id="inventory-preorder-results">${preorderStatusResults()}</div></div></details>`;
}

function inventoryPage() {
  const logs=list('inventory_logs').filter(log=>inventoryBucket==='all'||log.bucket===inventoryBucket);
  return `${heading('재고관리','',`<button class="secondary-button" data-action="admin-import">예판 등록</button><button class="primary-button" data-action="admin-adjust">재고 수정</button>`)}
  ${help('재고 보는 방법','빵은 판매와 빵 당첨, 우유·두유는 각각 판매와 이벤트 지급에 같은 현판 재고를 사용합니다. 접수 보관에는 판매와 이벤트 지급 대기를 함께 표시합니다. 예판 대기와 접수 보관 수량은 추첨에 사용하지 않습니다. 매장 예상은 현판·예판 대기·접수 보관의 합입니다. 추가 입고는 +, 차감은 −로 수정합니다.')}
  ${preorderStatusPanel()}
  <section class="content-card event-supply-card"><div><h2>이벤트 물품</h2><p>오트밀 미니바이트 <strong>${data().event_supplies?.find(s=>s.key==='oatmeal')?.stock||0}개</strong><small> · 지급 대기 ${list('reward_requests').filter(r=>r.status==='pending'&&r.supply_key==='oatmeal').length}개</small></p></div><button class="secondary-button" data-action="admin-supply-adjust">수정</button></section>
  <div class="table-wrap"><table><thead><tr><th>품목</th><th>현판·이벤트 가능</th><th>예판 대기</th><th>접수 보관</th><th>매장 예상</th><th></th></tr></thead><tbody>${productList().map(p=>{
    const held=heldStock(p.id);
    return `<tr><td><strong>${escape(p.name)}</strong></td><td>${p.stock}</td><td>${p.preorder_stock}</td><td>${held}</td><td><strong>${p.stock+p.preorder_stock+held}</strong></td><td><button class="secondary-button" data-action="admin-adjust" data-product="${p.id}">수정</button></td></tr>`;
  }).join('')}</tbody></table></div>
  <details id="inventory-history" class="history-section"><summary>재고 수정 히스토리</summary><div class="admin-subtabs">${[['all','전체'],['stock','현판·이벤트'],['preorder_stock','예판']].map(([key,label])=>`<button class="tab-chip ${inventoryBucket===key?'active':''}" data-action="admin-inventory-filter" data-bucket="${key}">${label}</button>`).join('')}</div>${logs.length?`<div class="table-wrap"><table><thead><tr><th>시간</th><th>품목</th><th>구분</th><th>변동</th><th>사유</th><th>담당자</th></tr></thead><tbody>${logs.map(log=>`<tr><td>${stamp(log.created_at)}</td><td>${escape(log.product_name)}</td><td>${bucketLabel(log.bucket)}</td><td>${log.delta>0?'+':''}${log.delta}</td><td>${escape(log.reason)}</td><td>${escape(log.actor)}</td></tr>`).join('')}</tbody></table></div>`:'<p>기록이 없습니다.</p>'}</details>`;
}

function buyerOptions(selected='',placeholder='구매자 선택',query='') {
  const users=list('users').filter(u=>matchesSearch(query,u.name,u.phone));
  return `<option value="">${escape(placeholder)}</option>${users.map(u=>`<option value="${u.id}" ${String(selected)===String(u.id)?'selected':''}>${escape(u.name)}${u.phone?` · ${escape(u.phone)}`:''}</option>`).join('')}${!users.length?'<option value="" disabled>검색된 계정이 없습니다.</option>':''}`;
}

function manualPreorderMatches() {
  const reservations=matchingPreorders(staffSearch.pickup);
  return `<p class="search-count" role="status">검색 결과 ${reservations.length}건</p>${reservations.length?`<div class="preorder-matches">${reservations.map(r=>`<article class="preorder-match"><div><strong>${escape(r.name)}</strong><small>${escape(phoneLabel(r.phone))} · ${escape(preorderLabel(r.status))}</small><p>${escape(preorderMenu(r))}</p></div><button type="button" class="secondary-button" data-action="admin-preorder-select" data-id="${r.id}" aria-label="${escape(r.name)} 예약 확인">예약 확인</button></article>`).join('')}</div>`:`<p class="form-hint">${list('reservations').length?'검색 결과가 없습니다.':'등록된 예약이 없습니다.'}</p>`}`;
}

async function lookupManualPreorder(name,phone) {
  const version=++manualLookupVersion;
  manualReservation=null;
  document.querySelector('#manual-preorder-result')?.remove();
  try {
    const response=await helpers.api('/api/staff/preorders/lookup',{method:'POST',body:{name:String(name).trim(),phone:String(phone).trim()}});
    if(version!==manualLookupVersion||manualSaleType!=='preorder')return;
    manualReservation=response.reservation;
    manualPickupUser=String(list('users').find(u=>u.name===manualReservation.name)?.id||'');
    manualPickupMode=list('users').length?'existing':'new';
    staffSearch.users='';
    helpers.render();
    document.querySelector('#manual-preorder-result')?.scrollIntoView({block:'nearest'});
  } catch(error) {
    if(version===manualLookupVersion)throw error;
  }
}

function manualPickupAccount(reservation, order) {
  if (order?.user_id===null) return '<input type="hidden" name="guest" value="1"><p class="callout">비회원 수령 · 주사위 미지급</p>';
  if (order) {
    const name=order.customer_name || list('users').find(u=>u.id===order.user_id)?.name || reservation.name;
    return `<input type="hidden" name="user_id" value="${order.user_id}"><p class="callout">수령 계정: ${buyerIdentity(order.user_id,name)}<span>이미 접수한 계정에 주사위를 추가합니다.</span></p>`;
  }
  const guestButton=`<button class="tab-chip ${manualPickupMode==='guest'?'active':''}" data-action="admin-pickup-mode" data-mode="guest" type="button" aria-pressed="${manualPickupMode==='guest'}">계정 없이 수령</button>`;
  if(manualPickupMode==='guest')return `<div class="admin-subtabs">${guestButton}<button class="tab-chip" data-action="admin-pickup-mode" data-mode="existing" type="button" ${!list('users').length?'disabled':''}>기존 계정에 추가</button><button class="tab-chip" data-action="admin-pickup-mode" data-mode="new" type="button">새 계정 만들기</button></div><input type="hidden" name="guest" value="1"><p class="form-hint">예약자 이름으로 수령만 기록합니다. 계정 생성과 주사위 지급은 하지 않습니다.</p>`;
  const samePhone=list('users').some(u=>u.phone===reservation.phone);
  const existing=manualPickupMode!=='new'||samePhone;
  return `<div class="admin-subtabs" role="group" aria-label="예약 수령 계정">${guestButton}<button class="tab-chip ${existing?'active':''}" data-action="admin-pickup-mode" data-mode="existing" type="button" aria-pressed="${existing}" ${!list('users').length?'disabled':''}>기존 계정에 추가</button><button class="tab-chip ${!existing?'active':''}" data-action="admin-pickup-mode" data-mode="new" type="button" aria-pressed="${!existing}" ${samePhone?'disabled':''}>새 계정 만들기</button></div>
    ${existing?`${searchField('users','admin-pickup-user-search','기존 계정 검색','닉네임 · 전화번호 검색')}<div class="field"><label for="admin-pickup-user">수령할 구매자 계정</label><select id="admin-pickup-user" name="user_id" required>${buyerOptions(manualPickupUser,'수령 계정 선택',staffSearch.users)}</select><div class="selected-profile" data-selected-profile>${manualPickupUser?buyerIdentity(Number(manualPickupUser)):''}</div><p id="pickup-account-count" class="search-count" role="status">검색된 계정 ${list('users').filter(u=>matchesSearch(staffSearch.users,u.name,u.phone)).length}명</p><p class="form-hint">검색 후 수령 계정을 선택해 주세요. 주사위는 선택한 계정에 추가됩니다.</p></div>`:`<p class="form-hint">${escape(reservation.name)} 님의 예약 전화번호로 계정을 함께 만듭니다. 아래 비밀번호를 구매자에게 알려주세요.</p><div class="field"><label for="admin-pickup-pin">새 구매자 숫자 4자리 비밀번호</label><input id="admin-pickup-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" required autocomplete="new-password"></div>`}`;
}

function manualPreorderPage() {
  const r = manualReservation;
  let result = '';
  if (r) {
    const order = list('orders').find(o=>o.reservation_id===r.id&&o.status!=='cancelled') || r.order;
    const completed = order?.status==='approved' || r.status==='approved';
    result = `<div id="manual-preorder-result" class="reservation-result"><div class="order-top"><h2>${escape(r.name)} 님의 예약</h2><span class="status ${completed?'approved':'pending'}">${completed?'수령 완료':order?.status==='pending'?'수령 요청 접수됨':'수령 대기'}</span></div><div class="order-lines">${r.items.map(item=>`<div class="order-line"><span>${escape(item.name)} × ${item.quantity}</span><span>${won(item.price*item.quantity)}</span></div>`).join('')}</div><div class="basket-total"><span>예약 금액</span><strong>${won(r.total)}</strong></div>
    ${completed?`<p class="callout">이미 수령 완료한 예약입니다.${order?` 주문 #${order.id} · 수령 계정: ${escape(order.customer_name||list('users').find(u=>u.id===order.user_id)?.name||r.name)}`:''}</p>`:`<form id="admin-manual-preorder-complete"><p class="form-hint">예약된 품목을 전달한 뒤 승인해 주세요. ${order?.user_id===null||manualPickupMode==='guest'?'비회원 수령은 주사위를 지급하지 않습니다.':r.dice_quantity?`주사위 ${r.dice_quantity}개를 지급합니다.`:'우유·두유는 주사위를 지급하지 않습니다.'}</p>${manualPickupAccount(r,order)}<button class="primary-button full" type="submit">예약한 빵 전달 완료 · 승인</button></form>`}</div>`;
  }
  return `${help('예약 수령 처리 방법','이름·전화번호 일부·메뉴로 검색한 뒤 예약 확인을 누릅니다. 예약 내역 그대로 빵을 전달하고 계정 없이 수령하거나 수령 계정을 선택해 승인합니다. 이미 접수된 요청은 같은 주문으로 처리하며, 완료된 예약은 다시 지급하지 않습니다.')}<section class="content-card narrow">${searchField('pickup','admin-pickup-search','예약 검색','이름 · 전화번호 뒷자리 · 메뉴 검색')}<div id="manual-preorder-matches">${manualPreorderMatches()}</div>${result}</section>`;
}

function salesPage() {
  const intro = `${heading('수기판매','구매자가 직접 입력하기 어려울 때 사용합니다.')}<div class="admin-subtabs" role="group" aria-label="수기 판매 유형">${[['walkin','현장 구매'],['preorder','예약한 빵 수령']].map(([key,label])=>`<button class="tab-chip ${manualSaleType===key?'active':''}" data-action="admin-sale-type" data-type="${key}" aria-pressed="${manualSaleType===key}">${label}</button>`).join('')}</div>`;
  if (manualSaleType==='preorder') return intro+manualPreorderPage();
  return `${intro}${help('수기 판매 방법','입금과 빵 전달을 먼저 확인합니다. 계정 없이 판매는 이름과 수량만 입력합니다. 판매 완료를 누르면 즉시 승인됩니다. 기존 계정에 연결하거나 새 계정을 만들면 빵 개수만큼 주사위가 지급됩니다. 음료는 제외합니다.')}<section class="content-card narrow"><div class="admin-subtabs"><button class="tab-chip ${customerMode==='guest'?'active':''}" data-action="admin-customer-mode" data-mode="guest">계정 없이 판매</button><button class="tab-chip ${customerMode==='existing'?'active':''}" data-action="admin-customer-mode" data-mode="existing">기존 구매자</button><button class="tab-chip ${customerMode==='new'?'active':''}" data-action="admin-customer-mode" data-mode="new">새 구매자</button></div><form id="admin-manual-sale">
  ${customerMode==='guest'?`<input type="hidden" name="guest" value="1"><div class="field"><label for="admin-sale-name">구매자 이름</label><input id="admin-sale-name" name="name" maxlength="30" required autocomplete="off"></div><p class="form-hint">계정을 만들지 않고 주문만 기록합니다. 주사위는 지급하지 않습니다.</p>`:customerMode==='existing'?`<div class="field"><label for="admin-sale-user">구매자</label><select id="admin-sale-user" name="user_id" required>${buyerOptions()}</select><div class="selected-profile" data-selected-profile></div></div>`:`<div class="form-grid"><div class="field"><label for="admin-sale-name">구매자 이름</label><input id="admin-sale-name" name="name" maxlength="30" required autocomplete="off"></div><div class="field"><label for="admin-sale-phone">구매자 전화번호</label><input id="admin-sale-phone" name="phone" type="tel" inputmode="tel" placeholder="010-1234-5678" maxlength="13" pattern="010(?:[0-9]{8}|-[0-9]{4}-[0-9]{4})" data-phone-input required></div><div class="field"><label for="admin-sale-pin">숫자 4자리 비밀번호</label><input id="admin-sale-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" required autocomplete="new-password"></div></div>`}
  ${productList().map(p=>`<div class="qty-input"><label for="admin-sale-qty-${p.id}">${escape(p.name)}<small>${won(p.price)} · 재고 ${p.stock}</small></label><input id="admin-sale-qty-${p.id}" type="number" name="quantity_${p.id}" min="0" max="${Math.min(p.stock,100)}" step="1" value="0" data-sale-product="${p.id}" data-price="${p.price}" aria-label="${escape(p.name)} 구매 수량" ${p.stock<1?'disabled':''}></div>`).join('')}
  <div class="form-total"><span>총 금액</span><strong><span data-sale-total>0</span>원</strong></div><button class="primary-button full" type="submit">판매 완료</button></form></section>`;
}

const eventStatus = status => ({awaiting_choice:'음료 선택 중',pending:'지급 대기',approved:'지급 완료',cancelled:'취소'}[status]||status);
function eventCard(r){
  const pending=r.status==='pending',choosing=r.status==='awaiting_choice';
  return `<article class="pending-order event-request"><div class="pending-title"><h3>${buyerIdentity(r.user_id,r.customer_name)}<small>이벤트 #${r.id} · ${r.roll_id?'주사위 당첨':`${r.threshold}점 보상`}</small></h3><span class="status ${pending||choosing?'pending':escape(r.status)}">${escape(eventStatus(r.status))}</span></div><div class="order-line"><strong>${escape(r.product_name)}${choosing?'':' × 1'}</strong>${Number.isInteger(r.remaining_stock)?`<small class="order-stock-note">(남은 재고 ${number(r.remaining_stock)}개)</small>`:''}</div><p class="form-hint">${stamp(r.requested_at||r.created_at)}${choosing?' · 구매자가 음료를 선택하면 재고를 확보합니다.':pending?' · 물품이 확보되어 있습니다. 전달 후 승인해 주세요.':''}</p>${pending||choosing?`<div class="order-controls"><button class="secondary-button" data-action="admin-event-cancel" data-id="${r.id}">취소</button>${pending?`<button class="primary-button" data-action="admin-event-transition" data-mode="approve" data-id="${r.id}">${i('check')}전달 완료 · 승인</button>`:''}</div>`:''}</article>`;
}
function eventResults(){
  const rows=list('reward_requests').filter(r=>r.status===eventFilter&&matchesSearch(staffSearch.events,r.customer_name,r.product_name,`#${r.id}`));
  return `<p class="search-count" role="status">검색 결과 ${rows.length}건</p><div class="order-queue">${rows.length?rows.map(eventCard).join(''):empty('해당 지급 요청이 없습니다.','구매자의 이벤트 당첨과 음료 선택을 기다려 주세요.','spark')}</div>`;
}
function instagramPanel(){
  return `<section class="content-card narrow"><h2>인스타 인증</h2><p class="form-hint">등록 사용자를 선택하면 인싸 마법사의 주사위 1개를 지급합니다. 계정당 한 번만 인증할 수 있습니다.</p><form id="admin-instagram"><div class="field"><label for="admin-event-user">등록 사용자</label><select id="admin-event-user" name="user_id" required>${buyerOptions('','사용자 선택')}</select><div class="selected-profile" data-selected-profile></div></div><p class="callout">인싸 마법사의 주사위 1개 지급</p><button class="primary-button full" type="submit">인스타 이벤트 인증 완료</button></form></section><details id="instagram-history" class="history-section"><summary>인스타 이벤트 기록 · ${list('events').length}명</summary><div class="table-wrap"><table><thead><tr><th>시간</th><th>구매자</th><th>지급 주사위</th></tr></thead><tbody>${list('events').map(e=>`<tr><td>${stamp(e.created_at)}</td><td>${buyerIdentity(e.user_id,e.customer_name)}</td><td>${e.dice}개</td></tr>`).join('')}</tbody></table></div></details>`;
}
function badgeManagement(){
  const picture=badge=>helpers.badgePicture?.(badge)||'';
  return `<details id="admin-badge-management" class="badge-management"><summary>배지 추가·보유 현황</summary><div class="badge-management-content"><section class="content-card narrow"><h2>새 배지 추가</h2><form id="admin-badge-create"><div class="field"><label for="badge-name">배지 이름</label><input id="badge-name" name="name" maxlength="40" required></div><div class="field"><label for="badge-description">획득 방법 안내</label><input id="badge-description" name="description" maxlength="240" placeholder="OO하면 이 배지를 얻을 수 있어요." required></div><div class="field"><label for="badge-icon">배지 그림</label><select id="badge-icon" name="icon" required>${(helpers.badgeIcons||[]).map(([key,label])=>`<option value="${key}">${escape(label)}</option>`).join('')}</select></div><p class="form-hint">추가한 배지는 획득 조건을 확인한 담당자가 지급합니다.</p><button type="submit" class="primary-button full">배지 추가</button></form></section><div class="table-wrap"><table><thead><tr><th>사용자</th><th>보유 배지·획득 시각</th><th>착용 배지</th></tr></thead><tbody>${list('users').map(user=>`<tr><td>${buyerIdentity(user.id,user.name)}<br><small class="muted">${escape(user.phone||'')}</small></td><td>${(user.badges||[]).filter(b=>b.owned).map(b=>`<span class="badge-mini" title="${stamp(b.earned_at)}">${picture(b)}${escape(b.name)} <small>${stamp(b.earned_at)}</small></span>`).join('')||'없음'}</td><td>${escape(user.equipped_badge?.name||'없음')}</td></tr>`).join('')}</tbody></table></div></div></details>`;
}
function titleManagement(){
  return `<details id="admin-title-management" class="badge-management"><summary>칭호 추가·보유 현황</summary><div class="badge-management-content"><section class="content-card narrow"><h2>커스텀 칭호 추가</h2><form id="admin-title-create"><div class="field"><label for="title-name">칭호 이름</label><input id="title-name" name="name" maxlength="40" required></div><div class="field"><label for="title-description">칭호 획득 방법</label><input id="title-description" name="description" maxlength="240" placeholder="예: 30점 보상을 받고 담당자에게 요청" required></div><div class="field"><label for="title-style">칭호 스타일</label><select id="title-style" name="style" required>${(helpers.titleStyles||[]).map(([key,label])=>`<option value="${key}">${escape(label)}</option>`).join('')}</select></div><button type="submit" class="primary-button full">칭호 추가</button></form></section><div class="table-wrap"><table><thead><tr><th>사용자</th><th>보유 칭호·획득 시각</th><th>착용 칭호</th></tr></thead><tbody>${list('users').map(user=>`<tr><td>${buyerIdentity(user.id,user.name)}<br><small class="muted">${escape(user.phone||'')}</small></td><td>${(user.titles||[]).filter(t=>t.owned).map(t=>`<span class="badge-mini">${helpers.profileTitle?.({equipped_title:t})||escape(t.name)} <small>${stamp(t.earned_at)}</small></span>`).join('')||'없음'}</td><td>${escape(user.equipped_title?.name||'없음')}</td></tr>`).join('')}</tbody></table></div></div></details>`;
}
function manualGrantPanel(){
  const guest=grantRecipientMode==='guest',supplies=data().event_supplies||[];
  const giftOptions=[['oatmeal',`오트밀 미니바이트 · 재고 ${supplies.find(s=>s.key==='oatmeal')?.stock||0}`],
    ['milk',`우유 · 재고 ${productList().find(p=>p.id===112)?.stock||0}`],
    ['soymilk',`두유 · 재고 ${productList().find(p=>p.id===113)?.stock||0}`],
    ['sunglasses','멋진 선글라스 (프로필 소품)'],['custom','기타 상품 (직접 입력)']];
  const recipients=guest?`<input type="hidden" name="guest" value="1"><div class="field"><label for="grant-name">받는 사람 이름</label><input id="grant-name" name="name" maxlength="30" required value="${escape(grantDraft.name||'')}" autocomplete="off"></div>`:
    `<div class="field"><label for="grant-user">등록 사용자</label><select id="grant-user" name="user_id" required>${buyerOptions(grantDraft.user_id||'','사용자 선택')}</select><div class="selected-profile" data-selected-profile>${grantDraft.user_id?buyerIdentity(Number(grantDraft.user_id)):''}</div></div>`;
  let itemFields='';
  if(grantKind==='badge'){
    const buyer=list('users').find(u=>u.id===Number(grantDraft.user_id));
    itemFields=`<div class="field"><label for="grant-badge">지급할 배지</label><select id="grant-badge" name="badge_id" required><option value="">배지 선택</option>${list('badges').map(b=>{const owned=buyer?.badges?.some(own=>own.id===b.id&&own.owned);return `<option value="${escape(b.id)}" ${grantDraft.badge_id===b.id?'selected':''} ${owned?'disabled':''}>${escape(b.name)}${owned?' · 보유 중':''}</option>`;}).join('')}</select></div>`;
  }else if(grantKind==='title'){
    const buyer=list('users').find(u=>u.id===Number(grantDraft.user_id));
    itemFields=`<div class="field"><label for="grant-title">지급할 칭호</label><select id="grant-title" name="title_id" required><option value="">칭호 선택</option>${list('titles').map(t=>{const owned=buyer?.titles?.some(own=>own.id===t.id&&own.owned);return `<option value="${escape(t.id)}" ${grantDraft.title_id===t.id?'selected':''} ${owned?'disabled':''}>${escape(t.name)}${owned?' · 보유 중':''}</option>`;}).join('')}</select></div>`;
  }else if(grantKind==='score')itemFields=`<div class="field"><label for="grant-points">지급할 점수</label><input id="grant-points" name="points" type="number" min="1" max="10000" step="1" value="${escape(grantDraft.points||1)}" required></div>`;
  else{
    itemFields=grantKind==='bread'?`<div class="field"><label for="grant-product">지급할 빵</label><select id="grant-product" name="product_id" required><option value="">빵 선택</option>${productList().filter(p=>p.reward_eligible??(p.dice_per_unit!==0)).map(p=>`<option value="${p.id}" ${String(p.id)===grantDraft.product_id?'selected':''} ${p.stock<1?'disabled':''}>${escape(p.name)} · 재고 ${p.stock}${escape(p.unit||'개')}</option>`).join('')}</select></div>`:
      `<div class="field"><label for="grant-gift">지급할 상품</label><select id="grant-gift" name="gift" required>${giftOptions.map(([key,label])=>`<option value="${key}" ${key===grantGift?'selected':''} ${guest&&key==='sunglasses'?'disabled':''}>${escape(label)}</option>`).join('')}</select></div>${grantGift==='custom'?`<div class="field"><label for="grant-gift-name">상품 이름</label><input id="grant-gift-name" name="gift_name" maxlength="80" value="${escape(grantDraft.gift_name||'')}" required></div><p class="form-hint">기타 상품은 지급 기록만 남깁니다.</p>`:grantGift==='sunglasses'?'<p class="form-hint">선택한 계정에서 프로필 선글라스를 착용할 수 있게 됩니다.</p>':''}`;
    itemFields+=grantKind==='gift'&&grantGift==='sunglasses'?'<input type="hidden" name="quantity" value="1">':`<div class="field"><label for="grant-quantity">지급 수량</label><input id="grant-quantity" name="quantity" type="number" min="1" max="100" step="1" value="${escape(grantDraft.quantity||1)}" required></div>`;
  }
  const history=[...list('manual_grants'),...list('badge_grants').map(g=>({...g,kind:'badge',quantity:1})),...list('title_grants').map(g=>({...g,kind:'title',quantity:1}))].sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||''))).slice(0,300);
  return `${help('임의 지급 방법',['badge','title'].includes(grantKind)?'획득 조건을 확인한 뒤 배지·칭호를 지급합니다. 계정마다 한 번씩만 지급하며 착용은 사용자가 선택합니다.':'물품을 전달한 뒤 등록합니다. 빵·우유·두유·오트밀은 재고가 차감되고 점수는 계정에 즉시 추가됩니다. 기존 지급 대기 요청은 먼저 해당 요청에서 승인하거나 취소해 주세요. 임의 지급은 구매 주사위나 매출을 추가하지 않습니다.')}
    <section class="content-card narrow"><h2>임의 지급</h2>
    <div class="admin-subtabs" role="group" aria-label="임의 지급 대상">${[['account','등록 사용자'],['guest','계정 없이 지급']].map(([key,label])=>`<button class="tab-chip ${grantRecipientMode===key?'active':''}" data-action="admin-grant-recipient" data-mode="${key}" aria-pressed="${grantRecipientMode===key}">${label}</button>`).join('')}</div>
    <form id="admin-manual-grant">${recipients}
      <div class="admin-subtabs" role="group" aria-label="지급 항목">${[['bread','빵'],['gift','상품'],['score','점수'],['badge','배지'],['title','칭호']].map(([key,label])=>`<button type="button" class="tab-chip ${grantKind===key?'active':''}" data-action="admin-grant-kind" data-kind="${key}" aria-pressed="${grantKind===key}" ${guest&&['score','badge','title'].includes(key)?'disabled':''}>${label}</button>`).join('')}</div>
      ${guest?'<p class="form-hint">계정 없이 빵·실물 상품 지급만 기록합니다. 점수와 프로필 소품은 등록 계정이 필요합니다.</p>':''}${itemFields}
      <div class="field"><label for="grant-reason">지급 사유</label><input id="grant-reason" name="reason" maxlength="200" value="${escape(grantDraft.reason||'')}" placeholder="예: 이벤트 지급 오류 보완" required></div>
      <button class="primary-button full" type="submit">${grantKind==='score'?'점수 지급하기':grantKind==='badge'?'배지 지급하기':grantKind==='title'?'칭호 지급하기':'지급 완료로 기록'}</button>
    </form></section>${grantKind==='badge'?badgeManagement():grantKind==='title'?titleManagement():''}
    <section class="manual-grant-history"><h2>임의 지급 기록 · ${history.length}건</h2>${history.length?`<div class="table-wrap"><table><thead><tr><th>번호·시간</th><th>받는 사람</th><th>지급 내용</th><th>사유</th><th>담당자</th></tr></thead><tbody>${history.map(g=>`<tr><td>${g.kind==='badge'?'배지 ':g.kind==='title'?'칭호 ':''}#${g.id}<br>${stamp(g.created_at)}</td><td>${buyerIdentity(g.user_id,g.customer_name)}</td><td>${g.kind==='score'?`${number(g.points)}점`:['badge','title'].includes(g.kind)?`${g.kind==='badge'?'배지':'칭호'} · ${escape(g.item_name)}`:`${escape(g.item_name)} × ${number(g.quantity)}${escape(productList().find(p=>p.id===g.product_id)?.unit||'개')}`}</td><td>${escape(g.reason)}</td><td>${escape(g.staff_name)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="form-hint">아직 임의 지급 기록이 없습니다.</p>'}</section>`;
}
function eventsPage() {
  const history=list('rewards').filter(r=>!r.fulfillment);
  return `${heading('이벤트',eventTab==='manual'?'빵·상품·점수·배지·칭호 지급과 담당자 기록을 관리합니다.':'당첨 물품을 전달한 뒤 승인해 주세요.',`<button class="secondary-button" data-action="admin-refresh">새로고침</button>`)}<div class="admin-subtabs"><button class="tab-chip ${eventTab==='requests'?'active':''}" data-action="admin-event-tab" data-tab="requests">물품 지급</button><button class="tab-chip ${eventTab==='instagram'?'active':''}" data-action="admin-event-tab" data-tab="instagram">인스타 인증</button><button class="tab-chip ${eventTab==='manual'?'active':''}" data-action="admin-event-tab" data-tab="manual">임의 지급</button></div>${eventTab==='manual'?manualGrantPanel():eventTab==='instagram'?instagramPanel():`${help('이벤트 지급 방법','구매자가 당첨되면 물품 1개를 확보하고 지급 대기에 표시합니다. 우유 보상은 구매자가 우유·두유 중 재고 있는 품목을 선택한 뒤 접수됩니다. 전달 완료·승인은 재고를 추가 차감하지 않으며, 취소하면 확보했던 재고 1개가 돌아옵니다. 취소 후 재추첨은 하지 않습니다. 선글라스 등 디지털 보상은 자동 지급합니다.')}<div class="admin-subtabs">${[['pending','지급 대기'],['awaiting_choice','음료 선택 중'],['approved','지급 완료'],['cancelled','취소']].map(([key,label])=>`<button class="tab-chip ${eventFilter===key?'active':''}" data-action="admin-event-filter" data-filter="${key}">${label} ${list('reward_requests').filter(r=>r.status===key).length}</button>`).join('')}</div>${searchField('events','admin-event-search','이벤트 요청 검색','이름 · 물품 검색')}<div id="admin-event-results">${eventResults()}</div><details id="reward-history" class="history-section"><summary>이전·자동 지급 기록 · ${history.length}건</summary><div class="table-wrap"><table><thead><tr><th>시간</th><th>구매자</th><th>보상</th></tr></thead><tbody>${history.map(r=>`<tr><td>${stamp(r.created_at)}</td><td>${buyerIdentity(r.user_id,r.customer_name)}</td><td>${escape(r.product_name)}</td></tr>`).join('')}</tbody></table></div></details>`}`;
}

function scheduleDateLabel(value){
  const day=new Date(`${value}T00:00:00Z`);
  if(!Number.isFinite(day.getTime())||day.toISOString().slice(0,10)!==value)return value;
  return `${day.getUTCMonth()+1}/${day.getUTCDate()}(${new Intl.DateTimeFormat('ko-KR',{weekday:'short',timeZone:'UTC'}).format(day)})`;
}
function renderSchedule(){
  const rows=list('schedule'),dated=rows.filter(row=>/^\d{4}-\d{2}-\d{2}$/.test(row.event_date||''));
  const legacy=rows.filter(row=>!dated.includes(row));
  const dates=[...new Set(dated.map(row=>row.event_date))].sort();
  const slots=[...new Set(dated.map(row=>row.time))].sort((a,b)=>a==='오픈'?-1:b==='오픈'?1:a.localeCompare(b,'ko'));
  const cell=shift=>`<span class="schedule-assignees">${escape(shift.name)}</span>${shift.role?`<small class="muted">${escape(shift.role)}</small>`:''}`;
  const grid=dated.length?`<div class="table-wrap"><table class="schedule-table" aria-label="날짜별 담당 시간표"><thead><tr><th scope="col">시간</th>${dates.map(day=>`<th scope="col" title="${escape(day)}">${escape(scheduleDateLabel(day))}</th>`).join('')}</tr></thead><tbody>${slots.map(slot=>`<tr><th scope="row">${escape(slot)}</th>${dates.map(day=>`<td>${dated.filter(row=>row.event_date===day&&row.time===slot).map(cell).join('<br>')||'<span class="muted">—</span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
  const old=legacy.length?`${dated.length?'<h3>공통 시간표</h3>':''}<div class="table-wrap"><table aria-label="공통 담당 시간표"><thead><tr><th>담당자</th><th>시간</th><th>역할</th></tr></thead><tbody>${legacy.map(shift=>`<tr><td>${escape(shift.name)}</td><td>${escape(shift.time)}</td><td>${escape(shift.role)}</td></tr>`).join('')}</tbody></table></div>`:'';
  return `<section class="history-section staff-schedule"><div class="section-heading"><h2>담당 시간표</h2><span>교대할 때 메모도 함께 확인해요</span></div>${rows.length?grid+old:empty('등록된 시간표가 없어요','담당 시간표는 운영 서버에서 등록합니다.','calendar')}</section>`;
}

function notesPage() {
  return `${heading('인수인계', '메모와 담당 시간표를 확인합니다.', `<button class="primary-button" data-action="admin-memo">${i('plus')}인수인계 메모 작성</button>`)}${help('인수인계 방법','다음 담당자가 알아야 할 내용을 메모로 남기고 교대 전 담당 시간표를 확인합니다.')}${list('memos').length ? `<div class="memo-grid">${list('memos').map(memo => `<article class="memo-card"><p>${escape(memo.content)}</p><footer><span>${escape(memo.author)} 담당자</span><span>${stamp(memo.created_at)}</span></footer></article>`).join('')}</div>` : empty('첫 인수인계 메모를 남겨주세요', '재고 위치, 전달할 이야기, 다음 교대자가 알아야 할 내용을 적어주세요.', 'note')}${renderSchedule()}`;
}

function help(title,description) { return `<details id="help-${helpers.state.route}" class="screen-help"><summary>${title}</summary><p>${description}</p></details>`; }

export function renderAdmin() {
  if (!helpers.state.staffData) return '<div class="system-loading"><span class="spinner"></span>&nbsp; 판매 현황을 불러오고 있어요.</div>';
  return ({ queue: queuePage, inventory: inventoryPage, sales: salesPage, events: eventsPage, notes: notesPage }[helpers.state.route] || queuePage)();
}

function loginForm() {
  return `<h1>담당자 로그인</h1><form id="staff-login"><div class="field"><label for="admin-login-name">담당자 이름</label><input id="admin-login-name" name="name" maxlength="30" autocomplete="name" required></div><div class="field"><label for="admin-login-password">동아리 공용 비밀번호</label><input id="admin-login-password" type="password" name="password" autocomplete="current-password" required></div><button class="primary-button full" type="submit">로그인</button></form>`;
}

export function renderStaffLogin() {
  return `<div class="staff-login"><div class="content-card">${loginForm()}</div><div class="staff-login-footer"><a href="/">구매자 페이지로 돌아가기</a></div></div>`;
}

export function openStaffLogin() {
  helpers.modal(loginForm());
}

function adjustmentModal(productId, bucket = 'stock') {
  const chosenBucket = ['stock','preorder_stock'].includes(bucket) ? bucket : 'stock';
  helpers.modal(`<div class="auth-logo">${i('box')} INVENTORY NOTE</div><h2>재고 수량 수정</h2><p class="modal-description">추가 입고는 +, 차감은 −로 적어주세요.<br>이유와 담당자 이름이 함께 기록됩니다.</p><form id="admin-inventory"><div class="field"><label for="admin-adjust-product">품목</label><select id="admin-adjust-product" name="product_id">${productList().map(product => `<option value="${product.id}"${String(product.id) === String(productId) ? ' selected' : ''}>${escape(product.name)}</option>`).join('')}</select></div><div class="form-grid"><div class="field"><label for="admin-adjust-bucket">재고 구분</label><select id="admin-adjust-bucket" name="bucket">${[['stock','현판·이벤트'],['preorder_stock','예판']].map(([key,label]) => `<option value="${key}"${key === chosenBucket ? ' selected' : ''}>${label}</option>`).join('')}</select></div><div class="field"><label for="admin-adjust-delta">수정할 수량</label><input id="admin-adjust-delta" name="delta" type="number" min="-10000" max="10000" step="1" placeholder="예: 10 또는 -2" required></div></div><div class="field"><label for="admin-adjust-reason">수정 사유</label><input id="admin-adjust-reason" name="reason" maxlength="200" placeholder="예: 플레인 휘낭시에 추가 입고" required></div><button class="primary-button full" type="submit">${i('check')}재고에 반영하기</button></form>`);
}

function importModal() {
  helpers.modal(`<h2>예판 예약 등록</h2><p class="form-hint">예약 수량은 현판에서 예판 재고로 이동합니다.</p><form id="admin-preorder-import"><div class="form-grid"><div class="field"><label for="reservation-name">예약자 이름</label><input id="reservation-name" name="name" maxlength="30" required></div><div class="field"><label for="reservation-phone">전화번호</label><input id="reservation-phone" name="phone" type="tel" maxlength="13" pattern="010(?:[0-9]{8}|-[0-9]{4}-[0-9]{4})" data-phone-input required></div></div>${productList().map(p=>`<div class="qty-input"><label for="reservation-qty-${p.id}">${escape(p.name)}<small>현판 가능 ${p.stock}개</small></label><input id="reservation-qty-${p.id}" type="number" min="0" max="${Math.min(p.stock,100)}" value="0" step="1" data-reservation-product="${p.id}" aria-label="${escape(p.name)} 예약 수량"></div>`).join('')}<button class="primary-button full" type="submit">예판 등록</button></form>`,{wide:true});
}

function memoModal() {
  helpers.modal(`<div class="auth-logo">${i('note')} HANDOVER NOTE</div><h2>다음 담당자에게</h2><p class="modal-description">작지만 중요한 이야기를 남겨주세요.<br>작성자 ${escape(helpers.state.user?.name)}님의 이름으로 기록됩니다.</p><form id="admin-memo"><div class="field"><label for="admin-memo-content">인수인계 내용</label><textarea id="admin-memo-content" name="content" rows="6" maxlength="2000" placeholder="예: 추가 휘낭시에는 오른쪽 박스에 있어요. 예약 빵 봉투도 확인해 주세요." required></textarea></div><button class="primary-button full" type="submit">${i('note')}메모 남기기</button></form>`);
}

export async function handleAdminClick(action, element) {
  if(action==='admin-supply-adjust'){helpers.modal(`<h2>오트밀 미니바이트 재고 수정</h2><form id="admin-event-supply"><div class="field"><label for="supply-delta">수정할 수량</label><input id="supply-delta" name="delta" type="number" min="-10000" max="10000" required></div><div class="field"><label for="supply-reason">수정 사유</label><input id="supply-reason" name="reason" maxlength="200" required></div><button type="submit" class="primary-button full">재고에 반영하기</button></form>`);return true;}
  if (!action?.startsWith('admin-')) return false;
  const { state, api, refresh, render, closeModal, toast } = helpers;
  if (action === 'admin-route') { state.route = element.dataset.route; location.hash = state.route; render(); }
  else if(action==='admin-event-tab'){eventTab=element.dataset.tab;render();}
  else if(action==='admin-grant-recipient'){
    grantRecipientMode=element.dataset.mode==='guest'?'guest':'account';
    if(grantRecipientMode==='guest'){if(['score','badge','title'].includes(grantKind))grantKind='bread';if(grantGift==='sunglasses')grantGift='oatmeal';}
    render();
  }
  else if(action==='admin-grant-kind'){
    if(['bread','gift','score','badge','title'].includes(element.dataset.kind)&&!(grantRecipientMode==='guest'&&['score','badge','title'].includes(element.dataset.kind)))grantKind=element.dataset.kind;
    render();
  }
  else if(action==='admin-event-filter'){eventFilter=element.dataset.filter;render();}
  else if(action==='admin-event-cancel'){
    const row=list('reward_requests').find(r=>r.id===Number(element.dataset.id));if(!row)return true;
    helpers.modal(`<h2>이벤트 요청을 취소할까요?</h2><p>${escape(row.customer_name)} · ${escape(row.product_name)}</p><p class="form-hint">${row.status==='pending'?'확보한 재고 1개를 반환합니다.':'아직 재고를 확보하지 않은 요청입니다.'} 취소 후 다시 뽑지 않습니다.</p><button class="primary-button full" data-action="admin-event-transition" data-mode="cancel" data-id="${row.id}">지급 취소</button>`);
  }
  else if(action==='admin-event-transition'){
    element.disabled=true;
    try{await api(`/api/staff/reward-requests/${Number(element.dataset.id)}/${element.dataset.mode}`,{method:'POST',body:{}});closeModal();await refresh();render();toast(element.dataset.mode==='approve'?'이벤트 물품 전달을 승인했어요.':'지급을 취소하고 확보했던 재고를 반환했어요.');}
    catch(error){element.disabled=false;toast(error.message,'error');}
  }
  else if (action === 'admin-order-filter') { orderFilter = element.dataset.filter; render(); }
  else if (action === 'admin-inventory-filter') { inventoryBucket = element.dataset.bucket; render(); }
  else if (action === 'admin-sale-type') {
    const next = element.dataset.type === 'preorder' ? 'preorder' : 'walkin';
    if (next !== manualSaleType) { manualSaleType = next; manualReservation = null; manualLookupVersion++; render(); }
  }
  else if (action === 'admin-customer-mode') { customerMode = element.dataset.mode; render(); }
  else if (action === 'admin-pickup-mode') { manualPickupMode = ['guest','new'].includes(element.dataset.mode)?element.dataset.mode:'existing'; render(); }
  else if (action === 'admin-preorder-select') {
    const reservation=list('reservations').find(r=>r.id===Number(element.dataset.id));
    if(!reservation){toast('예약 목록을 새로고침해 주세요.','error');return true;}
    element.disabled=true;
    try { await lookupManualPreorder(reservation.name,reservation.phone); }
    catch(error) { toast(error.message||'예약을 확인하지 못했어요.','error'); }
    finally { element.disabled=false; }
  }
  else if (action === 'admin-adjust') adjustmentModal(element.dataset.product, element.dataset.bucket);
  else if (action === 'admin-import') importModal();
  else if (action === 'admin-memo') memoModal();
  else if (action === 'admin-cancel') {
    const order = list('orders').find(row => row.id === Number(element.dataset.id));
    if (!order) return true;
    helpers.modal(`<div class="auth-logo">${i('bag')} ORDER #${order.id}</div><h2>주문을 취소할까요?</h2><p class="confirm-detail">${escape(order.customer_name)}님의 ${typeLabel(order.type)} 주문입니다.<br>${(order.items || []).map(item => `${escape(item.name)} × ${item.quantity}`).join(' · ')}<br>총 ${won(order.total)}<br><br>확보한 품목 ${order.quantity}개가 원래 재고로 돌아갑니다.</p><form id="admin-cancel-confirm" data-order="${order.id}"><button class="primary-button full" type="submit">주문 취소 · 재고 복구</button></form>`);
  } else if (action === 'admin-approve') {
    element.disabled = true;
    try {
      const {order} = await api(`/api/staff/orders/${Number(element.dataset.id)}/approve`, { method: 'POST', body: {} });
      const dice = order.dice_quantity ?? order.quantity;
      const message = order.user_id===null ? '비회원 주문을 승인했어요.' : dice ? `승인했어요. 주사위 ${dice}개를 지급했습니다.` : '승인했어요. 우유·두유는 주사위를 지급하지 않아요.';
      try { await refresh(); }
      catch { toast(`${message} 최신 현황을 가져오지 못했으니 새로고침해 주세요.`, 'error'); return true; }
      render();
      toast(message);
    }
    catch (error) { toast(error.message || '승인하지 못했어요. 다시 확인해 주세요.', 'error'); element.disabled = false; }
  } else if (action === 'admin-refresh') {
    element.disabled = true;
    try { await refresh(); render(); toast('최신 판매 현황을 가져왔어요.'); }
    catch (error) { toast(error.message || '새로고침하지 못했어요.', 'error'); element.disabled = false; }
  } else return false;
  return true;
}

async function createAction(scope, path, body) {
  const key = JSON.stringify([scope, helpers.state.user?.id, body]);
  const requestId = pendingRequests.get(key) || helpers.requestId();
  pendingRequests.set(key, requestId);
  try {
    const result = await helpers.api(path, { method: 'POST', body: { ...body, request_id: requestId } });
    pendingRequests.delete(key);
    return result;
  } catch (error) {
    if (error.status >= 400 && error.status < 500) pendingRequests.delete(key);
    throw error;
  }
}

function formError(form, error) {
  let target = form.querySelector('[data-form-error]');
  if (!target) { target = document.createElement('div'); target.className = 'error-message callout danger-text'; target.dataset.formError = ''; target.setAttribute('role', 'alert'); form.prepend(target); }
  target.textContent = error.message || '처리하지 못했어요. 입력 내용을 확인해 주세요.';
  target.scrollIntoView({ block: 'nearest' });
}

export async function handleAdminSubmit(form) {
  const accepted = ['admin-title-create','admin-badge-create','admin-manual-grant','admin-event-supply','staff-login','admin-inventory','admin-manual-sale','admin-instagram','admin-memo','admin-preorder-import','admin-cancel-confirm','admin-manual-preorder-complete'];
  if (!accepted.includes(form.id)) return false;
  const { state, api, submitButton, refresh, render, toast, closeModal } = helpers;
  const values = new FormData(form);
  const label = form.querySelector('[type="submit"]')?.dataset.label || form.querySelector('[type="submit"]')?.innerHTML || '저장하기';
  form.querySelector('[data-form-error]')?.remove();
  submitButton(form, true);
  try {
    let message = '';
    if (form.id === 'staff-login') {
      const response = await api('/api/staff/login', { method: 'POST', body: { name: values.get('name'), password: values.get('password') } });
      localStorage.setItem('kambo.staff.token', response.token);
      state.token = response.token;
      state.user = response.user;
      state.route = 'queue';
      history.replaceState(null,'','#queue');
      message = `${response.user.name}님, 오늘도 잘 부탁드려요.`;
    } else if(form.id==='admin-title-create'){
      await createAction('title-create','/api/staff/titles',{name:values.get('name'),description:values.get('description'),style:values.get('style')});
      message='칭호와 획득 안내를 추가했어요.';
    } else if(form.id==='admin-badge-create'){
      await createAction('badge-create','/api/staff/badges',{name:values.get('name'),description:values.get('description'),icon:values.get('icon')});
      message='배지와 획득 안내를 추가했어요.';
    } else if(form.id==='admin-manual-grant'){
      const body={kind:grantKind,reason:values.get('reason')};
      if(values.has('guest')){body.guest=true;body.name=values.get('name');}
      else body.user_id=Number(values.get('user_id'));
      if(grantKind==='badge')body.badge_id=values.get('badge_id');
      else if(grantKind==='title')body.title_id=values.get('title_id');
      else if(grantKind==='score')body.points=Number(values.get('points'));
      else{
        body.quantity=Number(values.get('quantity'));
        if(grantKind==='bread')body.product_id=Number(values.get('product_id'));
        else{body.gift=values.get('gift');if(body.gift==='custom')body.gift_name=values.get('gift_name');}
      }
      const {grant}=grantKind==='badge'?await createAction('badge-grant','/api/staff/badge-grants',
        {user_id:body.user_id,badge_id:body.badge_id,reason:body.reason}):grantKind==='title'?await createAction('title-grant','/api/staff/title-grants',{user_id:body.user_id,title_id:body.title_id,reason:body.reason}):await createAction('manual-event-grant','/api/staff/manual-event-grants',body);
      grantDraft={};
      message=grantKind==='badge'?`배지 지급 #${grant.id} 기록을 남겼어요.`:grantKind==='title'?`칭호 지급 #${grant.id} 기록을 남겼어요.`:`임의 지급 #${grant.id} 기록을 남겼어요.`;
    } else if(form.id==='admin-event-supply'){
      await createAction('event-supply','/api/staff/event-supplies',{key:'oatmeal',delta:Number(values.get('delta')),reason:values.get('reason')});
      message='이벤트 물품 재고를 반영했어요.';
    } else if (form.id === 'admin-inventory') {
      await createAction('inventory', '/api/staff/inventory', { product_id: Number(values.get('product_id')), bucket: values.get('bucket'), delta: Number(values.get('delta')), reason: values.get('reason') });
      message = '재고와 수정 기록을 반영했어요.';
    } else if (form.id === 'admin-manual-sale') {
      const items = [...form.querySelectorAll('[data-sale-product]')].map(input => ({ product_id: Number(input.dataset.saleProduct), quantity: Number(input.value) })).filter(item => item.quantity > 0);
      if (!items.length) throw new Error('구매한 품목을 한 개 이상 입력해 주세요.');
      const body = { items };
      if (values.has('guest')) { body.guest = true; body.name = values.get('name'); }
      else if (values.has('user_id')) body.user_id = Number(values.get('user_id'));
      else { body.name = values.get('name'); body.phone = helpers.normalizePhone(values.get('phone')); body.pin = values.get('pin'); }
      const {order} = await createAction('manual-sale', '/api/staff/manual-sale', body);
      message = order.user_id===null ? `비회원 수기 판매 #${order.id}를 등록했어요.` : order.dice_quantity ? `수기 판매를 등록하고 주사위 ${order.dice_quantity}개를 지급했어요.` : '수기 판매를 등록했어요. 우유·두유는 주사위를 지급하지 않아요.';
    } else if (form.id === 'admin-manual-preorder-complete') {
      if (!manualReservation) throw new Error('예약을 검색하고 예약 확인을 먼저 눌러 주세요.');
      const reservation = manualReservation, version = manualLookupVersion;
      const body = {name:reservation.name,phone:reservation.phone};
      if (values.has('guest')) body.guest = true;
      else if (values.has('user_id')) body.user_id = Number(values.get('user_id'));
      else body.pin = values.get('pin');
      const response = await createAction('manual-preorder',`/api/staff/preorders/${reservation.id}/complete`,body);
      if (manualSaleType==='preorder' && version===manualLookupVersion && manualReservation?.id===reservation.id) manualReservation = response.reservation;
      message = response.already_completed ? '이미 수령 완료한 예약이에요.' : `예약 수령을 완료했어요.${response.order.dice_quantity?` 주사위 ${response.order.dice_quantity}개를 지급했어요.`:''}`;
    } else if (form.id === 'admin-instagram') {
      await createAction('instagram', '/api/staff/instagram', { user_id: Number(values.get('user_id')) });
      message = '인스타 이벤트를 인증하고 전용 주사위 1개를 지급했어요.';
    } else if (form.id === 'admin-memo') {
      await api('/api/staff/memos', { method: 'POST', body: { content: values.get('content') } });
      message = '다음 담당자를 위한 메모를 남겼어요.';
    } else if (form.id === 'admin-preorder-import') {
      const items=[...form.querySelectorAll('[data-reservation-product]')].map(input=>({product_id:Number(input.dataset.reservationProduct),quantity:Number(input.value)})).filter(item=>item.quantity>0);
      if(!items.length)throw new Error('예약할 빵을 1개 이상 입력해 주세요.');
      const reservations=[{name:values.get('name'),phone:values.get('phone'),items}];
      const response = await api('/api/staff/preorders/import', { method: 'POST', body: { reservations } });
      message = `예약 ${response.imported}건을 등록했어요. 예판 재고도 함께 반영되었습니다.`;
    } else if (form.id === 'admin-cancel-confirm') {
      await api(`/api/staff/orders/${Number(form.dataset.order)}/cancel`, { method: 'POST', body: {} });
      message = '주문을 취소하고 재고를 복구했어요.';
    }
    closeModal();
    form.reset();
    try {
      await refresh();
    } catch {
      render();
      toast(`${message} 최신 현황을 가져오지 못했으니 새로고침해 주세요.`, 'error');
      return true;
    }
    render();
    toast(message);
  } catch (error) {
    formError(form, error);
  } finally {
    if (form.isConnected) submitButton(form, false, label);
  }
  return true;
}
