"""Explicitly install/uninstall this author's Windows logon file-event publisher."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape
from publish import ROOT, author_config
from versioning import REMOTE, state_dir

TASK='92k-VideoWorkbench-AutoPublish'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args()
    if os.name!='nt': raise SystemExit('Windows only; user updates do not need this watcher')
    state=state_dir(ROOT)
    if args.uninstall:
        subprocess.run(['schtasks','/End','/TN',TASK],capture_output=True)
        subprocess.run(['schtasks','/Delete','/TN',TASK,'/F'],check=True,capture_output=True)
        author_config(ROOT).unlink(missing_ok=True)
        print(json.dumps({'status':'disabled'})); return
    identity=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,check=True)
    sid=list(csv.reader(io.StringIO(identity.stdout.strip())))[0][1]
    pythonw=Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.exists(): raise SystemExit('pythonw.exe is required for hidden author watcher')
    config=author_config(ROOT);config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text(json.dumps({'root':str(ROOT.resolve()),'remote':REMOTE,'enabled':True}),encoding='utf-8')
    xml=f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(sid)}</UserId></LogonTrigger></Triggers>
<Principals><Principal id="Author"><UserId>{escape(sid)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure></Settings>
<Actions Context="Author"><Exec><Command>{escape(str(pythonw))}</Command><Arguments>{escape(chr(34)+str(ROOT/'scripts/watch_publish.py')+chr(34))}</Arguments><WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory></Exec></Actions></Task>'''
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/'task.xml';path.write_text(xml,encoding='utf-16')
        subprocess.run(['schtasks','/Create','/TN',TASK,'/XML',str(path),'/F'],check=True,capture_output=True)
    subprocess.run(['schtasks','/Run','/TN',TASK],check=True,capture_output=True)
    print(json.dumps({'status':'installed','task':TASK,'state_dir':str(state)}))


if __name__=='__main__':main()
