"""Test how ruamel.yaml parses the year field."""
import ruamel.yaml

yaml = ruamel.yaml.YAML(typ='safe')

# Test various YAML year formats
tests = [
    "year: 115-2",
    "year: '115-2'",
    "year: 115-1",
    "year: '115-1'",
    "year: 114-2",
]

for test in tests:
    result = yaml.load(test)
    value = result['year']
    print(f"{test:25s} -> {value!r} (type: {type(value).__name__})")

# Now test the full frontmatter from the problematic file
frontmatter = """type: question
qid: 115-2_1_28
exam_id: '1'
year: 115-2
question_number: 28
subject: 臨床生理學與病理學
question: 20 歲的男性肺功能檢查結果顯示，FEV1.0％是預測值 78％， FVC 是預測值 70％，下列選項何者較為合適？
（FEV1.0％：第一秒呼氣率；FVC：用力肺活量）
choices:
- A.阻塞型肺部疾病（obstructive pulmonary disease）
- B.侷限型肺部疾病（restrictive pulmonary disease）
- C.混合型肺部疾病（mixed pulmonary disease）
- D.正常
answer: B
difficulty: ''
topic: ''
key_concept: ''
summarize_including: false
images: []
"""

print("\n=== Full frontmatter parse ===")
try:
    result = yaml.load(frontmatter)
    print(f"year: {result.get('year')!r} (type: {type(result.get('year')).__name__})")
    print(f"exam_id: {result.get('exam_id')!r}")
    print(f"question_number: {result.get('question_number')!r}")
    print(f"All keys: {list(result.keys())}")
except Exception as e:
    print(f"PARSE ERROR: {e}")
