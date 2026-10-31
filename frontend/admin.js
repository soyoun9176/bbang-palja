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

function stat(label, value, caption, icon, featured = false, unit = '') {
  return `<article class="stat-card${featured ? ' featured' : ''}"><div class="stat-label">${i(icon)}${label}</div><div class="stat-value">${value}${unit ? `<small>${unit}</small>` : ''}</div><div class="stat-caption">${caption}</div></article>`;
}

function stats() {
  const s = data().stats || {};
  return `<div class="admin-stats">${stat('승인 대기', number(s.pending_orders), '입금과 빵 전달을 확인해 주세요', 'clock', true, '건')}${stat('누적 판매 금액', helpers.money(Number(s.revenue || 0)), '승인된 주문 기준 · 예판 포함', 'shop', false, '원')}${stat('판매한 빵', number(s.bread_sold), `승인 완료 ${number(s.approved_orders)}건`, 'bread', false, '개')}${stat('이벤트 참여', number(list('events').length), `남은 우유 ${number(s.milk_stock)}개`, 'spark', false, '명')}</div>`;
}

function orderCard(order) {
  const pending = order.status === 'pending';
  return `<article class="pending-order"><div class="pending-title"><h3>${escape(order.customer_name)}<small>#${order.id} · ${typeLabel(order.type)}</small></h3><span class="status ${escape(order.status)}">${i(pending ? 'clock' : order.status === 'approved' ? 'check' : 'x')}${statusLabel(order.status)}</span></div><div class="order-lines">${(order.items || []).map(item => `<div class="order-line"><span>${escape(item.name)} <b>× ${item.quantity}</b></span><span>${won(item.price * item.quantity)}</span></div>`).join('')}</div><div class="order-bottom"><span>${stamp(order.created_at)} 접수 · 총 ${order.quantity}개</span><strong>${won(order.total)}</strong></div>${pending ? `<div class="order-controls"><button class="secondary-button" data-action="admin-cancel" data-id="${order.id}">${i('x')}취소</button><button class="primary-button" data-action="admin-approve" data-id="${order.id}">${i('check')}${order.type === 'preorder' ? '빵 전달 완료 · 승인' : '입금 · 빵 전달 확인 후 승인'}</button></div>` : ''}</article>`;
}

function queuePage() {
  const pending = pendingOrders();
  const filtered = list('orders').filter(order => orderFilter === 'all' || order.status === orderFilter);
  const memo = list('memos')[0];
  return `${heading('오늘도, 빵 좋은 하루', '반가운 주문이 도착했어요. 하나씩 확인하고 행복을 건네주세요.', `<button class="secondary-button" data-action="admin-refresh">${i('clock')}새로고침</button><button class="primary-button" data-action="admin-route" data-route="sales">${i('plus')}수기 판매 등록</button>`)}${stats()}<div class="admin-grid"><section><div class="section-heading"><h2>주문 알림 <span>${pending.length}</span></h2><span>새 주문이 자동으로 업데이트돼요</span></div><div class="admin-subtabs">${[['pending','확인 대기'],['approved','승인 완료'],['cancelled','취소'],['all','전체 주문']].map(([key,label]) => `<button class="tab-chip ${orderFilter === key ? 'active' : ''}" data-action="admin-order-filter" data-filter="${key}">${label}${key === 'pending' ? ` ${pending.length}` : ''}</button>`).join('')}</div>${filtered.length ? filtered.map(orderCard).join('') : empty(orderFilter === 'pending' ? '지금은 대기 중인 주문이 없어요' : '아직 주문 내역이 없어요', orderFilter === 'pending' ? '새로운 주문이 들어오면 여기에 표시됩니다.' : '선택한 상태의 주문이 생기면 여기에 모아드릴게요.', 'bag')}</section><aside><div class="side-panel"><h2>${i('box')}현판 판매 가능 재고</h2>${productList().map(product => `<div class="inventory-mini"><img src="/assets/${escape(product.image)}.svg" alt=""><strong>${escape(product.name)}</strong><span>${product.stock}<small> 개</small></span></div>`).join('')}<button class="text-button" data-action="admin-route" data-route="inventory">전체 재고와 수정 내역 보기 →</button></div><div class="side-panel"><h2>${i('note')}이전 담당자의 한마디</h2><p class="plain-text">${memo ? escape(memo.content) : '아직 인수인계 메모가 없어요. 다음 담당자를 위해 메모를 남겨주세요.'}</p>${memo ? `<p class="hint-badge">${escape(memo.author)} · ${stamp(memo.created_at)}</p>` : ''}<button class="text-button" data-action="admin-route" data-route="notes">메모와 담당 시간표 보기 →</button></div><div class="little-note">${i('info')}승인 시 구매한 빵 개수만큼 주사위가 지급돼요. 취소한 주문의 재고는 자동으로 돌아옵니다.</div></aside></div>`;
}

