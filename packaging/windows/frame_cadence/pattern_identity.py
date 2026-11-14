"""Offline CPU barcode verification for the generated native pattern only.

No video or pixel data is written to disk. The caller keeps a bounded short
H.264 sample in memory; decode occurs only after the timed encoder has exited.
"""
import subprocess

WIDTH,HEIGHT=512,48
FRAME_BYTES=WIDTH*HEIGHT
MAX_INPUT_BYTES=256*1024*1024
MAX_FRAMES=6500


def distribution(values):
    data=sorted(values)
    if not data:return None
    return dict(count=len(data),mean=sum(data)/len(data),**{
        name:data[int((len(data)-1)*p)] for name,p in
        [('min',0),('p01',.01),('p50',.5),('p95',.95),('p99',.99),('max',1)]})


def decode_marker(pixels):
    if len(pixels)!=FRAME_BYTES:raise ValueError('Incorrect cropped image size')
    values=[];uncertain=0;minimum_margin=255
    for row in range(3):
        value=0
        for bit in range(32):
            # Interior pixels keep 4 px away from cell edges and chroma/luma
            # ringing. Only an in-memory 512x48 luma crop survives decoding.
            samples=[pixels[(row*16+y)*WIDTH+bit*16+x] for y in range(4,12) for x in range(4,12)]
            intensity=sum(samples)/len(samples)
            minimum_margin=min(minimum_margin,abs(intensity-128))
            if 48<intensity<208:uncertain+=1
            if intensity>=128:value|=1<<bit
        values.append(value)
    return dict(frame_id=values[0],render_qpc=values[1]|values[2]<<32,
        uncertain_bits=uncertain,min_threshold_margin=minimum_margin)


def summarize_markers(rows,frequency,window_end_qpc=None):
    for row in rows:
        row['included_in_summary']=not row['warmup'] and (window_end_qpc is None or row['arrival']<=window_end_qpc)
    selected=[r for r in rows if r['included_in_summary']]
    unique=[]
    for row in selected:
        if not unique or row['frame_id']!=unique[-1]['frame_id']:unique.append(row)
    def age(field):return distribution([(r[field]-r['render_qpc'])*1000/frequency for r in selected])
    return dict(measured_frames=len(selected),unique_frame_ids=len(unique),
        repeated_frame_ids=len(selected)-len(unique),
        skipped_renderer_ids=sum(max(0,b['frame_id']-a['frame_id']-1) for a,b in zip(unique,unique[1:])),
        render_to_os_present_ms=age('present'),render_to_capture_sample_ms=age('sample'),
        render_to_host_arrival_ms=age('arrival'))


def verify(ffmpeg,frames,records,frequency,window_end_qpc=None):
    if len(frames)>MAX_FRAMES or sum(map(len,frames))>MAX_INPUT_BYTES:
        raise ValueError('Generated-pattern video exceeded bounded memory limit')
    command=[str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin',
        '-hwaccel','none','-threads','1','-c:v','h264','-f','h264','-i','pipe:0',
        '-vf','crop=512:48:16:8,format=gray','-an','-fps_mode','passthrough',
        '-threads','1','-f','rawvideo','pipe:1']
    # The fixed input frame cap bounds raw output to less than 153 MiB. CPU H.264
    # decoder is explicit: this creates no capture/NVENC/GPU work or screenshot.
    decoded=subprocess.run(command,input=b''.join(frames),stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180)
    errors=[]
    if decoded.returncode:errors.append('Offline CPU decode failed: '+decoded.stderr.decode(errors='replace')[:2000])
    if len(decoded.stdout)%FRAME_BYTES:errors.append('Truncated luma marker output')
    count=len(decoded.stdout)//FRAME_BYTES
    if count!=len(frames) or count!=len(records):errors.append('Decoded/native/access-unit frame counts differ')
    rows=[]
    for i in range(min(count,len(records))):
        marker=decode_marker(memoryview(decoded.stdout)[i*FRAME_BYTES:(i+1)*FRAME_BYTES])
        native=records[i]
        marker.update(index=i,capture_sequence=native['sequence'],present=native['present'],
            sample=native['sample'],emit=native['emit'],arrival=native['arrival'],warmup=native['warmup'])
        if marker['uncertain_bits']:errors.append(f'Uncertain marker cells at frame {i}')
        if not 0<marker['render_qpc']<=marker['emit']+1:errors.append(f'Impossible renderer QPC at frame {i}')
        if i and (marker['frame_id']<rows[-1]['frame_id'] or marker['render_qpc']<rows[-1]['render_qpc']):
            errors.append(f'Backward marker identity/QPC at frame {i}')
        if i and (marker['frame_id']==rows[-1]['frame_id'])!=(marker['render_qpc']==rows[-1]['render_qpc']):
            errors.append(f'Inconsistent repeated identity/QPC at frame {i}')
        rows.append(marker)
    summary=summarize_markers(rows,frequency,window_end_qpc)
    return dict(scope='Offline decoded generated-pattern identity; source-render-to-host, not optics',
        status='completed' if not errors and count else 'failed',errors=errors[:30],
        cpu_decode_returncode=decoded.returncode,decoded_frames=count,stored_video_artifacts=False,
        captured_payload_bytes=sum(map(len,frames)),**summary,records=rows)
