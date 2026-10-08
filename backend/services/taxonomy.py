"""Category names transcribed from the official 2026 PDF table of contents.

Source: https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
Verified 2026-10-08. OWASP material licensed CC BY-SA 4.0.
"""
OWASP = dict(zip([f'LLM{i:02}:2026' for i in range(1, 11)], [
    'Prompt Injection', 'Sensitive Information Disclosure', 'Excessive Agency',
    'Supply Chain', 'Data and Model Poisoning', 'Unbounded Consumption',
    'Misinformation', 'Hidden Context Exposure', 'Vector and Embedding Weaknesses',
    'Improper Output Handling',
]))

SOURCES = [
    {'title': 'OWASP LLM Top 10 2026', 'url': 'https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/', 'date': '2026-08-03', 'content': 'Assess input trust boundaries, data disclosure, excessive agency and retrieval isolation.'},
    {'title': 'NIST AI 600-1', 'url': 'https://doi.org/10.6028/NIST.AI.600-1', 'date': '2024-07-26', 'content': 'Risk management and evaluation across the generative AI lifecycle.'},
]