function heldStock(productId) {
  return pendingOrders().reduce((sum, order) => sum + (order.items || []).filter(item => item.product_id === productId).reduce((count, item) => count + item.quantity, 0), 0);
}

function inventoryPage() {
  const products = productList();
  const sum = key => products.reduce((count, product) => count + product[key], 0);
  const logs = list('inventory_logs').filter(log => inventoryBucket === 'all' || log.bucket === inventoryBucket);
  return `${heading('빵 창고를 한눈에', '판매 가능 수량부터 예약 빵까지, 함께 정확하게 관리해요.', `<button class="secondary-button" data-action="admin-import">${i('upload')}예판 명단 등록</button><button class="primary-button" data-action="admin-adjust">${i('edit')}재고 수정</button>`)}<div class="admin-stats">${stat('현판 판매 가능', number(sum('stock')), '접수된 주문 수량은 이미 제외돼요', 'shop', true, '개')}${stat('예판 수령 전', number(sum('preorder_stock')), '아직 수령 요청하지 않은 예약 빵', 'bag', false, '개')}${stat('접수 보관', number(pendingOrders().reduce((total, order) => total + order.quantity, 0)), '승인 전, 따로 보관할 빵 수량', 'clock', false, '개')}${stat('이벤트 빵', number(sum('reward_stock')), '랜덤 뽑기에서 지급 가능한 빵', 'spark', false, '개')}</div><div class="table-wrap"><table><thead><tr><th>빵 이름</th><th>판매가</th><th>현판 가능</th><th>예판 대기</th><th>이벤트</th><th>접수 보관</th><th>매장 예상</th><th></th></tr></thead><tbody>${products.map(product => { const held = heldStock(product.id); return `<tr><td><div class="table-product"><img src="/assets/${escape(product.image)}.svg" alt=""><strong>${escape(product.name)}</strong></div></td><td>${won(product.price)}</td><td><span class="stock-number">${product.stock}</span></td><td>${product.preorder_stock}</td><td>${product.reward_stock}</td><td>${held}</td><td><strong>${product.stock + product.preorder_stock + product.reward_stock + held}</strong></td><td><button class="secondary-button" data-action="admin-adjust" data-product="${product.id}">${i('edit')}수정</button></td></tr>`; }).join('')}</tbody></table></div><div class="little-note">${i('info')}매장 예상 = 현판 가능 + 예판 대기 + 이벤트 + 접수 보관. 승인 전 주문은 재고에서 먼저 빠지지만 실제 전달할 때까지 ‘접수 보관’에 포함됩니다.</div><section class="history-section"><div class="section-heading"><h2>재고 수정 히스토리</h2><button class="secondary-button" data-action="admin-adjust" data-bucket="milk">${i('milk')}우유 재고 수정 · ${number(data().stats?.milk_stock)}개</button></div><div class="admin-subtabs">${[['all','전체'],['stock','현판'],['preorder_stock','예판'],['reward_stock','이벤트 빵'],['milk','우유']].map(([key,label]) => `<button class="tab-chip ${inventoryBucket === key ? 'active' : ''}" data-action="admin-inventory-filter" data-bucket="${key}">${label}</button>`).join('')}</div>${logs.length ? `<div class="table-wrap"><table><thead><tr><th>시간</th><th>품목</th><th>구분</th><th>변동</th><th>사유</th><th>담당자</th></tr></thead><tbody>${logs.map(log => `<tr><td>${stamp(log.created_at)}</td><td><strong>${escape(log.product_name)}</strong></td><td><span class="table-badge">${bucketLabel(log.bucket)}</span></td><td class="${log.delta < 0 ? 'danger-text' : ''}"><strong>${log.delta > 0 ? '+' : ''}${log.delta}</strong></td><td>${escape(log.reason)}</td><td>${escape(log.actor)}</td></tr>`).join('')}</tbody></table></div>` : empty('아직 재고 변동이 없어요', '주문 접수, 취소, 재고 수정 내역이 여기에 남습니다.', 'clock')}</section>`;
}

