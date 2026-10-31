"""Opt-in real Chromium regression for the original V2 workflow and real adapters."""
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_service import Workspace,Server,ROOT


@unittest.skipUnless(os.environ.get('WORKBENCH_BROWSER_TEST')=='1','Opt-in browser acceptance')
class BrowserTests(unittest.TestCase):
    def test_four_original_step_sequences_save_and_resume(self):
        from playwright.sync_api import sync_playwright,expect
        baseline=(ROOT/'prototype/index.html').read_text(encoding='utf-8')
        sequences={mode:re.findall(r"'([^']*)'",steps) for mode,steps in re.findall(r"(\w+):\{name:.*?steps:\[(.*?)\]",baseline)}
        with tempfile.TemporaryDirectory() as tmp:
            ws=Workspace(Path(tmp)/'index');server=Server(ws)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(channel='chrome',headless=True)
                    try:
                        page=browser.new_page(viewport={'width':1440,'height':1000})
                        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(server.origin+'/#session='+server.token)
                        page.get_by_text('这一次，你想做哪种视频？',exact=True).wait_for()
                        names={'talk':'口播视频剪辑','footage':'素材解说成片','generate':'AI 视频生成','hybrid':'真人混搭成片'}
                        for mode,name in names.items():
                            page.get_by_role('button',name='开始'+name,exact=True).click()
                            page.get_by_label('项目标题',exact=True).fill('Browser-'+mode)
                            page.get_by_text('保存位置',exact=True).click()
                            page.get_by_label('工程保存目录（绝对路径）',exact=True).fill(str(Path(tmp)/'projects'))
                            page.get_by_role('button',name='创建并进入',exact=True).click()
                            page.locator('#steps').wait_for()
                            expect(page.locator('#steps button')).to_have_text([str(i+1)+'. '+s for i,s in enumerate(sequences[mode])])
                            self.assertFalse(page.get_by_role('button',name='恢复原项目（不重提任务）',exact=True).is_visible())
                            self.assertFalse(page.get_by_role('button',name='复制接续指令',exact=True).is_visible())
                            if mode in ('talk','hybrid'):
                                page.get_by_label('选择本地真人视频',exact=True).wait_for()
                                self.assertEqual(page.locator('#step-content input').first.get_attribute('type'),'file')
                                page.get_by_label('参考文稿（可选）',exact=True).fill('Persistent '+mode)
                            elif mode=='footage':page.get_by_label('完整解说文案',exact=True).fill('Persistent footage')
                            else:
                                frame=page.frame_locator('#editor')
                                frame.locator('#script-text').fill('Persistent generation')
                                frame.locator('body.hosted-editor').wait_for()
                                frame.locator('#add-shot').click()
                            page.get_by_role('button',name='查看下一步',exact=True).click()
                            expect(page.locator('#steps [aria-current=step]')).to_have_text('2. '+sequences[mode][1])
                            entry=next(x for x in ws.list() if x['title']=='Browser-'+mode)
                            state=ws.call(entry['id'],'show')['project']
                            self.assertTrue(state['script'].startswith('Persistent'))
                            for i in range(2,6):
                                page.get_by_role('button',name='查看下一步',exact=True).click()
                                expect(page.locator('#steps [aria-current=step]')).to_have_text(str(i+1)+'. '+sequences[mode][i])
                                if i==2 and mode=='generate':
                                    page.frame_locator('#editor').locator('body.hosted-editor').wait_for()
                                    page.frame_locator('#editor').get_by_label('音色 audioId（实际有效ID）',exact=True).fill('test-voice')
                                if i==3 and mode=='generate':
                                    page.frame_locator('#editor').locator('[data-model]').fill('test-model')
                                    page.frame_locator('#editor').locator('[data-limit=visual]').fill('1')
                                if i==4 and mode=='generate':
                                    state=ws.call(entry['id'],'show')['project']
                                    self.assertEqual(state['shots'][0]['voice']['audioId'],'test-voice')
                                    self.assertEqual(state['shots'][0]['model'],'test-model')
                                    self.assertEqual(state['shots'][0]['limits']['visual'],1)
                                if i==3 and mode=='footage':
                                    page.get_by_role('button',name='核验素材和旁白时长',exact=True).wait_for()
                            page.reload()
                            expect(page.locator('#steps [aria-current=step]')).to_have_text('6. '+sequences[mode][5])
                            self.assertEqual(ws.call(entry['id'],'show')['reviews'],[])
                            page.get_by_role('button',name='开始创作',exact=True).click()
                        self.assertEqual(errors,[])
                        if os.environ.get('WORKBENCH_SCREENSHOT'):page.screenshot(path=os.environ['WORKBENCH_SCREENSHOT'],full_page=True)
                    finally:browser.close()
            finally:server.shutdown();server.server_close();thread.join();ws.close()


if __name__=='__main__':unittest.main()
