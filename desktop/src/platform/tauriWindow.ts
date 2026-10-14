import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

export function isTauriRuntime(): boolean {
  return isTauri()
}

export async function hidePanel(): Promise<boolean> {
  if (!isTauriRuntime()) return false
  try {
    await getCurrentWindow().hide()
    return true
  } catch {
    return false
  }
}
