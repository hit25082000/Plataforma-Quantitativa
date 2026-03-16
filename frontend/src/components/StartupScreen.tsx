import { isTauri } from "../utils/tauri";

type StartupStatus = "idle" | "checking" | "starting" | "ready" | "error";

interface StartupScreenProps {
  status: StartupStatus;
  error: string | null;
}

export function StartupScreen({ status, error }: StartupScreenProps) {
  if (!isTauri()) return null;
  if (status === "ready") return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/95 backdrop-blur-sm">
      <div className="rounded-lg border border-border bg-grid p-8 max-w-md text-center">
        {status === "idle" && (
          <p className="text-text">Conectando...</p>
        )}
        {status === "checking" && (
          <p className="text-text">Verificando serviços...</p>
        )}
        {status === "starting" && (
          <p className="text-text">Iniciando engine e distributor...</p>
        )}
        {status === "error" && (
          <div>
            <p className="text-red-400 font-medium">{error}</p>
            <p className="text-text/60 text-sm mt-2">
              Verifique se as credenciais Profit estão configuradas em Configurações.
            </p>
          </div>
        )}
        <div className="mt-4 h-1 w-32 mx-auto bg-border rounded overflow-hidden">
          <div
            className="h-full bg-emerald-500/80 transition-all duration-300"
            style={{
              width: status === "error" ? "0%" : "50%",
            }}
          />
        </div>
      </div>
    </div>
  );
}
