"""Pin providers for offline tests so they never depend on the local .env.

Import this before any other ``scripts`` module in a test file.
"""

import os

os.environ["EMBED_PROVIDER"] = "azure"
os.environ["LLM_PROVIDER"] = "azure"
