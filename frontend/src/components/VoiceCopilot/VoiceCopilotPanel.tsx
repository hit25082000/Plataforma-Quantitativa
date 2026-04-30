/**
 * M8 — Copiloto IA Conversacional: UI principal do painel de voz.
 *
 * Layout:
 * - Header com badge de status animado
 * - Botão central de Push-to-Talk com animações de estado
 * - Visualizador de amplitude (barra de onda sonora)
 * - Histórico de transcrições (max 20 linhas, auto-scroll)
 * - Toast de erro inline
 */

import { useCallback, useEffect, useRef } from "react";
import { useVoiceCopilot, type VoiceStatus } from "../../hooks/useVoiceCopilot";

// ---------------------------------------------------------------------------
// Helpers de status
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  VoiceStatus,
  { label: string; color: string; ringColor: string; pulse: boolean }
> = {
  idle: {
    label: "Inativo",
    color: "text-[--text]/40",
    ringColor: "#2a2a2a",
    pulse: false,
  },
  connecting: {
    label: "Conectando…",
    color: "text-amber-400",
    ringColor: "#b45309",
    pulse: true,
  },
  listening: {
    label: "Ouvindo",
    color: "text-emerald-400",
    ringColor: "#10b981",
    pulse: true,
  },
  thinking: {
    label: "Processando…",
    color: "text-sky-400",
    ringColor: "#0ea5e9",
    pulse: true,
  },
  speaking: {
    label: "Falando",
    color: "text-violet-400",
    ringColor: "#8b5cf6",
    pulse: true,
  },
  error: {
    label: "Erro",
    color: "text-red-400",
    ringColor: "#ef4444",
    pulse: false,
  },
};

// ---------------------------------------------------------------------------
// Sub-componente: visualizador de onda sonora
// ---------------------------------------------------------------------------

