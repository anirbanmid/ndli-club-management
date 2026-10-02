import os
import sys

os.environ["NDLI_TESTING"] = "true"
_tests_dir = os.path.dirname(__file__)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
_root_dir = os.path.abspath(os.path.join(_tests_dir, ".."))
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
