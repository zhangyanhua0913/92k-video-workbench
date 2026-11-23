"""Filter specified words from displayed talking-head subtitles only."""
import json
import re

WORDS = '债务重组，征信，银行，资质，产品，收费，服务费，返点，签，套路，欠债，骗，审核，费，案，价，引流，成本，资，账，债，月供，渠道，垫资，服务，护，政策，金融产品，额度，债务，款，清，清债，短期，高压，还款，重组，拆，补，催收，骚扰，钱，躲债，续命，停贷，咨询，签约，国企，养护，资料，重组机构，查询，周期，释放，申请，进件，提款，结清，方案，费用，公积金，涉诉，新增，借款，测额，提供，案列，答案，负债，利息，单位，公务，工资，信用卡，贷，借，逾期，机构，息，贷款，万，垫资费，利，弊，金，高息，网贷，审批，养，风险，批，合同，率'.split('，')
PATTERN = re.compile('|'.join(re.escape(w) for w in sorted(set(WORDS), key=lambda w: (-len(w), w))))
POLICY = 'talk-subtitle-filter-v1'

def enabled(root):
    marker = root / 'workbench-project.json'
    if not marker.exists():
        return True  # standalone talking-edit
    return json.loads(marker.read_text(encoding='utf-8'))['mode'] == 'talk'

def filter_cues(cues):
    combined = ''.join(cue['text'] for cue in cues)
    removed = bytearray(len(combined))
    for match in PATTERN.finditer(combined):
        removed[match.start():match.end()] = b'\x01' * (match.end() - match.start())
    result = []
    offset = 0
    for cue in cues:
        original = cue['text']
        text = ''.join(char for i, char in enumerate(original) if not removed[offset+i])
        offset += len(original)
        if text.strip():
            result.append({**cue, 'text': text})
    return result
