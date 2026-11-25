"""Dependency-free method definitions (safe for a lightweight preflight)."""

GEOMETRY_FORMULA = (
    'G=100*(1-0.30*min(degenerate_ratio/0.01,1)'
    '-0.30*min(nonmanifold_edge_ratio/0.10,1)'
    '-0.20*min(abs(triangles-target)/target,1)'
    '-0.20*(1-texture_match_fraction)); decode/measurement failure -> G=null; '
    'unavailable mandatory measurements -> G=null'
)
QUALITY_FORMULA = (
    'Q=0.5*(MUSIQ_mean/100)*100+0.5*G; '
    'either component unavailable -> null (no reweighting)'
)
VABENCH = {
    'paper_requested': 'arXiv:2512.09299',
    'read_success': True,
    'source': 'https://arxiv.org/html/2512.09299v2',
    'checked_on': '2026-10-24',
    'metric_definitions': {
        'text_audio_align': 'CLAP normalized embedding cosine (section 3.3.1)',
        'speech_clarity': 'DNSMOS OVRL; linguistic subset only',
        'speech_quality_naturalness': 'NISQAv2 mos-only; linguistic subset only',
        'audio_aesthetic': '(CE+CU+PQ-PC)/4 using Audiobox; not a 0..100 score',
    },
    'alignment_status': '未与 VABench 全套实现/数值对齐：已阅读v2正文3.3.1；CLAP采用归一化嵌入余弦定义，但未核对该benchmark具体checkpoint/聚合实现。DNSMOS、NISQAv2、Audiobox未执行，不声称数值可比。',
}
