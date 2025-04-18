# ChunkedHttp200_OK_proxy
Python 3 HTTP proxy with keepalive, chunking and "200 OK" header IMMEDIATELY upon connect

I wrote this proxy to stand inbetween N8N LLM workflows (Embeddings step, specifically) due to n8n's reliance upon the Undici HTTP/HTTPS client's default "3e5" millisecond (300 second / 5 minute) timeout for HTTP requests. This timeout manifests itself as "Headers Timeout Error" or "Body Timeout Error" when trying to use locally-running embeddings.

Undici could change its default, n8n could override this default, or individual n8n workflow components could override it. But rather than waiting for any of those to occur, you can use this proxy to stand inbetween n8n Embedding components and any locally-running vectorstore (PostgreSQL/pgvectors, qdrant, etc.).

This has worked for me so far using HTTP - I haven't tried it with HTTPS yet, so I can't vouch for that part.

But using this proxy has gotten me past n8n's (Undici's) "Headers Timeout Error" / "Body Timeout Error" - enough to keep moving on my locally-running n8n LLM-based automation prototypes.

I hope it helps you, as well!

- KA9CQL
  Mike

P.S. A few included comments aren't useful anymore, and a portion of code is disabled using an "if False" condition. Leaving them in the code doesn't hurt things for now, and I figure I can clean them up later. (I've got other "squirrels" to chase down ATM.)
