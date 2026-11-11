import importlib.util
from pathlib import Path
import sys
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("plugin", ROOT/"__init__.py", submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
sys.modules["plugin"] = module
spec.loader.exec_module(module)
from plugin import tools

class PluginTest(unittest.TestCase):
    def test_registration(self):
        class C:
            def __init__(self): self.registered=[]; self.skills=[]
            def register_tool(self,**kw): self.registered.append(kw)
            def register_skill(self,*a): self.skills.append(a)
        c=C();module.register(c)
        self.assertEqual([x["name"] for x in c.registered],["sauce_capture","sauce_render","sauce_inspect"])
        self.assertEqual(c.skills[0][0],"sauce-director")
    def test_rejects_private_urls_and_unsafe_actions(self):
        import os
        os.environ["SAUCE_ALLOWED_HOSTS"]="www.brimble.io"
        for url in ("http://www.brimble.io","https://localhost","file:///etc/passwd","https://x:pw@www.brimble.io"):
            with self.assertRaises(ValueError): tools._url(url)
        for actions in ([{"type":"script"}],[{"type":"click_link","selector":""}]):
            with self.assertRaises(ValueError): tools._check_actions(actions)
    def test_tool_errors_are_json(self):
        self.assertFalse(json.loads(tools.capture({"project":"../secrets","url":"https://www.brimble.io"}))["ok"])
        self.assertFalse(json.loads(tools.render({"run_id":"../secrets"}))["ok"])
if __name__=="__main__":unittest.main()
