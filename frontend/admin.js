let helpers;
let orderFilter = 'pending';
let inventoryBucket = 'all';
let customerMode = 'existing';
let inputListenerAdded = false;
const pendingRequests = new Map();

export function initAdmin(shared) {
  helpers = shared;
  if (!inputListenerAdded) {
    document.addEventListener('input', event => {
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
const bucketLabel = bucket => ({ stock: '현판', preorder_stock: '예판', reward_stock: '이벤트', milk: '우유' }[bucket] || bucket);
const pendingOrders = () => list('orders').filter(order => order.status === 'pending');

function heading(title, description, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="admin-actions">${actions}</div>` : ''}</div>`;
}

function empty(title, description, icon = 'box') {
  return `<div class="empty-state admin-empty">${i(icon)}<h2>${title}</h2><p>${description}</p></div>`;
}





function orderCard(order) {
  const pending = order.status === 'pending';
  return `<article class="pending-order"><div class="pending-title"><h3>${escape(order.customer_name)}<small>#${order.id} · ${typeLabel(order.type)}</small></h3><span class="status ${escape(order.status)}">${i(pending ? 'clock' : order.status === 'approved' ? 'check' : 'x')}${statusLabel(order.status)}</span></div><div class="order-lines">${(order.items || []).map(item => `<div class="order-line"><span>${escape(item.name)} <b>× ${item.quantity}</b></span><span>${won(item.price * item.quantity)}</span></div>`).join('')}</div><div class="order-bottom"><span>${stamp(order.created_at)} 접수 · 총 ${order.quantity}개</span><strong>${won(order.total)}</strong></div>${pending ? `<div class="order-controls"><button class="secondary-button" data-action="admin-cancel" data-id="${order.id}">${i('x')}취소</button><button class="primary-button" data-action="admin-approve" data-id="${order.id}">${i('check')}${order.type === 'preorder' ? '빵 전달 완료 · 승인' : '입금 · 빵 전달 확인 후 승인'}</button></div>` : ''}</article>`;
}

function queuePage() {
  const filtered=list('orders').filter(order=>orderFilter==='all'||order.status===orderFilter);
  return `${heading('주문 확인','이름·빵·입금 내역을 확인한 뒤 승인해 주세요.',`<button class="secondary-button" data-action="admin-refresh">새로고침</button>`)}
  ${help('주문 확인 방법','현판은 입금과 빵 전달을 확인한 뒤 승인합니다. 예판은 예약한 빵을 전달한 뒤 승인합니다. 승인하면 빵 개수만큼 주사위가 지급됩니다. 대기 주문을 취소하면 확보한 재고가 돌아옵니다.')}
  <div class="admin-subtabs">${[['pending','승인 대기'],['approved','승인 완료'],['cancelled','취소']].map(([key,label])=>`<button class="tab-chip ${orderFilter===key?'active':''}" data-action="admin-order-filter" data-filter="${key}">${label} ${list('orders').filter(o=>o.status===key).length}</button>`).join('')}</div>
  <div class="order-queue">${filtered.length?filtered.map(orderCard).join(''):empty('해당 주문이 없습니다.','새 주문은 자동으로 표시됩니다.','bag')}</div>`;
}

function heldStock(productId) {
  return pendingOrders().reduce((sum, order) => sum + (order.items || []).filter(item => item.product_id === productId).reduce((count, item) => count + item.quantity, 0), 0);
}

function inventoryPage() {
  const logs=list('inventory_logs').filter(log=>inventoryBucket==='all'||log.bucket===inventoryBucket);
  return `${heading('재고','판매·예약·이벤트 수량을 구분해서 관리합니다.',`<button class="secondary-button" data-action="admin-import">예판 등록</button><button class="primary-button" data-action="admin-adjust">재고 수정</button>`)}
  ${help('재고 보는 방법','현판 가능과 예판 대기는 아직 요청되지 않은 수량입니다. 요청된 빵은 접수 보관으로 이동합니다. 매장 예상은 현판·예판·이벤트·접수 보관의 합입니다. 추가 입고는 +, 차감은 −로 수정합니다.')}
  <div class="table-wrap"><table><thead><tr><th>빵</th><th>현판 가능</th><th>예판 대기</th><th>이벤트</th><th>접수 보관</th><th>매장 예상</th><th></th></tr></thead><tbody>${productList().map(p=>{
    const held=heldStock(p.id);
    return `<tr><td><strong>${escape(p.name)}</strong></td><td>${p.stock}</td><td>${p.preorder_stock}</td><td>${p.reward_stock}</td><td>${held}</td><td><strong>${p.stock+p.preorder_stock+p.reward_stock+held}</strong></td><td><button class="secondary-button" data-action="admin-adjust" data-product="${p.id}">수정</button></td></tr>`;
  }).join('')}</tbody></table></div>
  <div class="section-heading inventory-milk"><h2>우유 ${number(data().stats?.milk_stock)}개</h2><button class="secondary-button" data-action="admin-adjust" data-bucket="milk">우유 재고 수정</button></div>
  <details id="inventory-history" class="history-section"><summary>재고 수정 히스토리</summary><div class="admin-subtabs">${[['all','전체'],['stock','현판'],['preorder_stock','예판'],['reward_stock','이벤트 빵'],['milk','우유']].map(([key,label])=>`<button class="tab-chip ${inventoryBucket===key?'active':''}" data-action="admin-inventory-filter" data-bucket="${key}">${label}</button>`).join('')}</div>${logs.length?`<div class="table-wrap"><table><thead><tr><th>시간</th><th>품목</th><th>구분</th><th>변동</th><th>사유</th><th>담당자</th></tr></thead><tbody>${logs.map(log=>`<tr><td>${stamp(log.created_at)}</td><td>${escape(log.product_name)}</td><td>${bucketLabel(log.bucket)}</td><td>${log.delta>0?'+':''}${log.delta}</td><td>${escape(log.reason)}</td><td>${escape(log.actor)}</td></tr>`).join('')}</tbody></table></div>`:'<p>기록이 없습니다.</p>'}</details>`;
}

function buyerOptions(selected='') { return `<option value="">구매자 선택</option>${list('users').map(u=>`<option value="${u.id}" ${String(selected)===String(u.id)?'selected':''}>${escape(u.name)}</option>`).join('')}`; }

function salesPage() {
  return `${heading('수기 판매','구매자가 직접 입력하기 어려울 때 사용합니다.')}${help('수기 판매 방법','입금과 빵 전달을 먼저 확인합니다. 구매자와 수량을 입력한 뒤 판매 완료를 누르면 즉시 승인되고 주사위가 지급됩니다.')}<section class="content-card narrow"><div class="admin-subtabs"><button class="tab-chip ${customerMode==='existing'?'active':''}" data-action="admin-customer-mode" data-mode="existing">기존 구매자</button><button class="tab-chip ${customerMode==='new'?'active':''}" data-action="admin-customer-mode" data-mode="new">새 구매자</button></div><form id="admin-manual-sale">
  ${customerMode==='existing'?`<div class="field"><label for="admin-sale-user">구매자</label><select id="admin-sale-user" name="user_id" required>${buyerOptions()}</select></div>`:`<div class="form-grid"><div class="field"><label for="admin-sale-name">구매자 이름</label><input id="admin-sale-name" name="name" maxlength="30" required autocomplete="off"></div><div class="field"><label for="admin-sale-pin">숫자 4자리 비밀번호</label><input id="admin-sale-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" required autocomplete="new-password"></div></div>`}
  ${productList().map(p=>`<div class="qty-input"><label for="admin-sale-qty-${p.id}">${escape(p.name)}<small>${won(p.price)} · 재고 ${p.stock}</small></label><input id="admin-sale-qty-${p.id}" type="number" name="quantity_${p.id}" min="0" max="${Math.min(p.stock,100)}" step="1" value="0" data-sale-product="${p.id}" data-price="${p.price}" aria-label="${escape(p.name)} 구매 수량" ${p.stock<1?'disabled':''}></div>`).join('')}
  <div class="form-total"><span>총 금액</span><strong><span data-sale-total>0</span>원</strong></div><button class="primary-button full" type="submit">판매 완료 · 주사위 지급</button></form></section>`;
}

function eventsPage() {
  return `${heading('인스타 이벤트','참여를 확인하고 우유와 추가 주사위를 지급합니다.')}${help('인스타 이벤트 처리 방법','구매자를 선택하고 우유와 주사위 수량을 확인한 뒤 지급합니다. 한 사람당 한 번만 등록할 수 있습니다.')}<section class="content-card narrow"><h2>남은 우유 ${number(data().stats?.milk_stock)}개</h2><form id="admin-instagram"><div class="field"><label for="admin-event-user">구매자</label><select id="admin-event-user" name="user_id" required>${buyerOptions()}</select></div><div class="form-grid"><div class="field"><label for="admin-event-milk">지급할 우유</label><select id="admin-event-milk" name="milk_quantity">${[1,2,3,4,5].map(n=>`<option value="${n}">${n}개</option>`).join('')}</select></div><div class="field"><label for="admin-event-dice">추가 주사위</label><select id="admin-event-dice" name="dice">${[1,2,3,4,5,6,7,8,9,10].map(n=>`<option value="${n}">${n}개</option>`).join('')}</select></div></div><button class="primary-button full" type="submit">참여 확인 · 지급</button></form></section>
  <details id="instagram-history" class="history-section"><summary>인스타 이벤트 기록 · ${list('events').length}명</summary><div class="table-wrap"><table><thead><tr><th>시간</th><th>구매자</th><th>우유</th><th>추가 주사위</th></tr></thead><tbody>${list('events').map(e=>`<tr><td>${stamp(e.created_at)}</td><td>${escape(e.customer_name)}</td><td>${e.milk_quantity}</td><td>${e.dice}</td></tr>`).join('')}</tbody></table></div></details>
  <details id="reward-history" class="history-section"><summary>랜덤 빵 당첨 기록 · ${list('rewards').length}건</summary><p class="form-hint">당첨 화면을 확인하고 빵을 전달합니다. 이벤트 재고는 이미 차감됐습니다.</p><div class="table-wrap"><table><thead><tr><th>시간</th><th>구매자</th><th>빵</th><th>점수</th></tr></thead><tbody>${list('rewards').map(r=>`<tr><td>${stamp(r.created_at)}</td><td>${escape(r.customer_name)}</td><td>${escape(r.product_name)}</td><td>${r.threshold}</td></tr>`).join('')}</tbody></table></div></details>`;
}

function notesPage() {
  return `${heading('인수인계', '메모와 담당 시간표를 확인합니다.', `<button class="primary-button" data-action="admin-memo">${i('plus')}인수인계 메모 작성</button>`)}${help('인수인계 방법','다음 담당자가 알아야 할 내용을 메모로 남기고 교대 전 담당 시간표를 확인합니다.')}${list('memos').length ? `<div class="memo-grid">${list('memos').map(memo => `<article class="memo-card"><p>${escape(memo.content)}</p><footer><span>${escape(memo.author)} 담당자</span><span>${stamp(memo.created_at)}</span></footer></article>`).join('')}</div>` : empty('첫 인수인계 메모를 남겨주세요', '재고 위치, 전달할 이야기, 다음 교대자가 알아야 할 내용을 적어주세요.', 'note')}<section class="history-section"><div class="section-heading"><h2>오늘의 담당 시간표</h2><span>교대할 때 메모도 함께 확인해요</span></div>${list('schedule').length ? `<div class="table-wrap"><table><thead><tr><th>담당 팀</th><th>시간</th><th>역할</th></tr></thead><tbody>${list('schedule').map(shift => `<tr><td><div class="shift-name"><span class="avatar">${escape(shift.name.charAt(0))}</span><strong>${escape(shift.name)}</strong></div></td><td>${escape(shift.time)}</td><td>${escape(shift.role)}</td></tr>`).join('')}</tbody></table></div>` : empty('등록된 시간표가 없어요', '담당 시간표는 서버의 초기 설정에서 준비할 수 있어요.', 'calendar')}</section>`;
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
  const chosenBucket = ['stock','preorder_stock','reward_stock','milk'].includes(bucket) ? bucket : 'stock';
  helpers.modal(`<div class="auth-logo">${i('box')} INVENTORY NOTE</div><h2>재고 수량 수정</h2><p class="modal-description">추가 입고는 +, 차감은 −로 적어주세요.<br>이유와 담당자 이름이 함께 기록됩니다.</p><form id="admin-inventory"><div class="field"><label for="admin-adjust-product">품목</label><select id="admin-adjust-product" name="product_id">${productList().map(product => `<option value="${product.id}"${String(product.id) === String(productId) ? ' selected' : ''}>${escape(product.name)}</option>`).join('')}</select></div><div class="form-grid"><div class="field"><label for="admin-adjust-bucket">재고 구분</label><select id="admin-adjust-bucket" name="bucket">${[['stock','현판'],['preorder_stock','예판'],['reward_stock','이벤트 빵'],['milk','우유 (품목 선택 무관)']].map(([key,label]) => `<option value="${key}"${key === chosenBucket ? ' selected' : ''}>${label}</option>`).join('')}</select></div><div class="field"><label for="admin-adjust-delta">수정할 수량</label><input id="admin-adjust-delta" name="delta" type="number" min="-10000" max="10000" step="1" placeholder="예: 10 또는 -2" required></div></div><div class="field"><label for="admin-adjust-reason">수정 사유</label><input id="admin-adjust-reason" name="reason" maxlength="200" placeholder="예: 소금빵 추가 입고" required></div><button class="primary-button full" type="submit">${i('check')}재고에 반영하기</button></form>`);
}

function importModal() {
  helpers.modal(`<h2>예판 예약 등록</h2><p class="form-hint">예약 수량은 현판에서 예판 재고로 이동합니다.</p><form id="admin-preorder-import"><div class="form-grid"><div class="field"><label for="reservation-name">예약자 이름</label><input id="reservation-name" name="name" maxlength="30" required></div><div class="field"><label for="reservation-phone">전화번호</label><input id="reservation-phone" name="phone" type="tel" required></div></div>${productList().map(p=>`<div class="qty-input"><label for="reservation-qty-${p.id}">${escape(p.name)}<small>현판 가능 ${p.stock}개</small></label><input id="reservation-qty-${p.id}" type="number" min="0" max="${Math.min(p.stock,100)}" value="0" step="1" data-reservation-product="${p.id}" aria-label="${escape(p.name)} 예약 수량"></div>`).join('')}<button class="primary-button full" type="submit">예판 등록</button></form>`,{wide:true});
}

function memoModal() {
  helpers.modal(`<div class="auth-logo">${i('note')} HANDOVER NOTE</div><h2>다음 담당자에게</h2><p class="modal-description">작지만 중요한 이야기를 남겨주세요.<br>작성자 ${escape(helpers.state.user?.name)}님의 이름으로 기록됩니다.</p><form id="admin-memo"><div class="field"><label for="admin-memo-content">인수인계 내용</label><textarea id="admin-memo-content" name="content" rows="6" maxlength="2000" placeholder="예: 추가 소금빵은 오른쪽 박스에 있어요. 예약 빵 봉투도 확인해 주세요." required></textarea></div><button class="primary-button full" type="submit">${i('note')}메모 남기기</button></form>`);
}

export async function handleAdminClick(action, element) {
  if (!action?.startsWith('admin-')) return false;
  const { state, api, refresh, render, closeModal, toast } = helpers;
  if (action === 'admin-route') { state.route = element.dataset.route; location.hash = state.route; render(); }
  else if (action === 'admin-order-filter') { orderFilter = element.dataset.filter; render(); }
  else if (action === 'admin-inventory-filter') { inventoryBucket = element.dataset.bucket; render(); }
  else if (action === 'admin-customer-mode') { customerMode = element.dataset.mode; render(); }
  else if (action === 'admin-adjust') adjustmentModal(element.dataset.product, element.dataset.bucket);
  else if (action === 'admin-import') importModal();
  else if (action === 'admin-memo') memoModal();
  else if (action === 'admin-cancel') {
    const order = list('orders').find(row => row.id === Number(element.dataset.id));
    if (!order) return true;
    helpers.modal(`<div class="auth-logo">${i('bag')} ORDER #${order.id}</div><h2>주문을 취소할까요?</h2><p class="confirm-detail">${escape(order.customer_name)}님의 ${typeLabel(order.type)} 주문입니다.<br>${(order.items || []).map(item => `${escape(item.name)} × ${item.quantity}`).join(' · ')}<br>총 ${won(order.total)}<br><br>확보한 빵 ${order.quantity}개가 원래 재고로 돌아갑니다.</p><form id="admin-cancel-confirm" data-order="${order.id}"><button class="primary-button full" type="submit">주문 취소 · 재고 복구</button></form>`);
  } else if (action === 'admin-approve') {
    element.disabled = true;
    try {
      await api(`/api/staff/orders/${Number(element.dataset.id)}/approve`, { method: 'POST', body: {} });
      try { await refresh(); }
      catch { toast('승인하고 주사위를 지급했어요. 최신 현황을 가져오지 못했으니 새로고침해 주세요.', 'error'); return true; }
      render();
      toast('승인했어요. 구매자에게 주사위가 지급되었습니다.');
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
  const accepted = ['staff-login','admin-inventory','admin-manual-sale','admin-instagram','admin-memo','admin-preorder-import','admin-cancel-confirm'];
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
    } else if (form.id === 'admin-inventory') {
      await createAction('inventory', '/api/staff/inventory', { product_id: Number(values.get('product_id')), bucket: values.get('bucket'), delta: Number(values.get('delta')), reason: values.get('reason') });
      message = '재고와 수정 기록을 반영했어요.';
    } else if (form.id === 'admin-manual-sale') {
      const items = [...form.querySelectorAll('[data-sale-product]')].map(input => ({ product_id: Number(input.dataset.saleProduct), quantity: Number(input.value) })).filter(item => item.quantity > 0);
      if (!items.length) throw new Error('구매한 빵을 한 개 이상 입력해 주세요.');
      const body = { items };
      if (values.has('user_id')) body.user_id = Number(values.get('user_id'));
      else { body.name = values.get('name'); body.pin = values.get('pin'); }
      await createAction('manual-sale', '/api/staff/manual-sale', body);
      message = '수기 판매가 등록되고 주사위가 지급되었어요.';
    } else if (form.id === 'admin-instagram') {
      await createAction('instagram', '/api/staff/instagram', { user_id: Number(values.get('user_id')), milk_quantity: Number(values.get('milk_quantity')), dice: Number(values.get('dice')) });
      message = '인스타 참여를 기록하고 우유와 주사위를 지급했어요.';
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
