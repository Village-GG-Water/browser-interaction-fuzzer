import unittest
import sys
import os

# Add the package directory to sys.path for testing if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from user_interaction_simulator.backend_loader import load_backend
from user_interaction_simulator.base import NullBackend

class TestBackendLoader(unittest.TestCase):
    def test_load_null(self):
        backend = load_backend("null")
        self.assertIsInstance(backend, NullBackend)
        self.assertFalse(backend.refresh_context())

    def test_auto_detect(self):
        # On non-linux systems, it should return NullBackend with a warning
        # On linux, it should return AtspiBackend (if dependencies are met) or NullBackend
        backend = load_backend()
        self.assertIsNotNone(backend)

if __name__ == '__main__':
    unittest.main()
