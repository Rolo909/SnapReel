import sys
from unittest.mock import MagicMock

# Mock heavy dependencies so tests can run without them
sys.modules['llama_cpp'] = MagicMock()
sys.modules['edge_tts'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['diffusers'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()