function buyerOptions(selected = '') {
  return `<option value="">구매자를 선택해 주세요</option>${list('users').map(user => `<option value="${user.id}"${String(selected) === String(user.id) ? ' selected' : ''}>${escape(user.name)} · ${user.score}점 · 주사위 ${user.dice_balance}개</option>`).join('')}`;
}

function salesPage() {
  return `${heading('손으로 적어도, 빠짐없이', '직접 주문하기 어려운 구매자의 빵과 주사위를 대신 챙겨주세요.')}<div class="admin-grid"><section class="content-card"><div class="section-heading"><h2>수기 판매 등록</h2><span>입금과 빵 전달 후 등록</span></div><div class="admin-subtabs"><button class="tab-chip ${customerMode === 'existing' ? 'active' : ''}" data-action="admin-customer-mode" data-mode="existing">기존 구매자</button><button class="tab-chip ${customerMode === 'new' ? 'active' : ''}" data-action="admin-customer-mode" data-mode="new">이름으로 계정 등록</button></div><form id="admin-manual-sale">${customerMode === 'existing' ? `<div class="field"><label for="admin-sale-user">구매자</label><select id="admin-sale-user" name="user_id" required>${buyerOptions()}</select></div>` : `<div class="form-grid"><div class="field"><label for="admin-sale-name">구매자 이름</label><input id="admin-sale-name" name="name" maxlength="30" placeholder="실명을 입력해 주세요" required autocomplete="off"></div><div class="field"><label for="admin-sale-pin">구매자 비밀번호 4자리</label><input id="admin-sale-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" placeholder="숫자 네 자리" required autocomplete="new-password"></div></div><p class="form-hint">새 이름이면 계정이 생성됩니다. 같은 이름이 있으면 기존 비밀번호가 필요해요. 구매자에게 이름과 비밀번호를 꼭 알려주세요.</p>`}<div class="section-heading"><h2>구매한 빵</h2><span>현판 재고에서 차감됩니다</span></div>${productList().map(product => `<div class="qty-input"><label for="admin-sale-qty-${product.id}">${escape(product.name)} <small class="inline-tag">${won(product.price)} · 재고 ${product.stock}</small></label><input id="admin-sale-qty-${product.id}" type="number" name="quantity_${product.id}" min="0" max="${Math.min(product.stock, 100)}" step="1" value="0" data-sale-product="${product.id}" data-price="${product.price}" aria-label="${escape(product.name)} 구매 수량"${product.stock < 1 ? ' disabled' : ''}></div>`).join('')}<div class="form-total"><span>총 구매 금액</span><strong><span data-sale-total>0</span>원</strong></div><button class="primary-button full" type="submit">${i('check')}판매 완료 · 주사위 지급</button><p class="form-hint">등록 즉시 승인되며 빵 개수만큼 주사위가 지급됩니다. 입력 내용을 확인한 후 등록해 주세요.</p></form></section><aside><div class="side-panel"><h2>${i('info')}수기 판매는 이렇게</h2><p>1. 구매자의 계정을 선택하거나 새로 등록해요.<br>2. 실제 구매한 빵 수량을 입력해요.<br>3. 입금과 빵 전달을 확인해요.<br>4. 판매 완료를 누르면 재고와 주사위가 함께 반영돼요.</p></div><div class="side-panel"><h2>${i('upload')}예판 명단 준비</h2><p>판매 전에 이름, 전화번호, 예약 빵을 등록해 두세요. 예약 수량은 현판에서 예판으로 이동합니다.</p><button class="secondary-button full" data-action="admin-import">${i('upload')}예판 명단 등록하기</button></div></aside></div>`;
}

