"""Owned titles and the one selected for public display."""

TITLE_STYLES=('magic','gold','lightning')


def catalog(tx):
    return tx.all("SELECT id,name,description,style,rule,threshold FROM titles "
                  "ORDER BY CASE WHEN rule='milestone' THEN 0 ELSE 1 END,threshold,created_at,id")


def award(tx,user_id,title_id,stamp,*,milestone_id=None,achievement_id=None,staff_id=None,reason):
    existing=tx.one('SELECT * FROM user_titles WHERE user_id=? AND title_id=?',(user_id,title_id))
    if existing:
        return existing
    source='milestone' if milestone_id is not None else 'achievement' if achievement_id is not None else 'manual'
    tx.execute('INSERT INTO user_titles(user_id,title_id,source,milestone_id,achievement_id,granted_by,reason,earned_at) '
               'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,title_id) DO NOTHING',
               (user_id,title_id,source,milestone_id,achievement_id,staff_id,reason,stamp))
    # First earned title is visible immediately. The VVIP gold title takes priority;
    # subsequent normal rewards preserve an existing selection and avatar draft.
    selected=tx.one('SELECT t.id,t.style FROM user_profiles p LEFT JOIN titles t ON t.id=p.title_id WHERE p.user_id=?',(user_id,))
    title=tx.one('SELECT style FROM titles WHERE id=?',(title_id,))
    if not selected or selected['style'] is None or title_id=='vvip' or (title['style']=='gold' and selected['style']!='gold'):
        tx.execute("INSERT INTO user_profiles(user_id,appearance,title_id,updated_at) VALUES(?,'',?,?) "
                   'ON CONFLICT(user_id) DO UPDATE SET title_id=excluded.title_id,updated_at=excluded.updated_at',
                   (user_id,title_id,stamp))
    return tx.one('SELECT * FROM user_titles WHERE user_id=? AND title_id=?',(user_id,title_id))


def award_milestone(tx,claim):
    for title in tx.all("SELECT id FROM titles WHERE rule='milestone' AND threshold=?",(claim['threshold'],)):
        award(tx,claim['user_id'],title['id'],claim['created_at'],milestone_id=claim['id'],reason=f"{claim['threshold']}점 보상 획득")


def profile_catalog(row):
    earned=row.get('earned_titles',{})
    return [{**title,'owned':title['id'] in earned,'earned_at':earned.get(title['id'],{}).get('earned_at')}
            for title in row.get('title_catalog',[])]


def equipped(row):
    selected=row.get('title_id')
    if selected not in row.get('earned_titles',{}):
        return None
    return next(({key:title[key] for key in ('id','name','style')}
                 for title in row.get('title_catalog',[]) if title['id']==selected),None)
