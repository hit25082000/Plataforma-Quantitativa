/**
 * M8 — Copiloto IA Conversacional (Gemini Live API / WebSocket)
 *
 * Arquitetura:
 * 1. startSession() → POST /api/voice/session (distributor retorna ws_url + setup_message)
 * 2. Frontend abre WebSocket diretamente com a Gemini Live API
 * 3. Envia setup_message como primeira mensagem
 * 4. Captura microfone → PCM16 16kHz → base64 → WebSocket (chunks de ~250ms)
 * 5. Recebe áudio PCM16 24kHz da IA → decodifica → reproduz via AudioContext
 * 6. IA invoca Function Call via toolCall → frontend POST /api/voice/function-call
 *    → envia toolResponse no WebSocket
 * 7. Transcrições (input/output) via inputTranscription / outputTranscription
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { distributorApiBase } from "../config/distributorApi";

// ---------------------------------------------------------------------------
// Tipos públicos (interface idêntica à versão OpenAI — VoiceCopilotPanel não muda)
// ---------------------------------------------------------------------------

export type VoiceStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export interface TranscriptLine {
  role: "user" | "assistant";
  text: string;
  ts: string;
}

export interface VoiceCopilotState {
  status: VoiceStatus;
  error: string | null;
  transcript: TranscriptLine[];
  /** Amplitude do microfone (0-100) */
  micAmplitude: number;
  startSession: () => Promise<void>;
  stopSession: () => void;
  togglePushToTalk: () => void;
  clearTranscript: () => void;
  isSupported: boolean;
}

// ---------------------------------------------------------------------------
// Constantes de áudio
// ---------------------------------------------------------------------------

const MIC_SAMPLE_RATE = 16_000;     // Hz enviado ao Gemini
const OUTPUT_SAMPLE_RATE = 24_000;  // Hz recebido do Gemini
const CHUNK_INTERVAL_MS = 250;      // frequência de envio de chunks de áudio
const MAX_TRANSCRIPT = 20;

// ---------------------------------------------------------------------------
// Helpers de conversão PCM16
// ---------------------------------------------------------------------------

function float32ToPcm16(input: Float32Array): ArrayBuffer {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 32768 : s * 32767;
  }
  return output.buffer;
}

