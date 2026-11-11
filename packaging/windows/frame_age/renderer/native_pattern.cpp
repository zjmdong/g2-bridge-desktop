// Research-only 100 Hz source. No USB access, display configuration, or focus activation.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi1_3.h>
#include <wrl/client.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
constexpr int kX = 3440, kY = 0, kWidth = 1920, kHeight = 1080;
static std::atomic<bool> g_running{true};

static int64_t qpc() { LARGE_INTEGER n; QueryPerformanceCounter(&n); return n.QuadPart; }
static void check(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        std::ostringstream msg; msg << operation << " failed: 0x" << std::hex << static_cast<unsigned>(result);
        throw std::runtime_error(msg.str());
    }
}
static std::string utf8(const std::wstring& s) {
    if (s.empty()) return {};
    int bytes = WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0, nullptr, nullptr);
    std::string result(bytes, 0);
    WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), result.data(), bytes, nullptr, nullptr);
    return result;
}
static std::string quoted(const std::string& s) {
    std::ostringstream out; out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c == '\n') out << "\\n";
        else if (c == '\r') out << "\\r";
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
        else out << c;
    }
    return out.str() + '"';
}

struct Options {
    double seconds = 90;
    std::string mode = "complex";
    fs::path output;
};
static Options options(int argc, wchar_t** argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        std::wstring flag = argv[i];
        if (flag == L"--help") {
            std::cout << "native_pattern --mode motion|complex|texture --seconds 5..600 --output NEW.json\n"
                         "Requires existing nonprimary 1920x1080 at (3440,0), current 100 Hz.\n"
                         "Shows without activation. Escape, Ctrl+C, close, or duration stops. No USB.\n";
            std::exit(0);
        }
        if (i + 1 >= argc) throw std::runtime_error("Missing option value");
        std::wstring value = argv[++i];
        if (flag == L"--mode") {
            if (value != L"motion" && value != L"complex" && value != L"texture")
                throw std::runtime_error("mode must be motion, complex, or texture");
            o.mode = utf8(value);
        } else if (flag == L"--seconds") {
            size_t used = 0; o.seconds = std::stod(value, &used);
            if (used != value.size() || !std::isfinite(o.seconds) || o.seconds < 5 || o.seconds > 600)
                throw std::runtime_error("seconds must be 5..600");
        } else if (flag == L"--output") o.output = value;
        else throw std::runtime_error("Unknown option: " + utf8(flag));
    }
    if (o.output.empty()) throw std::runtime_error("--output NEW.json is required");
    o.output = fs::absolute(o.output);
    if (fs::exists(o.output)) throw std::runtime_error("Output already exists; select a unique new path");
    if (!fs::exists(o.output.parent_path())) throw std::runtime_error("Output directory does not exist");
    return o;
}

struct Monitor {
    HMONITOR handle = nullptr;
    MONITORINFOEXW info{};
    DEVMODEW mode{};
};
static Monitor target_monitor() {
    Monitor m;
    RECT desired{kX, kY, kX + kWidth, kY + kHeight};
    m.handle = MonitorFromRect(&desired, MONITOR_DEFAULTTONULL);
    m.info.cbSize = sizeof(m.info);
    if (!m.handle || !GetMonitorInfoW(m.handle, &m.info)) throw std::runtime_error("Target extended monitor is not active");
    const RECT r = m.info.rcMonitor;
    if ((m.info.dwFlags & MONITORINFOF_PRIMARY) || r.left != kX || r.top != kY ||
        r.right != kX + kWidth || r.bottom != kY + kHeight)
        throw std::runtime_error("Require nonprimary monitor exactly 1920x1080 at (3440,0); no display was changed");
    m.mode.dmSize = sizeof(m.mode);
    if (!EnumDisplaySettingsExW(m.info.szDevice, ENUM_CURRENT_SETTINGS, &m.mode, 0) ||
        m.mode.dmPelsWidth != kWidth || m.mode.dmPelsHeight != kHeight || m.mode.dmDisplayFrequency != 100)
        throw std::runtime_error("Existing target display must already be 1920x1080 at 100 Hz");
    return m;
}

