"""Isolated UTF-8 worker: reuse FredTalk's actual roughcut implementation, never its HTTP server."""
import importlib.util
import json
import sys
from pathlib import Path

root=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('fred_review_snapshot',root/'server.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
cuts=json.loads((root/'cuts.json').read_text(encoding='utf-8'))
# Container durations can differ from the decoded PCM end by a fractional sample.
# Project decisions remain untouched; project the execution snapshot to its real sample clock.
duration=module.PROJECT['duration']
for cut in cuts:
    for key in ('start','end'):
        value=cut[key]
        if value>duration:
            assert value-duration<=1/48000+1e-8,'Cut exceeds actual audio by more than one sample'
        cut[key]=min(duration,max(0,round(value*48000)/48000))
cuts=module.validate(cuts)
result=module.export(cuts)
result['retained_spans']=module.retained(cuts)
print(json.dumps(result,ensure_ascii=False))
