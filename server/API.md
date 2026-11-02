# API contract

All requests and responses use JSON. Send `Authorization: Bearer <token>` after login. Errors have `{ "error": "Korean explanation" }` and an appropriate 4xx/5xx status. Money is KRW integer. IDs are integers. Timestamps are UTC ISO strings. Requests that create orders, roll dice, grant Instagram bonuses, or claim rewards require a unique `request_id` string; retries with the same body and ID return the original result. An ID reused for different input returns 409.

## Public and buyer

- `GET /api/config` → `{demo, reward_step:7, staff_password_hint?}`. Password hint exists only in local demo.
- `POST /api/auth/register` or `/api/auth/login` body `{name,pin}` → `{token,user}`. PIN is exactly four numeric digits. Register rejects an existing name.
- `POST /api/staff/login` body `{name,password}` → `{token,user}`.
- `GET /api/auth/me` → `{user}`. `POST /api/auth/logout` → `{ok:true}`.
- `GET /api/products` → `{products:[{id,name,subtitle,price,stock,preorder_stock,reward_stock,category,image}]}`.
- `GET /api/orders` → `{orders:[order]}` for current buyer.
- `POST /api/orders` body `{items:[{product_id,quantity}],request_id}` → `{order}`. Reserves walk-in stock immediately.
- `GET /api/preorders/lookup?name=김소연&phone=01012345678` → `{reservation:{id,name,phone,items,total,status}}`. Only the logged-in buyer's own name may be queried.
- `POST /api/preorders/:id/claim` body `{request_id}` → `{order}`. Requires that buyer's successful name/phone lookup within the last 24 hours. Existing claim returns its order, including across retries.
- `POST /api/dice/roll` body `{request_id}` → `{value,score,dice_balance}`. Die result is 1–6.
- `GET /api/leaderboard` → `{leaders:[entry],neighbors:[entry],me:entry,total_participants}`. `entry={rank,id,name,score,is_me}`. Leaders are top three; neighbors contain self and up to two users on each side.
- `POST /api/rewards/claim` body `{request_id}` → `{reward:{id,product_name,product_id,threshold,created_at},user}`. One bread for each 7 score points; weighted by current reward inventory.
- `GET /api/rewards` → `{rewards:[reward]}`.

`user={id,name,role,score,dice_balance,rewards_claimed}`. `order={id,type,status,customer_name,user_id,items,total,quantity,created_at,approved_at,cancelled_at}`. Order types: `walkin`, `preorder`, `manual`. Status: `pending`, `approved`, `cancelled`. `items=[{product_id,name,quantity,price}]`.

## Staff

- `GET /api/staff/dashboard` → `{orders,products,stats:{revenue,approved_orders,pending_orders,bread_sold,milk_stock},users,inventory_logs,events,memos,schedule,rewards}`. Newest orders and logs first. Staff-only account list contains buyer users only. Rewards include `customer_name` for handing out event bread.
- `POST /api/staff/orders/:id/approve` or `/cancel` body `{}` → `{order}`. Repeated identical transition is a no-op; approved orders cannot cancel, cancelled orders cannot approve. Approval grants quantity dice. Cancellation restores reserved inventory exactly once.
- `POST /api/staff/inventory` body `{product_id,bucket,delta,reason,request_id?}` → `{products,milk_stock}`. Supplying `request_id` makes retries safe and rejects different input with the same ID. Bucket is `stock`, `preorder_stock`, `reward_stock`, or `milk`; milk ignores product_id. Delta must be nonzero integer. Result cannot be negative; unclaimed reservations' allocated bread cannot be removed from `preorder_stock`.
- `POST /api/staff/manual-sale` body `{user_id,items:[{product_id,quantity}],request_id}` → `{order,user}`. Instead of `user_id`, `{name,pin}` can create a buyer account for someone without a phone; an existing name requires that buyer's PIN. Immediate approval, inventory decrement, dice grant.
- `POST /api/staff/instagram` body `{user_id,milk_quantity:1,dice:1,request_id}` → `{event,user,milk_stock}`. Instagram bonus once per buyer.
- `POST /api/staff/memos` body `{content}` → `{memo}`.
- `POST /api/staff/preorders/import` body `{reservations:[{name,phone,items:[{product_id,quantity}]}]}` → `{imported:number}`. Atomic whole batch. A reservation's bread moves from walk-in `stock` into reserved `preorder_stock`. Duplicate name/phone is rejected.

Inventory log: `{id,product_id,product_name,bucket,delta,reason,actor,created_at}`. Event: `{id,user_id,customer_name,type,milk_quantity,dice,created_at}`. Memo: `{id,content,author,created_at}`. Schedule: `{id,name,time,role}`.

Demo buyer: `김소연 / 1234`, preorder telephone `01012345678`. Staff: any name and configured `STAFF_PASSWORD` (local default `butter2026`).
