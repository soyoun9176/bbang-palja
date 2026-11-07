"""Badge definitions, earned ownership and profile-safe metadata."""

BADGE_ICONS = ('spark','flask','star','heart','bread','trophy')
STARTER_BADGES = (
    ('score_5','마법의 씨앗','5점 보상을 받으면 이 배지를 얻을 수 있어요.','spark',5),
    ('score_10','빛나는 연금술','10점 보상을 받으면 이 배지를 얻을 수 있어요.','flask',10),
)


def catalog(tx):
    return tx.all("SELECT id,name,description,icon,rule,threshold FROM badges "
                  "ORDER BY CASE WHEN rule='milestone' THEN 0 ELSE 1 END,threshold,created_at,id")


def award(tx,user_id,badge_id,stamp,*,milestone_id=None,achievement_id=None,staff_id=None,reason):
    source='milestone' if milestone_id is not None else 'achievement' if achievement_id is not None else 'manual'
    tx.execute('INSERT INTO user_badges(user_id,badge_id,source,milestone_id,achievement_id,granted_by,reason,earned_at) '
               'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,badge_id) DO NOTHING',
               (user_id,badge_id,source,milestone_id,achievement_id,staff_id,reason,stamp))
    return tx.one('SELECT * FROM user_badges WHERE user_id=? AND badge_id=?',(user_id,badge_id))


def award_milestone(tx,claim):
    for badge in tx.all("SELECT id FROM badges WHERE rule='milestone' AND threshold=?",(claim['threshold'],)):
        award(tx,claim['user_id'],badge['id'],claim['created_at'],milestone_id=claim['id'],
              reason=f"{claim['threshold']}점 보상 획득")


def initialize(tx,stamp):
    for badge_id,name,description,icon,threshold in STARTER_BADGES:
        tx.execute("INSERT INTO badges(id,name,description,icon,rule,threshold,created_at) VALUES(?,?,?,?,'milestone',?,?) "
                   'ON CONFLICT(id) DO NOTHING',(badge_id,name,description,icon,threshold,stamp))
    # Existing successful claims earn badges once, with their original timestamps.
    for claim in tx.all("SELECT m.id,m.user_id,m.threshold,m.created_at FROM milestone_claims m "
                        "JOIN users u ON u.id=m.user_id WHERE u.role='buyer'"):
        award_milestone(tx,claim)


def profile_catalog(row):
    earned=row.get('earned_badges',{})
    return [{**badge,'owned':badge['id'] in earned,
             'earned_at':earned.get(badge['id'],{}).get('earned_at')}
            for badge in row.get('badge_catalog',[])]


def equipped(row):
    selected=row.get('badge_id')
    if selected not in row.get('earned_badges',{}):
        return None
    return next(({key:badge[key] for key in ('id','name','icon')}
                 for badge in row.get('badge_catalog',[]) if badge['id']==selected),None)