function AmplitudeBar({ amplitude }: { amplitude: number }) {
  const bars = 12;
  return (
    <div
      className="flex items-center justify-center gap-[3px] h-8"
      aria-hidden="true"
    >
      {Array.from({ length: bars }, (_, i) => {
        const center = (bars - 1) / 2;
        const dist = Math.abs(i - center) / center; // 0 no centro, 1 nas bordas
        // Barras centrais ficam mais altas com amplitude; bordas ficam menores
        const height = amplitude > 0
          ? Math.max(4, Math.round(amplitude * (1 - dist * 0.6)))
          : 4;
        return (
          <div
            key={i}
            style={{
              height: `${height}px`,
              width: "3px",
              borderRadius: "2px",
              background:
                amplitude > 60
                  ? "rgb(16 185 129)"
                  : amplitude > 20
                  ? "rgb(16 185 129 / 0.75)"
                  : "rgb(42 42 42)",
              transition: "height 60ms linear, background 200ms ease",
            }}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-componente: botão Push-to-Talk
// ---------------------------------------------------------------------------

function PushToTalkButton({
  status,
  onClick,
  disabled,
}: {
  status: VoiceStatus;
  onClick: () => void;
  disabled?: boolean;
}) {
  const cfg = STATUS_CONFIG[status];
  const isListening = status === "listening";
  const isThinking = status === "thinking";
  const isSpeaking = status === "speaking";
  const isConnecting = status === "connecting";

  return (
    <div className="relative flex items-center justify-center">
      {/* Anel pulsante externo */}
      {(isListening || isSpeaking) && (
        <>
          <div
            className="absolute rounded-full pointer-events-none"
            style={{
              width: "88px",
              height: "88px",
              border: `2px solid ${cfg.ringColor}`,
              opacity: 0.3,
              animation: "pq-voice-ring 1.8s ease-out infinite",
            }}
          />
          <div
            className="absolute rounded-full pointer-events-none"
            style={{
              width: "76px",
              height: "76px",
              border: `1.5px solid ${cfg.ringColor}`,
              opacity: 0.5,
              animation: "pq-voice-ring 1.8s ease-out 0.6s infinite",
            }}
          />
        </>
      )}

      {/* Spinner de processamento */}
      {isThinking && (
        <div
          className="absolute rounded-full pointer-events-none"
          style={{
            width: "76px",
            height: "76px",
            border: "2px solid transparent",
            borderTopColor: cfg.ringColor,
            animation: "pq-voice-spin 0.9s linear infinite",
          }}
        />
      )}

      {/* Botão principal */}
      <button
        id="voice-copilot-ptt-btn"
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={
          status === "idle" || status === "error"
            ? "Iniciar sessão de voz"
            : "Parar sessão de voz"
        }
        style={{
          width: "64px",
          height: "64px",
          borderRadius: "50%",
          background:
            isListening
              ? "radial-gradient(circle, rgb(16 185 129 / 0.25), rgb(16 185 129 / 0.08))"
              : isSpeaking
              ? "radial-gradient(circle, rgb(139 92 246 / 0.25), rgb(139 92 246 / 0.08))"
              : isThinking
              ? "radial-gradient(circle, rgb(14 165 233 / 0.2), rgb(14 165 233 / 0.06))"
              : isConnecting
              ? "radial-gradient(circle, rgb(180 83 9 / 0.2), rgb(180 83 9 / 0.06))"
              : "radial-gradient(circle, rgb(255 255 255 / 0.07), rgb(255 255 255 / 0.02))",
          border: `2px solid ${cfg.ringColor}`,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.4 : 1,
          transition: "border-color 300ms ease, background 300ms ease, transform 80ms ease",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
        onMouseDown={(e) => { (e.currentTarget.style.transform = "scale(0.93)"); }}
        onMouseUp={(e) => { (e.currentTarget.style.transform = "scale(1)"); }}
        onMouseLeave={(e) => { (e.currentTarget.style.transform = "scale(1)"); }}
      >
        {/* Ícone SVG de microfone */}
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isListening ? "#10b981" : isSpeaking ? "#8b5cf6" : "#666"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          {status === "idle" || status === "error" ? (
            /* Microfone com X quando inativo/erro */
            <>
              <rect x="9" y="2" width="6" height="11" rx="3" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <line x1="12" y1="19" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </>
          ) : status === "thinking" ? (
            /* Ícone de processamento (brain) */
            <>
              <circle cx="12" cy="12" r="3" />
              <path d="M12 3a9 9 0 0 1 9 9" />
              <path d="M3 12a9 9 0 0 1 9-9" />
            </>
          ) : (
            /* Microfone ativo */
            <>
              <rect x="9" y="2" width="6" height="11" rx="3" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <line x1="12" y1="19" x2="12" y2="22" />
              <line x1="8" y1="22" x2="16" y2="22" />
            </>
          )}
        </svg>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Componente principal
// ---------------------------------------------------------------------------

export function VoiceCopilotPanel() {
  const {
    status,
    error,
    transcript,
    micAmplitude,
    startSession,
    stopSession,
    clearTranscript,
    isSupported,
  } = useVoiceCopilot();

  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll para o fim do transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const handleMainButton = useCallback(() => {
    if (status === "idle" || status === "error") {
      void startSession();
    } else {
      stopSession();
    }
  }, [status, startSession, stopSession]);

  const cfg = STATUS_CONFIG[status];
  const isActive = status !== "idle" && status !== "error";

  return (
    <div className="flex flex-col h-full min-h-0 bg-grid text-text/90">
      {/* Keyframes injetados via style tag */}
      <style>{`
        @keyframes pq-voice-ring {
          0%   { transform: scale(1); opacity: 0.5; }
          100% { transform: scale(1.5); opacity: 0; }
        }
        @keyframes pq-voice-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>

      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <h2 className="font-mono text-sm font-semibold tracking-wide text-text">
            Copiloto 007
          </h2>
          <p className="text-[10px] text-text/50 mt-0.5">
            Interação por voz em tempo real · Gemini Live API
          </p>
        </div>
        {/* Badge de status */}
        <div className="flex items-center gap-1.5">
          <div
            style={{
              width: "7px",
              height: "7px",
              borderRadius: "50%",
              background: cfg.ringColor,
              boxShadow: cfg.pulse ? `0 0 6px ${cfg.ringColor}` : "none",
              animation: cfg.pulse ? "pulse 1.5s ease-in-out infinite" : "none",
            }}
          />
          <span className={`text-[10px] font-mono ${cfg.color}`}>{cfg.label}</span>
        </div>
      </div>

      {/* Área central: botão + visualizador */}
      <div className="shrink-0 flex flex-col items-center gap-4 px-4 py-5 border-b border-border/50">
        <PushToTalkButton
          status={status}
          onClick={handleMainButton}
          disabled={!isSupported}
        />

        {/* Visualizador de amplitude */}
        <AmplitudeBar amplitude={isActive ? micAmplitude : 0} />

        {/* Label de ação */}
        <p className="text-[10px] text-text/40 font-mono">
          {!isSupported
            ? "WebRTC não suportado neste navegador"
            : status === "idle" || status === "error"
            ? "Clique para iniciar sessão de voz"
            : status === "listening"
            ? "Fale sua pergunta sobre o mercado…"
            : status === "thinking"
            ? "Consultando dados e processando…"
            : status === "speaking"
            ? "IA respondendo…"
            : "Conectando à Realtime API…"}
        </p>

        {/* Toast de erro */}
        {error && (
          <div className="w-full rounded border border-red-900/50 bg-red-950/30 px-3 py-2 flex items-start gap-2">
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#ef4444"
              strokeWidth="2"
              strokeLinecap="round"
              className="mt-0.5 shrink-0"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <p className="text-[10px] text-red-300/90 font-mono leading-snug">{error}</p>
          </div>
        )}
      </div>

      {/* Transcript */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden px-4 py-3 gap-2">
        <div className="flex items-center justify-between shrink-0">
          <p className="text-[10px] text-text/40 font-mono">Transcrição</p>
          {transcript.length > 0 && (
            <button
              id="voice-copilot-clear-btn"
              type="button"
              onClick={clearTranscript}
              className="text-[9px] text-text/30 hover:text-text/60 font-mono transition-colors"
            >
              limpar
            </button>
          )}
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto pq-saldo-scroll space-y-2">
          {transcript.length === 0 ? (
            <p className="text-[10px] text-text/25 font-mono italic">
              {isSupported
                ? 'Inicie uma sessão e fale, ex.: "Qual é o sinal atual?"'
                : "WebRTC não disponível neste ambiente."}
            </p>
          ) : (
            transcript.map((line, i) => (
              <div
                key={`${line.ts}-${i}`}
                className={
                  line.role === "user"
                    ? "flex justify-end"
                    : "flex justify-start"
                }
              >
                <div
                  className={
                    line.role === "user"
                      ? "max-w-[85%] rounded-lg rounded-tr-sm px-3 py-2 text-[11px] font-mono leading-snug bg-sky-900/30 border border-sky-800/30 text-sky-100/90"
                      : "max-w-[85%] rounded-lg rounded-tl-sm px-3 py-2 text-[11px] font-mono leading-snug bg-emerald-900/20 border border-emerald-800/30 text-emerald-100/90"
                  }
                >
                  <span className="block text-[9px] opacity-40 mb-0.5 font-mono">
                    {line.role === "user" ? "Você" : "Copiloto 007"} ·{" "}
                    {new Date(line.ts).toLocaleTimeString("pt-BR", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  {line.text}
                </div>
              </div>
            ))
          )}
          <div ref={transcriptEndRef} />
        </div>
      </div>

      {/* Footer: info de custo */}
      <div className="shrink-0 px-4 py-2 border-t border-border/40">
        <p className="text-[9px] text-text/20 font-mono text-center">
          Gemini Live API · gemini-3.1-flash-live-preview · cobrado por minuto de áudio
        </p>
      </div>
    </div>
  );
}