static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp) {
    switch (message) {
    case WM_MOUSEACTIVATE: return MA_NOACTIVATE;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: ValidateRect(hwnd, nullptr); return 0;
    case WM_KEYDOWN: if (wp == VK_ESCAPE) g_running = false; return 0;
    case WM_DISPLAYCHANGE: g_running = false; return 0;
    case WM_CLOSE: g_running = false; return 0;
    case WM_DESTROY: g_running = false; return 0;
    default: return DefWindowProcW(hwnd, message, wp, lp);
    }
}
static BOOL WINAPI console_handler(DWORD type) {
    if (type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT) { g_running = false; return TRUE; }
    return FALSE;
}

// Deterministic multiscale ground/siding detail with continuous camera motion.
// No per-frame texture uploads and no CPU animation timer.
static const char* kShader = R"HLSL(
cbuffer Scene : register(b0) {
    float elapsed; uint frameId; uint qpcLow; uint qpcHigh;
    uint sceneMode; float cyclePhase; float rotationSin; float rotationCos;
};
Texture2D<float4> staticTexture : register(t0);
SamplerState textureSampler : register(s0);
struct Vertex { float4 position : SV_POSITION; float2 uv : TEXCOORD0; };
Vertex vs_main(uint id : SV_VertexID) {
    Vertex v; v.uv = float2((id << 1) & 2, id & 2);
    v.position = float4(v.uv.x*2-1, 1-v.uv.y*2, 0, 1); return v;
}
float hash(float2 p) { return frac(sin(dot(p, float2(127.1,311.7))) * 43758.5453); }
float noise(float2 p) {
    float2 a = floor(p), f = frac(p); f = f*f*(3-2*f);
    return lerp(lerp(hash(a), hash(a+float2(1,0)), f.x),
                lerp(hash(a+float2(0,1)), hash(a+1), f.x), f.y);
}
float grid(float2 p, float width) {
    float2 d = min(frac(p), 1-frac(p));
    float2 aa = max(fwidth(p), 0.002);
    return 1-min(smoothstep(width-aa.x, width+aa.x, d.x),
                 smoothstep(width-aa.y, width+aa.y, d.y));
}
float3 complex_scene(float2 uv) {
    float2 p = (uv-float2(.5,.43))*float2(1.77778,1);
    float angle = .045*sin(elapsed*.47);
    p = float2(p.x*cos(angle)-p.y*sin(angle), p.x*sin(angle)+p.y*cos(angle));
    float3 color;
    if (p.y > 0) {
        float z = .22/max(p.y,.005);
        float2 world = float2(p.x*z + .13*sin(elapsed*.35), z-elapsed*1.6);
        float detail = .52*noise(world*10)+.28*noise(world*31)+.20*noise(world*91);
        float checkers = fmod(floor(world.x*4)+floor(world.y*4)+100000,2);
        color = lerp(float3(.12,.19,.09),float3(.38,.34,.23),detail);
        color += checkers*.07;
        color *= 1-grid(world*2,.015)*.5;
        float road = 1-smoothstep(.28,.32,abs(world.x));
        color = lerp(color, float3(.13,.14,.15)+detail*.10, road);
        float stripe = (1-smoothstep(.012,.022,abs(world.x)))*step(.48,frac(world.y*1.8));
        color = lerp(color,float3(.9,.8,.3),stripe);
        color = lerp(float3(.52,.61,.66),color,saturate(p.y*8));
    } else {
        float2 sky = float2(p.x*3+elapsed*.16,p.y*4);
        float cloud = smoothstep(.40,.8,noise(sky*3)*.65+noise(sky*8)*.35);
        color = lerp(float3(.16,.36,.63),float3(.78,.83,.86),cloud);
        float ridge = -.025-.035*noise(float2((p.x+elapsed*.03)*23,0));
        if (p.y > ridge) color = float3(.12,.23,.17)+noise(sky*51)*.09;
    }
    float2 panels = float2(uv.x*22+elapsed*.31, uv.y*11);
    float side = smoothstep(.29,.40,abs(uv.x-.5)) * smoothstep(.34,.50,uv.y);
    float panel = noise(panels*3)*.45 + noise(panels*11)*.2 + .25;
    float3 siding = float3(panel*.66,panel*.72,panel*.78)*(1-grid(panels,.018)*.7);
    color = lerp(color,siding,side*.8);
    return color;
}
float3 texture_scene(float2 uv) {
    // Two cached texture samples per pixel, no procedural noise or trig.
    // All displacement is an integer texture period per 200-frame cycle.
    float2 a = uv*float2(2,1.125)+float2(cyclePhase*2,cyclePhase);
    float2 p = (uv-.5)*float2(1.77778,1);
    p = float2(p.x*rotationCos-p.y*rotationSin,p.x*rotationSin+p.y*rotationCos);
    float2 b = p*2.5+float2(-cyclePhase,cyclePhase*2);
    float3 first = staticTexture.Sample(textureSampler,a).rgb;
    float3 second = staticTexture.Sample(textureSampler,b).bgr;
    // Regions have different motion fields, retaining detail without a single
    // globally translating picture that compresses to almost no residual.
    float region = fmod(floor(uv.x*4)+floor(uv.y*3),2);
    return lerp(first*.8+second*.2,first*.25+second*.75,region);
}
float segment(float2 p, float2 a, float2 b) {
    float2 ab = b-a; float t=saturate(dot(p-a,ab)/dot(ab,ab));
    return 1-smoothstep(.055,.10,length(p-(a+ab*t)));
}
float hex_digit(float2 p, uint d) {
    static const uint masks[16] = {63,6,91,79,102,109,125,7,127,111,119,124,57,94,121,113};
    uint m=masks[d&15]; float a=0;
    if(m&1) a=max(a,segment(p,float2(.2,.1),float2(.8,.1)));
    if(m&2) a=max(a,segment(p,float2(.8,.1),float2(.8,.5)));
    if(m&4) a=max(a,segment(p,float2(.8,.5),float2(.8,.9)));
    if(m&8) a=max(a,segment(p,float2(.2,.9),float2(.8,.9)));
    if(m&16) a=max(a,segment(p,float2(.2,.5),float2(.2,.9)));
    if(m&32) a=max(a,segment(p,float2(.2,.1),float2(.2,.5)));
    if(m&64) a=max(a,segment(p,float2(.2,.5),float2(.8,.5)));
    return a;
}
float4 ps_main(Vertex input) : SV_TARGET {
    float2 uv=input.uv, px=input.position.xy;
    float3 color;
    [branch] if(sceneMode==2) color=texture_scene(uv);
    else if(sceneMode==1) color=complex_scene(uv);
    else color=float3(.08,.08,.08);
    if (sceneMode==0) {
        float2 g=frac(uv*float2(16,9));
        color += (1-step(.015,min(g.x,g.y)))*.08;
    }
    float2 box;
    if(sceneMode==2) box=float2(.14+.72*(1-abs(2*cyclePhase-1)),.78);
    else box=float2(.5+.36*sin(elapsed*1.7),.78+.10*cos(elapsed*1.1));
    if(all(abs(uv-box)<float2(.035,.04))) color=float3(.1,.95,.25);
    if(px.y<132) {
        color=float3(.015,.015,.015);
        // 32 columns x 3 rows: frame ID, QPC low32, QPC high32, LSB first.
        int2 cell=int2(floor((px-float2(16,8))/16));
        if(cell.x>=0 && cell.x<32 && cell.y>=0 && cell.y<3) {
            uint v=cell.y==0 ? frameId : (cell.y==1 ? qpcLow : qpcHigh);
            color=((v>>cell.x)&1) ? float3(1,1,1) : float3(0,0,0);
        }
        // Numeric view: 8 hex frame-ID digits then 16 QPC digits, MSB first.
        float2 digitp=(px-float2(16,70))/float2(22,38);
        int cellx=int(floor(digitp.x)); uint digit=0;
        if(digitp.y>=0 && digitp.y<1 && cellx>=0 && cellx<26 && cellx!=8 && cellx!=9) {
            if(cellx<8) digit=(frameId>>(28-cellx*4))&15;
            else if(cellx<18) digit=(qpcHigh>>(28-(cellx-10)*4))&15;
            else digit=(qpcLow>>(28-(cellx-18)*4))&15;
            color=lerp(color,float3(.9,.95,1),hex_digit(frac(digitp),digit));
        }
    }
    return float4(saturate(color),1);
}
)HLSL";

