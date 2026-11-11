"""Desktop H.264 policy shared by probing, settings and the capture adapter."""

# The receiver supports High. Baseline was used during early compatibility
# debugging; retain the separate colour-description-free VUI policy.
# CABAC/8x8 transforms improve motion fidelity without B frames or lookahead.
H264_PROFILE = 'high'
H264_ENTROPY_CODER = 'cabac'
# Preserve saturated colour edges next to letterboxing at the fixed bitrate.
# Negative chroma offsets allocate finer U/V quantization without extra frames.
H264_CHROMA_QP_OFFSET = -4
