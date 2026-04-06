; NSIS hooks for installer lifecycle.
; Ensures stale background processes do not block upgrade/install.

!macro NSIS_HOOK_PREINSTALL
  StrCpy $0 "$LOCALAPPDATA\Plataforma Quantitativa\logs"
  CreateDirectory "$0"
  StrCpy $1 "$0\installer-runtime.log"
  FileOpen $2 "$1" a
  FileWrite $2 "[preinstall] start$\r$\n"
  FileWrite $2 "[preinstall] taskkill engine.exe$\r$\n"
  FileClose $2
  DetailPrint "Encerrando processos em execucao (engine/distributor/OCR/app)..."
  nsExec::ExecToLog 'taskkill /F /IM engine.exe /T'
  FileOpen $2 "$1" a
  FileWrite $2 "[preinstall] taskkill distributor.exe$\r$\n"
  FileClose $2
  nsExec::ExecToLog 'taskkill /F /IM distributor.exe /T'
  FileOpen $2 "$1" a
  FileWrite $2 "[preinstall] taskkill profit_ocr_service.exe$\r$\n"
  FileClose $2
  nsExec::ExecToLog 'taskkill /F /IM profit_ocr_service.exe /T'
  FileOpen $2 "$1" a
  FileWrite $2 "[preinstall] taskkill plataforma-quantitativa.exe$\r$\n"
  FileClose $2
  nsExec::ExecToLog 'taskkill /F /IM plataforma-quantitativa.exe /T'
  Sleep 1200
  FileOpen $2 "$1" a
  FileWrite $2 "[preinstall] done$\r$\n"
  FileClose $2
!macroend

!macro NSIS_HOOK_POSTINSTALL
  StrCpy $0 "$LOCALAPPDATA\Plataforma Quantitativa\logs"
  CreateDirectory "$0"
  StrCpy $1 "$0\installer-runtime.log"
  FileOpen $2 "$1" a
  FileWrite $2 "[postinstall] start$\r$\n"
  FileClose $2
  ; Tesseract is required by OCR overlay runtime.
  IfFileExists "C:\Program Files\Tesseract-OCR\tesseract.exe" tesseract_ok check_x86
check_x86:
  IfFileExists "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" tesseract_ok tesseract_missing

tesseract_missing:
  FileOpen $2 "$1" a
  FileWrite $2 "[postinstall] tesseract=missing$\r$\n"
  FileClose $2
  MessageBox MB_ICONQUESTION|MB_YESNO "Tesseract OCR nao foi detectado. Deseja abrir a pagina oficial para instalar agora?" IDYES open_tesseract IDNO done
open_tesseract:
  FileOpen $2 "$1" a
  FileWrite $2 "[postinstall] user_action=open_tesseract_url$\r$\n"
  FileClose $2
  ExecShell "open" "https://github.com/UB-Mannheim/tesseract/releases/latest"
  Goto done

tesseract_ok:
  FileOpen $2 "$1" a
  FileWrite $2 "[postinstall] tesseract=detected$\r$\n"
  FileClose $2
  DetailPrint "Tesseract OCR detectado."

done:
  FileOpen $2 "$1" a
  FileWrite $2 "[postinstall] done$\r$\n"
  FileClose $2
!macroend