struct Constants {
    float elapsed;
    uint32_t frame, qpc_low, qpc_high, mode;
    float phase, rotation_sin, rotation_cos;
};
static_assert(sizeof(Constants) == 32);
struct Row {
    int64_t wait_start=0, wait_end=0, render_start=0, present_start=0, present_end=0, stats_end=0;
    uint32_t frame=0, last_present=0;
    HRESULT present_result=S_OK, count_result=S_OK, statistics_result=S_OK;
    DXGI_FRAME_STATISTICS statistics{};
};

struct Graphics {
    HWND hwnd=nullptr;
    HANDLE frame_event=nullptr;
    ComPtr<IDXGIAdapter1> adapter;
    ComPtr<IDXGIOutput> output;
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain2> swap;
    ComPtr<ID3D11RenderTargetView> target;
    ComPtr<ID3D11VertexShader> vs;
    ComPtr<ID3D11PixelShader> ps;
    ComPtr<ID3D11Buffer> constant;
    ComPtr<ID3D11ShaderResourceView> texture_view;
    ComPtr<ID3D11SamplerState> sampler;
    DXGI_ADAPTER_DESC1 description{};

    ~Graphics() {
        if(context) { context->ClearState(); context->Flush(); }
        target.Reset(); swap.Reset();
        if(frame_event) CloseHandle(frame_event);
        if(hwnd) DestroyWindow(hwnd);
    }
    void initialize(const Monitor& monitor, bool texture_mode) {
        ComPtr<IDXGIFactory1> factory;
        check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"CreateDXGIFactory1");
        for(UINT ai=0; !adapter; ++ai) {
            ComPtr<IDXGIAdapter1> candidate;
            HRESULT hr=factory->EnumAdapters1(ai,&candidate);
            if(hr==DXGI_ERROR_NOT_FOUND) break;
            check(hr,"EnumAdapters1");
            for(UINT oi=0;;++oi) {
                ComPtr<IDXGIOutput> candidate_output;
                hr=candidate->EnumOutputs(oi,&candidate_output);
                if(hr==DXGI_ERROR_NOT_FOUND) break;
                check(hr,"EnumOutputs"); DXGI_OUTPUT_DESC desc{};
                check(candidate_output->GetDesc(&desc),"Get output descriptor");
                if(desc.AttachedToDesktop && desc.Monitor==monitor.handle) {
                    adapter=candidate; output=candidate_output; break;
                }
            }
        }
        if(!adapter) throw std::runtime_error("Target monitor has no active DXGI output");
        check(adapter->GetDesc1(&description),"Adapter description");
        D3D_FEATURE_LEVEL level;
        check(D3D11CreateDevice(adapter.Get(),D3D_DRIVER_TYPE_UNKNOWN,nullptr,D3D11_CREATE_DEVICE_BGRA_SUPPORT,
              nullptr,0,D3D11_SDK_VERSION,&device,&level,&context),"D3D11CreateDevice");

