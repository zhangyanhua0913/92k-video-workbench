"""Integration tests against disposable local Git remotes, never GitHub."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import publish as publisher
from versioning import git, update, session, state_dir


class GitUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.remote=self.base/'remote.git';self.author=self.base/'author';self.user=self.base/'user'
        subprocess.run(['git','init','--bare','--initial-branch=main',str(self.remote)],check=True,capture_output=True)
        subprocess.run(['git','clone',str(self.remote),str(self.author)],check=True,capture_output=True)
        self.identity(self.author)
        self.write(self.author,'VERSION','0.1.0-prototype.1\n')
        self.write(self.author,'README.md','first\n');self.write(self.author,'scripts/tool.py','print(1)\n')
        self.commit(self.author);git(self.author,'push','origin','main')
        subprocess.run(['git','clone',str(self.remote),str(self.user)],check=True,capture_output=True)
        self.identity(self.user)

    def tearDown(self):self.tmp.cleanup()
    def identity(self,repo):
        git(repo,'config','user.name','Fixture');git(repo,'config','user.email','fixture@example.com')
    def write(self,repo,path,text):
        p=repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    def commit(self,repo):git(repo,'add','-A');git(repo,'commit','-m','fixture')
    def upstream(self,path='README.md',text='second\n'):
        self.write(self.author,path,text);self.write(self.author,'VERSION','0.1.0-prototype.2\n')
        self.commit(self.author);git(self.author,'push','origin','main')
    def update(self):return update(self.user,str(self.remote))

    def test_clean_fast_forward_and_version(self):
        self.upstream();self.assertEqual(self.update()['status'],'updated')
        self.assertEqual((self.user/'VERSION').read_text().strip(),'0.1.0-prototype.2')
        self.assertEqual(self.update()['status'],'unchanged')

    def test_unrelated_local_edits_and_staged_changes_survive(self):
        self.write(self.user,'scripts/tool.py','print("user")\n');git(self.user,'add','scripts/tool.py')
        before=git(self.user,'diff','--cached').stdout
        self.upstream();self.assertEqual(self.update()['status'],'updated')
        self.assertEqual((self.user/'scripts/tool.py').read_text(),'print("user")\n')
        self.assertEqual(git(self.user,'diff','--cached').stdout,before)

    def test_overlapping_local_edit_is_not_overwritten(self):
        self.write(self.user,'README.md','user edits\n');before=git(self.user,'rev-parse','HEAD').stdout
        self.upstream();self.assertEqual(self.update()['status'],'local_changes')
        self.assertEqual((self.user/'README.md').read_text(),'user edits\n')
        self.assertEqual(git(self.user,'rev-parse','HEAD').stdout,before)

    def test_untracked_collision_is_not_overwritten(self):
        self.write(self.user,'docs/new.md','my notes\n');self.upstream('docs/new.md','upstream\n')
        self.assertEqual(self.update()['status'],'local_changes')
        self.assertEqual((self.user/'docs/new.md').read_text(),'my notes\n')

    def test_diverged_history_is_not_reset(self):
        self.write(self.user,'README.md','local commit\n');self.commit(self.user)
        before=git(self.user,'rev-parse','HEAD').stdout;self.upstream()
        self.assertEqual(self.update()['status'],'local_history')
        self.assertEqual(git(self.user,'rev-parse','HEAD').stdout,before)

    def test_active_wrapper_defers_update(self):
        self.upstream()
        with session(self.user,auto_update=False):self.assertEqual(self.update()['status'],'active_session')
        self.assertEqual(self.update()['status'],'updated')

    def test_custom_branch_and_different_remote(self):
        self.assertEqual(update(self.user,'unexpected')['status'],'different_remote')
        git(self.user,'switch','-c','custom')
        self.assertEqual(self.update()['status'],'custom_branch')

    def test_archive_install_and_offline_preserve_version(self):
        self.assertEqual(update(self.base)['status'],'archive_install')
        git(self.user,'remote','set-url','origin',str(self.base/'missing.git'))
        self.assertEqual(update(self.user,str(self.base/'missing.git'))['status'],'offline')

    def test_scan_rejects_private_content_and_unrelated_tree(self):
        self.write(self.user,'scripts/key.txt','api_key = "'+'a'*40+'"\n')
        self.write(self.user,'other-project/source.py','print(1)')
        blocked={x['path'] for x in publisher.scan(self.user)}
        self.assertIn('scripts/key.txt',blocked);self.assertIn('other-project/source.py',blocked)

    def test_publishing_requires_opt_in_and_verifies_remote(self):
        self.assertEqual(publisher.publish(self.user)['status'],'disabled')
        previous=publisher.REMOTE;publisher.REMOTE=str(self.remote)
        try:
            (state_dir(self.user)/'author.json').write_text(json.dumps({'root':str(self.user.resolve()),'remote':str(self.remote),'enabled':True}))
            self.write(self.user,'README.md','author update\n')
            result=publisher.publish(self.user,'fixture release')
            self.assertEqual(result['status'],'published');self.assertEqual(result['version'],'0.1.0-prototype.2')
            self.assertEqual(publisher.publish(self.user)['version'],'0.1.0-prototype.2')
            self.assertIn(result['commit'],git(self.author,'ls-remote','origin','refs/heads/main').stdout)
        finally:publisher.REMOTE=previous


if __name__=='__main__':unittest.main()
