from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from gk_vector.update import update_tool,install_pending_update,_run,REPOSITORY,PENDING_FILE
from gk_vector import server


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.calls=[]
        self.pulled=False

    def tearDown(self):
        self.temp.cleanup()

    def runner(self,command,root,timeout):
        self.calls.append(command)
        responses={('git','rev-parse','--show-toplevel'):str(self.root),
                   ('git','symbolic-ref','--short','HEAD'):'main',
                   ('git','remote','get-url','origin'):REPOSITORY,
                   ('git','status','--porcelain','--untracked-files=no'):''}
        if command[:2]==['git','pull']:
            self.pulled=True
        output=responses.get(tuple(command),'')
        if command==['git','rev-parse','HEAD']:
            output='new' if self.pulled else 'old'
        return subprocess.CompletedProcess(command,0,output,'')

    def test_simple_update_pulls_main_and_installs_current_environment(self):
        result=update_tool(self.root,self.runner)
        self.assertEqual(result['status'],'updated')
        self.assertTrue(result['restart_required'])
        self.assertIn(['git','pull','--ff-only','origin','main'],self.calls)
        self.assertTrue((self.root/PENDING_FILE).exists())
        self.assertFalse(any(c[0]!= 'git' for c in self.calls))
        install_pending_update(self.root,self.runner)
        installers=[c for c in self.calls if c[0]!= 'git']
        self.assertEqual(len(installers),3)
        self.assertTrue(all(c[0]==sys.executable for c in installers))
        self.assertIn('--no-build-isolation',installers[1])
        self.assertFalse((self.root/PENDING_FILE).exists())

    def test_dirty_code_or_wrong_remote_does_not_pull(self):
        for command,output in [(['git','status','--porcelain','--untracked-files=no'],' M README.md'),
                               (['git','remote','get-url','origin'],'https://example.com/other.git'),
                               (['git','symbolic-ref','--short','HEAD'],'feature')]:
            self.pulled=False
            def blocked(args,root,timeout):
                if args==command:return subprocess.CompletedProcess(args,0,output,'')
                return self.runner(args,root,timeout)
            result=update_tool(self.root,blocked)
            self.assertEqual(result['status'],'blocked')
            self.assertFalse(self.pulled)

    def test_dependency_failure_remains_pending_for_next_startup(self):
        def failed(command,root,timeout):
            if command[0]!= 'git':return subprocess.CompletedProcess(command,1,'','Package installation failed')
            return self.runner(command,root,timeout)
        update_tool(self.root,self.runner)
        with self.assertRaisesRegex(RuntimeError,'installation failed'):
            install_pending_update(self.root,failed)
        self.assertTrue((self.root/PENDING_FILE).exists())

    def test_mcp_requests_restart_before_more_artwork_work(self):
        with patch.object(server,'RESTART_REQUIRED',False),patch.object(server,'update_tool',return_value={'status':'updated','restart_required':True}):
            self.assertTrue(server.update_gk_vector()['restart_required'])
            with self.assertRaisesRegex(ValueError,'Restart'):
                with server.active_operation():pass

    def test_actual_fast_forward_preserves_settings_and_artwork(self):
        seed=self.root/'seed';remote=self.root/'origin.git';client=self.root/'client'
        seed.mkdir()
        def git(*args,cwd=seed):
            result=_run(['git',*args],cwd,60)
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout
        git('init','-b','main')
        git('config','user.name','Updater Test')
        git('config','user.email','updater@example.invalid')
        (seed/'README.md').write_text('old')
        (seed/'.gitignore').write_text('gk-vector.local.json\noutput/\n')
        (seed/'requirements-lock.txt').write_text('')
        git('add','.')
        git('-c','core.hooksPath=/dev/null','commit','-m','Initial')
        git('init','--bare','-b','main',str(remote))
        git('remote','add','origin',str(remote))
        git('push','-u','origin','main')
        git('clone',str(remote),str(client))
        (client/'gk-vector.local.json').write_text('{"output_folder":"output"}')
        (client/'output').mkdir()
        (client/'output/artwork.txt').write_text('preserve me')
        (seed/'README.md').write_text('new')
        git('add','README.md')
        git('-c','core.hooksPath=/dev/null','commit','-m','Update')
        git('push','origin','main')
        def runner(command,root,timeout):
            if command[0]=='git':return _run(command,root,timeout)
            return subprocess.CompletedProcess(command,0,'Test installer succeeded','')
        with patch('gk_vector.update.REPOSITORY',str(remote)):
            result=update_tool(client,runner)
        self.assertEqual(result['status'],'updated')
        self.assertEqual((client/'README.md').read_text(),'new')
        self.assertEqual((client/'output/artwork.txt').read_text(),'preserve me')
        self.assertEqual((client/'gk-vector.local.json').read_text(),'{"output_folder":"output"}')