        WNDCLASSEXW wc{}; wc.cbSize=sizeof(wc); wc.lpfnWndProc=window_proc;
        wc.hInstance=GetModuleHandleW(nullptr); wc.lpszClassName=L"G2NativeTimingPattern";
        wc.hCursor=LoadCursorW(nullptr,IDC_ARROW);
        if(!RegisterClassExW(&wc) && GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)
            throw std::runtime_error("RegisterClassEx failed");
        hwnd=CreateWindowExW(WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW,wc.lpszClassName,
            L"G2 native 100 Hz timing pattern",WS_POPUP,kX,kY,kWidth,kHeight,
            nullptr,nullptr,wc.hInstance,nullptr);
        if(!hwnd) throw std::runtime_error("CreateWindowEx failed");

        ComPtr<IDXGIFactory2> factory2; check(factory.As(&factory2),"DXGI factory2");
        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width=kWidth; desc.Height=kHeight; desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count=1; desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount=2; desc.Scaling=DXGI_SCALING_STRETCH;
        desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD; desc.AlphaMode=DXGI_ALPHA_MODE_IGNORE;
        desc.Flags=DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
        ComPtr<IDXGISwapChain1> swap1;
        check(factory2->CreateSwapChainForHwnd(device.Get(),hwnd,&desc,nullptr,nullptr,&swap1),"CreateSwapChainForHwnd");
        check(factory->MakeWindowAssociation(hwnd,DXGI_MWA_NO_ALT_ENTER),"MakeWindowAssociation");
        check(swap1.As(&swap),"IDXGISwapChain2");
        check(swap->SetMaximumFrameLatency(1),"SetMaximumFrameLatency(1)");
        frame_event=swap->GetFrameLatencyWaitableObject();
        if(!frame_event) throw std::runtime_error("Missing frame latency waitable object");
        ComPtr<ID3D11Texture2D> backbuffer;
        check(swap->GetBuffer(0,IID_PPV_ARGS(&backbuffer)),"Swapchain buffer");
        check(device->CreateRenderTargetView(backbuffer.Get(),nullptr,&target),"Render target");
        auto compile=[&](const char* entry,const char* profile) {
            ComPtr<ID3DBlob> code, errors;
            HRESULT hr=D3DCompile(kShader,strlen(kShader),"native_pattern",nullptr,nullptr,entry,profile,
                                 D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&code,&errors);
            if(FAILED(hr) && errors) throw std::runtime_error(static_cast<const char*>(errors->GetBufferPointer()));
            check(hr,"D3DCompile"); return code;
        };
        auto v=compile("vs_main","vs_5_0"), p=compile("ps_main","ps_5_0");
        check(device->CreateVertexShader(v->GetBufferPointer(),v->GetBufferSize(),nullptr,&vs),"Vertex shader");
        check(device->CreatePixelShader(p->GetBufferPointer(),p->GetBufferSize(),nullptr,&ps),"Pixel shader");
        D3D11_BUFFER_DESC bd{}; bd.ByteWidth=sizeof(Constants); bd.Usage=D3D11_USAGE_DYNAMIC;
        bd.BindFlags=D3D11_BIND_CONSTANT_BUFFER; bd.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;
        check(device->CreateBuffer(&bd,nullptr,&constant),"Constants buffer");
        if(texture_mode) create_static_texture();
        ShowWindow(hwnd,SW_SHOWNOACTIVATE);
        if(!SetWindowPos(hwnd,HWND_TOP,kX,kY,kWidth,kHeight,SWP_NOACTIVATE|SWP_SHOWWINDOW))
            throw std::runtime_error("SetWindowPos failed");
    }
    void create_static_texture() {
        constexpr unsigned size=1024;
        auto hash=[](unsigned x,unsigned y) {
            uint32_t n=x*0x9e3779b9u+y*0x85ebca6bu+0x1234567u;
            n^=n>>16; n*=0x7feb352du; n^=n>>15; n*=0x846ca68bu; n^=n>>16;
            return float(n&255);
        };
        auto noise=[&](unsigned x,unsigned y,unsigned period) {
            unsigned cells=size/period, ix=x/period, iy=y/period;
            float fx=float(x%period)/period, fy=float(y%period)/period;
            fx=fx*fx*(3-2*fx); fy=fy*fy*(3-2*fy);
            float a=hash(ix,iy), b=hash((ix+1)%cells,iy);
            float c=hash(ix,(iy+1)%cells), d=hash((ix+1)%cells,(iy+1)%cells);
            return (a+(b-a)*fx)*(1-fy)+(c+(d-c)*fx)*fy;
        };
        std::vector<std::vector<uint32_t>> levels(11);
        levels[0].resize(size*size);
        for(unsigned y=0;y<size;++y) for(unsigned x=0;x<size;++x) {
            float coarse=noise(x,y,128), medium=noise(x,y,32);
            float fine=noise(x,y,8), grain=noise(x,y,2);
            float detail=coarse*.15f+medium*.30f+fine*.40f+grain*.15f;
            bool seam=(x%64<2)||(y%64<2);
            float tile=((x/64+y/64)&1) ? 1.12f : .88f;
            auto channel=[&](float value) { return uint32_t(std::clamp(value,0.f,255.f)); };
            uint32_t red=channel((detail*.82f+coarse*.18f)*tile);
            uint32_t green=channel((detail*.88f+medium*.12f)*tile);
            uint32_t blue=channel((detail*.84f+fine*.16f)*tile);
            if(seam) { red/=3; green/=3; blue/=3; }
            levels[0][y*size+x]=red|(green<<8)|(blue<<16)|0xff000000u;
        }
        std::vector<D3D11_SUBRESOURCE_DATA> data(11);
        unsigned previous=size;
        data[0]={levels[0].data(),size*4,0};
        for(unsigned mip=1;mip<11;++mip) {
            unsigned width=previous/2; levels[mip].resize(width*width);
            for(unsigned y=0;y<width;++y) for(unsigned x=0;x<width;++x) {
                uint32_t result=0xff000000u;
                for(unsigned shift=0;shift<24;shift+=8) {
                    unsigned sum=0;
                    for(unsigned dy=0;dy<2;++dy) for(unsigned dx=0;dx<2;++dx)
                        sum+=(levels[mip-1][(y*2+dy)*previous+x*2+dx]>>shift)&255;
                    result|=(sum/4)<<shift;
                }
                levels[mip][y*width+x]=result;
            }
            data[mip]={levels[mip].data(),width*4,0}; previous=width;
        }
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width=size; desc.Height=size; desc.MipLevels=11; desc.ArraySize=1;
        desc.Format=DXGI_FORMAT_R8G8B8A8_UNORM; desc.SampleDesc.Count=1;
        desc.Usage=D3D11_USAGE_IMMUTABLE; desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        ComPtr<ID3D11Texture2D> texture;
        check(device->CreateTexture2D(&desc,data.data(),&texture),"Immutable texture");
        check(device->CreateShaderResourceView(texture.Get(),nullptr,&texture_view),"Texture view");
        D3D11_SAMPLER_DESC sd{};
        sd.Filter=D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_WRAP;
        sd.ComparisonFunc=D3D11_COMPARISON_NEVER; sd.MaxLOD=D3D11_FLOAT32_MAX;
        check(device->CreateSamplerState(&sd,&sampler),"Texture sampler");
    }
    void draw(const Constants& c) {
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check(context->Map(constant.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped),"Map constants");
        memcpy(mapped.pData,&c,sizeof(c)); context->Unmap(constant.Get(),0);
        ID3D11RenderTargetView* rtv=target.Get(); context->OMSetRenderTargets(1,&rtv,nullptr);
        D3D11_VIEWPORT viewport{0,0,float(kWidth),float(kHeight),0,1}; context->RSSetViewports(1,&viewport);
        context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context->IASetInputLayout(nullptr); context->VSSetShader(vs.Get(),nullptr,0); context->PSSetShader(ps.Get(),nullptr,0);
        ID3D11Buffer* cb=constant.Get(); context->PSSetConstantBuffers(0,1,&cb);
        ID3D11ShaderResourceView* view=texture_view.Get(); context->PSSetShaderResources(0,1,&view);
        ID3D11SamplerState* ss=sampler.Get(); context->PSSetSamplers(0,1,&ss);
        context->Draw(3,0);
    }
};

