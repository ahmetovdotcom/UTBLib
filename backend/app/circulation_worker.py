"""Local durable notices only; external email/SMS providers are not configured."""
import argparse,time
from .db import Session
from .circulation_service import sweep

def once():
    with Session() as s:
        try: print(sweep(s),flush=True)
        except Exception:
            s.rollback();print('Проверка книговыдачи не завершена; повтор через минуту.',flush=True)
            raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.once:once();return
    while True:
        try:once()
        except Exception:pass
        time.sleep(60)
if __name__=='__main__':main()
