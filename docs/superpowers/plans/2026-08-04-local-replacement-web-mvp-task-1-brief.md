### Task 1: Feature Gate And Phase 0 Tests

**Files:**
- Modify: `backend/platform_features.py`
- Create: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes: existing `platform_features.env_flag_enabled(name, env=None, default=False) -> bool`
- Produces: `platform_features.replacement_web_enabled(env=None) -> bool`

- [ ] **Step 1: Write failing tests for the feature gate and source declarations**

Add this test file:

```python
# tests/test_replacement_web_mvp.py
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class ReplacementWebFeatureGateTests(unittest.TestCase):
    def test_replacement_web_feature_gate_defaults_off_and_is_reversible(self):
        features = importlib.import_module("platform_features")

        self.assertFalse(features.replacement_web_enabled({}))
        self.assertFalse(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "0"})
        )
        self.assertTrue(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "1"})
        )
        self.assertTrue(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "true"})
        )
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebFeatureGateTests -v
```

Expected: FAIL because `replacement_web_enabled` does not exist.

- [ ] **Step 3: Add the feature gate**

In `backend/platform_features.py`, add:

```python
REPLACEMENT_WEB_ENABLED_ENV = "MATRIX_REPLACEMENT_WEB_ENABLED"
```

Near the other flag helpers, add:

```python
def replacement_web_enabled(env=None):
    return env_flag_enabled(REPLACEMENT_WEB_ENABLED_ENV, env=env)
```

- [ ] **Step 4: Run tests and verify feature gate passes**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebFeatureGateTests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Do not commit until `docs/IMPLEMENTATION.md` line numbers are current. When ready:

```bash
git add backend/platform_features.py tests/test_replacement_web_mvp.py
git commit -m "feat: gate local replacement web mvp"
```

---