static bool wait_frame(HANDLE event, int64_t deadline) {
    while(g_running) {
        if(qpc() >= deadline) return false;
        DWORD result=MsgWaitForMultipleObjectsEx(1,&event,200,QS_ALLINPUT,MWMO_INPUTAVAILABLE);
        if(result==WAIT_OBJECT_0) return true;
        if(result==WAIT_FAILED) throw std::runtime_error("Frame wait failed");
        MSG msg;
        while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) {
            if(msg.message==WM_QUIT) g_running=false;
            TranslateMessage(&msg); DispatchMessageW(&msg);
        }
        if(GetAsyncKeyState(VK_ESCAPE)&0x8000) g_running=false;
    }
    return false;
}

static void save(const Options& o,const Monitor& monitor,const DXGI_ADAPTER_DESC1& adapter,
                 int64_t frequency,int64_t start,int64_t finish,const std::vector<Row>& rows,size_t count,
                 HWND foreground_before,HWND foreground_after,const std::string& error) {
    // Exclusive CREATE_NEW prevents accidental overwrite, including races.
    HANDLE file=CreateFileW(o.output.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE) throw std::runtime_error("Cannot create new output JSON");
    std::ostringstream j; j << std::setprecision(12);
    j << "{\n\"schema\":1,\n\"scope\":\"Source renderer only; Present return is not goggles display completion\",\n"
      << "\"mode\":" << quoted(o.mode) << ",\n\"seconds_requested\":" << o.seconds
      << ",\n\"texture_cycle_frames\":" << (o.mode=="texture"?200:0)
      << ",\n\"display\":" << quoted(utf8(monitor.info.szDevice)) << ",\n\"gpu\":" << quoted(utf8(adapter.Description))
      << ",\n\"rectangle\":[3440,0,1920,1080],\n\"display_refresh_hz\":" << monitor.mode.dmDisplayFrequency
      << ",\n\"swapchain\":\"flip-discard,2 buffers,max-frame-latency1,Present1 sync interval1\",\n"
      << "\"clock\":\"QueryPerformanceCounter\",\n\"frequency\":" << frequency
      << ",\n\"start_qpc\":" << start << ",\n\"finish_qpc\":" << finish
      << ",\n\"foreground_before\":" << reinterpret_cast<uintptr_t>(foreground_before)
      << ",\n\"foreground_after_show\":" << reinterpret_cast<uintptr_t>(foreground_after)
      << ",\n\"focus_unchanged_on_show\":" << (foreground_before==foreground_after?"true":"false")
      << ",\n\"marker\":{\"origin\":[16,8],\"cell\":[16,16],\"columns\":32,\"rows\":[\"frame_id\",\"qpc_low32\",\"qpc_high32\"],\"bit_order\":\"LSB first\"}"
      << ",\n\"error\":" << quoted(error) << ",\n\"capacity\":" << rows.size() << ",\n\"count\":" << count << ",\n\"records\":[\n";
    for(size_t i=0;i<count;++i) {
        const Row& r=rows[i]; if(i) j << ",\n";
        j << "{\"frame\":" << r.frame << ",\"wait_start\":" << r.wait_start << ",\"wait_end\":" << r.wait_end
          << ",\"render_start\":" << r.render_start << ",\"present_start\":" << r.present_start
          << ",\"present_end\":" << r.present_end << ",\"stats_end\":" << r.stats_end
          << ",\"present_hresult\":" << r.present_result << ",\"last_present_count_hresult\":" << r.count_result
          << ",\"last_present_count\":" << r.last_present << ",\"statistics_hresult\":" << r.statistics_result
          << ",\"statistics_valid\":" << (SUCCEEDED(r.statistics_result)?"true":"false")
          << ",\"statistics_present_count\":" << r.statistics.PresentCount
          << ",\"present_refresh_count\":" << r.statistics.PresentRefreshCount
          << ",\"sync_refresh_count\":" << r.statistics.SyncRefreshCount
          << ",\"sync_qpc\":" << r.statistics.SyncQPCTime.QuadPart << "}";
    }
    j << "\n]}\n";
    std::string text=j.str(); size_t offset=0;
    while(offset<text.size()) {
        DWORD written=0, amount=static_cast<DWORD>(std::min<size_t>(text.size()-offset,1<<20));
        if(!WriteFile(file,text.data()+offset,amount,&written,nullptr) || !written) {
            CloseHandle(file); throw std::runtime_error("Output JSON write failed");
        }
        offset+=written;
    }
    CloseHandle(file);
}

