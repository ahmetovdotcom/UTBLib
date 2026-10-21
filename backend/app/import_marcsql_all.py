"""User-run two-stage import. Does not clear data or perform any SQL Server writes."""
import argparse
import sys
from .import_marcsql import main as catalogue
from .import_marcsql_copies import main as copies

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',required=True,help='Явно разрешить сохранение в локальном приложении')
    args=parser.parse_args()
    print('Этап 1/2: весь каталог. SQL Server используется только для SELECT.',flush=True)
    sys.argv=['import_marcsql','--apply','--limit','0','--report','/import/reimport-catalog.jsonl'];catalogue()
    print('Этап 2/2: экземпляры имеющегося фонда. Спорные строки попадут в отчёт.',flush=True)
    sys.argv=['import_marcsql_copies','--apply','--limit','0','--report','/import/reimport-copies.jsonl'];copies()
    print('Оба этапа завершены без ошибок. Проверьте итоговое количество и пропуски в отчёте.',flush=True)

if __name__=='__main__':main()
