from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
class Strict(BaseModel): model_config=ConfigDict(extra='forbid')
class Policy(Strict):
    max_loans:int=Field(default=10,ge=1,le=500)
    scarce_max:int=Field(default=2,ge=1,le=10000)
    standard_max:int=Field(default=5,ge=2,le=100000)
    scarce_days:int=Field(default=3,ge=1,le=365)
    standard_days:int=Field(default=5,ge=1,le=365)
    abundant_days:int=Field(default=7,ge=1,le=365)
    manual_days:int=Field(default=30,ge=1,le=365)
    renewals_enabled:bool=True
    max_renewals:int=Field(default=1,ge=0,le=50)
    renewal_days:int=Field(default=14,ge=1,le=365)
    block_overdue:bool=True
    block_incidents:bool=True
    fine_per_day:Decimal=Field(default=Decimal('0'),ge=0,le=1000000,decimal_places=2)
    presumed_lost_days:int=Field(default=0,ge=0,le=3650)
    preparation_days:int=Field(default=1,ge=1,le=30)
    pickup_days:int=Field(default=1,ge=1,le=30)
    reservation_extensions:int=Field(default=1,ge=0,le=10)
    max_reservations:int=Field(default=3,ge=1,le=100)
    @model_validator(mode='after')
    def thresholds(self):
        if self.standard_max<=self.scarce_max: raise ValueError('Пороги должны возрастать')
        return self
class Operation(Strict):
    request_key:UUID
class IssueLine(Strict):
    copy_id:int=Field(gt=0)
    due_on:date|None=None
    reason:str=Field(default='',max_length=2000)
class IssueInput(Operation):
    reader_id:int=Field(gt=0)
    items:list[IssueLine]=Field(min_length=1,max_length=100)
    override:bool=False
    reason:str=Field(default='',max_length=2000)
class RenewInput(Operation):
    version:int=Field(ge=1)
    due_on:date|None=None
    override:bool=False
    reason:str=Field(default='',max_length=2000)
class ReturnInput(Operation):
    version:int=Field(ge=1)
    condition:Literal['unchanged','good','worn','minor','moderate','severe','irreparable','lost']='unchanged'
    incident:Literal['none','damaged','lost']='none'
    action:Literal['none','repair','replacement','write_off','return_to_fund','fine']='none'
    notes:str=Field(default='',max_length=2000)
    amount:Decimal=Field(default=Decimal('0'),ge=0,le=999999999,decimal_places=2)
    @model_validator(mode='after')
    def consistent(self):
        if (self.condition=='lost')!=(self.incident=='lost'):raise ValueError('Для утраты укажите состояние и инцидент «Утрата»')
        damage=self.condition in ('minor','moderate','severe','irreparable')
        if damage!=(self.incident=='damaged'):raise ValueError('Повреждение должно сопровождаться инцидентом')
        if self.incident!='none' and len(self.notes.strip())<5:raise ValueError('Опишите инцидент')
        if self.incident=='damaged' and self.action=='none':raise ValueError('Выберите предварительное действие')
        if self.condition in ('severe','irreparable') and self.action in ('fine','return_to_fund'):raise ValueError('Непригодную книгу нельзя вернуть в оборот')
        if self.incident=='none' and (self.amount or self.action!='none'):raise ValueError('Обычный возврат не содержит инцидента')
        return self
class ReserveInput(Operation):
    reader_id:int=Field(gt=0)
    record_id:int=Field(gt=0)
    branch_id:int|None=None
class ReservationAction(Operation):
    version:int=Field(ge=1)
    action:Literal['ready','cancel','extend','retry']
    reason:str=Field(default='',max_length=2000)
class FineAction(Operation):
    action:Literal['paid','waived']
    reason:str=Field(min_length=5,max_length=2000)
class IncidentAction(Operation):
    version:int=Field(ge=1)
    action:Literal['repaired','found','replacement','written_off','no_action']
    reason:str=Field(min_length=5,max_length=2000)
class CopySettings(Operation):
    version:int=Field(ge=1)
    branch_id:int|None=None
    condition:Literal['good','worn','minor','moderate','severe','irreparable']='good'
    operation_state:Literal['normal','repair','processing','transfer','display','reserve_stock']='normal'
    access:Literal['free','reading_room','limited']='free'
    defects:str=Field(default='',max_length=2000)
    reason:str=Field(min_length=5,max_length=2000)
class SettingsInput(Operation):
    version:int=Field(ge=0)
    policy:Policy
class ReaderLimits(Operation):
    max_loans:int|None=Field(default=None,ge=1,le=500)
    reason:str=Field(min_length=5,max_length=2000)

class AccountLink(Operation):
    user_id:int|None=Field(default=None,gt=0)