int wmain(int argc,wchar_t** argv) {
    try {
        Options o=options(argc,argv);
        if(!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) && GetLastError()!=ERROR_ACCESS_DENIED)
            throw std::runtime_error("Could not set DPI awareness");
        Monitor monitor=target_monitor();
        SetConsoleCtrlHandler(console_handler,TRUE);
        LARGE_INTEGER frequency; QueryPerformanceFrequency(&frequency);
        std::vector<Row> rows(static_cast<size_t>(std::ceil(o.seconds*120))+4096);
        size_t count=0; int64_t start=0,finish=0;
        std::string error;
        HWND before=GetForegroundWindow(), after=nullptr;
        DXGI_ADAPTER_DESC1 adapter{};
        {
            Graphics graphics; graphics.initialize(monitor,o.mode=="texture"); adapter=graphics.description;
            after=GetForegroundWindow(); start=qpc();
            try {
                while(g_running && count<rows.size()) {
                    Row row; row.frame=static_cast<uint32_t>(count);
                    row.wait_start=qpc();
                    if(!wait_frame(graphics.frame_event,start+static_cast<int64_t>(o.seconds*frequency.QuadPart))) break;
                    row.wait_end=qpc();
                    if(double(row.wait_end-start)/frequency.QuadPart>=o.seconds) break;
                    if(GetAsyncKeyState(VK_ESCAPE)&0x8000) break;
                    row.render_start=qpc();
                    uint64_t stamp=static_cast<uint64_t>(row.render_start);
                    float phase=float(row.frame%200)/200;
                    float angle=.12f*std::sin(phase*6.28318530718f);
                    Constants c{float(double(row.render_start-start)/frequency.QuadPart),row.frame,
                        uint32_t(stamp),uint32_t(stamp>>32),
                        o.mode=="texture"?2u:(o.mode=="complex"?1u:0u),
                        phase,std::sin(angle),std::cos(angle)};
                    graphics.draw(c);
                    DXGI_PRESENT_PARAMETERS parameters{};
                    row.present_start=qpc(); row.present_result=graphics.swap->Present1(1,0,&parameters); row.present_end=qpc();
                    row.count_result=graphics.swap->GetLastPresentCount(&row.last_present);
                    row.statistics_result=graphics.swap->GetFrameStatistics(&row.statistics); row.stats_end=qpc();
                    rows[count++]=row;
                    check(row.present_result,"Present1");
                    if(row.present_result==DXGI_STATUS_OCCLUDED) throw std::runtime_error("Pattern window became occluded");
                }
                if(count==rows.size()) throw std::runtime_error("Fixed record capacity exhausted");
            } catch(const std::exception& e) { error=e.what(); }
            finish=qpc();
        } // GPU/window released before JSON serialization; no per-frame file I/O.
        save(o,monitor,adapter,frequency.QuadPart,start,finish,rows,count,before,after,error);
        std::cout << "Saved " << count << " source-present records to " << utf8(o.output.wstring()) << "\n";
        if(!error.empty()) { std::cerr << error << "\n"; return 2; }
        return 0;
    } catch(const std::exception& e) { std::cerr << e.what() << "\n"; return 2; }
}
