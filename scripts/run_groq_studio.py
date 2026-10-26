"""Explicitly enable local Groq narration; never alter Azure resources."""
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env', override=False)
    if not os.getenv('GROQ_API_KEY', '').strip():
        sys.exit('Add GROQ_API_KEY to the local .env before starting the model studio.')
    if os.getenv('DISABLE_PAID_MODELS', '').lower() == 'true':
        sys.exit('Model generation is disabled in this environment. Use a separate local environment.')
    os.environ['LLM_PROVIDER'] = 'groq'
    os.environ.pop('API_BASE_URL', None)
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, '-m', 'streamlit', 'run', 'src/ui/app.py',
                             '--server.address', '127.0.0.1', *sys.argv[1:]])
