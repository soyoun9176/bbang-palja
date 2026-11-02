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
    if (path === '/api/config') return response({demo: false, reward_step: 7});
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

test('reaching the score target opens the bread draw without claiming it automatically', async () => {
  const f = fixture();
  await f.run('refresh()');
  f.run("state.config.reward_step=7; state.route='dice'");
  let prompt='';
  f.context.captureModal = html => {prompt=html;};
  f.run('modal = captureModal');
  f.context.fetchOverride = async (path, options) => {
    if(path==='/api/dice/roll') return f.response({value: 3, score: 8, dice_balance: 1});
    if(path==='/api/auth/me') return f.response({user:{id:1,name:'구매자1',role:'buyer',score:8,dice_balance:1,rewards_claimed:0}});
    return f.context.normalFetch(path, options);
  };
  await f.run('rollDice()');
  assert.match(prompt, /7점 달성/);
  assert.match(prompt, /data-action="claim-reward"/);
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
