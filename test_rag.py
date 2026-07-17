import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.abspath('.'), '.env'))

from rag import search, library_stats

print("Stats:", library_stats())
results = search('pulp capping success rate', limit=5)
print("Results found:", len(results))
for r in results:
    print(" -", r['pmid'], "sim:", r.get('similarity'))