function eventsPage() {
  return `${heading('작은 이벤트, 더 큰 즐거움', '인스타그램 참여를 확인하고 우유와 보너스 주사위를 건네주세요.')}<div class="admin-grid"><section class="content-card"><div class="section-heading"><h2>인스타 이벤트 참여 등록</h2><span>한 사람당 한 번</span></div><form id="admin-instagram"><div class="field"><label for="admin-event-user">참여 구매자</label><select id="admin-event-user" name="user_id" required>${buyerOptions()}</select></div><div class="form-grid"><div class="field"><label for="admin-event-milk">지급할 우유</label><select id="admin-event-milk" name="milk_quantity">${[1,2,3,4,5].map(n => `<option value="${n}">${n}개</option>`).join('')}</select></div><div class="field"><label for="admin-event-dice">보너스 주사위</label><select id="admin-event-dice" name="dice">${[1,2,3,4,5,6,7,8,9,10].map(n => `<option value="${n}">${n}개</option>`).join('')}</select></div></div><button class="primary-button full" type="submit">${i('spark')}참여 확인 · 이벤트 지급</button><p class="form-hint">등록하면 우유 재고가 차감되고 주사위가 즉시 추가됩니다. 이미 참여한 구매자는 중복 등록할 수 없어요.</p></form></section><aside><div class="milk-card">${i('milk')} 나눌 수 있는 우유<br><b>${number(data().stats?.milk_stock)}</b> 개 남았어요</div><div class="side-panel" style="margin-top:17px"><h2>${i('heart')}참여 확인 체크</h2><p>게시물 또는 스토리와 계정을 확인한 후 등록해 주세요. 휴대폰 화면을 함께 확인하면 이름을 헷갈리지 않아요.</p></div></aside></div><section class="history-section"><h2>인스타 이벤트 기록 <span class="inline-tag">${list('events').length}명</span></h2>${list('events').length ? `<div class="table-wrap"><table><thead><tr><th>참여 시간</th><th>구매자</th><th>우유</th><th>보너스 주사위</th></tr></thead><tbody>${list('events').map(event => `<tr><td>${stamp(event.created_at)}</td><td><strong>${escape(event.customer_name)}</strong></td><td>${event.milk_quantity}개</td><td>+${event.dice}개</td></tr>`).join('')}</tbody></table></div>` : empty('첫 번째 참여자를 기다리고 있어요', '참여를 등록하면 우유 지급과 주사위 기록을 함께 볼 수 있어요.', 'spark')}</section><section class="history-section"><h2>랜덤 빵 당첨 기록</h2><p class="form-hint">구매자에게 당첨 화면을 확인하고 해당 빵을 전달해 주세요. 당첨 시 이벤트 재고는 이미 차감됩니다.</p>${list('rewards').length ? `<div class="table-wrap"><table><thead><tr><th>당첨 시간</th><th>구매자</th><th>당첨 빵</th><th>달성 점수</th></tr></thead><tbody>${list('rewards').map(reward => `<tr><td>${stamp(reward.created_at)}</td><td><strong>${escape(reward.customer_name)}</strong></td><td>${escape(reward.product_name)}</td><td>${reward.threshold}점</td></tr>`).join('')}</tbody></table></div>` : empty('아직 당첨된 빵이 없어요', '구매자가 목표 점수에 도달하고 빵을 뽑으면 여기에 표시됩니다.', 'bread')}</section>`;
}

