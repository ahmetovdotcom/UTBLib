"""Authenticated catalog work; imports and technical-only saves are excluded."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, distinct, case
from .db import RecordActivity as Activity, Record, User

def comparable(marc):
    leader=marc['leader']
    # populate changes n to c on any save; ignore only that automatic status transition.
    if len(leader)>5 and leader[5] in ('n','c'): leader=leader[:5]+'n'+leader[6:]
    return {'leader':leader,'fields':[f for f in marc['fields'] if f['tag']!='005']}

def record_activity(s,user,record_id,marc,creating):
    title=' '.join(sf['value'] for f in marc['fields'] if f['tag']=='245' for sf in f.get('subfields',[]) if sf['code'] in ('a','b','n','p')) or 'Без заглавия'
    s.add(Activity(actor_id=user.id,actor_name=user.display_name,record_id=record_id,
                   action='created' if creating else 'updated',title=title))

def make_router(auth,db):
    router=APIRouter(prefix='/api/statistics',dependencies=[Depends(auth)])
    @router.get('/staff')
    def staff(date_from:date|None=None,date_to:date|None=None,user_id:int|None=None,
              action:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),s=Depends(db)):
        if date_from and date_to and date_from>date_to: raise HTTPException(422,'Начало периода позже окончания')
        if date_to==date.max: raise HTTPException(422,'Дата вне допустимого диапазона')
        if action not in (None,'created','updated'): raise HTTPException(422,'Неизвестное действие')
        conditions=[]
        tz=ZoneInfo('Asia/Almaty')
        if date_from: conditions.append(Activity.created_at>=datetime.combine(date_from,time.min,tz).astimezone(timezone.utc))
        if date_to: conditions.append(Activity.created_at<datetime.combine(date_to+timedelta(days=1),time.min,tz).astimezone(timezone.utc))
        counts=[func.count(distinct(case((Activity.action=='created',Activity.record_id)))).label('created'),
                func.count(distinct(case((Activity.action=='updated',Activity.record_id)))).label('updated'),
                func.count(distinct(Activity.record_id)).label('processed'),func.count(Activity.id).label('operations')]
        employees=[]
        for row in s.execute(select(Activity.actor_id,*counts).where(*conditions).group_by(Activity.actor_id)):
            employee=s.get(User,row.actor_id)
            employees.append({**dict(row._mapping),'name':employee.display_name,'deleted':employee.deleted})
        employees.sort(key=lambda x:(-x['processed'],x['name']))
        if user_id is not None: conditions.append(Activity.actor_id==user_id)
        summary=dict(s.execute(select(*counts).where(*conditions)).one()._mapping)
        if action: conditions.append(Activity.action==action)
        # One row per employee, record and action, even after multiple revisions.
        grouped=select(Activity.actor_id,Activity.record_id,Activity.action,func.max(Activity.id).label('last_id'),
                       func.count().label('operations')).where(*conditions).group_by(Activity.actor_id,Activity.record_id,Activity.action).subquery()
        total=s.scalar(select(func.count()).select_from(grouped))
        rows=[]
        query=select(Activity,grouped.c.operations,Record.id.label('existing')).join(grouped,Activity.id==grouped.c.last_id).outerjoin(Record,Record.id==Activity.record_id).order_by(Activity.created_at.desc(),Activity.id.desc()).offset(offset).limit(limit)
        for event,operations,existing in s.execute(query):
            stamp=event.created_at
            if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
            rows.append({'record_id':event.record_id,'actor_id':event.actor_id,'name':event.actor_name,'action':event.action,
                         'title':event.title,'at':stamp.isoformat(),'operations':operations,'exists':existing is not None})
        return {'summary':summary,'employees':employees,'rows':rows,'total':total}
    return router
