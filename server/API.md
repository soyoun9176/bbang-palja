# API contract

All requests and responses use JSON. Send `Authorization: Bearer <token>` after login. Errors have `{ "error": "Korean explanation" }` and an appropriate 4xx/5xx status. Money is KRW integer. IDs are integers. Timestamps are UTC ISO strings. Requests that create orders, roll dice, grant Instagram bonuses, or claim rewards require a unique `request_id` string; retries with the same body and ID return the original result. An ID reused for different input returns 409.

## Public and buyer

- `GET /api/health` → `{ok:true,commit?}`. Deployed releases report their exact Git commit; local development omits `commit`.

- `GET /api/config` → `{demo, reward_step:10, staff_password_hint?}`. Password hint exists only in local demo.
- `POST /api/auth/register` or `/api/auth/login` body `{name,pin}` → `{token,user}`. PIN is exactly four numeric digits. Register rejects an existing name.
- `POST /api/staff/login` body `{name,password}` → `{token,user}`.
- `GET /api/auth/me` → `{user}`. `POST /api/auth/logout` → `{ok:true}`.
- `GET /api/products` → `{products:[{id,name,subtitle,price,stock,preorder_stock,reward_stock,category,image,unit}]}`.
- `GET /api/orders` → `{orders:[order]}` for current buyer.
- `POST /api/orders` body `{items:[{product_id,quantity}],request_id}` → `{order}`. Reserves walk-in stock immediately.
- `GET /api/preorders/lookup?name=김소연&phone=01012345678` → `{reservation:{id,name,phone,items,total,status}}`. Only the logged-in buyer's own name may be queried.
- `POST /api/preorders/:id/claim` body `{request_id}` → `{order}`. Requires that buyer's successful name/phone lookup within the last 24 hours. Existing claim returns its order, including across retries.
- `POST /api/dice/roll` body `{request_id}` → `{value,score,dice_balance}`. Die result is 1–6.
- `GET /api/leaderboard` → `{leaders:[entry],neighbors:[entry],me:entry,total_participants}`. `entry={rank,id,name,score,is_me}`. Leaders are top three; neighbors contain self and up to two users on each side.
- `POST /api/rewards/claim` body `{request_id}` → `{reward:{id,product_name,product_id,threshold,created_at},user}`. One bread for each 10 score points; weighted by the square of each available walk-in stock count (`stock² / Σstock²`). A win deducts one unit from `stock` in the same transaction as the draw. Pending-order stock and preorder stock are excluded.
  A successful claim increments `rewards_claimed` and earns `level=min(5,rewards_claimed)` in the same transaction. Score alone does not level up. Level caps at five (50 points), while bread continues every ten points thereafter. No available stock returns 409 without consuming a claim or advancing level. Previous reward records/counts remain intact; the next threshold is `(rewards_claimed+1)*10`.
- `GET /api/rewards` → `{rewards:[reward]}`.

`user={id,name,role,score,dice_balance,rewards_claimed,level}`. `order={id,type,status,customer_name,user_id,items,total,quantity,dice_quantity,created_at,approved_at,cancelled_at}`. Order types: `walkin`, `preorder`, `manual`. Status: `pending`, `approved`, `cancelled`. `items=[{product_id,name,quantity,price}]`.

`reward_stock` in product responses is a deprecated compatibility field fixed at zero after startup migration. Any old separate stock is moved to `stock` once, with inventory logs; staff writes to `reward_stock` are rejected.

The current menu and prices are documented in [docs/MENU.md](../docs/MENU.md). `name` is the actual product/flavor; `subtitle` is the alchemy concept. `unit` is `개` or `세트`. One donut set contains five donuts, costs 2,000 KRW, consumes one inventory unit, and grants one die upon approval.

## Staff

- `GET /api/staff/dashboard` → `{orders,products,stats:{revenue,approved_orders,pending_orders,bread_sold,milk_stock},users,inventory_logs,events,memos,schedule,rewards}`. Newest orders and logs first. Staff-only account list contains buyer users only. Rewards include `customer_name` for handing out event bread.
- `POST /api/staff/orders/:id/approve` or `/cancel` body `{}` → `{order}`. Repeated identical transition is a no-op; approved orders cannot cancel, cancelled orders cannot approve. Approval grants `dice_quantity` dice (bread units only; milk grants none). Cancellation restores reserved inventory exactly once.
- `POST /api/staff/inventory` body `{product_id,bucket,delta,reason,request_id?}` → `{products,milk_stock}`. Supplying `request_id` makes retries safe and rejects different input with the same ID. Use bucket `stock` (bread sales/rewards or milk sales/Instagram gifts) or `preorder_stock`. Milk is product 112. Legacy bucket `milk` remains an alias for product 112 `stock`; product_id is ignored for this alias. Delta must be nonzero integer. Result cannot be negative; unclaimed reservations' allocated bread cannot be removed from `preorder_stock`.
- `POST /api/staff/manual-sale` body `{user_id,items:[{product_id,quantity}],request_id}` → `{order,user}`. Instead of `user_id`, `{name,pin}` can create a buyer account for someone without a phone; an existing name requires that buyer's PIN. Immediate approval and inventory decrement. Dice are granted only for bread units.
- `POST /api/staff/preorders/lookup` body `{name,phone}` → `{reservation:{id,name,phone,items,total,status,dice_quantity,order}}`. Staff-only exact lookup; includes any linked pickup order. This does not grant a buyer's 24-hour claim authorization.
- `POST /api/staff/preorders/:id/complete` body `{name,phone,user_id,request_id}` → `{order,user,reservation,already_completed}`. Immediately completes the matching reservation using its original items/prices and reserved inventory. `user_id` must be a buyer with the reservation's name. Instead of `user_id`, provide `pin` to create the buyer account under that name; an existing account requires its matching PIN. An existing pickup request is approved without another inventory deduction. Repeated completion returns the same order without additional dice or stock changes. A linked order keeps its existing buyer. Account creation, stock, order, reservation and dice commit together.
- `POST /api/staff/instagram` body `{user_id,milk_quantity:1,dice:1,request_id}` → `{event,user,milk_stock}`. One certification per registered buyer. `milk_quantity` and `dice` default to 1; explicit 0 skips that benefit. Both may be 0 to record certification only. A skipped milk benefit never checks or changes milk stock. Inventory, selected dice, certification and retry identity are committed together.
- `POST /api/staff/memos` body `{content}` → `{memo}`.
- `POST /api/staff/preorders/import` body `{reservations:[{name,phone,items:[{product_id,quantity}]}]}` → `{imported:number}`. Atomic whole batch. A reservation's bread moves from walk-in `stock` into reserved `preorder_stock`. Duplicate name/phone is rejected.

Inventory log: `{id,product_id,product_name,bucket,delta,reason,actor,created_at}`. Event: `{id,user_id,customer_name,type,milk_quantity,dice,created_at}`. Memo: `{id,content,author,created_at}`. Schedule: `{id,name,time,role}`.

Demo buyer: `김소연 / 1234`, preorder telephone `01012345678`. Staff: any name and configured `STAFF_PASSWORD` (local default `butter2026`).

Products include `dice_per_unit` (1 for bread, 0 for milk) and `reward_eligible` (false for milk). `order.quantity` counts all purchased units; `order.dice_quantity` counts only bread units, including legacy bread order items. Milk costs 2,000 KRW and is excluded from random bread rewards. `stats.milk_stock` is a compatibility view of product 112 stock; `stats.bread_sold` excludes milk. Existing `settings.milk_stock` moves into product 112 once on startup and is then kept at zero.