function notesPage() {
  return `${heading('다음 손길에게 남기는 메모', '함께 일하는 우리가 놓치지 않도록, 작고 중요한 이야기를 남겨요.', `<button class="primary-button" data-action="admin-memo">${i('plus')}인수인계 메모 작성</button>`)}${list('memos').length ? `<div class="memo-grid">${list('memos').map(memo => `<article class="memo-card"><p>${escape(memo.content)}</p><footer><span>${escape(memo.author)} 담당자</span><span>${stamp(memo.created_at)}</span></footer></article>`).join('')}</div>` : empty('첫 인수인계 메모를 남겨주세요', '재고 위치, 전달할 이야기, 다음 교대자가 알아야 할 내용을 적어주세요.', 'note')}<section class="history-section"><div class="section-heading"><h2>오늘의 담당 시간표</h2><span>교대할 때 메모도 함께 확인해요</span></div>${list('schedule').length ? `<div class="table-wrap"><table><thead><tr><th>담당 팀</th><th>시간</th><th>역할</th></tr></thead><tbody>${list('schedule').map(shift => `<tr><td><div class="shift-name"><span class="avatar">${escape(shift.name.charAt(0))}</span><strong>${escape(shift.name)}</strong></div></td><td>${escape(shift.time)}</td><td>${escape(shift.role)}</td></tr>`).join('')}</tbody></table></div>` : empty('등록된 시간표가 없어요', '담당 시간표는 서버의 초기 설정에서 준비할 수 있어요.', 'calendar')}</section>`;
}

function guidePage() {
  const guides = [
    ['bag', '현장 주문 확인', '구매자가 주문을 접수하면 재고가 먼저 확보됩니다. 입금 금액과 구매한 빵을 확인하고 전달한 뒤 승인해 주세요. 승인하면 빵 개수만큼 주사위가 지급됩니다.'],
    ['clock', '예약 빵 전달', '미리 등록한 이름과 전화번호로 예약을 찾습니다. 수령 요청이 오면 예약 내역을 확인하고 빵을 건넨 뒤 승인해 주세요. 예판은 현판 재고와 따로 관리됩니다.'],
    ['x', '주문 취소', '확인 대기 중인 주문만 취소할 수 있습니다. 접수하며 확보했던 재고가 자동으로 복구됩니다. 이미 승인한 주문은 취소할 수 없으니 승인 전 꼭 확인해 주세요.'],
    ['edit', '재고 수정과 확인', '추가 입고는 양수, 파손·오입력 정정은 음수로 입력합니다. 수정 사유를 남기면 시간과 담당자가 함께 기록됩니다. 미수령 예약에 필요한 예판 수량은 줄일 수 없습니다.'],
    ['user', '수기 판매 등록', '구매자 선택 후 빵 수량을 입력합니다. 새 구매자는 이름과 네 자리 비밀번호로 등록할 수 있어요. 수기 판매는 즉시 승인되므로 입금과 빵 전달을 먼저 확인해 주세요.'],
    ['spark', '인스타와 랜덤 빵', '인스타 이벤트는 구매자당 한 번 참여할 수 있습니다. 우유와 보너스 주사위를 입력해 등록하세요. 랜덤 빵은 목표 점수마다 뽑을 수 있고 이벤트 재고 비율로 결정됩니다.'],
    ['upload', '예판 명단 등록', '이름·전화번호·빵 번호·수량이 담긴 JSON 배열을 붙여 넣습니다. 예약 수량은 현판에서 예판 재고로 이동해요. 같은 이름과 전화번호의 중복 예약은 등록되지 않습니다.'],
    ['note', '인수인계 메모', '다음 담당자가 알아야 할 특이사항과 재고 위치를 남겨주세요. 작성자의 이름과 시간이 자동으로 기록됩니다. 교대 전 메모와 담당 시간표를 함께 확인해 주세요.'],
  ];
  return `${heading('처음이어도, 차근차근', '판매부터 이벤트까지, 캄보딜라이트 담당자를 위한 작은 안내서.')}<div class="pickup-intro"><img src="/assets/salt-bread.svg" alt="소금빵 일러스트"><div><h2>확인하고, 건네고, 승인하기</h2><p>입금과 빵 전달을 모두 확인한 뒤 승인해 주세요.<br>구매자의 주사위와 재고 기록은 자동으로 챙겨드릴게요.</p></div></div><div class="guide-grid">${guides.map(([icon,title,description]) => `<article class="guide-card"><h3>${i(icon)} ${title}</h3><p>${description}</p></article>`).join('')}</div>`;
}

