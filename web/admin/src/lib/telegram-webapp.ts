import type { TelegramAdminWebSessionPayload } from "@/lib/admin-web-api"

type TelegramWebAppBridge = {
  initData?: string
  ready?: () => void
  expand?: () => void
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebAppBridge
    }
  }
}

export function prepareTelegramWebApp(): void {
  const webApp = window.Telegram?.WebApp
  webApp?.ready?.()
  webApp?.expand?.()
}

export function readTelegramLaunchContext(): TelegramAdminWebSessionPayload | null {
  const initData = window.Telegram?.WebApp?.initData?.trim()
  if (!initData) {
    return null
  }

  const params = new URLSearchParams(window.location.search)
  const tenantPublicId =
    params.get("tenant_public_id")?.trim() ||
    params.get("tenant")?.trim() ||
    params.get("workspace")?.trim() ||
    undefined
  const entrypoint = params.get("entrypoint") === "tenant" || tenantPublicId ? "tenant" : "master"

  return {
    init_data: initData,
    entrypoint,
    tenant_public_id: entrypoint === "tenant" ? tenantPublicId : undefined,
  }
}
