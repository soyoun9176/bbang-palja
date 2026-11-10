"""Purchase achievements: server-side approved totals and durable first-arrival awards."""
from datetime import datetime, timedelta, timezone

from .catalog import PRODUCTS, REWARD_PRODUCT_IDS
from .badges import award as award_badge
from .titles import award as award_title, award_milestone as award_milestone_title
from .notices import publish as publish_notice

KST=timezone(timedelta(hours=9))
BREADS={p[0]:p[1] for p in PRODUCTS if p[0] in REWARD_PRODUCT_IDS}
FINANCIERS=(101,102,103,104)
ACHIEVEMENT_BADGES=(
    ('ach_elements','원소 수집가','휘낭시에 4종을 모두 구매하면 이 배지를 얻을 수 있어요.','flask'),
    ('ach_vvip','캄딜 VVIP','빵 메뉴 11종을 모두 구매하면 이 배지를 얻을 수 있어요.','trophy'),
    ('ach_focus','빵 몰입가','한 가지 빵을 누적 5개 이상 구매하면 이 배지를 얻을 수 있어요.','bread'),
    ('ach_fast','번개 연금술사','예판 선착순 10명 또는 날짜별 현판 첫 구매자가 되면 이 배지를 얻을 수 있어요.','spark'),
)
TITLES=(
    ('score_15','멋쟁이 마법사','15점 보상을 받으면 얻을 수 있어요.','magic','milestone',15),
    ('score_30','대현자 연금술사','30점 보상을 받으면 얻을 수 있어요.','gold','milestone',30),
    ('elements','원소 수집가','휘낭시에 4종 모두 구매','magic','achievement',None),
    ('vvip','캄딜 VVIP','빵 메뉴 11종 모두 구매','gold','achievement',None),
    ('fast','⚡ 우사인볼트 연금술사','예판 선착순 10명 또는 날짜별 현판 첫 구매자','lightning','achievement',None),
)+tuple((f'focus_{pid}',f'{name} 몰입가',f'{name} 누적 5개 이상 구매','magic','achievement',None) for pid,name in BREADS.items())


def local_day(stamp):
    value=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(KST).date().isoformat()


def purchase_totals(tx,user_id=None):
    where=' AND o.user_id=?' if user_id is not None else ''
    rows=tx.all("SELECT o.user_id,i.product_id,SUM(i.quantity) AS quantity FROM orders o JOIN order_items i ON i.order_id=o.id "
                "WHERE o.status='approved' AND o.user_id IS NOT NULL"+where+' GROUP BY o.user_id,i.product_id',
                (user_id,) if user_id is not None else ())
    result={}
    for row in rows:
        if row['product_id'] in BREADS:
            result.setdefault(row['user_id'],{})[row['product_id']]=row['quantity']
    return result


def award(tx,user_id,key,scope,stamp,badge_id,title_id,*,order_id=None,reservation_id=None,exclusive_key=None,notify=True):
    existing=tx.one('SELECT id FROM user_achievements WHERE user_id=? AND achievement_key=? AND scope=?',(user_id,key,scope))
    tx.execute('INSERT INTO user_achievements(user_id,achievement_key,scope,exclusive_key,order_id,reservation_id,earned_at) '
               'VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
               (user_id,key,scope,exclusive_key,order_id,reservation_id,stamp))
    row=tx.one('SELECT * FROM user_achievements WHERE user_id=? AND achievement_key=? AND scope=?',(user_id,key,scope))
    if row is None:
        return  # A different account already holds this exclusive arrival award.
    reason={'elements':'휘낭시에 4종 구매','all_breads':'빵 11종 구매','focus':'같은 빵 5개 구매',
            'preorder_fast':'예판 선착순 10명','walkin_fast':f'{scope} 현판 첫 구매'}[key]
    award_badge(tx,user_id,badge_id,row['earned_at'],achievement_id=row['id'],reason=reason)
    award_title(tx,user_id,title_id,row['earned_at'],achievement_id=row['id'],reason=reason)
    if notify and existing is None:
        names={'elements':'원소 수집가','all_breads':'캄딜 VVIP','preorder_fast':'준비된 번개','walkin_fast':'오늘의 번개'}
        name=f'{BREADS[int(scope)]} 몰입가' if key=='focus' else names[key]
        publish_notice(tx,'achievement',f'{name} 도전과제를 달성했습니다!',stamp,
                       user_id=user_id,achievement_id=row['id'])


