"""Opt-in real Chromium acceptance. Set WORKBENCH_BROWSER_TEST=1; requires playwright + Chrome."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workspace_service import Workspace, Server


@unittest.skipUnless(os.environ.get('WORKBENCH_BROWSER_TEST') == '1', 'Opt-in browser acceptance')
class BrowserTests(unittest.TestCase):
    def test_four_modes_iframes_refresh_and_no_script_errors(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp)/'index'); server = Server(ws)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(channel='chrome', headless=True)
                    try:
                        page = browser.new_page(viewport={'width':1440,'height':1000})
                        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(server.origin+'/#session='+server.token)
                        page.get_by_text('这次想制作什么视频？', exact=True).wait_for()
                        for index, mode in enumerate(['talk','footage','generate','hybrid']):
                            if index: page.get_by_role('button', name='开始创作', exact=True).click()
                            page.get_by_role('button', name='创建项目', exact=True).nth(index).click()
                            page.get_by_label('项目标题', exact=True).fill('Browser-'+mode)
                            page.get_by_label('工程保存目录（绝对路径）', exact=True).fill(str(Path(tmp)/'projects'))
                            page.get_by_role('button', name='创建并进入', exact=True).click()
                            page.locator('#status').wait_for()
                            if mode == 'footage':
                                page.get_by_label('完整解说文案',exact=True).fill('Persistent narration')
                                page.get_by_role('button',name='保存方案',exact=True).click()
                                page.get_by_text('方案已保存。之前的审阅仅适用于旧版本。',exact=True).wait_for()
                            elif mode == 'generate':
                                frame=page.frame_locator('#editor')
                                frame.locator('#tabs button').first.wait_for()
                                self.assertIn('脚本与分镜', frame.locator('#tabs').inner_text())
                            else:
                                frame=page.frame_locator('#editor')
                                frame.get_by_text('导入本期素材',exact=True).wait_for()
                            page.reload()
                            page.get_by_role('button', name='我的项目', exact=True).click()
                            page.get_by_text('Browser-'+mode,exact=True).wait_for()
                        self.assertEqual(errors, [])
                        if os.environ.get('WORKBENCH_SCREENSHOT'): page.screenshot(path=os.environ['WORKBENCH_SCREENSHOT'],full_page=True)
                    finally: browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(); ws.close()


if __name__=='__main__': unittest.main()
