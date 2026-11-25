import os
import tempfile

# Ensure all tests run with isolated temporary data dir inside workspace/temp
if "INTERVIEW_TOOL_DATA_DIR" not in os.environ:
    _test_dir = tempfile.mkdtemp(prefix="test_interview_data_")
    os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir
