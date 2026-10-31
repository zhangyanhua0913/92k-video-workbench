"""Checkout newline changes must not masquerade as dependency upgrades."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/talking-edit/scripts'))
from auto_gold import dependencies


class GoldDependencyTests(unittest.TestCase):
    def fixture(self, root):
        dest=root/'deps/gold-motion-v1';dest.mkdir(parents=True)
        template=Path(__file__).resolve().parents[1]/'skills/talking-edit/templates/gold-motion'
        for name in ('package.json','package-lock.json'):
            (dest/name).write_bytes((template/name).read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
        cli=dest/'node_modules/@remotion/cli/remotion-cli.js';cli.parent.mkdir(parents=True);cli.touch()
        return dest

    def test_existing_crlf_cache_accepted_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=self.fixture(root);before=(dest/'package-lock.json').read_bytes()
            with patch.dict(os.environ,{'TALKING_EDIT_HOME':str(root)}),patch('registry.config',return_value={'node':'dummy-existing-node'}):
                self.assertEqual(dependencies(),dest)
            self.assertEqual((dest/'package-lock.json').read_bytes(),before)

    def test_real_dependency_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=self.fixture(root);(dest/'package.json').write_text('{}')
            with patch.dict(os.environ,{'TALKING_EDIT_HOME':str(root)}),patch('registry.config',return_value={'node':'dummy-existing-node'}):
                with self.assertRaises(ValueError):dependencies()


if __name__=='__main__':unittest.main()
