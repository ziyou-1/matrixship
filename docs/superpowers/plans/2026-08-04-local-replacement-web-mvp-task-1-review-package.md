# Task 1 Review Package

Base: 5e3c052
Head: working tree (no commit per user confirmation)

## Git Status
```
 M backend/platform_features.py
?? tests/test_replacement_web_mvp.py
```

## Diff
```diff
diff --git a/backend/platform_features.py b/backend/platform_features.py
index 9c5e3a9..74bdb9d 100644
--- a/backend/platform_features.py
+++ b/backend/platform_features.py
@@ -12,6 +12,7 @@ XHS_ENABLED_ENV = "MATRIX_XHS_ENABLED"
 VIDEO_REPLACEMENT_ENABLED_ENV = "MATRIX_VIDEO_REPLACEMENT_ENABLED"
 PENDING_PUBLISH_UI_ENABLED_ENV = "MATRIX_PENDING_PUBLISH_UI_ENABLED"
 DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV = "MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED"
+REPLACEMENT_WEB_ENABLED_ENV = "MATRIX_REPLACEMENT_WEB_ENABLED"
 _TRUTHY = {"1", "true", "yes", "on"}
 _XHS_ALIASES = {"xhs", "xiaohongshu", "rednote", "小红书"}
 
@@ -40,6 +41,10 @@ def digital_human_tts_upload_enabled(env=None):
     return env_flag_enabled(DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV, env=env)
 
 
+def replacement_web_enabled(env=None):
+    return env_flag_enabled(REPLACEMENT_WEB_ENABLED_ENV, env=env)
+
+
 def filter_xhs_capabilities(capabilities, env=None):
     values = list(capabilities or [])
     if xhs_enabled(env):
```

## New File: tests/test_replacement_web_mvp.py
```python
# tests/test_replacement_web_mvp.py
import importlib
from pathlib import Path
import sys
import unittest


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
