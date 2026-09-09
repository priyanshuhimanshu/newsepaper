import os
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'app/news-storage-01-firebase-adminsdk-fbsvc-934ae7bccd.json'
from app.storage import init_firebase
from firebase_admin import firestore

init_firebase()
db = firestore.client()

# Check epapers collection
epapers = list(db.collection('epapers').limit(3).stream())
print("=== Epapers ===")
for e in epapers:
    d = e.to_dict()
    print(f"  {e.id} -> filename: {d.get('filename')}")

# Check if chunks exist
chunks = list(db.collection('pdf_chunks').limit(3).stream())
print(f"\n=== Pdf Chunks: {len(chunks)} found ===")
for c in chunks:
    d = c.to_dict()
    print(f"  {c.id} -> doc_id: {d.get('doc_id')}, chunk: {d.get('chunk_index')}, data len: {len(d.get('data', ''))}")