def reconcile(tx,stamp,*,notify=True):
    """Called under the global write lock after approval/cancel and on startup."""
    for user_id,counts in purchase_totals(tx).items():
        for pid,count in counts.items():
            if count>=5:
                award(tx,user_id,'focus',str(pid),stamp,'ach_focus',f'focus_{pid}',notify=notify)
        if all(counts.get(pid,0)>0 for pid in FINANCIERS):
            award(tx,user_id,'elements','',stamp,'ach_elements','elements',notify=notify)
        if all(counts.get(pid,0)>0 for pid in BREADS):
            award(tx,user_id,'all_breads','',stamp,'ach_vvip','vvip',notify=notify)
    # Import order is the original preorder application order. Rank distinct people,
    # including uncollected reservations; arrival/pickup order cannot steal a slot.
    phones=[]
    for reservation in tx.all('SELECT id,phone FROM reservations ORDER BY created_at,id'):
        if reservation['phone'] not in phones:
            phones.append(reservation['phone'])
        if phones.index(reservation['phone'])>=10:
            continue
        order=tx.one("SELECT id,user_id,approved_at FROM orders WHERE reservation_id=? AND status='approved' ORDER BY id LIMIT 1",(reservation['id'],))
        if order and order['user_id'] is not None:
            award(tx,order['user_id'],'preorder_fast','',order['approved_at'] or stamp,'ach_fast','fast',
                  order_id=order['id'],reservation_id=reservation['id'],exclusive_key='preorder:'+reservation['phone'],notify=notify)
    # First non-cancelled bread order per KST date. An earlier pending order blocks
    # later approvals; a guest order occupies the first spot but earns no account reward.
    days=set()
    arrivals=tx.all("SELECT o.id,o.user_id,o.status,o.created_at,o.approved_at FROM orders o WHERE o.type IN ('walkin','manual') "
                    "AND o.status!='cancelled' AND EXISTS(SELECT 1 FROM order_items i WHERE i.order_id=o.id AND i.product_id BETWEEN 101 AND 111) ORDER BY o.created_at,o.id")
    for order in arrivals:
        day=local_day(order['created_at'])
        if day in days:
            continue
        days.add(day)
        if order['status']=='approved' and order['user_id'] is not None:
            award(tx,order['user_id'],'walkin_fast',day,order['approved_at'] or stamp,'ach_fast','fast',
                  order_id=order['id'],exclusive_key='walkin:'+day,notify=notify)


def initialize(tx,stamp):
    for badge_id,name,description,icon in ACHIEVEMENT_BADGES:
        tx.execute("INSERT INTO badges(id,name,description,icon,rule,created_at) VALUES(?,?,?,?,'achievement',?) ON CONFLICT(id) DO NOTHING",
                   (badge_id,name,description,icon,stamp))
    for title_id,name,description,style,rule,threshold in TITLES:
        tx.execute('INSERT INTO titles(id,name,description,style,rule,threshold,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                   (title_id,name,description,style,rule,threshold,stamp))
    for claim in tx.all("SELECT m.* FROM milestone_claims m JOIN users u ON u.id=m.user_id WHERE u.role='buyer'"):
        award_milestone_title(tx,claim)
    # Historical backfills award ownership without broadcasting old achievements.
    reconcile(tx,stamp,notify=False)


def progress(counts,awards):
    """Private account progress; public ranking entries receive no purchase data."""
    owned={row['achievement_key'] for row in awards}
    focus=sorted(counts,key=lambda pid:(-counts[pid],pid))
    main=focus[0] if focus else next(iter(BREADS))
    focus_rewards=[{'name':f'{name} 몰입가','quantity':counts.get(pid,0),'owned':counts.get(pid,0)>=5} for pid,name in BREADS.items()]
    return [
        {'id':'elements','name':'원소 수집가','description':'휘낭시에 4종을 모두 구매해요.','current':sum(counts.get(pid,0)>0 for pid in FINANCIERS),'target':4,'unit':'종','completed':'elements' in owned,'badge_id':'ach_elements','title':'원소 수집가',
         'items':[{'name':BREADS[pid],'quantity':counts.get(pid,0)} for pid in FINANCIERS]},
        {'id':'all_breads','name':'캄딜 VVIP','description':'빵 메뉴 11종을 모두 구매해요.','current':len(counts),'target':len(BREADS),'unit':'종','completed':'all_breads' in owned,'badge_id':'ach_vvip','title':'캄딜 VVIP','style':'gold',
         'items':[{'name':name,'quantity':counts.get(pid,0)} for pid,name in BREADS.items()]},
        {'id':'focus','name':'한 가지 빵에 몰입!','description':'같은 빵을 누적 5개 이상 구매해요.','current':min(counts.get(main,0),5),'target':5,'unit':'개','completed':'focus' in owned,'badge_id':'ach_focus','title':f'{BREADS[main]} 몰입가','items':focus_rewards},
        {'id':'preorder_fast','name':'준비된 번개','description':'신청 순서 기준 예판 선착순 10명 · 수령 승인 후 달성','current':int('preorder_fast' in owned),'target':1,'unit':'회','completed':'preorder_fast' in owned,'badge_id':'ach_fast','title':'⚡ 우사인볼트 연금술사','style':'lightning'},
        {'id':'walkin_fast','name':'오늘의 번개','description':'날짜별 첫 현장 빵 주문 · 구매 승인 후 달성','current':int('walkin_fast' in owned),'target':1,'unit':'회','completed':'walkin_fast' in owned,'badge_id':'ach_fast','title':'⚡ 우사인볼트 연금술사','style':'lightning',
         'dates':[row['scope'] for row in awards if row['achievement_key']=='walkin_fast']},
    ]
