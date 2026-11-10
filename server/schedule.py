"""Import private staff assignments without embedding event data in source code."""
from datetime import date
import re


def replace_dates(tx, rows):
    """Validate first, then replace only supplied dates in the caller's write lock."""
    if not isinstance(rows,list) or not 1<=len(rows)<=500:
        raise ValueError('시간표는 1~500칸으로 입력해 주세요.')
    prepared=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or not {'event_date','time','name'}<=set(row) or set(row)-{'event_date','time','name','role'}:
            raise ValueError('시간표는 event_date, time, name, 선택 항목 role만 입력해 주세요.')
        day=row['event_date']
        if not isinstance(day,str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) is None:
            raise ValueError('날짜는 YYYY-MM-DD 형식으로 입력해 주세요.')
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError('존재하지 않는 날짜입니다.') from None
        slot=row['time']
        if not isinstance(slot,str):
            raise ValueError('시간대를 입력해 주세요.')
        slot=slot.strip().replace('–','-').replace('—','-')
        if slot!='오픈':
            match=re.fullmatch(r'([0-2]\d):([0-5]\d)-([0-2]\d):([0-5]\d)',slot)
            if not match:
                raise ValueError('시간대는 오픈 또는 HH:MM-HH:MM 형식으로 입력해 주세요.')
            a,b,c,d=map(int,match.groups())
            if not (a<24 and c<=24 and (c<24 or d==0) and a*60+b<c*60+d):
                raise ValueError('시간 범위를 확인해 주세요.')
        name=row['name'];role=row.get('role','')
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:
            raise ValueError('담당자 명단은 1~120자로 입력해 주세요.')
        if not isinstance(role,str) or len(role.strip())>80:
            raise ValueError('역할은 80자 이내로 입력해 주세요.')
        if (day,slot) in seen:
            raise ValueError('같은 날짜·시간대는 한 칸에 모아서 입력해 주세요.')
        seen.add((day,slot))
        prepared.append((name.strip(),slot,role.strip(),day))
    days=sorted({row[3] for row in prepared})
    for day in days:
        tx.execute('DELETE FROM schedule WHERE event_date=?',(day,))
    for row in prepared:
        tx.insert('INSERT INTO schedule(name,time,role,event_date) VALUES(?,?,?,?)',row)
    return {'imported':len(prepared),'dates':days}
