# OVR STAB QA field execution (manual assisted)

- base_url: `http://127.0.0.1:8000`
- api_health: `0`
- api_debug: `0`
- api_status: `0`
- trace_exists: `0`
- trace_path: `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl`
- tasks_ready: `0/4`

## Tasks

| id | state | title | blockers |
| --- | --- | --- | --- |
| OVR-STAB-QA-02 | blocked | Zoom/eixo vertical com transicao controlada | api_indisponivel: health/debug/status nao responderam; trace_ausente: C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl; sessao_real_nao_confirmada: usar --assume-manual-ready para registrar sessao assistida |
| OVR-STAB-QA-03 | blocked | OCR ruim com degradacao controlada | api_indisponivel: health/debug/status nao responderam; trace_ausente: C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl; sessao_real_nao_confirmada: usar --assume-manual-ready para registrar sessao assistida |
| OVR-STAB-QA-04 | blocked | Multi-monitor e DPI | api_indisponivel: health/debug/status nao responderam; trace_ausente: C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl; sessao_real_nao_confirmada: usar --assume-manual-ready para registrar sessao assistida; requer_multi_monitor: executar em 100/125/150 com captura manual |
| OVR-STAB-QA-05 | blocked | Carga com muitos targets/histograma | api_indisponivel: health/debug/status nao responderam; trace_ausente: C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ocr_overlay_trace.jsonl; sessao_real_nao_confirmada: usar --assume-manual-ready para registrar sessao assistida; requer_carga_real: validar throughput com VP/targets/histograma ativos |

## Evidence dirs discovered

- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-qa-evidence-20260429-162929`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\ovr-stab-qa-evidence-20260429-161246`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\vp-sato-performance-20260429-142306`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\vp-sato-performance-20260429-142240`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\vp-sato-performance-20260429-142131`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\vp-sato-performance-20260429-141850`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-150407`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-145816`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-145356`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-144520`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-143411`
- `C:\Users\luiz.domingues\Dev\Plataforma Quantitativa\distributor\logs\m9-rag-operational-evidence-20260424-143126`