export function renderAdmin() {
  if (!helpers.state.staffData) return '<div class="system-loading"><span class="spinner"></span>&nbsp; 판매 현황을 불러오고 있어요.</div>';
  return ({ queue: queuePage, inventory: inventoryPage, sales: salesPage, events: eventsPage, notes: notesPage, guide: guidePage }[helpers.state.route] || queuePage)();
}

function loginForm() {
  return `<div class="auth-logo">${i('shield')} KAMBO DELIGHT · STAFF</div><h2>담당자 전용 공간</h2><p class="modal-description">동아리에서 공유한 비밀번호로 로그인하고<br>오늘의 빵과 주문을 함께 챙겨주세요.</p><form id="staff-login"><div class="field"><label for="admin-login-name">담당자 이름</label><input id="admin-login-name" name="name" maxlength="30" autocomplete="name" placeholder="메모와 기록에 남길 이름" required></div><div class="field"><label for="admin-login-password">동아리 공용 비밀번호</label><input id="admin-login-password" type="password" name="password" autocomplete="current-password" placeholder="담당자 비밀번호" required></div><button class="primary-button full" type="submit">${i('shield')}판매 대시보드 들어가기</button>${helpers.state.config?.demo ? `<p class="form-hint demo">로컬 데모 비밀번호: <strong>${escape(helpers.state.config.staff_password_hint || 'butter2026')}</strong><br>이름은 자유롭게 입력해 주세요.</p>` : ''}</form>`;
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

const importExample = [ { name: '홍길동', phone: '01012345678', items: [ { product_id: 1, quantity: 2 }, { product_id: 2, quantity: 1 } ] } ];

function importModal() {
  helpers.modal(`<div class="auth-logo">${i('upload')} PREORDER LIST</div><h2>예판 명단 등록</h2><p class="modal-description">예약 명단을 JSON 배열로 입력해 주세요.<br>등록한 수량은 현판에서 예판 재고로 이동합니다.</p><div class="form-hint">빵 번호: ${productList().map(product => `${product.id} ${escape(product.name)}`).join(' · ')}</div><form id="admin-preorder-import"><div class="field"><label for="admin-import-json">예약 명단 JSON</label><textarea id="admin-import-json" name="reservations" rows="10" placeholder="${escape(JSON.stringify(importExample, null, 2))}" required spellcheck="false"></textarea></div><div class="button-row"><button type="button" class="secondary-button" data-action="admin-import-example">예시 채우기</button><button class="primary-button" type="submit">${i('upload')}명단 등록</button></div><p class="form-hint">전화번호는 문자열로 입력해 주세요. 중복 예약이나 재고 부족이 있으면 전체 명단이 반영되지 않습니다.</p></form>`, { wide: true });
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
  else if (action === 'admin-import-example') { const field = document.querySelector('#admin-import-json'); if (field) field.value = JSON.stringify(importExample, null, 2); }
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
  const label = form.querySelector('[type="submit"]')?.textContent?.trim() || '저장하기';
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
      let reservations;
      try { reservations = JSON.parse(values.get('reservations')); } catch { throw new Error('JSON 형식을 확인해 주세요. 예시의 쉼표와 큰따옴표를 참고해 주세요.'); }
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
