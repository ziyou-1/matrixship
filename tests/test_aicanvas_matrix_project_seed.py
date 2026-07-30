from pathlib import Path
import ast
import copy
import datetime
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / ".tmp-aicanvas-server-current.py"


def load_create_project():
    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_create_local_comic_project_from_payload"
    )
    module = types.ModuleType("aicanvas_matrix_project_seed_under_test")
    projects = {}
    module.__dict__.update({
        "datetime": datetime,
        "copy": copy,
        "LOCAL_COMIC_PROJECTS": projects,
        "_take_local_comic_project_id": lambda: 321,
        "_get_request_account_scope": lambda: "user-44",
        "_save_local_comic_state": lambda: None,
    })
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER), "exec"), module.__dict__)
    return module


class AICanvasMatrixProjectSeedTest(unittest.TestCase):
    def test_matrix_project_accepts_exact_storyboards_without_auto_assets(self):
        module = load_create_project()
        payload = {
            "title": "matrix replacement",
            "source_mode": "matrix_video_replacement",
            "source_text": "three exact segments",
            "config": {"manualAssetsOnly": True, "storyboardCount": 3},
            "storyboards": [
                {"sequence": index, "description": "shot %d" % index, "audio_prompt": {"dialogue": {"text": "line %d" % index}}}
                for index in range(1, 4)
            ],
        }

        project = module._create_local_comic_project_from_payload(payload)

        self.assertEqual(project["source_mode"], "matrix_video_replacement")
        self.assertEqual([item["id"] for item in project["storyboards"]], [321001, 321002, 321003])
        self.assertEqual([item["sequence"] for item in project["storyboards"]], [1, 2, 3])
        self.assertEqual(project["storyboards"][1]["audio_prompt"]["dialogue"]["text"], "line 2")
        self.assertEqual(project["characters"], [])
        self.assertEqual(project["scenes"], [])
        self.assertEqual(project["props"], [])

    def test_regular_project_does_not_accept_external_storyboard_seed(self):
        module = load_create_project()

        project = module._create_local_comic_project_from_payload({
            "source_mode": "local_flow",
            "storyboards": [{"sequence": 1, "description": "untrusted seed"}],
        })

        self.assertEqual(project["storyboards"], [])


if __name__ == "__main__":
    unittest.main()
