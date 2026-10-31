"""Windows file-event publisher. No periodic directory scanning; opt-in author only."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from publish import ROOT, publish
from versioning import Lock, state_dir


def main():
    if os.name != 'nt': raise SystemExit('Windows author watcher only')
    state=state_dir(ROOT)
    try: instance=Lock(state/'watcher.lock')
    except OSError: return
    # Fixed script, path passed via environment rather than interpolated into PowerShell code.
    code=r'''
$ErrorActionPreference='Stop'
$w=New-Object IO.FileSystemWatcher
$w.Path=$env:WB_WATCH_ROOT
$w.IncludeSubdirectories=$true
$w.NotifyFilter=[IO.NotifyFilters]'FileName,DirectoryName,LastWrite,Size'
$w.EnableRaisingEvents=$true
foreach($kind in @('Changed','Created','Deleted','Renamed')) {
  Register-ObjectEvent $w $kind -SourceIdentifier ('wb-'+$kind) | Out-Null
}
while($true) {
  $event=Wait-Event
  $name=$event.SourceEventArgs.Name
  Remove-Event -EventIdentifier $event.EventIdentifier
  if($name -and $name -notmatch '(^|[\\/])(\.git|__pycache__|node_modules|runtime|projects|private|user|local)([\\/]|$)') {
    [Console]::WriteLine('changed');[Console]::Out.Flush()
  }
}
'''
    child=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        env={**os.environ,'WB_WATCH_ROOT':str(ROOT)},creationflags=subprocess.CREATE_NO_WINDOW)
    changes=queue.Queue()
    def reader():
        for line in child.stdout:
            changes.put(time.monotonic())
        changes.put(None)
    threading.Thread(target=reader,daemon=True).start()
    def run():
        try: result=publish(message='Auto-publish source changes after 30 seconds idle')
        except Exception as exc: result={'status':'error','type':type(exc).__name__}
        with (state/'publish.log').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),**result},ensure_ascii=False)+'\n')
    try:
        run()  # One startup reconciliation, including a pending failed push.
        while True:
            event=changes.get()
            if event is None: break
            while True:
                try:
                    event=changes.get(timeout=30)
                    if event is None: return
                except queue.Empty: break
            run()
    finally:
        child.terminate();instance.close()


if __name__=='__main__': main()