function pcm16ToFloat32(pcm16Buffer: ArrayBuffer): Float32Array {
  const int16 = new Int16Array(pcm16Buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768;
  }
  return float32;
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // Processar em chunks para evitar stack overflow com buffers grandes
  const CHUNK = 8192;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function normalizeTranscriptChunk(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function joinTranscriptChunks(chunks: string[]): string {
  return normalizeTranscriptChunk(chunks.join(" "));
}

// ---------------------------------------------------------------------------
// Hook principal
// ---------------------------------------------------------------------------

export function useVoiceCopilot(): VoiceCopilotState {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [micAmplitude, setMicAmplitude] = useState(0);

  // Refs WebSocket + áudio
  const wsRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const outCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const sendIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Buffer acumulador de PCM para envio periódico
  const pcmBufferRef = useRef<Float32Array[]>([]);
  // Transcrições parciais do turno atual
  const userTranscriptPartsRef = useRef<string[]>([]);
  const assistantTranscriptPartsRef = useRef<string[]>([]);
  // Tempo agendado para próximo chunk de saída (fila de reprodução)
  const nextPlayTimeRef = useRef(0);
  const ptEnabled = useRef(true); // push-to-talk: mic habilitado?

  const isSupported =
    typeof WebSocket !== "undefined" &&
    typeof AudioContext !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function";

  // ---------------------------------------------------------------------------
  // Visualizador de amplitude (RMS sobre o buffer acumulado)
  // ---------------------------------------------------------------------------

  const startAmplitudeLoop = useCallback(() => {
    const tick = () => {
      const buf = pcmBufferRef.current;
      if (buf.length > 0) {
        const last = buf[buf.length - 1];
        let rms = 0;
        for (const v of last) rms += v * v;
        rms = Math.sqrt(rms / last.length);
        setMicAmplitude(Math.min(100, Math.round(rms * 400)));
      }
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
  }, []);

  const stopAmplitudeLoop = useCallback(() => {
    if (animFrameRef.current != null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    setMicAmplitude(0);
  }, []);

  // ---------------------------------------------------------------------------
  // Reprodução de áudio PCM16 recebido do Gemini (fila de chunks)
  // ---------------------------------------------------------------------------

  const playPcmChunk = useCallback((base64Audio: string) => {
    if (!outCtxRef.current) return;
    const ctx = outCtxRef.current;
    try {
      const buffer = base64ToArrayBuffer(base64Audio);
      const float32 = pcm16ToFloat32(buffer);
      const audioBuffer = ctx.createBuffer(1, float32.length, OUTPUT_SAMPLE_RATE);
      audioBuffer.getChannelData(0).set(float32);
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      const startAt = Math.max(ctx.currentTime, nextPlayTimeRef.current);
      source.start(startAt);
      nextPlayTimeRef.current = startAt + audioBuffer.duration;
    } catch {
      // chunk inválido — ignorar
    }
  }, []);

  const appendTranscriptLine = useCallback(
    (role: "user" | "assistant", text: string) => {
      const clean = normalizeTranscriptChunk(text);
      if (!clean) return;
      setTranscript((prev) =>
        [...prev, { role, text: clean, ts: new Date().toISOString() }].slice(-MAX_TRANSCRIPT),
      );
    },
    [],
  );

  const flushUserTranscript = useCallback(() => {
    const text = joinTranscriptChunks(userTranscriptPartsRef.current);
    userTranscriptPartsRef.current = [];
    if (!text) return;
    appendTranscriptLine("user", text);
  }, [appendTranscriptLine]);

  const flushAssistantTranscript = useCallback(() => {
    const text = joinTranscriptChunks(assistantTranscriptPartsRef.current);
    assistantTranscriptPartsRef.current = [];
    if (!text) return;
    appendTranscriptLine("assistant", text);
  }, [appendTranscriptLine]);

  // ---------------------------------------------------------------------------
  // Function Calling bridge
  // ---------------------------------------------------------------------------

  const executeFunctionCall = useCallback(
    async (callId: string, functionName: string): Promise<unknown> => {
      const base = distributorApiBase();
      try {
        const res = await fetch(`${base}/api/voice/function-call`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ function_name: functionName, call_id: callId }),
        });
        const data = (await res.json()) as { ok?: boolean; result?: unknown; error?: string };
        return data.result ?? { error: data.error ?? "Erro desconhecido" };
      } catch (e) {
        return { error: `Falha de rede: ${String(e)}` };
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Handler de mensagens WebSocket (protocolo Gemini BidiGenerateContent)
  // ---------------------------------------------------------------------------

  const handleWsMessage = useCallback(
    (ev: MessageEvent) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(String(ev.data)) as Record<string, unknown>;
      } catch {
        return;
      }

      // -- Setup completo
      if (msg["setupComplete"] != null) {
        setStatus("listening");
        setError(null);
        return;
      }

      // -- Conteúdo do servidor (áudio + transcrições)
      const serverContent = msg["serverContent"] as Record<string, unknown> | undefined;
      if (serverContent) {
        // Áudio de resposta da IA
        const modelTurn = serverContent["modelTurn"] as Record<string, unknown> | undefined;
        if (modelTurn) {
          setStatus("speaking");
          flushUserTranscript();
          const parts = (modelTurn["parts"] as Array<Record<string, unknown>>) ?? [];
          for (const part of parts) {
            const inlineData = part["inlineData"] as Record<string, unknown> | undefined;
            if (inlineData?.["data"]) {
              playPcmChunk(inlineData["data"] as string);
            }
          }
        }

        // IA interrompida (barge-in)
        if (serverContent["interrupted"] === true) {
          nextPlayTimeRef.current = 0; // descarta fila de reprodução
          assistantTranscriptPartsRef.current = [];
          setStatus("listening");
        }

        // Transcrição de entrada (usuário)
        const inputTx = serverContent["inputTranscription"] as Record<string, unknown> | undefined;
        if (inputTx?.["text"]) {
          const text = (inputTx["text"] as string).trim();
          if (text) {
            userTranscriptPartsRef.current.push(text);
            setStatus("thinking");
          }
        }

        // Transcrição de saída (IA)
        const outputTx = serverContent["outputTranscription"] as Record<string, unknown> | undefined;
        if (outputTx?.["text"]) {
          const text = (outputTx["text"] as string).trim();
          if (text) {
            flushUserTranscript();
            assistantTranscriptPartsRef.current.push(text);
          }
        }

        // Turno concluído
        if (serverContent["turnComplete"] === true) {
          flushUserTranscript();
          flushAssistantTranscript();
          setStatus("listening");
        }
      }

      // -- Function Calling (toolCall)
      const toolCall = msg["toolCall"] as Record<string, unknown> | undefined;
      if (toolCall) {
        const calls = (toolCall["functionCalls"] as Array<Record<string, unknown>>) ?? [];
        for (const call of calls) {
          const callId = String(call["id"] ?? "");
          const name = String(call["name"] ?? "");
          if (!name) continue;

          void executeFunctionCall(callId, name).then((result) => {
            if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
            wsRef.current.send(
              JSON.stringify({
                toolResponse: {
                  functionResponses: [
                    { id: callId, response: { output: result } },
                  ],
                },
              }),
            );
          });
        }
      }

      // -- Erro da API
      const apiError = msg["error"] as Record<string, unknown> | undefined;
      if (apiError) {
        const msg2 = String(
          (apiError["message"] as string) ?? "Erro na sessão Gemini Live.",
        );
        setError(msg2);
        setStatus("error");
      }
    },
    [executeFunctionCall, flushAssistantTranscript, flushUserTranscript, playPcmChunk],
  );

  // ---------------------------------------------------------------------------
  // Cleanup de sessão
  // ---------------------------------------------------------------------------

  const stopSession = useCallback(() => {
    stopAmplitudeLoop();

    if (sendIntervalRef.current) {
      clearInterval(sendIntervalRef.current);
      sendIntervalRef.current = null;
    }
    if (sessionTimeoutRef.current) {
      clearTimeout(sessionTimeoutRef.current);
      sessionTimeoutRef.current = null;
    }

    // Desconectar processamento de áudio
    if (processorRef.current) {
      try { processorRef.current.disconnect(); } catch { /* ignore */ }
      processorRef.current = null;
    }
    if (micCtxRef.current) {
      void micCtxRef.current.close();
      micCtxRef.current = null;
    }
    if (outCtxRef.current) {
      void outCtxRef.current.close();
      outCtxRef.current = null;
    }

    // Liberar microfone
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }

    // Fechar WebSocket
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }

    pcmBufferRef.current = [];
    userTranscriptPartsRef.current = [];
    assistantTranscriptPartsRef.current = [];
    nextPlayTimeRef.current = 0;
    ptEnabled.current = true;
    setStatus("idle");
  }, [stopAmplitudeLoop]);

  // Cleanup no unmount
  useEffect(() => {
    return () => {
      stopAmplitudeLoop();
      if (sendIntervalRef.current) clearInterval(sendIntervalRef.current);
      if (sessionTimeoutRef.current) clearTimeout(sessionTimeoutRef.current);
      processorRef.current?.disconnect();
      void micCtxRef.current?.close();
      void outCtxRef.current?.close();
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      wsRef.current?.close();
    };
  }, [stopAmplitudeLoop]);

  // ---------------------------------------------------------------------------
  // Iniciar sessão
  // ---------------------------------------------------------------------------

  const startSession = useCallback(async () => {
    if (!isSupported) {
      setError("AudioContext ou WebSocket não suportado neste navegador.");
      setStatus("error");
      return;
    }
    if (status !== "idle" && status !== "error") return;

    setStatus("connecting");
    setError(null);

    // 1. Obter params de conexão do distributor
    const base = distributorApiBase();
    let sessionData: {
      ok?: boolean;
      ws_url?: string;
      transport?: string;
      setup_message?: unknown;
      max_duration_s?: number;
      error?: string;
    };
    try {
      const res = await fetch(`${base}/api/voice/session`, { method: "POST" });
      sessionData = (await res.json()) as typeof sessionData;
    } catch (e) {
      setError(`Distributor indisponível: ${String(e)}`);
      setStatus("error");
      return;
    }

    if (!sessionData.ok || !sessionData.ws_url || !sessionData.setup_message) {
      setError(sessionData.error ?? "Params de conexão inválidos.");
      setStatus("error");
      return;
    }

    // 2. Capturar microfone
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      micStreamRef.current = stream;
    } catch (e) {
      setError(`Permissão de microfone negada: ${String(e)}`);
      setStatus("error");
      return;
    }

    // 3. Configurar pipeline de captura PCM16
    const micCtx = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });
    micCtxRef.current = micCtx;
    const outCtx = new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE });
    outCtxRef.current = outCtx;

    const source = micCtx.createMediaStreamSource(stream);
    // ScriptProcessorNode (deprecated mas amplo suporte) — acumula amostras
    const processor = micCtx.createScriptProcessor(4096, 1, 1);
    processorRef.current = processor;
    processor.onaudioprocess = (e) => {
      if (!ptEnabled.current) return;
      const inputData = e.inputBuffer.getChannelData(0);
      pcmBufferRef.current.push(new Float32Array(inputData));
    };
    source.connect(processor);
    processor.connect(micCtx.destination);

    // 4. Iniciar loop de amplitude
    startAmplitudeLoop();

    // 5. Loop de envio de chunks ao WebSocket (a cada CHUNK_INTERVAL_MS)
    const ws = new WebSocket(sessionData.ws_url);
    wsRef.current = ws;
    ws.onmessage = handleWsMessage;
    ws.onerror = () => {
      setError("Erro na conexão WebSocket com a Gemini Live API.");
      setStatus("error");
    };
    ws.onclose = (ev) => {
      if (status !== "idle") {
        setError(`Conexão encerrada (${ev.code}): ${ev.reason || "sem motivo"}`);
      }
      stopSession();
    };

    ws.onopen = () => {
      // Quando o distributor faz proxy local, ele já envia o setup_message
      // para a Gemini Live API. No modo direto, o frontend mantém o envio.
      if (sessionData.transport !== "proxy") {
        ws.send(JSON.stringify(sessionData.setup_message));
      }

      // Iniciar envio periódico de chunks de áudio
      sendIntervalRef.current = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const chunks = pcmBufferRef.current.splice(0);
        if (chunks.length === 0 || !ptEnabled.current) return;

        // Concatenar todos os Float32 acumulados
        const totalLen = chunks.reduce((s, c) => s + c.length, 0);
        const merged = new Float32Array(totalLen);
        let offset = 0;
        for (const c of chunks) {
          merged.set(c, offset);
          offset += c.length;
        }

        const pcm16Buffer = float32ToPcm16(merged);
        const b64 = arrayBufferToBase64(pcm16Buffer);
        ws.send(
          JSON.stringify({
            realtimeInput: {
              audio: {
                data: b64,
                mimeType: `audio/pcm;rate=${MIC_SAMPLE_RATE}`,
              },
            },
          }),
        );
      }, CHUNK_INTERVAL_MS);
    };

    // 6. Timeout automático de sessão
    const maxMs = (sessionData.max_duration_s ?? 600) * 1000;
    sessionTimeoutRef.current = setTimeout(() => stopSession(), maxMs);
  }, [isSupported, status, handleWsMessage, startAmplitudeLoop, stopSession]);

  // ---------------------------------------------------------------------------
  // Push-to-Talk: silencia o microfone sem encerrar a sessão
  // ---------------------------------------------------------------------------

  const togglePushToTalk = useCallback(() => {
    if (!wsRef.current) return;
    ptEnabled.current = !ptEnabled.current;

    if (!ptEnabled.current) {
      // Microfone silenciado → sinaliza fim de atividade ao Gemini
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ realtimeInput: { audioStreamEnd: true } }),
        );
      }
      stopAmplitudeLoop();
      setStatus("idle");
    } else {
      // Microfone reativado
      startAmplitudeLoop();
      setStatus("listening");
    }
  }, [startAmplitudeLoop, stopAmplitudeLoop]);

  const clearTranscript = useCallback(() => setTranscript([]), []);

  return {
    status,
    error,
    transcript,
    micAmplitude,
    startSession,
    stopSession,
    togglePushToTalk,
    clearTranscript,
    isSupported,
  };
}
