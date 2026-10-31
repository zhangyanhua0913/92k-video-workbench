"""Runs only inside the isolated optional ASR environment. Output stays local."""
import json
import sys
import wave
import numpy as np
from faster_whisper import WhisperModel

model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',local_files_only=True)
with wave.open(sys.argv[2],'rb') as wav:
    assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
    audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
segments,info=model.transcribe(audio,word_timestamps=True,vad_filter=False,beam_size=5)
rows=[]
for i,s in enumerate(segments):
    rows.append(dict(id='cue-'+str(i+1),start=s.start,end=s.end,text=s.text.strip(),
        words=[dict(start=w.start,end=w.end,word=w.word,probability=w.probability) for w in (s.words or [])]))
with open(sys.argv[3],'x',encoding='utf-8') as f:
    json.dump({'language':info.language,'cues':rows,'listeningReviewed':False},f,ensure_ascii=False)
