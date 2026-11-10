"""The shared event board retains only its two newest notices, under the write lock."""


def publish(tx, kind, content, stamp, *, user_id=None, achievement_id=None, staff_id=None):
    notice_id = tx.insert(
        'INSERT INTO event_notices(kind,user_id,achievement_id,content,created_at,created_by) VALUES(?,?,?,?,?,?)',
        (kind, user_id, achievement_id, content, stamp, staff_id))
    # Sequence order remains reliable when timestamps tie or an older approval is reconciled.
    tx.execute('DELETE FROM event_notices WHERE id NOT IN (SELECT id FROM event_notices ORDER BY id DESC LIMIT 2)')
    return notice_id
