"""Create a source release without local secrets, databases or development artifacts."""
from pathlib import Path
import hashlib
import tarfile

root=Path(__file__).resolve().parents[1]
target=root.parent/'library-catalog-server-2026-10-21.tar.gz'
allowed=['backend','frontend','data','deploy','compose.server.yaml','compose.yaml','compose.import.yaml',
         '.env.example','.env.marcsql.example','README.md','SERVER_DEPLOY.md','AUTH.md','KSU.md',
         'MARCSQL_IMPORT.md','MARCSQL_COPIES_IMPORT.md','ACQUISITIONS.md','STOCK_OPERATIONS.md','TECHNICAL.md','VERIFICATION.md']
def safe(info):
    parts=Path(info.name).parts
    if any(p in ('.git','node_modules','dist','__pycache__','.pytest_cache','.venv','backups') for p in parts):return None
    name=parts[-1]
    if name.startswith('.env') and not name.endswith('.example'):return None
    if name.endswith(('.dump','.db','.jsonl','.pyc')) or name in ('test-created.json','test-failure.png','.DS_Store'):return None
    info.uid=info.gid=0;info.uname=info.gname='';return info
with tarfile.open(target,'w:gz') as archive:
    for item in allowed:
        archive.add(root/item,arcname='library-catalog/'+item,filter=safe)
checksum=hashlib.sha256(target.read_bytes()).hexdigest()
target.with_name(target.name+'.sha256').write_text(checksum+'  '+target.name+'\n')
print(target)
