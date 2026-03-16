"""
CPPA Pinecone Sync: upserts, updates, and deletes documents in Pinecone
on behalf of other apps. Other apps call sync_to_pinecone() with app_type (str),
namespace, and a preprocessing function; this app handles Pinecone I/O,
failure tracking (PineconeFailList), and sync status (PineconeSyncStatus).
"""
